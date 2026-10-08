"""Stage 7: rank each topic's clue clusters and pick its most common clues.

Clues are picked in order of how often they're asked: the number of distinct sets a
cluster appears in, then the number of questions, then the earlier median position. Only
clues above the giveaway count; the giveaway sentence itself is never a clue (see clues.py).

A topic gets 10 picks, rising to 20 for the most-asked topics (10 at 10 questions or fewer,
15 at about 32, 20 at 100 or more). Clusters seen in fewer than ``min_sets`` sets (one set
for small topics) or made only of the topic's own names are left out.

Heatmap statistics are stored for every cluster: position histogram, difficulty bands,
years and a rising/steady/fading trend. ``impact`` keeps the earlier earliness-weighted
score (sqrt(sets) * earliness ** 0.25) for display; it no longer decides the picks.
"""

import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from hortum_common.text import normalize
from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS cluster_scores;
CREATE TABLE cluster_scores (
    cluster_id INTEGER PRIMARY KEY REFERENCES clue_clusters(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    n_sets INTEGER NOT NULL,
    median_position REAL NOT NULL,
    share_in_power REAL NOT NULL,
    specificity REAL NOT NULL,
    impact REAL NOT NULL,
    eligible INTEGER NOT NULL,
    rank INTEGER,                    -- 1..20 for the picked clues, else NULL
    display_label TEXT NOT NULL,     -- a specific name, or the clue's opening words
    position_hist TEXT NOT NULL,     -- JSON: 10 bins from lead-in to end
    difficulty_hist TEXT NOT NULL,   -- JSON: {unrated, middle_school, high_school, college, open}
    first_year INTEGER,
    last_year INTEGER,
    trend TEXT NOT NULL              -- rising | steady | fading
);
CREATE INDEX cluster_scores_topic ON cluster_scores(topic_id, rank);
"""

TOP_MIN, TOP_MAX = 10, 20


@dataclass
class ClusterStats:
    cluster_id: int
    topic_id: str
    representative: str
    key_terms: list[str]
    positions: list[float] = field(default_factory=list)
    in_power: list[int] = field(default_factory=list)
    difficulties: list[int] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    sets: set[str] = field(default_factory=set)
    tossups: set[str] = field(default_factory=set)

    @property
    def median_position(self) -> float:
        return float(np.median(self.positions))

    @property
    def share_in_power(self) -> float:
        return sum(self.in_power) / len(self.in_power)


@dataclass(frozen=True)
class Weights:
    power_bonus: float = 0.0
    specificity_exponent: float = 0.0
    min_sets: int = 2
    frequency_mode: str = "sqrt"  # "log": log(1 + sets); "sqrt": sqrt(sets) rewards common clues
    earliness_exponent: float = 0.25  # below 1 softens the penalty for mid-question clues


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
    )


def is_self_reference(terms: list[str], aliases: set[str]) -> bool:
    """A cluster made only of the topic's own names ("Invisible Man", "Ralph Ellison")."""
    return bool(terms) and all(normalize(t) in aliases for t in terms[:3])


def pick_count(n_tossups: int) -> int:
    """10 picks for a topic asked 10 times or fewer, 20 for one asked 100+ times."""
    if n_tossups <= 10:
        return TOP_MIN
    return min(TOP_MAX, round(TOP_MIN + 10 * math.log10(n_tossups / 10)))


def pick(candidates: list[ClusterStats], n_tossups: int) -> list[int]:
    """The most common clusters first: most sets, then most questions, then earliest."""
    ordered = sorted(
        candidates,
        key=lambda c: (-len(c.sets), -len(c.tossups), c.median_position, c.cluster_id),
    )
    return [c.cluster_id for c in ordered[: pick_count(n_tossups)]]


def load_stats(conn: sqlite3.Connection) -> dict[str, list[ClusterStats]]:
    clusters: dict[int, ClusterStats] = {}
    for cid, topic_id, terms, rep in conn.execute(
        "SELECT k.id, k.topic_id, k.key_terms, c.text FROM clue_clusters k "
        "JOIN clues c ON c.id = k.representative_clue_id"
    ):
        clusters[cid] = ClusterStats(cid, topic_id, rep, json.loads(terms))
    for cid, position, in_power, difficulty, year, set_id, tossup_id in conn.execute(
        "SELECT m.cluster_id, c.position, c.in_power, t.difficulty, s.year, t.set_id, t.id "
        "FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
        "JOIN tossups t ON t.id = c.tossup_id JOIN sets s ON s.id = t.set_id"
    ):
        stats = clusters[cid]
        stats.positions.append(position)
        stats.in_power.append(in_power)
        stats.difficulties.append(difficulty or 0)
        if year:
            stats.years.append(year)
        stats.sets.add(set_id)
        stats.tossups.add(tossup_id)
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
        settings.score_frequency_mode,
        settings.score_earliness_exponent,
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
        candidates = [stats for stats, _, _, eligible in scored if eligible]
        ranks = {
            cid: r for r, cid in enumerate(pick(candidates, topic_size.get(topic_id, 0)), start=1)
        }
        ranked_topics += bool(ranks)
        for stats, spec, value, eligible in scored:
            bands = Counter(difficulty_band(d) for d in stats.difficulties)
            rows.append(
                (stats.cluster_id, topic_id, len(stats.sets), stats.median_position,
                 stats.share_in_power, spec, value, int(eligible), ranks.get(stats.cluster_id),
                 display_label(stats, topic_freq),
                 json.dumps(position_hist(stats.positions)), json.dumps(dict(bands)),
                 min(stats.years, default=None), max(stats.years, default=None),
                 trend(stats.years, topic_years.get(topic_id, [])))
            )  # fmt: skip
        reporter.advance()
        if len(rows) > 50_000:
            conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 15)})", rows)
            rows.clear()
    conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 15)})", rows)
    conn.commit()
    reporter.stat("Topics with ranked clues", f"{ranked_topics:,} of {len(by_topic):,}")
    picked = conn.execute("SELECT COUNT(*) FROM cluster_scores WHERE rank IS NOT NULL").fetchone()[
        0
    ]
    reporter.stat("High-impact clues picked", f"{picked:,}")
    conn.close()
