"""content.db: everything fetched (Phase 5) or generated (Phase 6) per topic.

All of it can be rebuilt by fetching again, so it isn't backed up.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichments (
    topic_id TEXT NOT NULL,
    kind TEXT NOT NULL,               -- wiki | images | books | videos
    status TEXT NOT NULL,             -- ok | empty | unavailable
    payload TEXT NOT NULL,            -- JSON
    source_version INTEGER NOT NULL,  -- bump a fetcher's version to refetch lazily
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, kind)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    topic_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,             -- queued | running | done | failed
    priority INTEGER NOT NULL DEFAULT 0,  -- higher runs first: a page view beats a batch
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    not_before TEXT NOT NULL,         -- ISO 8601 UTC: backoff after a failure
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- One open job per topic and kind: asking twice doesn't queue twice.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_open ON jobs(topic_id, kind)
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS jobs_next ON jobs(status, priority, not_before);
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
