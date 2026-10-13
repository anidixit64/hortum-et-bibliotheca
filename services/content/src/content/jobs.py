"""A small job queue in content.db: one writer (the worker), any number of producers."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

FETCHED = ("wiki", "images", "books", "videos")  # Phase 5: free sources
GENERATED = (
    "clues",
    "explanations",
    "summary",
    "facts",
    "theme",
    "special",
)  # Phase 6: written or edited by a model
KINDS = FETCHED + GENERATED
BACKOFF_BASE_SECONDS = 60  # 1, 2, 4, 8... minutes after each failure
# How long a terminally failed section stays failed before a page view queues it again.
REQUEUE_AFTER = timedelta(seconds=20)
# table, kind that must already be stored. A failed dependency is claimable so the job
# can record that it is blocked instead of sitting in the queue.
DEPENDENCIES: dict[str, tuple[str, str]] = {
    "explanations": ("generations", "clues"),
    "summary": ("generations", "clues"),
    "facts": ("enrichments", "wiki"),
    "theme": ("enrichments", "images"),
    "special": ("enrichments", "wiki"),
}


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


def dependency_ready(conn: sqlite3.Connection, topic_id: str, kind: str) -> bool:
    """False while this section's input is still being fetched or written."""
    dep = DEPENDENCIES.get(kind)
    if dep is None:
        return True
    table, need = dep
    stored = conn.execute(
        f"SELECT 1 FROM {table} WHERE topic_id = ? AND kind = ?", (topic_id, need)
    ).fetchone()
    if stored:
        return True
    status = conn.execute(
        "SELECT status FROM jobs WHERE topic_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
        (topic_id, need),
    ).fetchone()
    return status is not None and status[0] == "failed"


def claim(conn: sqlite3.Connection) -> Job | None:
    """Takes the most urgent runnable job and marks it running.

    Explanations and the summary stay queued until clue cleanup is stored. Facts, theme,
    and the special section stay queued until the fetch they read is stored. That keeps
    the threads on work that can finish, instead of deferring for 20 seconds.
    """
    stamp = now().isoformat()
    with conn:
        rows = conn.execute(
            "SELECT id, topic_id, kind FROM jobs "
            "WHERE status = 'queued' AND not_before <= ? ORDER BY priority DESC, id",
            (stamp,),
        ).fetchall()
        chosen = next((row for row in rows if dependency_ready(conn, row[1], row[2])), None)
        if chosen is None:
            return None
        job_id, topic_id, kind = chosen
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? "
            "WHERE id = ?",
            (stamp, job_id),
        )
        attempts = conn.execute("SELECT attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
    return Job(job_id, topic_id, kind, attempts)


def requeue_failed(conn: sqlite3.Connection, topic_id: str, kind: str, priority: int = 0) -> bool:
    """Queue a section again after it failed for good. A page view calls this so adding
    API keys (or a transient provider error) gets another try. A failure from the last
    few seconds stays failed so polling does not restart it on every request."""
    row = conn.execute(
        "SELECT id, updated_at FROM jobs WHERE topic_id = ? AND kind = ? AND status = 'failed' "
        "ORDER BY id DESC LIMIT 1",
        (topic_id, kind),
    ).fetchone()
    if row is None:
        return False
    updated = datetime.fromisoformat(row[1])
    if now() - updated < REQUEUE_AFTER:
        return False
    open_job = conn.execute(
        "SELECT 1 FROM jobs WHERE topic_id = ? AND kind = ? AND status IN ('queued', 'running')",
        (topic_id, kind),
    ).fetchone()
    if open_job:
        return False
    stamp = now().isoformat()
    with conn:
        conn.execute(
            "UPDATE jobs SET status = 'queued', attempts = 0, last_error = NULL, "
            "priority = MAX(priority, ?), not_before = ?, updated_at = ? WHERE id = ?",
            (priority, stamp, stamp, row[0]),
        )
    return True


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


def defer(conn: sqlite3.Connection, job: Job, until: datetime, reason: str) -> None:
    """Back in the queue until ``until`` without using up an attempt: every backend is out
    of quota, which isn't the job's fault."""
    with conn:
        conn.execute(
            "UPDATE jobs SET status = 'queued', attempts = attempts - 1, last_error = ?, "
            "not_before = ?, updated_at = ? WHERE id = ?",
            (reason[:500], until.isoformat(), now().isoformat(), job.id),
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
