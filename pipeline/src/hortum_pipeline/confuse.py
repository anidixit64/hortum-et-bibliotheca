"""Stage 9: "don't confuse with": topics players mix up.

Candidate pairs come from three signals, each kept with its evidence:

* **reject**: an answer line rejects another topic ("do not accept meiosis" on a mitosis
  question). The strongest signal: a question writer saw players make that mistake.
  Prompts aren't used: they mostly name broader terms ("primates" for monkeys, "fly" for
  Drosophila), which is hierarchy, not confusion.
* **same name**: two topics whose titles, minus any parenthetical, are the same name
  ("Mercury (planet)", "Mercury (element)"; "Vertigo" and "Vertigo (film)"). Aliases
  aren't enough: answer lines accept near-synonyms ("boiling" for vaporization), parts of
  overlapping answers ("Allende" for the 1973 Chilean coup), and main answers grouped
  under an event named after them ("Joseph Smith" under his killing).
* **look-alike**: names a letter or two apart in the same category whose questions are
  also about similar things: clue centroids at least ``confuse_lookalike_min_similarity``
  apart in cosine ("Tyrosine"/"Cytosine" 0.78, "Henry I"/"Henry II" 0.86, but not
  "Shale"/"Whale" 0.23 or "Leaf"/"Lead" 0.33). Names differing only in digits
  ("1870s"/"1890s", election years) don't count.

Clue overlap alone isn't a signal: a topic's nearest neighbors by clue centroid are
siblings, not confusions (Poe -> Shakespeare 0.93, Electron -> Photon 0.94, Austria ->
Italy 0.89), and well above most same-category pairs (99th percentile 0.81).

A reject entry names another topic when the whole entry is that topic's name, or when a
name inside it covers at least half the entry ("prophase I"); a name buried in an
explanation ("... afterwards. First Giovanni's Room ...") doesn't count.

Confusion is symmetric: if mitosis questions reject meiosis, meiosis's page lists mitosis
too. Each topic keeps its ``confuse_top`` best pairs:

    score = reject_weight * log(1 + questions rejecting, either way)
            + same_name_weight * [same name] + lookalike_weight * [look-alike]
"""

import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz.distance import Levenshtein

from hortum_common.text import normalize
from hortum_pipeline import db
from hortum_pipeline.cluster import EmbeddingCache, text_key
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.relate import (
    STOPWORDS,
    AliasMatcher,
    capitalized_share,
    load_aliases,
    tokenize,
)

SCHEMA = """
DROP TABLE IF EXISTS confusions;
CREATE TABLE confusions (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    other_topic_id TEXT NOT NULL REFERENCES topics(id),
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    reasons TEXT NOT NULL,       -- JSON: subset of ["reject", "same_name", "lookalike"]
    evidence TEXT NOT NULL,      -- JSON: {"reject": [{tossup_id, text}], "same_name": alias, ...}
    PRIMARY KEY (topic_id, other_topic_id)
);
"""

_PAREN = re.compile(r"\s*\([^)]*\)")
_REJECT_EXAMPLES = 3


@dataclass
class Pair:
    rejects: dict[str, str] = field(default_factory=dict)  # tossup id -> reject text
    same_name: str | None = None
    lookalike: tuple[str, str] | None = None

    def reasons(self) -> list[str]:
        out = []
        if self.rejects:
            out.append("reject")
        if self.same_name:
            out.append("same_name")
        if self.lookalike:
            out.append("lookalike")
        return out


def base_name(display_name: str) -> str:
    """ "Mercury (planet)" -> "mercury": the name a player would say."""
    return normalize(_PAREN.sub("", display_name))


def is_lookalike(a: str, b: str) -> bool:
    """Names a letter or two apart: "monet"/"manet", "iran"/"iraq", "austria"/"australia"."""
    if a == b or min(len(a), len(b)) < 4 or a in b or b in a:
        return False
    if re.sub(r"\d", "", a) == re.sub(r"\d", "", b):
        return False  # "1870s"/"1890s", "16th century"/"19th century"
    limit = 1 if max(len(a), len(b)) < 8 else 2
    return Levenshtein.distance(a, b, score_cutoff=limit) <= limit


def topic_centroids(
    conn: sqlite3.Connection, settings: PipelineSettings, topic_ids: set[str]
) -> dict[str, np.ndarray]:
    """Mean clue embedding (unit length) per topic, from the cluster stage's cache."""
    cache = EmbeddingCache(settings.data_dir / "cache" / "embeddings" / "minilm.db")
    keys: dict[str, list[str]] = defaultdict(list)
    for topic_id, text in conn.execute(
        "SELECT topic_id, text FROM clues WHERE kind = 'clue' AND topic_id IS NOT NULL"
    ):
        if topic_id in topic_ids:
            keys[topic_id].append(text_key(text))
    out = {}
    for topic_id, topic_keys in keys.items():
        mean = cache.get(topic_keys).mean(axis=0)
        out[topic_id] = mean / max(float(np.linalg.norm(mean)), 1e-9)
    return out


