"""Stage 7: rank each topic's clue clusters and pick its high-impact clues.

A high-impact clue is common enough to be worth knowing and early enough to win the buzz:

    frequency    F = sqrt(distinct sets)      (or log(1 + sets))
    earliness    E = 1 - median position + power_bonus * share before the power mark
    specificity  S = how rarely the cluster's key terms appear in *other* topics (0..1)
    last line    L = share of the cluster's clues in the last line before the giveaway
    impact       = F * E ** earliness_exponent * S ** specificity_exponent * (1 + bonus * L)

The last line before the giveaway carries the well-known clues; its small bonus keeps the
picks from being only niche lead-in facts.

The tuned weights (see config.py) lean on frequency: a clue in 38 sets at mid-question
("Ras the Exhorter") must outrank one in 6 sets near the start.

Clusters seen in fewer than ``min_sets`` sets (one set for small topics) or made only of
the topic's own names are left out; from the rest, up to 10 are picked by maximal marginal
relevance so the picks aren't near-duplicates. Heatmap statistics are stored for every
cluster: position histogram, difficulty bands, years and a rising/steady/fading trend.
"""

import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from hortum_common.text import normalize
from hortum_pipeline import db
from hortum_pipeline.cluster import EmbeddingCache, text_key
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.relate import STOPWORDS, tokenize

SCHEMA = """
DROP TABLE IF EXISTS cluster_scores;
CREATE TABLE cluster_scores (
    cluster_id INTEGER PRIMARY KEY REFERENCES clue_clusters(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    n_sets INTEGER NOT NULL,
    median_position REAL NOT NULL,
    share_in_power REAL NOT NULL,
    share_last_line REAL NOT NULL,   -- share of clues in the last line before the giveaway
    specificity REAL NOT NULL,
    impact REAL NOT NULL,
    eligible INTEGER NOT NULL,
    rank INTEGER,                    -- 1..10 for the picked clues, else NULL
    display_label TEXT NOT NULL,     -- a specific name, or the clue's opening words
    position_hist TEXT NOT NULL,     -- JSON: 10 bins from lead-in to end
    difficulty_hist TEXT NOT NULL,   -- JSON: {unrated, middle_school, high_school, college, open}
    first_year INTEGER,
    last_year INTEGER,
    trend TEXT NOT NULL              -- rising | steady | fading
);
CREATE INDEX cluster_scores_topic ON cluster_scores(topic_id, rank);
"""

TOP_MIN, TOP_MAX = 5, 10


@dataclass
class ClusterStats:
    cluster_id: int
    topic_id: str
    representative: str
    key_terms: list[str]
    positions: list[float] = field(default_factory=list)
    in_power: list[int] = field(default_factory=list)
    last_line: list[int] = field(default_factory=list)
    difficulties: list[int] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    sets: set[str] = field(default_factory=set)

    @property
    def median_position(self) -> float:
        return float(np.median(self.positions))

    @property
    def share_in_power(self) -> float:
        return sum(self.in_power) / len(self.in_power)

    @property
    def share_last_line(self) -> float:
        return sum(self.last_line) / len(self.last_line) if self.last_line else 0.0


@dataclass(frozen=True)
class Weights:
    power_bonus: float = 0.0
    specificity_exponent: float = 0.0
    min_sets: int = 2
    mmr_lambda: float = 0.7
    frequency_mode: str = "sqrt"  # "log": log(1 + sets); "sqrt": sqrt(sets) rewards common clues
    earliness_exponent: float = 0.25  # below 1 softens the penalty for mid-question clues
    last_line_bonus: float = 0.0  # extra weight for clues in the last line before the giveaway


_VAGUE_TOPICS = 50  # a term found in more topics than this is too generic to be a label


def display_label(stats: ClusterStats, topic_freq: Counter[str]) -> str:
    """The most common *specific* key term, else the representative clue's opening words.

    "Peace", "Role" or "agent" can top a cluster's terms yet say nothing on their own.
    """
    for term in stats.key_terms:
        if topic_freq.get(term.lower(), 0) <= _VAGUE_TOPICS:
            return term
    words = stats.representative.split()
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


def difficulty_band(difficulty: int | None) -> str:
    if not difficulty:
        return "unrated"
    if difficulty == 1:
        return "middle_school"
    if difficulty <= 5:
        return "high_school"
    if difficulty <= 9:
        return "college"
    return "open"


def position_hist(positions: list[float]) -> list[int]:
    hist = [0] * 10
    for p in positions:
        hist[min(9, int(p * 10))] += 1
    return hist


