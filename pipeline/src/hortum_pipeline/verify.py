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


STAGE_CHECKS: dict[str, list[CheckFn]] = {
    "ingest": [check_ingest],
    "parse-answers": [check_parse],
    "group": [check_group],
    "link": [check_link],
    "facts": [check_facts, check_search],
}
TABLE_FOR = {
    "ingest": "tossups",
    "parse-answers": "answer_parses",
    "group": "tossup_groups",
    "link": "group_links",
    "facts": "topic_facts",
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
