"""Checks that each stage's output in corpus.db is complete and sane.

Every check is a small SQL-backed assertion with a threshold. They run automatically after
each stage (a failure stops the pipeline) and on demand with ``hortum-pipeline verify``.
The golden lists pin answers whose correct result was confirmed by hand, so a scoring
change that breaks them is caught immediately.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hortum_common.text import normalize
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.overrides import OverrideStore


@dataclass
class Check:
    stage: str
    name: str
    passed: bool
    detail: str


CheckFn = Callable[[sqlite3.Connection, PipelineSettings], list[Check]]

# (answer as written, category, subcategory or "") -> Wikipedia title, each confirmed by hand.
GOLDEN_LINKS: list[tuple[str, str, str, str]] = [
    ("Immanuel Kant", "Philosophy", "", "Immanuel Kant"),
    ("Emily Dickinson", "Literature", "", "Emily Dickinson"),
    ("Jorge Luis Borges", "Literature", "", "Jorge Luis Borges"),
    ("Johannes Brahms", "Fine Arts", "", "Johannes Brahms"),
    ("Sikhism", "Religion", "", "Sikhism"),
    ("friction", "Science", "Physics", "Friction"),
    ("Odin", "Mythology", "", "Odin"),
    ("entropy", "Science", "Physics", "Entropy"),
    ("Charlemagne", "History", "", "Charlemagne"),
    ("mitochondria", "Science", "Biology", "Mitochondria"),
    ("Howl", "Literature", "American Literature", "Howl (poem)"),
    ("moment of inertia", "Science", "Physics", "Moment of inertia"),
    ("Invisible Man", "Literature", "American Literature", "Invisible Man"),
    ("reflection", "Science", "Physics", "Reflection (physics)"),
    ("Quetzalcoatl", "Mythology", "", "Quetzalcōātl"),
    ("apoptosis", "Science", "Biology", "Apoptosis"),
    ("William Butler Yeats", "Literature", "British Literature", "W. B. Yeats"),
    ("Gibbs free energy", "Science", "Chemistry", "Gibbs free energy"),
    # The cases that drove the linking design:
    ("mercury", "Science", "Chemistry", "Mercury (element)"),
    ("Mercury", "Science", "Other Science", "Mercury (planet)"),
    ("The Republic", "Philosophy", "", "Republic (Plato)"),
    ("The Awakening", "Literature", "American Literature", "The Awakening (Chopin novel)"),
    ("France", "Fine Arts", "Auditory Fine Arts", "France"),
    ("the moon", "Mythology", "", "Moon"),
    ("snakes", "Mythology", "", "Snake"),
    ("free radicals", "Science", "Biology", "Radical (chemistry)"),
    ("soccer", "Pop Culture", "", "Association football"),
]
GOLDEN_MIN_SHARE = 0.9  # Wikipedia titles get renamed; allow a little drift

# Facts confirmed by hand: (Wikipedia title, property, expected value prefix)
GOLDEN_FACTS = [
    ("Leo Tolstoy", "P569", "1828-09-09"),
    ("Immanuel Kant", "P569", "1724-04-22"),
]


def _one(conn: sqlite3.Connection, sql: str, *args: object) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0] or 0)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def check_ingest(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    n = _one(conn, "SELECT COUNT(*) FROM tossups")
    meta = dict(conn.execute("SELECT key, value FROM pipeline_meta WHERE stage = 'ingest'"))
    lines = int(meta.get("source_lines", -1))
    accounted = n + int(meta.get("duplicates", 0)) + int(meta.get("skipped", 0))
    out.append(
        Check(
            "ingest",
            "every source line kept, deduplicated or skipped",
            accounted == lines,
            f"{n:,} kept + {meta.get('duplicates')} duplicates + {meta.get('skipped')} "
            f"skipped = {accounted:,} of {lines:,} lines",
        )
    )
    empty = _one(conn, "SELECT COUNT(*) FROM tossups WHERE question_text = '' OR answer_text = ''")
    out.append(Check("ingest", "no empty questions or answers", empty == 0, f"{empty} empty"))
    orphans = _one(
        conn,
        "SELECT COUNT(*) FROM tossups t LEFT JOIN sets s ON s.id = t.set_id WHERE s.id IS NULL",
    )
    out.append(
        Check("ingest", "every question belongs to a known set", orphans == 0, f"{orphans} orphans")
    )
    dangling = _one(
        conn,
        "SELECT COUNT(*) FROM tossup_duplicates d LEFT JOIN tossups t ON t.id = d.kept_id "
        "WHERE t.id IS NULL",
    )
    out.append(
        Check("ingest", "duplicates point at kept questions", dangling == 0, f"{dangling} dangling")
    )
    return out


def check_parse(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    n = _one(conn, "SELECT COUNT(*) FROM tossups")
    parsed = _one(conn, "SELECT COUNT(*) FROM answer_parses")
    out.append(
        Check("parse-answers", "every question parsed once", parsed == n, f"{parsed:,} of {n:,}")
    )
    confident = _one(
        conn, "SELECT COUNT(*) FROM answer_parses WHERE confidence >= ?", settings.review_threshold
    )
    share = confident / max(parsed, 1)
    out.append(
        Check(
            "parse-answers",
            "≥95% of answers confident or fixed by hand",
            share >= 0.95,
            f"{share:.2%} at confidence ≥ {settings.review_threshold}",
        )
    )
    store = OverrideStore(settings.answer_overrides_path)
    stale = 0
    for fix in store.all():
        want = "excluded" if fix.exclude else "override"
        rows = conn.execute(
            "SELECT DISTINCT source, main FROM answer_parses WHERE line_key = ?", (fix.line_key,)
        ).fetchall()
        if any(src != want or (not fix.exclude and main != fix.main) for src, main in rows):
            stale += 1
    out.append(
        Check(
            "parse-answers",
            "every hand fix is applied",
            stale == 0,
            f"{len(store):,} fixes, {stale} not applied",
        )
    )
    blank = _one(
        conn, "SELECT COUNT(*) FROM answer_parses WHERE source != 'excluded' AND main = ''"
    )
    out.append(
        Check("parse-answers", "no blank answers outside exclusions", blank == 0, f"{blank} blank")
    )
    return out


def check_group(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    eligible = _one(
        conn,
        "SELECT COUNT(*) FROM answer_parses WHERE source != 'excluded' AND main_norm != '' "
        "AND confidence >= ?",
        settings.group_min_confidence,
    )
    grouped = _one(conn, "SELECT COUNT(*) FROM tossup_groups")
    summed = _one(conn, "SELECT SUM(n_tossups) FROM candidate_groups")
    return [
        Check(
            "group",
            "every eligible answer in exactly one group",
            grouped == eligible,
            f"{grouped:,} grouped of {eligible:,} eligible",
        ),
        Check("group", "group sizes add up", summed == grouped, f"{summed:,} vs {grouped:,}"),
    ]


def check_link(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    groups = _one(conn, "SELECT COUNT(*) FROM candidate_groups")
    status = dict(conn.execute("SELECT status, COUNT(*) FROM group_links GROUP BY status"))
    decided = sum(status.values())
    out.append(
        Check("link", "every group has a decision", decided == groups, f"{decided:,} of {groups:,}")
    )
    if settings.link_new_requests is None:
        skipped = status.get("skipped", 0)
        out.append(Check("link", "no groups skipped", skipped == 0, f"{skipped:,} skipped"))
    rate = status.get("linked", 0) / max(groups, 1)
    out.append(Check("link", "≥85% of groups linked", rate >= 0.85, f"{rate:.1%} linked"))
    bad = _one(
        conn,
        "SELECT COUNT(*) FROM group_links WHERE status='linked' AND (qid IS NULL OR title IS NULL)",
    )
    out.append(Check("link", "linked groups have an ID and title", bad == 0, f"{bad} incomplete"))
    in_topics = _one(conn, "SELECT COUNT(*) FROM tossup_topics")
    grouped = _one(conn, "SELECT COUNT(*) FROM tossup_groups")
    out.append(
        Check(
            "link",
            "every grouped question has a topic",
            in_topics == grouped,
            f"{in_topics:,} of {grouped:,}",
        )
    )
    summed = _one(conn, "SELECT SUM(n_tossups) FROM topics")
    out.append(
        Check("link", "topic sizes add up", summed == in_topics, f"{summed:,} vs {in_topics:,}")
    )
    aliases = _one(conn, "SELECT COUNT(*) FROM topic_aliases")
    indexed = _one(conn, "SELECT COUNT(*) FROM topic_aliases_fts")
    out.append(
        Check(
            "link",
            "search index covers every alias",
            indexed == aliases,
            f"{indexed:,} indexed of {aliases:,}",
        )
    )

    hits, misses = 0, []
    for answer, category, subcategory, title in GOLDEN_LINKS:
        sql = (
            "SELECT l.title FROM candidate_groups g JOIN group_links l ON l.group_id = g.id "
            "WHERE g.norm_key = ? AND g.category = ?"
        )
        args: list[object] = [normalize(answer, singularize=True), category]
        if subcategory:
            sql += " AND g.subcategory = ?"
            args.append(subcategory)
        row = conn.execute(sql + " ORDER BY g.n_tossups DESC LIMIT 1", args).fetchone()
        if row and row[0] == title:
            hits += 1
        else:
            misses.append(f"{answer} → {row[0] if row else 'missing'} (want {title})")
    share = hits / len(GOLDEN_LINKS)
    out.append(
        Check(
            "link",
            f"golden links ≥{GOLDEN_MIN_SHARE:.0%} correct",
            share >= GOLDEN_MIN_SHARE,
            f"{hits}/{len(GOLDEN_LINKS)}" + (f"; misses: {'; '.join(misses)}" if misses else ""),
        )
    )
    return out


def check_facts(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    linked = _one(conn, "SELECT COUNT(*) FROM topics WHERE wikidata_qid IS NOT NULL")
    described = _one(
        conn,
        "SELECT COUNT(*) FROM topics WHERE wikidata_qid IS NOT NULL AND description IS NOT NULL",
    )
    share = described / max(linked, 1)
    out.append(
        Check(
            "facts",
            "≥90% of linked topics have a description",
            share >= 0.9,
            f"{share:.1%} of {linked:,}",
        )
    )
    orphan = _one(
        conn,
        "SELECT COUNT(*) FROM topic_facts f LEFT JOIN topics t ON t.id = f.topic_id "
        "WHERE t.id IS NULL",
    )
    out.append(Check("facts", "facts belong to known topics", orphan == 0, f"{orphan} orphans"))
    for title, prop, prefix in GOLDEN_FACTS:
        values = [
            json.loads(v).get("time", "")
            for (v,) in conn.execute(
                "SELECT f.value FROM topic_facts f JOIN topics t ON t.id = f.topic_id "
                "WHERE t.wikipedia_title = ? AND f.property = ?",
                (title, prop),
            )
        ]
        ok = any(v.lstrip("+").startswith(prefix) for v in values)
        out.append(Check("facts", f"{title} {prop} = {prefix}", ok, ", ".join(values) or "missing"))
    return out


def check_search(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    """End-to-end: the catalog's search over this corpus.db (skipped if not importable)."""
    try:
        from catalog.search import SearchIndex
    except ImportError:
        return [
            Check("search", "catalog search importable", True, "skipped: catalog not installed")
        ]
    index = SearchIndex(settings.corpus_path)
    expectations = [
        ("socer", "Association football"),
        ("futbol", "Association football"),
        ("the republic", "Republic (Plato)"),
        ("the moon", "Moon"),
        ("kant", "Immanuel Kant"),
        ("the awakening", "The Awakening (Chopin novel)"),
    ]
    out = []
    for query, want in expectations:
        top = [r.name for r in index.search(query, 1)]
        out.append(Check("search", f"'{query}' → {want}", top[:1] == [want], f"got {top[:1]}"))
    senses = {r.name for r in index.search("Mercury", 3)}
    want_senses = {"Mercury (element)", "Mercury (planet)"}
    out.append(
        Check(
            "search",
            "'Mercury' → element and planet in top 3",
            want_senses <= senses,
            f"got {sorted(senses)}",
        )
    )
    return out


