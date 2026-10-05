"""Stage 2: parse every answer line, applying hand fixes from the overrides file."""

import json
import sqlite3
from collections import Counter
from collections.abc import Iterable

from hortum_common.text import normalize
from hortum_pipeline import db
from hortum_pipeline.answers import PARSER_VERSION, ParsedAnswer, line_key, parse_answer
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.overrides import AnswerOverride, OverrideStore
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS answer_parses;
CREATE TABLE answer_parses (
    tossup_id TEXT PRIMARY KEY REFERENCES tossups(id),
    line_key TEXT NOT NULL,
    main TEXT NOT NULL,
    main_norm TEXT NOT NULL,
    parser_main TEXT NOT NULL, -- the parser's own answer, kept so a hand fix can be undone
    required TEXT NOT NULL,   -- JSON list of strings
    accept TEXT NOT NULL,     -- JSON list of {text, condition?}
    prompt TEXT NOT NULL,
    reject TEXT NOT NULL,
    notes TEXT NOT NULL,
    issues TEXT NOT NULL,
    parser_confidence REAL NOT NULL,
    confidence REAL NOT NULL, -- 1.0 once fixed by hand
    source TEXT NOT NULL,     -- parser | override | excluded
    parser_version TEXT NOT NULL
);
CREATE INDEX answer_parses_line_key ON answer_parses(line_key);
CREATE INDEX answer_parses_confidence ON answer_parses(confidence);
"""

_INSERT = "INSERT INTO answer_parses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
_BATCH = 5_000


Row = tuple[str | float, ...]


def _row(tossup_id: str, key: str, parsed: ParsedAnswer, fix: AnswerOverride | None) -> Row:
    main, confidence, source = parsed.main, parsed.confidence, "parser"
    if fix is not None:
        main, confidence = fix.main, 1.0
        source = "excluded" if fix.exclude else "override"
    return (
        tossup_id,
        key,
        main,
        normalize(main, singularize=True),
        parsed.main,
        json.dumps(parsed.required, ensure_ascii=False),
        json.dumps([a.as_dict() for a in parsed.accept], ensure_ascii=False),
        json.dumps([a.as_dict() for a in parsed.prompt], ensure_ascii=False),
        json.dumps([a.as_dict() for a in parsed.reject], ensure_ascii=False),
        json.dumps(parsed.notes, ensure_ascii=False),
        json.dumps(parsed.issues),
        parsed.confidence,
        confidence,
        source,
        PARSER_VERSION,
    )


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "tossups", "ingest")
    db.recreate(conn, SCHEMA)
    store = OverrideStore(settings.answer_overrides_path)

    total = conn.execute("SELECT COUNT(*) FROM tossups").fetchone()[0]
    reporter.begin("Parsing answer lines", total)
    issue_counts: Counter[str] = Counter()
    low = fixed = 0
    rows: list[Row] = []
    reader = conn.execute("SELECT id, answer_html FROM tossups ORDER BY id")
    for tossup_id, answer_html in reader:
        key = line_key(answer_html)
        parsed = parse_answer(answer_html)
        fix = store.get(key)
        rows.append(_row(tossup_id, key, parsed, fix))
        issue_counts.update(parsed.issues)
        if fix is not None:
            fixed += 1
        elif parsed.confidence < settings.review_threshold:
            low += 1
        if len(rows) >= _BATCH:
            conn.executemany(_INSERT, rows)
            reporter.advance(len(rows))
            reporter.stat("Low confidence", f"{low:,}")
            rows.clear()
    conn.executemany(_INSERT, rows)
    reporter.advance(len(rows))
    conn.commit()

    reporter.stat("Low confidence", f"{low:,}")
    reporter.stat("Fixed by hand", f"{fixed:,}")
    reporter.stat(
        "Parsed with confidence",
        f"{100 * (total - low) / max(total, 1):.1f}% (threshold {settings.review_threshold})",
    )
    for issue, count in issue_counts.most_common():
        reporter.log(f"issue {issue}: {count:,}")
    conn.close()


def apply_overrides(conn: sqlite3.Connection, overrides: Iterable[AnswerOverride]) -> int:
    """Updates only the rows matching the given fixes; returns how many questions changed."""
    changed = 0
    for fix in overrides:
        cursor = conn.execute(
            "UPDATE answer_parses SET main = ?, main_norm = ?, confidence = 1.0, source = ? "
            "WHERE line_key = ?",
            (
                fix.main,
                normalize(fix.main, singularize=True),
                "excluded" if fix.exclude else "override",
                fix.line_key,
            ),
        )
        changed += cursor.rowcount
    conn.commit()
    return changed


def revert_override(conn: sqlite3.Connection, key: str) -> int:
    """Puts the parser's own answer back for one answer line."""
    rows = conn.execute(
        "SELECT tossup_id, parser_main FROM answer_parses WHERE line_key = ?", (key,)
    ).fetchall()
    for tossup_id, parser_main in rows:
        conn.execute(
            "UPDATE answer_parses SET main = ?, main_norm = ?, confidence = parser_confidence, "
            "source = 'parser' WHERE tossup_id = ?",
            (parser_main, normalize(parser_main, singularize=True), tossup_id),
        )
    conn.commit()
    return len(rows)
