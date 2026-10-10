"""A small job queue in content.db: one writer (the worker), any number of producers."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

KINDS = ("wiki", "images", "books", "videos")
BACKOFF_BASE_SECONDS = 60  # 1, 2, 4, 8... minutes after each failure


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Job:
    id: int
    topic_id: str
    kind: str
    attempts: int


def enqueue(conn: sqlite3.Connection, topic_id: str, kind: str, priority: int = 0) -> bool:
    """Queues a job unless one is already open for this topic and kind. True if queued.

    Re-asking with a higher priority (a page view after a batch request) raises it.
    """
    stamp = now().isoformat()
    with conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO jobs (topic_id, kind, status, priority, not_before, "
            "created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, ?, ?)",
            (topic_id, kind, priority, stamp, stamp, stamp),
        )
        if not cursor.rowcount:
            conn.execute(
                "UPDATE jobs SET priority = MAX(priority, ?) "
                "WHERE topic_id = ? AND kind = ? AND status = 'queued'",
                (priority, topic_id, kind),
            )
    return bool(cursor.rowcount)


def claim(conn: sqlite3.Connection) -> Job | None:
    """Takes the most urgent runnable job and marks it running."""
    stamp = now().isoformat()
    with conn:
        row = conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? "
            "WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND not_before <= ? "
            "            ORDER BY priority DESC, id LIMIT 1) "
            "RETURNING id, topic_id, kind, attempts",
            (stamp, stamp),
        ).fetchone()
    return Job(*row) if row else None


def finish(conn: sqlite3.Connection, job: Job) -> None:
    with conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', last_error = NULL, updated_at = ? WHERE id = ?",
            (now().isoformat(), job.id),
        )


def fail(conn: sqlite3.Connection, job: Job, error: str, max_attempts: int) -> None:
    """Requeues with exponential backoff, or gives up after ``max_attempts``."""
    stamp = now()
    retry = job.attempts < max_attempts
    delay = timedelta(seconds=BACKOFF_BASE_SECONDS * 2 ** (job.attempts - 1))
    with conn:
        conn.execute(
            "UPDATE jobs SET status = ?, last_error = ?, not_before = ?, updated_at = ? "
            "WHERE id = ?",
            (
                "queued" if retry else "failed",
                error[:500],
                (stamp + delay).isoformat(),
                stamp.isoformat(),
                job.id,
            ),
        )


def recover(conn: sqlite3.Connection) -> int:
    """Jobs left 'running' by a worker that died go back in the queue."""
    with conn:
        return conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'").rowcount


def open_kinds(conn: sqlite3.Connection, topic_id: str) -> dict[str, str]:
    """Kind -> status for this topic's open or failed jobs."""
    return dict(
        conn.execute(
            "SELECT kind, status FROM jobs WHERE topic_id = ? AND status != 'done' ORDER BY id",
            (topic_id,),
        ).fetchall()
    )
