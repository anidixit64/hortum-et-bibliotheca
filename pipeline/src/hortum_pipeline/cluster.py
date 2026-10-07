"""Stage 6: group clues that state the same fact in different words.

Every clue (kind "clue", in a topic) is embedded with the MiniLM sentence model, and
clues within a topic are merged by average-linkage clustering on cosine distance, with a
bonus for each key term two clues share ("Brockway", "Liberty Paints"). Chosen against
the hand-labeled clues: MiniLM + a 0.2 shared-term bonus at threshold 0.6 scored pairwise
F1 0.76, against 0.60 for the best TF-IDF setting.

Embeddings are cached per clue text in data/cache/embeddings, so re-runs are fast.
"""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.cluster import AgglomerativeClustering

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384

SCHEMA = """
DROP TABLE IF EXISTS clue_cluster_members;
DROP TABLE IF EXISTS clue_clusters;
CREATE TABLE clue_clusters (
    id INTEGER PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    label TEXT NOT NULL,
    key_terms TEXT NOT NULL,              -- JSON: most common key terms, most common first
    representative_clue_id INTEGER NOT NULL REFERENCES clues(id),
    n_clues INTEGER NOT NULL,
    n_tossups INTEGER NOT NULL,
    n_sets INTEGER NOT NULL
);
CREATE INDEX clue_clusters_topic ON clue_clusters(topic_id);
CREATE TABLE clue_cluster_members (
    clue_id INTEGER PRIMARY KEY REFERENCES clues(id),
    cluster_id INTEGER NOT NULL REFERENCES clue_clusters(id)
);
CREATE INDEX clue_cluster_members_cluster ON clue_cluster_members(cluster_id);
"""

Embedder = Callable[[Sequence[str]], np.ndarray]


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class EmbeddingCache:
    """Unit-length float32 vectors keyed by clue text, kept across runs."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, v BLOB)")

    def missing(self, keys: Sequence[str]) -> list[str]:
        have: set[str] = set()
        for start in range(0, len(keys), 900):
            chunk = keys[start : start + 900]
            marks = ",".join("?" * len(chunk))
            have.update(
                r[0]
                for r in self.conn.execute(f"SELECT key FROM vectors WHERE key IN ({marks})", chunk)
            )
        return [k for k in keys if k not in have]

    def put(self, keys: Sequence[str], vectors: np.ndarray) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vectors VALUES (?, ?)",
            [(k, v.astype(np.float32).tobytes()) for k, v in zip(keys, vectors, strict=True)],
        )
        self.conn.commit()

    def get(self, keys: Sequence[str]) -> np.ndarray:
        found: dict[str, bytes] = {}
        for start in range(0, len(keys), 900):
            chunk = keys[start : start + 900]
            marks = ",".join("?" * len(chunk))
            found.update(
                self.conn.execute(f"SELECT key, v FROM vectors WHERE key IN ({marks})", chunk)
            )
        return np.stack([np.frombuffer(found[k], dtype=np.float32) for k in keys])


def minilm_embedder() -> Embedder:
    from fastembed import TextEmbedding  # imported lazily: loading the model takes seconds

    model = TextEmbedding(MODEL)

    def embed(texts: Sequence[str]) -> np.ndarray:
        vectors = np.array(list(model.embed(list(texts), batch_size=64)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-9)
        return np.asarray(vectors / norms, dtype=np.float32)

    return embed


def similarity(vectors: np.ndarray, terms: list[list[str]], term_bonus: float) -> np.ndarray:
    """Cosine similarity plus ``term_bonus`` per shared key term, capped at 1."""
    sim = vectors @ vectors.T
    vocab: dict[str, int] = {}
    rows, cols = [], []
    for i, clue_terms in enumerate(terms):
        for term in {t.lower() for t in clue_terms}:
            rows.append(i)
            cols.append(vocab.setdefault(term, len(vocab)))
    if vocab and term_bonus:
        incidence = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(terms), len(vocab)))
        shared = (incidence @ incidence.T).toarray()
        np.fill_diagonal(shared, 0)
        sim = np.minimum(1.0, sim + term_bonus * shared)
    return np.asarray(sim, dtype=np.float64)


def cluster_topic(sim: np.ndarray, threshold: float) -> np.ndarray:
    if len(sim) == 1:
        return np.zeros(1, dtype=int)
    model = AgglomerativeClustering(
        metric="precomputed", linkage="average", distance_threshold=threshold, n_clusters=None
    )
    return np.asarray(model.fit_predict(np.clip(1.0 - sim, 0.0, 2.0)))


def summarize(
    texts: list[str], terms: list[list[str]], sim: np.ndarray
) -> tuple[int, str, list[str]]:
    """Medoid index, a short label, and the cluster's most common key terms."""
    medoid = int(np.argmax(sim.sum(axis=1)))
    counts = Counter(t for clue_terms in terms for t in dict.fromkeys(clue_terms))
    common = [t for t, _ in counts.most_common(5)]
    label = common[0] if common else " ".join(texts[medoid].split()[:8])
    return medoid, label, common