def reject_targets(
    text: str, matcher: AliasMatcher, category: str | None, topic_id: str
) -> list[str]:
    """Topics a reject entry names: the whole entry as a name, else names covering half of it.

    The question's own topic is never the rejected one, which settles shared names: "The
    Invisible Man" rejected on an *Invisible Man* question is H. G. Wells's novel.
    """
    owners = [o for o in matcher.aliases.get(normalize(text), []) if o.topic_id != topic_id]
    chosen = matcher.choose(owners, category) if owners else None
    if chosen:
        return [chosen.topic_id]
    tokens = tokenize(text)
    content = [t for t in tokens if t.key not in STOPWORDS]
    return [
        topic
        for alias, topic, _, _ in matcher.find(tokens, category, exclude=topic_id)
        if len(alias.split()) * 2 >= len(content)
    ]


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "related_topics", "relate")
    db.recreate(conn, SCHEMA)
    topics = {
        tid: (name, category, n)
        for tid, name, category, n in conn.execute(
            "SELECT id, display_name, primary_category, n_tossups FROM topics"
        )
    }
    pairs: dict[tuple[str, str], Pair] = defaultdict(Pair)

    def pair(a: str, b: str) -> Pair:
        return pairs[(a, b) if a < b else (b, a)]

    # 1. Answer-line rejects.
    reporter.begin("Reading answer-line rejects", None)
    share = capitalized_share(
        r[0] for r in conn.execute("SELECT text FROM clues WHERE kind != 'note'")
    )
    matcher = AliasMatcher(
        load_aliases(conn, share, settings.relate_min_cap_share),
        {w for w, v in share.items() if v >= settings.relate_min_cap_share},
    )
    n_rejects = 0
    for tossup_id, topic_id, reject in conn.execute(
        "SELECT a.tossup_id, tt.topic_id, a.reject FROM answer_parses a "
        "JOIN tossup_topics tt ON tt.tossup_id = a.tossup_id WHERE a.reject != '[]'"
    ):
        category = topics[topic_id][1]
        for entry in json.loads(reject):
            for other in reject_targets(entry["text"], matcher, category, topic_id):
                if other != topic_id:
                    pair(topic_id, other).rejects.setdefault(tossup_id, entry["text"])
                    n_rejects += 1
    reporter.stat("Rejects naming another topic", f"{n_rejects:,}")

    # 2. Same name: titles that are the same name once the parenthetical goes.
    reporter.begin("Finding topics that share a name", None)
    named: dict[str, list[str]] = defaultdict(list)
    for tid, (name, _, n) in topics.items():
        if n >= settings.confuse_same_name_min_questions:
            named[base_name(name)].append(tid)
    n_same = 0
    for name, tids in named.items():
        if len(name) < 4 or not 2 <= len(tids) <= settings.confuse_same_name_max_owners:
            continue
        for a in tids:
            for b in tids:
                if a < b:
                    pair(a, b).same_name = name
                    n_same += 1
    reporter.stat("Same-name pairs", f"{n_same:,}")

    # 3. Look-alike names within a category, about similar things.
    reporter.begin("Comparing names within each category", None)
    by_category: dict[str | None, list[tuple[str, str]]] = defaultdict(list)
    for tid, (name, category, n) in topics.items():
        if n >= settings.confuse_lookalike_min_questions:
            by_category[category].append((tid, base_name(name)))
    similar_names: list[tuple[str, str, str, str]] = []
    for members in by_category.values():
        by_length: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for tid, name in members:
            by_length[len(name)].append((tid, name))
        for length, group in by_length.items():
            nearby = [m for d in range(-2, 3) for m in by_length.get(length + d, [])]
            for a, name_a in group:
                for b, name_b in nearby:
                    if a < b and is_lookalike(name_a, name_b):
                        similar_names.append((a, b, name_a, name_b))
    centroids = topic_centroids(conn, settings, {t for c in similar_names for t in c[:2]})
    n_look = 0
    for a, b, name_a, name_b in similar_names:
        if a not in centroids or b not in centroids:
            continue
        if float(centroids[a] @ centroids[b]) >= settings.confuse_lookalike_min_similarity:
            pair(a, b).lookalike = (name_a, name_b)
            n_look += 1
    reporter.stat("Look-alike pairs", f"{n_look:,} of {len(similar_names):,} similar names")

    # 4. Score and keep the best per topic.
    reporter.begin("Ranking confusions", None)
    by_topic: dict[str, list[tuple[float, str, Pair]]] = defaultdict(list)
    for (a, b), p in pairs.items():
        value = (
            settings.confuse_reject_weight * math.log1p(len(p.rejects))
            + settings.confuse_same_name_weight * bool(p.same_name)
            + settings.confuse_lookalike_weight * bool(p.lookalike)
        )
        by_topic[a].append((value, b, p))
        by_topic[b].append((value, a, p))
    rows = []
    for topic_id, candidates in by_topic.items():
        candidates.sort(key=lambda c: (-c[0], c[1]))
        for rank, (value, other, p) in enumerate(candidates[: settings.confuse_top], start=1):
            evidence: dict[str, object] = {}
            if p.rejects:
                evidence["reject"] = [
                    {"tossup_id": t, "text": text}
                    for t, text in sorted(p.rejects.items())[:_REJECT_EXAMPLES]
                ]
                evidence["n_rejects"] = len(p.rejects)
            if p.same_name:
                evidence["same_name"] = p.same_name
            if p.lookalike:
                evidence["lookalike"] = list(p.lookalike)
            rows.append(
                (topic_id, other, rank, round(value, 4), json.dumps(p.reasons()),
                 json.dumps(evidence, ensure_ascii=False))
            )  # fmt: skip
    conn.executemany("INSERT INTO confusions VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    reporter.stat("Topics with confusions", f"{len(by_topic):,} of {len(topics):,}")
    reporter.stat("Confusion links kept", f"{len(rows):,}")
    conn.close()
