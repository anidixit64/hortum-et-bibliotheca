"""Measure the clue cleanup on a fixed set of topics.

    uv run python services/content/eval/cleanup_eval.py [--gui] [--limit N]

For each topic in topics.tsv (100 topics that agent review rounds examined in October
2026), runs the cleanup exactly as the worker does, stores the result in content.db (so
those pages show it), and writes before/after top-10 lists to data/eval/ for a blind
comparison. Needs the catalog running (CONTENT_CATALOG_URL).
"""

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from content import cleanup, db, worker
from content.config import get_settings

HERE = Path(__file__).parent


def run(reporter: Any, limit: int | None) -> Path:
    settings = get_settings()
    conn: sqlite3.Connection = db.connect(settings.db_path)
    topics = [line.split("\t") for line in (HERE / "topics.tsv").read_text().splitlines()]
    topics = topics[:limit] if limit else topics
    out = Path("data/eval") / f"cleanup_{datetime.now(UTC):%Y%m%d_%H%M}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    reporter.begin("Cleaning clue lists", len(topics))
    tokens = done = failed = 0
    with httpx.Client(base_url=settings.catalog_url, timeout=60) as catalog, out.open("w") as f:
        for topic_id, name in topics:
            started = time.time()
            try:
                before = catalog.get(
                    f"/topics/{topic_id}/clue-candidates", params={"limit": cleanup.CANDIDATES}
                ).json()
                payload, fingerprint, reply = worker.clean_clues(settings, catalog, topic_id)
            except Exception as exc:  # noqa: BLE001 - one topic's failure mustn't stop the run
                reporter.log(f"{name}: {type(exc).__name__}: {exc}")
                failed += 1
                reporter.advance()
                continue
            worker.store_generation(
                conn, topic_id, "clues", fingerprint, cleanup.PROMPT_VERSION, payload, reply
            )
            tokens += (reply.input_tokens + reply.output_tokens) if reply else 0
            done += 1
            f.write(json.dumps({
                "topic_id": topic_id, "name": name, "seconds": round(time.time() - started, 1),
                "model": reply.model if reply else None,
                "before": [{"label": c["label"], "q": c["n_questions"],
                            "sentences": c["sentences"][:2]} for c in before["candidates"][:10]],
                "after": [{"label": c["label"], "q": c["n_questions"],
                           "spellings": c["spellings"][:4]} for c in payload["clues"][:10]],
                "edits": payload["edits"], "rejected": payload["rejected"],
            }, ensure_ascii=False) + "\n")  # fmt: skip
            f.flush()
            reporter.advance()
            reporter.stat("Cleaned / failed", f"{done} / {failed}")
            reporter.stat("Tokens", f"{tokens:,}")
    worker.ner_for(settings).close()
    reporter.stat("Results", str(out))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not args.gui:
        from hortum_pipeline.progress import ConsoleReporter

        run(ConsoleReporter(), args.limit)
        return
    import tkinter as tk

    from hortum_pipeline.gui.progress_window import ProgressWindow

    root = tk.Tk()
    window = ProgressWindow(root, "Clue cleanup evaluation", [])
    window.run(lambda reporter: run(reporter, args.limit) and 0)


if __name__ == "__main__":
    main()