def run(
    settings: PipelineSettings,
    reporter: Reporter,
    embedder_factory: Callable[[], Embedder] = minilm_embedder,
) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "clues", "clues")
    db.recreate(conn, SCHEMA)

    rows = conn.execute(
        "SELECT c.id, c.topic_id, c.text, c.key_terms, c.tossup_id, t.set_id "
        "FROM clues c JOIN tossups t ON t.id = c.tossup_id "
        "WHERE c.kind = 'clue' AND c.topic_id IS NOT NULL ORDER BY c.topic_id, c.id"
    ).fetchall()
    keys = [text_key(r[2]) for r in rows]

    # 1. Embed whatever isn't cached yet (the slow part, done once).
    cache = EmbeddingCache(settings.data_dir / "cache" / "embeddings" / "minilm.db")
    unique = list(dict.fromkeys(keys))
    todo = cache.missing(unique)
    text_of = {k: r[2] for k, r in zip(keys, rows, strict=True)}
    reporter.begin("Embedding clues (MiniLM)", len(todo))
    reporter.stat("Clues to embed / already cached", f"{len(todo):,} / {len(unique) - len(todo):,}")
    if todo:
        embed = embedder_factory()
        for start in range(0, len(todo), 512):
            batch = todo[start : start + 512]
            cache.put(batch, embed([text_of[k] for k in batch]))
            reporter.advance(len(batch))

    # 2. Cluster topic by topic.
    by_topic: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_topic[row[1]].append(index)
    reporter.begin("Clustering clues within each topic", len(by_topic))
    cluster_id = 0
    clusters: list[tuple[object, ...]] = []
    members: list[tuple[int, int]] = []
    for topic_id, indices in by_topic.items():
        vectors = cache.get([keys[i] for i in indices])
        terms = [json.loads(rows[i][3]) for i in indices]
        sim = similarity(vectors, terms, settings.cluster_term_bonus)
        labels = cluster_topic(sim, settings.cluster_threshold)
        for label in np.unique(labels):
            local = np.flatnonzero(labels == label)
            group = [indices[j] for j in local]
            medoid, name, common = summarize(
                [rows[i][2] for i in group], [terms[j] for j in local], sim[np.ix_(local, local)]
            )
            cluster_id += 1
            clusters.append(
                (cluster_id, topic_id, name, json.dumps(common, ensure_ascii=False),
                 rows[group[medoid]][0], len(group), len({rows[i][4] for i in group}),
                 len({rows[i][5] for i in group}))
            )  # fmt: skip
            members.extend((rows[i][0], cluster_id) for i in group)
        reporter.advance()
        if len(members) > 50_000:
            _flush(conn, clusters, members)
    _flush(conn, clusters, members)
    conn.commit()

    sizes = dict(conn.execute(
        "SELECT CASE WHEN n_tossups >= 3 THEN '3+' WHEN n_tossups = 2 THEN '2' ELSE '1' END, "
        "COUNT(*) FROM clue_clusters GROUP BY 1"
    ))  # fmt: skip
    reporter.stat("Clusters", f"{cluster_id:,} from {len(rows):,} clues")
    reporter.stat(
        "Clusters seen in 1 / 2 / 3+ questions",
        " / ".join(f"{sizes.get(k, 0):,}" for k in ("1", "2", "3+")),
    )
    conn.close()


def _flush(
    conn: sqlite3.Connection, clusters: list[tuple[object, ...]], members: list[tuple[int, int]]
) -> None:
    conn.executemany("INSERT INTO clue_clusters VALUES (?, ?, ?, ?, ?, ?, ?, ?)", clusters)
    conn.executemany("INSERT INTO clue_cluster_members VALUES (?, ?)", members)
    clusters.clear()
    members.clear()