def check_clues(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    n = _one(conn, "SELECT COUNT(*) FROM tossups")
    laid_out = _one(conn, "SELECT COUNT(*) FROM question_layout")
    out.append(Check("clues", "every question split", laid_out == n, f"{laid_out:,} of {n:,}"))
    empty = _one(conn, "SELECT COUNT(*) FROM question_layout WHERE n_clues = 0")
    out.append(Check("clues", "every question has a clue", empty == 0, f"{empty} without"))

    bad = 0
    total = 0
    for clean, start, end, text in conn.execute(
        "SELECT l.clean_text, c.char_start, c.char_end, c.text "
        "FROM clues c JOIN question_layout l ON l.tossup_id = c.tossup_id"
    ):
        total += 1
        bad += clean[start:end] != text
    out.append(
        Check(
            "clues",
            "every clue's span reproduces its text exactly",
            bad == 0,
            f"{bad} of {total:,} differ",
        )
    )

    marked = _one(conn, "SELECT COUNT(*) FROM tossups WHERE question_text LIKE '%(*)%'")
    found = _one(conn, "SELECT COUNT(*) FROM question_layout WHERE power_char IS NOT NULL")
    out.append(
        Check(
            "clues",
            "every power mark located",
            found == marked,
            f"{found:,} of {marked:,} marked questions",
        )
    )

    with_giveaway = _one(
        conn, "SELECT COUNT(DISTINCT tossup_id) FROM clues WHERE kind = 'giveaway'"
    )
    share = with_giveaway / max(n, 1)
    out.append(Check("clues", "giveaway found in ≥95% of questions", share >= 0.95, f"{share:.1%}"))

    counts = sorted(
        r[0]
        for r in conn.execute("SELECT COUNT(*) FROM clues WHERE kind = 'clue' GROUP BY tossup_id")
    )
    median = counts[len(counts) // 2] if counts else 0
    out.append(
        Check(
            "clues",
            "median clues per question between 3 and 9",
            3 <= median <= 9,
            f"median {median}",
        )
    )
    clues = _one(conn, "SELECT COUNT(*) FROM clues WHERE kind = 'clue'")
    tiny = _one(
        conn,
        "SELECT COUNT(*) FROM clues WHERE kind = 'clue' "
        "AND length(text) - length(replace(text, ' ', '')) < 3",
    )
    out.append(
        Check(
            "clues",
            "under 2% of clues are fragments (<4 words)",
            tiny / max(clues, 1) < 0.02,
            f"{tiny:,} of {clues:,}",
        )
    )
    return out


def check_cluster(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    topical = _one(conn, "SELECT COUNT(*) FROM clues WHERE kind = 'clue' AND topic_id IS NOT NULL")
    assigned = _one(conn, "SELECT COUNT(*) FROM clue_cluster_members")
    out.append(
        Check(
            "cluster",
            "every topical clue in exactly one cluster",
            assigned == topical,
            f"{assigned:,} of {topical:,}",
        )
    )
    summed = _one(conn, "SELECT SUM(n_clues) FROM clue_clusters")
    out.append(
        Check("cluster", "cluster sizes add up", summed == assigned, f"{summed:,} vs {assigned:,}")
    )
    crossed = _one(
        conn,
        "SELECT COUNT(*) FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
        "JOIN clue_clusters k ON k.id = m.cluster_id WHERE c.topic_id != k.topic_id",
    )
    out.append(
        Check("cluster", "clusters never cross topics", crossed == 0, f"{crossed} crossings")
    )
    stray = _one(
        conn,
        "SELECT COUNT(*) FROM clue_clusters k LEFT JOIN clue_cluster_members m "
        "ON m.clue_id = k.representative_clue_id AND m.cluster_id = k.id WHERE m.clue_id IS NULL",
    )
    out.append(
        Check(
            "cluster", "each representative belongs to its cluster", stray == 0, f"{stray} strays"
        )
    )
    if settings.labels_path.is_file():
        f1, pairs = labeled_pair_f1(conn, settings)
        out.append(
            Check(
                "cluster",
                "same-fact pairs F1 ≥ 0.70 on labeled topics",
                f1 >= 0.70,
                f"F1 {f1:.3f} over {pairs:,} labeled pairs",
            )
        )
    return out


def labeled_pair_f1(conn: sqlite3.Connection, settings: PipelineSettings) -> tuple[float, int]:
    """Pairwise F1: do clues naming the same labeled fact share a cluster, and only those?"""
    from hortum_pipeline.labels import load

    tp = fp = fn = pairs = 0
    for topic in load(settings.labels_path):
        rows = conn.execute(
            "SELECT c.text, m.cluster_id FROM clues c "
            "JOIN clue_cluster_members m ON m.clue_id = c.id WHERE c.topic_id = ?",
            (topic.id,),
        ).fetchall()
        tagged = []
        for text, cluster_id in rows:
            hits = [i for i, clue in enumerate(topic.clues) if clue.found_in(text)]
            if len(hits) == 1:
                tagged.append((hits[0], cluster_id))
        for a in range(len(tagged)):
            for b in range(a + 1, len(tagged)):
                same_fact = tagged[a][0] == tagged[b][0]
                same_cluster = tagged[a][1] == tagged[b][1]
                tp += same_fact and same_cluster
                fp += (not same_fact) and same_cluster
                fn += same_fact and not same_cluster
                pairs += 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return 2 * precision * recall / max(precision + recall, 1e-9), pairs


def check_score(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
    out = []
    clusters = _one(conn, "SELECT COUNT(*) FROM clue_clusters")
    scored = _one(conn, "SELECT COUNT(*) FROM cluster_scores")
    out.append(
        Check("score", "every cluster scored", scored == clusters, f"{scored:,} of {clusters:,}")
    )
    bad_rank = _one(
        conn,
        "SELECT COUNT(*) FROM (SELECT topic_id, COUNT(rank) n, MAX(rank) m FROM cluster_scores "
        "WHERE rank IS NOT NULL GROUP BY topic_id) WHERE n > 10 OR m != n",
    )
    out.append(
        Check(
            "score",
            "ranks run 1..n with at most 10 per topic",
            bad_rank == 0,
            f"{bad_rank} topics malformed",
        )
    )
    ineligible = _one(
        conn, "SELECT COUNT(*) FROM cluster_scores WHERE rank IS NOT NULL AND eligible = 0"
    )
    out.append(
        Check("score", "only eligible clusters are picked", ineligible == 0, f"{ineligible} picked")
    )
    big = _one(conn, "SELECT COUNT(*) FROM topics WHERE n_tossups >= 3")
    ranked = _one(
        conn,
        "SELECT COUNT(DISTINCT s.topic_id) FROM cluster_scores s "
        "JOIN topics t ON t.id = s.topic_id WHERE s.rank IS NOT NULL AND t.n_tossups >= 3",
    )
    share = ranked / max(big, 1)
    out.append(
        Check(
            "score",
            "≥95% of topics with 3+ questions have picks",
            share >= 0.95,
            f"{share:.1%} of {big:,}",
        )
    )
    if settings.labels_path.is_file():
        from hortum_pipeline.clue_eval import evaluate, summary

        p5, r10 = summary(evaluate(conn, settings.labels_path))
        out.append(
            Check(
                "score",
                "labeled topics: precision@5 ≥ 0.85 and recall@10 ≥ 0.75",
                p5 >= 0.85 and r10 >= 0.75,
                f"precision@5 {p5:.3f}, recall@10 {r10:.3f}",
            )
        )
        )
    return out


TRACERS_PATH = Path("pipeline/eval/tracers.yaml")


def _tracer_actual(conn: sqlite3.Connection, stage: str, tid: str) -> dict[str, object] | None:
    """What the corpus holds for one tracer question at one stage."""
    if stage == "ingest":
        row = conn.execute("SELECT answer_text FROM tossups WHERE id = ?", (tid,)).fetchone()
        return {"answer_text": row[0]} if row else None
    if stage == "parse-answers":
        row = conn.execute(
            "SELECT main, accept, prompt, reject FROM answer_parses WHERE tossup_id = ?", (tid,)
        ).fetchone()
        if not row:
            return None
        texts = [[a["text"] for a in json.loads(col)] for col in row[1:]]
        return {"main": row[0], "accept": texts[0], "prompt": texts[1], "reject": texts[2]}
    if stage == "group":
        row = conn.execute(
            "SELECT g.norm_key, g.category, g.subcategory FROM tossup_groups tg "
            "JOIN candidate_groups g ON g.id = tg.group_id WHERE tg.tossup_id = ?",
            (tid,),
        ).fetchone()
        return dict(zip(("norm_key", "category", "subcategory"), row, strict=True)) if row else None
    if stage == "link":
        row = conn.execute(
            "SELECT t.id, t.wikipedia_title FROM tossup_topics tt "
            "JOIN topics t ON t.id = tt.topic_id WHERE tt.tossup_id = ?",
            (tid,),
        ).fetchone()
        return {"topic": row[0], "title": row[1]} if row else None
    if stage == "score":
        rows = conn.execute(
            "SELECT c.ordinal, s.rank FROM clues c JOIN clue_cluster_members m ON m.clue_id = c.id "
            "JOIN cluster_scores s ON s.cluster_id = m.cluster_id WHERE c.tossup_id = ?",
            (tid,),
        ).fetchall()
        return {"ranks": {r[0]: r[1] for r in rows}} if rows else None
    if stage == "cluster":
        rows = conn.execute(
            "SELECT c.ordinal, k.n_tossups, k.label, k.key_terms FROM clues c "
            "JOIN clue_cluster_members m ON m.clue_id = c.id "
            "JOIN clue_clusters k ON k.id = m.cluster_id WHERE c.tossup_id = ? ORDER BY c.ordinal",
            (tid,),
        ).fetchall()
        if not rows:
            return None
        return {
            "cluster_questions": {r[0]: r[1] for r in rows},
            "cluster_terms": {r[0]: [r[2], *json.loads(r[3])] for r in rows},
        }
    if stage == "clues":
        layout = conn.execute(
            "SELECT power_word FROM question_layout WHERE tossup_id = ?", (tid,)
        ).fetchone()
        rows = conn.execute(
            "SELECT kind, in_power, text, key_terms FROM clues "
            "WHERE tossup_id = ? ORDER BY ordinal",
            (tid,),
        ).fetchall()
        if not layout:
            return None
        return {
            "power_word": layout[0],
            "kinds": [r[0] for r in rows],
            "in_power": [bool(r[1]) for r in rows],
            "texts": [r[2] for r in rows],
            "key_terms": {i: json.loads(r[3]) for i, r in enumerate(rows)},
        }
    return None


def _tracer_mismatches(expect: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    problems = []
    for key, want in expect.items():
        if key == "starts":
            texts = actual["texts"]
            for i, prefix in enumerate(want):
                if i >= len(texts) or not texts[i].startswith(prefix):
                    got = texts[i][:40] if i < len(texts) else "missing"
                    problems.append(f"clue {i} starts {got!r}, want {prefix!r}")
        elif key == "rank_at_most":
            for index, worst in want.items():
                got = actual["ranks"].get(int(index))
                if got is None or got > worst:
                    problems.append(f"clue {index} cluster rank {got}, want ≤{worst}")
        elif key == "cluster_min_questions":
            for index, minimum in want.items():
                got = actual["cluster_questions"].get(int(index), 0)
                if got < minimum:
                    problems.append(f"clue {index} cluster spans {got} questions, want ≥{minimum}")
        elif key == "cluster_mentions":
            for index, terms in want.items():
                got = [t.lower() for t in actual["cluster_terms"].get(int(index), [])]
                if not any(term.lower() in got for term in terms):
                    problems.append(f"clue {index} cluster terms {got[:5]} lack any of {terms}")
        elif key == "key_terms":
            for index, terms in want.items():
                got = actual["key_terms"].get(int(index), [])
                missing = [t for t in terms if t not in got]
                if missing:
                    problems.append(f"clue {index} key terms missing {missing} (got {got})")
        elif actual.get(key) != want:
            problems.append(f"{key} = {actual.get(key)!r}, want {want!r}")
    return problems


def check_tracers(stage: str) -> CheckFn:
    def check(conn: sqlite3.Connection, settings: PipelineSettings) -> list[Check]:
        if not settings.tracers_path.is_file():
            return []
        out = []
        for tracer in yaml.safe_load(settings.tracers_path.read_text(encoding="utf-8"))["tracers"]:
            expect = tracer["expect"].get(stage)
            if expect is None:
                continue
            actual = _tracer_actual(conn, stage, tracer["id"])
            problems = (
                ["missing from corpus"] if actual is None else _tracer_mismatches(expect, actual)
            )
            out.append(
                Check(
                    stage,
                    f"tracer {tracer['topic']} ({tracer['id'][:8]})",
                    not problems,
                    "; ".join(problems) or "as expected",
                )
            )
        return out

    return check


STAGE_CHECKS: dict[str, list[CheckFn]] = {
    "ingest": [check_ingest, check_tracers("ingest")],
    "parse-answers": [check_parse, check_tracers("parse-answers")],
    "group": [check_group, check_tracers("group")],
    "link": [check_link, check_tracers("link")],
    "facts": [check_facts, check_search],
    "clues": [check_clues, check_tracers("clues")],
    "cluster": [check_cluster, check_tracers("cluster")],
    "score": [check_score, check_tracers("score")],
}
TABLE_FOR = {
    "ingest": "tossups",
    "parse-answers": "answer_parses",
    "group": "tossup_groups",
    "link": "group_links",
    "facts": "topic_facts",
    "clues": "question_layout",
    "cluster": "clue_clusters",
    "score": "cluster_scores",
}


def run_checks(settings: PipelineSettings, stages: list[str] | None = None) -> list[Check]:
    conn = sqlite3.connect(f"file:{settings.corpus_path}?mode=ro", uri=True)
    try:
        present = _tables(conn)
        results: list[Check] = []
        for stage, fns in STAGE_CHECKS.items():
            if stages is not None and stage not in stages:
                continue
            if TABLE_FOR[stage] not in present:
                results.append(Check(stage, "stage output present", False, "not run yet"))
                continue
            for fn in fns:
                results.extend(fn(conn, settings))
        return results
    finally:
        conn.close()


def format_report(results: list[Check]) -> str:
    lines = []
    for check in results:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"{mark}  [{check.stage}] {check.name}: {check.detail}")
    failed = sum(not c.passed for c in results)
    lines.append(f"{len(results) - failed}/{len(results)} checks passed")
    return "\n".join(lines)
