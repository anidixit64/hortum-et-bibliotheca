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

Picking puts how many questions a clue appears in first: clues seen in more questions
always come before clues seen in fewer, and impact only orders clues seen equally often.
So a topic's picks start with its 3+ question clues, and two-question (or, for small
topics, one-question) clues fill in only when there aren't 10 of those. The last-line
bonus is the clue just before "for 10 points", not the giveaway ask. Giveaway facts
reach the hall from the terms stage, not from these clusters.

Clusters seen in fewer than ``min_sets`` sets (one set for small topics) or made only of
the topic's own names are left out. A candidate is skipped when it nearly duplicates an
earlier pick (in meaning, or by repeating its label with plurals folded). Heatmap
statistics are stored for every cluster: position histogram, difficulty bands, years and
a rising/steady/fading trend.

Labels come from what a cluster's clues share (see ``labeling``): the key term or noun
phrase named by the most of them. Only the clues naming the label (the cluster's core)
are counted and charted, so a cluster that took in a neighboring fact is judged by the
fact it's labeled with.
"""

import json
import math
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from hortum_common.text import normalize
from hortum_pipeline import db, labeling, phrases
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
    n_questions INTEGER NOT NULL,    -- questions whose clue names the label
    rank INTEGER,                    -- 1..10 for the picked clues, else NULL
    skipped TEXT,                    -- why an eligible clue wasn't picked
    display_label TEXT NOT NULL,     -- a specific name or noun phrase, or the opening words
    position_hist TEXT NOT NULL,     -- JSON: 10 bins from lead-in to end
    difficulty_hist TEXT NOT NULL,   -- JSON: {unrated, middle_school, high_school, college, open}
    first_year INTEGER,
    last_year INTEGER,
    trend TEXT NOT NULL              -- rising | steady | fading
);
CREATE INDEX cluster_scores_topic ON cluster_scores(topic_id, rank);
"""

TOP_MIN, TOP_MAX = 5, 10


# One clue in a cluster: id, position, in power, in the last line, difficulty, year, set,
# question.
Member = tuple[int, float, int, int, int, int | None, str, str]


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
    tossups: set[str] = field(default_factory=set)
    members: list[Member] = field(default_factory=list)

    def add(self, member: Member) -> None:
        _, position, in_power, last_line, difficulty, year, set_id, tossup = member
        self.members.append(member)
        self.positions.append(position)
        self.in_power.append(in_power)
        self.last_line.append(last_line)
        self.difficulties.append(difficulty or 0)
        if year:
            self.years.append(year)
        self.sets.add(set_id)
        self.tossups.add(tossup)

    def restrict(self, clue_ids: set[int], representative: str) -> "ClusterStats":
        """The same cluster counting only the given clues."""
        core = ClusterStats(self.cluster_id, self.topic_id, representative, self.key_terms)
        for member in self.members:
            if member[0] in clue_ids:
                core.add(member)
        return core

    @property
    def n_questions(self) -> int:
        return len(self.tossups)

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
    duplicate_threshold: float = 0.5  # redundancy above the topic baseline that skips a clue
    frequency_mode: str = "sqrt"  # "log": log(1 + sets); "sqrt": sqrt(sets) rewards common clues
    earliness_exponent: float = 0.25  # below 1 softens the penalty for mid-question clues
    last_line_bonus: float = 0.0  # extra weight for clues in the last line before the giveaway


_VAGUE_TOPICS = 50  # a term found in more topics than this is too generic to be a label


def specific_term(stats: ClusterStats, topic_freq: Counter[str]) -> str | None:
    """The most common key term that says something: "Peace", "Role" or "agent" can top a
    cluster's terms yet say nothing on their own."""
    for term in stats.key_terms:
        if topic_freq.get(term.lower(), 0) <= _VAGUE_TOPICS:
            return term
    return None


def display_label(stats: ClusterStats, topic_freq: Counter[str], phrase: str | None = None) -> str:
    """A specific key term, else the cluster's noun phrase, else the clue's opening words."""
    term = specific_term(stats, topic_freq)
    if term:
        return term
    if phrase:
        return phrase
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
    words = {t.key for t in tokenize(label.rstrip("…"))} - STOPWORDS
    return frozenset(normalize(w, singularize=True) for w in words)


def same_label(a: str, b: str) -> bool:
    """One label within the other: "Snow Queen" / "The Snow Queen", "Geiger and Marsden" /
    "Ernest Marsden and Hans Geiger", "womb chamber" / "womb chambers". Clustering split
    one fact; pick it once."""
    words_a, words_b = label_words(a), label_words(b)
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)


