import sqlite3
from datetime import datetime

from content import jobs


def test_enqueue_dedups_and_raises_priority(conn: sqlite3.Connection) -> None:
    assert jobs.enqueue(conn, "Q1", "wiki")
    assert not jobs.enqueue(conn, "Q1", "wiki", priority=10)  # already open
    assert jobs.enqueue(conn, "Q2", "wiki")
    first = jobs.claim(conn)
    assert first is not None and first.topic_id == "Q1"  # raised to 10, ahead of Q2


def test_failures_back_off_then_give_up(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "books")
    job = jobs.claim(conn)
    assert job is not None
    jobs.fail(conn, job, "timeout", max_attempts=2)
    assert jobs.claim(conn) is None  # waiting out the backoff
    status, not_before = conn.execute("SELECT status, not_before FROM jobs").fetchone()
    assert status == "queued" and datetime.fromisoformat(not_before) > jobs.now()
    conn.execute("UPDATE jobs SET not_before = ?", (jobs.now().isoformat(),))
    job = jobs.claim(conn)
    assert job is not None and job.attempts == 2
    jobs.fail(conn, job, "timeout again", max_attempts=2)
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "failed"
    assert jobs.open_kinds(conn, "Q1") == {"books": "failed"}


def test_a_dead_workers_jobs_are_recovered(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "wiki")
    assert jobs.claim(conn) is not None
    assert jobs.claim(conn) is None
    assert jobs.recover(conn) == 1
    assert jobs.claim(conn) is not None
