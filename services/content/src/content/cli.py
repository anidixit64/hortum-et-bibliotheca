"""hortum-content: run the worker, queue topics, see progress."""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

import httpx

from content import db, jobs, worker
from content.config import get_settings


def export_overrides(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    """Merge the cleanup's off-topic answer groups into the link overrides file, keeping
    entries already there (hand-written ones included). Returns (new, total)."""
    entries: dict[tuple[str, str, str], dict[str, object]] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                entries[(entry["key"], entry.get("category") or "", entry["topic"])] = entry
    before = len(entries)
    for topic_id, model, payload, created in conn.execute(
        "SELECT topic_id, model, payload, created_at FROM generations WHERE kind = 'clues'"
    ):
        for group in json.loads(payload).get("excluded_groups", []):
            key = (group["key"], group.get("category") or "", topic_id)
            entries.setdefault(key, {
                "key": group["key"], "category": group.get("category") or "", "topic": topic_id,
                "answer": group["answer"], "action": "unlink",
                "source": f"cleanup:{model}", "decided": created[:10],
            })  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for _, e in sorted(entries.items()))
    )
    return len(entries) - before, len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hortum-content")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("worker", help="Process jobs until stopped")
    run.add_argument("--once", action="store_true", help="Process ready jobs, then exit")
    queue = sub.add_parser("enqueue", help="Queue enrichments for topics")
    queue.add_argument("topics", nargs="+", help="Topic ids (Q1784288) or slugs")
    queue.add_argument("--kinds", nargs="+", choices=jobs.KINDS, default=list(jobs.KINDS))
    sub.add_parser("status", help="Job counts by kind and status")
    export = sub.add_parser(
        "export-overrides",
        help="Write off-topic answer groups found by the cleanup to the pipeline's overrides",
    )
    export.add_argument("--path", default="pipeline/overrides/links.jsonl")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = db.connect(settings.db_path)
    if args.command == "export-overrides":
        added, total = export_overrides(conn, Path(args.path))
        print(f"{added} new, {total} in {args.path}; rebuild from the link stage to apply")
        return 0
    if args.command == "enqueue":
        queued = sum(jobs.enqueue(conn, t, k) for t in args.topics for k in args.kinds)
        print(f"queued {queued} job(s)")
    elif args.command == "status":
        for kind, status, n in conn.execute(
            "SELECT kind, status, COUNT(*) FROM jobs GROUP BY 1, 2 ORDER BY 1, 2"
        ):
            print(f"{kind:8} {status:8} {n}")
    elif args.once:
        jobs.recover(conn)
        worker.log_providers(settings)
        http = worker.make_http(conn, settings)
        with httpx.Client(base_url=settings.catalog_url, timeout=30) as catalog:
            done = 0
            while worker.run_once(conn, settings, http, catalog):
                done += 1
        print(f"processed {done} job(s), {http.network_requests} web request(s)")
    else:
        worker.run_forever(conn, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