def pick(
    candidates: list[tuple[int, float]],
    vectors: dict[int, np.ndarray],
    weights: Weights,
    labels: dict[int, str] | None = None,
    questions: dict[int, int] | None = None,
    overlap: Callable[[int, int], bool] | None = None,
    reasons: dict[int, str] | None = None,
) -> list[int]:
    """Up to 10 clues, most questions first (impact breaks ties), skipping near-duplicates.

    Redundancy is measured against the topic's own baseline: every clue about one novel
    resembles every other (same characters, same setting), so raw similarity would treat
    "Ras the Exhorter" as a duplicate of "Dr. Bledsoe" and skip the topic's most-asked clues.
    A candidate counts as a duplicate when it's more alike than the topic's typical pair by
    ``duplicate_threshold`` of the remaining distance, when its label repeats an earlier
    pick's (see ``same_label``), or when ``overlap`` says the two state one fact. Why each
    unpicked candidate was skipped goes in ``reasons``.
    """
    if not candidates:
        return []
    k = max(TOP_MIN, min(TOP_MAX, len(candidates)))
    counts = questions or {}
    ordered = sorted(candidates, key=lambda c: (-counts.get(c[0], 0), -c[1], c[0]))
    ids = [cid for cid, _ in ordered]
    index = {cid: i for i, cid in enumerate(ids)}
    matrix = np.stack([vectors[cid] for cid in ids])
    sims = matrix @ matrix.T
    n = len(ids)
    baseline = float((sims.sum() - np.trace(sims)) / (n * (n - 1))) if n > 1 else 0.0
    chosen: list[int] = []
    why = reasons if reasons is not None else {}
    for cid in ids:
        if len(chosen) == k:
            why[cid] = "full"
            continue
        sim, near = max(
            ((float(sims[index[cid], index[c]]), c) for c in chosen), default=(baseline, None)
        )
        redundancy = max(0.0, (sim - baseline) / max(1.0 - baseline, 1e-6))
        if redundancy > weights.duplicate_threshold:
            why[cid] = f"similar to {near}"
            continue
        repeat = next((c for c in chosen if labels and same_label(labels[cid], labels[c])), None)
        if repeat is not None:
            why[cid] = f"same label as {repeat}"
            continue
        same_fact = next((c for c in chosen if overlap and overlap(cid, c)), None)
        if same_fact is not None:
            why[cid] = f"same fact as {same_fact}"
            continue
        chosen.append(cid)
    return chosen


def load_stats(conn: sqlite3.Connection) -> dict[str, list[ClusterStats]]:
    clusters: dict[int, ClusterStats] = {}
    for cid, topic_id, terms, rep_text in conn.execute(
        "SELECT k.id, k.topic_id, k.key_terms, c.text FROM clue_clusters k "
        "JOIN clues c ON c.id = k.representative_clue_id"
    ):
        clusters[cid] = ClusterStats(cid, topic_id, rep_text, json.loads(terms))
    for cid, *member in conn.execute(
        "SELECT m.cluster_id, c.id, c.position, c.in_power, "
        "COALESCE(c.ordinal = l.last_ordinal, 0), "
        "t.difficulty, s.year, t.set_id, t.id "
        "FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
        "LEFT JOIN (SELECT tossup_id, MAX(ordinal) AS last_ordinal FROM clues "
        "      WHERE kind = 'clue' GROUP BY tossup_id) l ON l.tossup_id = c.tossup_id "
        "JOIN tossups t ON t.id = c.tossup_id JOIN sets s ON s.id = t.set_id"
    ):
        clusters[cid].add(tuple(member))
    by_topic: dict[str, list[ClusterStats]] = defaultdict(list)
    for stats in clusters.values():
        by_topic[stats.topic_id].append(stats)
    return by_topic


