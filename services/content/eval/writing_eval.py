"""Generate the written sections for a set of topics, for a fact-check review.

    uv run python services/content/eval/writing_eval.py [--gui] [--topics FILE] [--limit N]
        [--keep-clues] [--refetch]

For each topic, runs a first open through the worker (Wikipedia text, clue cleanup,
explanations, summary, fun facts, special sections), storing everything in the content
database (CONTENT_DB_PATH; point it at a copy to leave the real one alone), then writes a
review file to data/eval/ with every section and the Wikipedia text it came from.
--keep-clues keeps each topic's stored clue cleanup, so only the writing changes;
--refetch fetches the Wikipedia text again. CONTENT_USE_CLAUDE_CODE=false tests Gemini
alone. Needs the catalog running (CONTENT_CATALOG_URL).
"""

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from content import db, jobs, worker, writing
from content.config import get_settings

HERE = Path(__file__).parent
KINDS = ("wiki", "clues", "explanations", "summary", "facts", "special")
SOURCE_SHOWN = 3000  # words of the article in the review file


def first_open(
    conn: sqlite3.Connection,
    settings: Any,
    http: Any,
    catalog: httpx.Client,
    topic_id: str,
    keep_clues: bool,
    refetch: bool,
) -> None:
    """Queue a topic's sections and work until none are left (deferred jobs wait)."""
    kinds = [k for k in KINDS[1:] if not (keep_clues and k == "clues")]
    with conn:
        for kind in kinds:
            conn.execute(
                "DELETE FROM generations WHERE topic_id = ? AND kind = ?", (topic_id, kind)
            )
        if refetch:
            conn.execute(
                "DELETE FROM enrichments WHERE topic_id = ? AND kind = 'wiki'", (topic_id,)
            )
    for kind in ["wiki", *kinds]:
        jobs.enqueue(conn, topic_id, kind, 50)
    deadline = time.time() + 2400  # rate limits defer jobs for minutes at a time
    while time.time() < deadline:
        if worker.run_once(conn, settings, http, catalog) is None:
            left = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE topic_id = ? AND status IN ('queued', 'running')",
                (topic_id,),
            ).fetchone()[0]
            if not left:
                return
            time.sleep(3)


def models(conn: sqlite3.Connection, topic_id: str) -> str:
    rows = conn.execute(
        "SELECT kind, model FROM generations WHERE topic_id = ? ORDER BY kind", (topic_id,)
    )
    return ", ".join(f"{kind}: {model}" for kind, model in rows)


def run(
    reporter: Any, topics_file: Path, limit: int | None, keep_clues: bool, refetch: bool
) -> Path:
    settings = get_settings()
    conn = db.connect(settings.db_path)
    http = worker.make_http(conn, settings)
    topics = [line.split("\t") for line in topics_file.read_text().splitlines()][:limit]
    out = Path("data/eval") / f"writing_{datetime.now(UTC):%Y%m%d_%H%M}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    reporter.begin("Writing topic pages", len(topics))
    written = 0
    with httpx.Client(base_url=settings.catalog_url, timeout=60) as catalog, out.open("w") as f:
        for topic_id, name in topics:
            first_open(conn, settings, http, catalog, topic_id, keep_clues, refetch)
            rows = {
                kind: json.loads(payload)
                for kind, payload in conn.execute(
                    "SELECT kind, payload FROM generations WHERE topic_id = ?", (topic_id,)
                )
            }
            wiki = conn.execute(
                "SELECT payload FROM enrichments WHERE topic_id = ? AND kind = 'wiki' "
                "AND status = 'ok'",
                (topic_id,),
            ).fetchone()
            summary = rows.get("summary")
            if not summary:
                reporter.log(f"{name}: no summary")
                reporter.advance()
                continue
            written += 1
            f.write(f"\n######## {name} [{topic_id}]\nMODELS: {models(conn, topic_id)}\n")
            f.write(f"HOOK: {summary['hook']}\n\nSUMMARY:\n{summary['summary']}\n")
            for clue in rows.get("explanations", {}).get("clues", []):
                f.write(
                    f"\nCLUE #{clue['rank']} {clue['label']}\n  one line: {clue['one_line']}\n"
                    f"  explanation: {clue['explanation']}\n"
                )
            for fact in rows.get("facts", {}).get("facts", []):
                f.write(f"\nFUN FACT: {fact['fact']}\n  quoted: {fact['source_sentence']}\n")
            if special := rows.get("special"):
                feature = special["feature"]
                f.write(f"\nTIMELINE ({special['timeline']['kind']}):\n")
                for event in special["timeline"]["events"]:
                    f.write(f"  {event['year']}: {event['label']}\n")
                f.write(f"\nFEATURE ({feature['form']}): {feature['title']}\n{feature['body']}\n")
                for step in feature["steps"]:
                    f.write(f"  STEP {step['label']}: {step['detail']}\n")
            source = writing.source_text(json.loads(wiki[0]) if wiki else None)
            words = source.split()
            f.write(
                f"\nWIKIPEDIA SOURCE ({len(words)} words; first {SOURCE_SHOWN} shown):\n"
                f"{' '.join(words[:SOURCE_SHOWN])}\n"
            )
            f.flush()
            reporter.advance()
            reporter.stat("Written", written)
    worker.ner_for(settings).close()
    reporter.stat("Review file", str(out))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--topics", type=Path, default=HERE / "fresh_topics.tsv")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--keep-clues", action="store_true")
    parser.add_argument("--refetch", action="store_true")
    args = parser.parse_args()
    if not args.gui:
        from hortum_pipeline.progress import ConsoleReporter

        run(ConsoleReporter(), args.topics, args.limit, args.keep_clues, args.refetch)
        return
    import tkinter as tk

    from hortum_pipeline.gui.progress_window import ProgressWindow

    root = tk.Tk()
    window = ProgressWindow(root, "Written sections evaluation", [])

    def job(reporter: Any) -> int:
        run(reporter, args.topics, args.limit, args.keep_clues, args.refetch)
        return 0

    window.run(job)


if __name__ == "__main__":
    main()
