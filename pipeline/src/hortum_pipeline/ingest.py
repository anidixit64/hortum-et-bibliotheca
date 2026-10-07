"""Stage 1: load the NDJSON dump into corpus.db."""

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS tossup_duplicates;
DROP TABLE IF EXISTS tossups;
DROP TABLE IF EXISTS sets;
CREATE TABLE sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    year INTEGER,
    is_standard INTEGER
);
CREATE TABLE tossups (
    id TEXT PRIMARY KEY,
    text_hash TEXT NOT NULL UNIQUE,
    set_id TEXT NOT NULL REFERENCES sets(id),
    packet_name TEXT,
    packet_number INTEGER,
    number INTEGER,
    category TEXT,
    subcategory TEXT,
    alt_subcategory TEXT,
    difficulty INTEGER,
    question_text TEXT NOT NULL,
    question_html TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    answer_html TEXT NOT NULL,
    n_reports INTEGER NOT NULL DEFAULT 0,
    meta_score INTEGER NOT NULL
);
CREATE TABLE tossup_duplicates (
    tossup_id TEXT PRIMARY KEY,
    kept_id TEXT NOT NULL
);
"""

# Author/editor initials appended to answer lines: "<AP>", "<Edited>", "[AU]", "(1)".
_TRAILING_TAGS = re.compile(r"(?:\s*(?:<[^<>/]{1,40}>|\[[A-Z]{1,4}\]|\(\d{1,2}\)))+\s*$")
_HASH_TEXT = re.compile(r"\W+")
_BATCH = 5_000


def unwrap(value: Any) -> Any:
    """Converts MongoDB extended JSON ({"$numberInt": "8"}, {"$oid": ...}) to plain values."""
    if isinstance(value, dict):
        if len(value) == 1:
            key, inner = next(iter(value.items()))
            if key in ("$numberInt", "$numberLong"):
                return int(inner)
            if key == "$numberDouble":
                return float(inner)
            if key == "$oid":
                return inner
            if key == "$date":
                return unwrap(inner)
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    return value


def strip_trailing_tags(answer: str) -> str:
    return _TRAILING_TAGS.sub("", answer).strip()


def text_hash(question_text: str) -> str:
    return hashlib.sha1(_HASH_TEXT.sub("", question_text.lower()).encode()).hexdigest()


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b""))


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield unwrap(json.loads(line))


def to_row(rec: dict[str, Any]) -> tuple[Any, ...] | None:
    answer_text = strip_trailing_tags(rec.get("answer_sanitized") or "")
    question_text = (rec.get("question_sanitized") or "").strip()
    if not answer_text or not question_text:
        return None
    packet = rec.get("packet") or {}
    optional = ("subcategory", "alternate_subcategory", "difficulty", "number", "packet")
    meta_score = sum(1 for key in optional if rec.get(key) not in (None, ""))
    return (
        rec["_id"],
        text_hash(question_text),
        rec["set"]["_id"],
        packet.get("name"),
        packet.get("number"),
        rec.get("number"),
        rec.get("category"),
        rec.get("subcategory"),
        rec.get("alternate_subcategory"),
        rec.get("difficulty"),
        question_text,
        rec.get("question") or question_text,
        answer_text,
        strip_trailing_tags(rec.get("answer") or answer_text),
        len(rec.get("reports") or []),
        meta_score,
    )


_INSERT = """
INSERT INTO tossups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(text_hash) DO UPDATE SET
    id = excluded.id, set_id = excluded.set_id, packet_name = excluded.packet_name,
    packet_number = excluded.packet_number, number = excluded.number,
    category = excluded.category, subcategory = excluded.subcategory,
    alt_subcategory = excluded.alt_subcategory, difficulty = excluded.difficulty,
    question_text = excluded.question_text, question_html = excluded.question_html,
    answer_text = excluded.answer_text, answer_html = excluded.answer_html,
    n_reports = excluded.n_reports, meta_score = excluded.meta_score
WHERE excluded.meta_score > tossups.meta_score
"""


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    source = settings.raw_tossups
    if not source.is_file():
        raise FileNotFoundError(f"raw dump not found at {source}")

    conn = db.connect(settings.corpus_path)
    db.recreate(conn, SCHEMA)
    source_lines = count_lines(source)
    reporter.begin("Reading questions", source_lines)

    kept: dict[str, tuple[str, int]] = {}  # text_hash -> (tossup id, meta_score)
    duplicates: list[tuple[str, str]] = []  # (dropped tossup id, text_hash)
    sets: dict[str, tuple[Any, ...]] = {}
    rows: list[tuple[Any, ...]] = []
    skipped = 0

    def flush() -> None:
        conn.executemany("INSERT OR IGNORE INTO sets VALUES (?, ?, ?, ?)", list(sets.values()))
        conn.executemany(_INSERT, rows)
        rows.clear()

    for rec in read_records(source):
        reporter.advance()
        row = to_row(rec)
        if row is None:
            skipped += 1
            continue
        s = rec["set"]
        sets.setdefault(
            s["_id"], (s["_id"], s["name"], s.get("year"), int(bool(s.get("standard"))))
        )
        tossup_id, digest, score = row[0], row[1], row[-1]
        if digest in kept:
            prev_id, prev_score = kept[digest]
            if score > prev_score:
                duplicates.append((prev_id, digest))
                kept[digest] = (tossup_id, score)
            else:
                duplicates.append((tossup_id, digest))
                continue
        else:
            kept[digest] = (tossup_id, score)
        rows.append(row)
        if len(rows) >= _BATCH:
            flush()

    flush()
    # Resolve against the final keeper: a better copy may have replaced an earlier one.
    conn.executemany(
        "INSERT OR REPLACE INTO tossup_duplicates VALUES (?, ?)",
        [(dup, kept[digest][0]) for dup, digest in duplicates],
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM tossups").fetchone()[0]
    db.record_meta(
        conn,
        "ingest",
        {"source_lines": source_lines, "duplicates": len(duplicates), "skipped": skipped},
    )
    reporter.stat("Tossups kept", f"{total:,}")
    reporter.stat("Duplicates removed", f"{len(duplicates):,}")
    reporter.stat("Skipped (empty question or answer)", f"{skipped:,}")
    conn.close()