def trend(years: list[int], topic_years: list[int]) -> str:
    """Rising/fading: is this clue's share of the topic's recent questions up or down?"""
    if len(years) < 3 or not topic_years:
        return "steady"
    cutoff = sorted(topic_years)[int(len(topic_years) * 2 / 3)]
    recent = sum(y >= cutoff for y in years) / len(years)
    baseline = sum(y >= cutoff for y in topic_years) / len(topic_years)
    if baseline == 0:
        return "steady"
    ratio = recent / baseline
    return "rising" if ratio >= 1.5 else "fading" if ratio <= 0.5 else "steady"


def specificity(terms: list[str], topic_freq: Counter[str], n_topics: int) -> float:
    """Mean normalized IDF of the cluster's top terms; 0.5 when it has none."""
    scored = [t for t in terms[:3] if topic_freq.get(t.lower())]
    if not scored:
        return 0.5
    idf = [math.log(n_topics / topic_freq[t.lower()]) for t in scored]
    return min(1.0, float(np.mean(idf)) / math.log(n_topics))


def impact(stats: ClusterStats, spec: float, weights: Weights) -> float:
    n = len(stats.sets)
    frequency = math.sqrt(n) if weights.frequency_mode == "sqrt" else math.log1p(n)
    earliness = 1.0 - stats.median_position + weights.power_bonus * stats.share_in_power
    return float(
        frequency
        * max(earliness, 0.0) ** weights.earliness_exponent
        * spec**weights.specificity_exponent
        * (1.0 + weights.last_line_bonus * stats.share_last_line)
    )


def is_self_reference(terms: list[str], aliases: set[str]) -> bool:
    """A cluster made only of the topic's own names ("Invisible Man", "Ralph Ellison")."""
    return bool(terms) and all(normalize(t) in aliases for t in terms[:3])


def label_words(label: str) -> frozenset[str]:
    return frozenset(t.key for t in tokenize(label.rstrip("…"))) - STOPWORDS


def same_label(a: str, b: str) -> bool:
    """One label within the other: "Snow Queen" / "The Snow Queen", "Geiger and Marsden" /
    "Ernest Marsden and Hans Geiger". Clustering split one fact; pick it once."""
    words_a, words_b = label_words(a), label_words(b)
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)


def pick(
    candidates: list[tuple[int, float]],
    vectors: dict[int, np.ndarray],
    weights: Weights,
    labels: dict[int, str] | None = None,
) -> list[int]:
    """Maximal marginal relevance: high impact, but not near-duplicates of earlier picks.

    Redundancy is measured against the topic's own baseline: every clue about one novel
    resembles every other (same characters, same setting), so raw similarity would treat
    "Ras the Exhorter" as a duplicate of "Dr. Bledsoe" and skip the topic's most-asked clues.
    Only pairs more alike than the topic's typical pair count as duplicates. A candidate
    whose label repeats an earlier pick's (see ``same_label``) is skipped outright.
    """
    if not candidates:
        return []
    k = max(TOP_MIN, min(TOP_MAX, len(candidates)))
    top = max(score for _, score in candidates) or 1.0
    ids = [cid for cid, _ in candidates]
    index = {cid: i for i, cid in enumerate(ids)}
    matrix = np.stack([vectors[cid] for cid in ids])
    sims = matrix @ matrix.T
    n = len(ids)
    baseline = float((sims.sum() - np.trace(sims)) / (n * (n - 1))) if n > 1 else 0.0
    chosen: list[int] = []
    pool = dict(candidates)
    while pool and len(chosen) < k:

        def mmr(cid: int) -> float:
            raw = max((float(sims[index[cid], index[c]]) for c in chosen), default=baseline)
            redundancy = max(0.0, (raw - baseline) / max(1.0 - baseline, 1e-6))
            return weights.mmr_lambda * pool[cid] / top - (1 - weights.mmr_lambda) * redundancy

        best = max(pool, key=mmr)
        del pool[best]
        if labels and any(same_label(labels[best], labels[c]) for c in chosen):
            continue
        chosen.append(best)
    return chosen


