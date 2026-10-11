"""Generate the written sections for a set of topics, for a fact-check review.

    uv run python services/content/eval/writing_eval.py [--gui] [--topics FILE] [--limit N]

For each topic, runs a first open through the worker (Wikipedia text, clue cleanup,
explanations, summary), storing everything in content.db, then writes a review file to
data/eval/ with the hook, summary, explanations and the Wikipedia text they came from.
Needs the catalog running (CONTENT_CATALOG_URL).
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
KINDS = ("wiki", "clues", "explanations", "summary")


def first_open(
    conn: sqlite3.Connection, settings: Any, http: Any, catalog: httpx.Client, topic_id: str
) -> None:
    """Queue a topic's sections and work until none are left (deferred jobs wait)."""
    with conn:
        for kind in KINDS[1:]:
            conn.execute(
                "DELETE FROM generations WHERE topic_id = ? AND kind = ?", (topic_id, kind)
            )
    for kind in KINDS:
        jobs.enqueue(conn, topic_id, kind, 50)
    deadline = time.time() + 900
    while time.time() < deadline:
        if worker.run_once(conn, settings, http, catalog) is None:
            left = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE topic_id = ? AND status IN ('queued', 'running')",
                (topic_id,),
            ).fetchone()[0]
            if not left:
                return
            time.sleep(3)


def run(reporter: Any, topics_file: Path, limit: int | None) -> Path:
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
            first_open(conn, settings, http, catalog, topic_id)
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
            f.write(f"\n######## {name} [{topic_id}]\n")
            f.write(f"HOOK: {summary['hook']}\n\nSUMMARY:\n{summary['summary']}\n")
            for clue in rows.get("explanations", {}).get("clues", []):
                f.write(
                    f"\nCLUE #{clue['rank']} {clue['label']}\n  one line: {clue['one_line']}\n"
                    f"  explanation: {clue['explanation']}\n"
                )
            source = writing.source_text(json.loads(wiki[0]) if wiki else None)
            f.write(f"\nWIKIPEDIA SOURCE (first 1500 words):\n{' '.join(source.split()[:1500])}\n")
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
    args = parser.parse_args()
    if not args.gui:
        from hortum_pipeline.progress import ConsoleReporter

        run(ConsoleReporter(), args.topics, args.limit)
        return
    import tkinter as tk

    from hortum_pipeline.gui.progress_window import ProgressWindow

    root = tk.Tk()
    window = ProgressWindow(root, "Written sections evaluation", [])
    window.run(lambda reporter: run(reporter, args.topics, args.limit) and 0)


if __name__ == "__main__":
    main()