def load_texts(
    conn: sqlite3.Connection, cluster_ids: list[int]
) -> dict[int, list[tuple[int, str, list[str]]]]:
    """(clue id, text, key terms) of every clue in the given clusters."""
    out: dict[int, list[tuple[int, str, list[str]]]] = defaultdict(list)
    for start in range(0, len(cluster_ids), 900):
        chunk = cluster_ids[start : start + 900]
        for cid, clue_id, text, terms in conn.execute(
            "SELECT m.cluster_id, c.id, c.text, c.key_terms FROM clue_cluster_members m "
            "JOIN clues c ON c.id = m.clue_id "
            f"WHERE m.cluster_id IN ({','.join('?' * len(chunk))}) ORDER BY c.id",
            chunk,
        ):
            out[cid].append((clue_id, text, json.loads(terms)))
    return out


def run(
    settings: PipelineSettings,
    reporter: Reporter,
    parser_factory: Callable[[], phrases.Parser] = phrases.load_parser,
) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "clue_clusters", "cluster")
    db.recreate(conn, SCHEMA)
    weights = Weights(
        settings.score_power_bonus,
        settings.score_specificity_exponent,
        settings.score_min_sets,
        settings.score_duplicate_threshold,
        settings.score_frequency_mode,
        settings.score_earliness_exponent,
        settings.score_last_line_bonus,
    )

    reporter.begin("Gathering cluster statistics", None)
    by_topic = load_stats(conn)
    by_id = {stats.cluster_id: stats for clusters in by_topic.values() for stats in clusters}
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

    freq = phrases.DocFrequency.from_corpus(conn)

    reporter.begin("Labeling clusters", None)
    eligible: dict[int, bool] = {}
    for topic_id, clusters in by_topic.items():
        min_sets = weights.min_sets if topic_size.get(topic_id, 0) >= 6 else 1
        for stats in clusters:
            eligible[stats.cluster_id] = len(stats.sets) >= min_sets and not is_self_reference(
                stats.key_terms, aliases[topic_id]
            )
    members = load_texts(conn, [cid for cid, ok in eligible.items() if ok])

    name_words: dict[str, frozenset[str]] = defaultdict(frozenset)
    for topic_id, names in aliases.items():
        name_words[topic_id] = frozenset().union(*(labeling.word_set(n) for n in names))

    def usable(topic_id: str) -> Callable[[str], bool]:
        def check(term: str) -> bool:
            if topic_freq.get(term.lower(), 0) > _VAGUE_TOPICS:
                return False
            words = labeling.label_words(term)
            return bool(words) and not words <= name_words[topic_id]  # the answer's own name

        return check

    choices: dict[int, labeling.Choice] = {}
    need_phrases: list[int] = []
    for cid, rows_ in members.items():
        choice = labeling.choose(
            [t for _, t, _ in rows_], [k for *_, k in rows_], usable(by_id[cid].topic_id), freq
        )
        if choice:
            choices[cid] = choice
        else:
            need_phrases.append(cid)
    reporter.stat("Clusters labeled by a key term", f"{len(choices):,} of {len(members):,}")
    parse = parser_factory()
    flat = [labeling.clean(t) for cid in need_phrases for _, t, _ in members[cid]]
    docs = iter(parse(flat))
    for cid in need_phrases:
        rows_ = members[cid]
        cluster_docs = [next(docs) for _ in rows_]
        choice = labeling.choose(
            [t for _, t, _ in rows_],
            [k for *_, k in rows_],
            usable(by_id[cid].topic_id),
            freq,
            cluster_docs,
        )
        assert choice is not None
        choices[cid] = choice
    reporter.stat(
        "… by a noun phrase / opening words",
        f"{sum(c.source == 'phrase' for c in choices.values()):,} / "
        f"{sum(c.source == 'opening' for c in choices.values()):,}",
    )

    # Count and chart each eligible cluster by its core: the clues naming its label.
    core: dict[int, ClusterStats] = {}
    core_words: dict[int, list[frozenset[str]]] = {}
    for cid, choice in choices.items():
        rows_ = members[cid]
        kept = {rows_[i][0] for i in choice.core}
        representative = by_id[cid].representative
        if not any(rows_[i][1] == representative for i in choice.core):
            representative = rows_[choice.core[0]][1]
        core[cid] = by_id[cid].restrict(kept, representative)
        topic_id = by_id[cid].topic_id
        min_sets = weights.min_sets if topic_size.get(topic_id, 0) >= 6 else 1
        if len(core[cid].sets) < min_sets:
            eligible[cid] = False  # only one set states the labeled fact
        core_words[cid] = [labeling.word_set(labeling.clean(rows_[i][1])) for i in choice.core]

    # A cluster's anchors: other terms most of its core names ("Bonus Army" in clues
    # labeled "Douglas MacArthur"). Two clusters sharing an anchor that no third cluster of
    # the topic has state one fact.
    anchors: dict[int, set[str]] = {}
    anchor_users: dict[tuple[str, str], int] = defaultdict(int)
    for cid, choice in choices.items():
        if len(choice.core) < 2:
            anchors[cid] = set()
            continue
        rows_ = members[cid]
        counts: Counter[str] = Counter()
        for i in choice.core:
            counts.update({t for t in map(labeling.tidy, rows_[i][2]) if t})
        check = usable(by_id[cid].topic_id)
        anchors[cid] = {
            fold
            for term, n in counts.items()
            if n * 2 >= len(choice.core) and check(term) and not labeling.plain_word(term, freq)
            for fold in [" ".join(sorted(labeling.label_words(term)))]
            if fold
        }
        for fold in anchors[cid]:
            anchor_users[(by_id[cid].topic_id, fold)] += 1

    def overlap(a: int, b: int) -> bool:
        """Two clusters state one fact: most clues of either name the other's label, or
        they share an anchor no other cluster of the topic has."""
        for x, y in ((a, b), (b, a)):
            words = core_words[y]
            if sum(labeling.names(w, choices[x].label) for w in words) * 2 >= len(words):
                return True
        topic_id = by_id[a].topic_id
        return any(anchor_users[(topic_id, f)] == 2 for f in anchors[a] & anchors[b])

    reporter.begin("Picking clues", len(by_topic))
    rows: list[tuple[object, ...]] = []
    ranked_topics = 0
    for topic_id, clusters in by_topic.items():
        scored = []
        for stats in clusters:
            view = core.get(stats.cluster_id, stats)
            spec = specificity(view.key_terms, topic_freq, n_topics)
            scored.append((view, spec, impact(view, spec, weights), eligible[stats.cluster_id]))
        candidates = sorted(
            ((v.cluster_id, value) for v, _, value, ok in scored if ok),
            key=lambda x: (-core[x[0]].n_questions, -x[1]),
        )[:60]
        vectors = {}
        if candidates:
            matrix = cache.get([text_key(core[cid].representative) for cid, _ in candidates])
            vectors = {cid: matrix[i] for i, (cid, _) in enumerate(candidates)}
        labels = {
            v.cluster_id: choices[v.cluster_id].label
            if v.cluster_id in choices
            else display_label(v, topic_freq)
            for v, *_ in scored
        }
        questions = {v.cluster_id: v.n_questions for v, *_ in scored}
        reasons: dict[int, str] = {}
        picked = pick(candidates, vectors, weights, labels, questions, overlap, reasons)
        ranks = {cid: r for r, cid in enumerate(picked, start=1)}
        ranked_topics += bool(ranks)
        for view, spec, value, ok in scored:
            bands = Counter(difficulty_band(d) for d in view.difficulties)
            rows.append(
                (view.cluster_id, topic_id, len(view.sets), view.median_position,
                 view.share_in_power, view.share_last_line, spec, value, int(ok),
                 view.n_questions, ranks.get(view.cluster_id),
                 reasons.get(view.cluster_id) if ok else None,
                 labels[view.cluster_id],
                 json.dumps(position_hist(view.positions)), json.dumps(dict(bands)),
                 min(view.years, default=None), max(view.years, default=None),
                 trend(view.years, topic_years.get(topic_id, [])))
            )  # fmt: skip
        reporter.advance()
        if len(rows) > 50_000:
            conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 18)})", rows)
            rows.clear()
    conn.executemany(f"INSERT INTO cluster_scores VALUES ({','.join('?' * 18)})", rows)
    conn.commit()
    reporter.stat("Topics with ranked clues", f"{ranked_topics:,} of {len(by_topic):,}")
    picked = conn.execute("SELECT COUNT(*) FROM cluster_scores WHERE rank IS NOT NULL").fetchone()[
        0
    ]
    reporter.stat("High-impact clues picked", f"{picked:,}")
    conn.close()
