"""hortum-content: run the worker, queue topics, see progress."""

import argparse
import logging
import sys

import httpx

from content import db, jobs, worker
from content.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hortum-content")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("worker", help="Process jobs until stopped")
    run.add_argument("--once", action="store_true", help="Process ready jobs, then exit")
    queue = sub.add_parser("enqueue", help="Queue enrichments for topics")
    queue.add_argument("topics", nargs="+", help="Topic ids (Q1784288) or slugs")
    queue.add_argument("--kinds", nargs="+", choices=jobs.KINDS, default=list(jobs.KINDS))
    sub.add_parser("status", help="Job counts by kind and status")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = db.connect(settings.db_path)
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