def load_stats(conn: sqlite3.Connection) -> dict[str, list[ClusterStats]]:
    clusters: dict[int, ClusterStats] = {}
    for cid, topic_id, terms, rep in conn.execute(
        "SELECT k.id, k.topic_id, k.key_terms, c.text FROM clue_clusters k "
        "JOIN clues c ON c.id = k.representative_clue_id"
    ):
        clusters[cid] = ClusterStats(cid, topic_id, rep, json.loads(terms))
    for cid, position, in_power, last_line, difficulty, year, set_id in conn.execute(
        "SELECT m.cluster_id, c.position, c.in_power, c.ordinal = l.last_ordinal, "
        "t.difficulty, s.year, t.set_id "
        "FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
        "JOIN (SELECT tossup_id, MAX(ordinal) AS last_ordinal FROM clues "
        "      WHERE kind = 'clue' GROUP BY tossup_id) l ON l.tossup_id = c.tossup_id "
        "JOIN tossups t ON t.id = c.tossup_id JOIN sets s ON s.id = t.set_id"
    ):
        stats = clusters[cid]
        stats.positions.append(position)
        stats.in_power.append(in_power)
        stats.last_line.append(last_line)
        stats.difficulties.append(difficulty or 0)
        if year:
            stats.years.append(year)
        stats.sets.add(set_id)
    by_topic: dict[str, list[ClusterStats]] = defaultdict(list)
    for stats in clusters.values():
        by_topic[stats.topic_id].append(stats)
    return by_topic


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "clue_clusters", "cluster")
    db.recreate(conn, SCHEMA)
    weights = Weights(
        settings.score_power_bonus,
        settings.score_specificity_exponent,
        settings.score_min_sets,
        settings.score_mmr_lambda,
        settings.score_frequency_mode,
        settings.score_earliness_exponent,
        settings.score_last_line_bonus,
    )

    reporter.begin("Gathering cluster statistics", None)
    by_topic = load_stats(conn)
    topic_freq: Counter[str] = Counter()
    for clusters in by_topic.values():
        topic_freq.update({t.lower() for c in clusters for t in c.key_terms})
    n_topics = max(len(by_topic), 2)
    aliases: dict[str, set[str]] = defaultdict(set)
    for topic_id, alias in conn.execute("SELECT topic_id, alias_search FROM topic_aliases"):
        aliases[topic_id].add(alias)
    topic_size = dict(conn.execute("SELECT id, n_tossups FROM topics"))
    topic_years: dict[str, list[int]] = defaultdict(list)
    for topic_id, year in conn.execute(
        "SELECT tt.topic_id, s.year FROM tossup_topics tt JOIN tossups t ON t.id = tt.tossup_id "
        "JOIN sets s ON s.id = t.set_id WHERE s.year IS NOT NULL"
    ):
        topic_years[topic_id].append(year)
    cache = EmbeddingCache(settings.data_dir / "cache" / "embeddings" / "minilm.db")

    reporter.begin("Scoring clusters", len(by_topic))
    rows: list[tuple[object, ...]] = []
    ranked_topics = 0
    for topic_id, clusters in by_topic.items():
        min_sets = weights.min_sets if topic_size.get(topic_id, 0) >= 6 else 1
        scored = []
        for stats in clusters:
            spec = specificity(stats.key_terms, topic_freq, n_topics)
            value = impact(stats, spec, weights)
            eligible = len(stats.sets) >= min_sets and not is_self_reference(
                stats.key_terms, aliases[topic_id]
            )
            scored.append((stats, spec, value, eligible))
        candidates = sorted(
            ((s.cluster_id, v) for s, _, v, ok in scored if ok), key=lambda x: -x[1]
        )[:60]
        vectors = {}
        if candidates:
            reps = {s.cluster_id: s.representative for s, *_ in scored}
            matrix = cache.get([text_key(reps[cid]) for cid, _ in candidates])
            vectors = {cid: matrix[i] for i, (cid, _) in enumerate(candidates)}
        labels = {stats.cluster_id: display_label(stats, topic_freq) for stats, *_ in scored}
        picked = pick(candidates, vectors, weights, labels)
        ranks = {cid: r for r, cid in enumerate(picked, start=1)}
        ranked_topics += bool(ranks)
        for stats, spec, value, eligible in scored:
            bands = Counter(difficulty_band(d) for d in stats.difficulties)
            rows.append(
                (stats.cluster_id, topic_id, len(stats.sets), stats.median_position,
                 stats.share_in_power, stats.share_last_line, spec, value, int(eligible),
                 ranks.get(stats.cluster_id),
                 labels[stats.cluster_id],
                 json.dumps(position_hist(stats.positions)), json.dumps(dict(bands)),
                 min(stats.years, default=None), max(stats.years, default=None),
                 trend(stats.years, topic_years.get(topic_id, [])))
            )  # fmt: skip
        reporter.advance()
        if len(rows) > 50_000:
            conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 16)})", rows)
            rows.clear()
    conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 16)})", rows)
    conn.commit()
    reporter.stat("Topics with ranked clues", f"{ranked_topics:,} of {len(by_topic):,}")
    picked = conn.execute("SELECT COUNT(*) FROM cluster_scores WHERE rank IS NOT NULL").fetchone()[
        0
    ]
    reporter.stat("High-impact clues picked", f"{picked:,}")
    conn.close()
