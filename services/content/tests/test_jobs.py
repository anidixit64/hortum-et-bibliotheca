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


def test_dependents_wait_until_their_input_is_stored(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "clues", priority=5)
    jobs.enqueue(conn, "Q1", "summary", priority=4)
    jobs.enqueue(conn, "Q1", "wiki", priority=6)
    jobs.enqueue(conn, "Q1", "facts", priority=1)
    first = jobs.claim(conn)
    assert first is not None and first.kind == "wiki"
    jobs.finish(conn, first)
    # Facts reads the wiki row, which is not stored yet. Summary reads the cleanup.
    second = jobs.claim(conn)
    assert second is not None and second.kind == "clues"
    assert jobs.claim(conn) is None
    with conn:
        conn.execute(
            "INSERT INTO enrichments VALUES "
            "('Q1', 'wiki', 'ok', '{}', 1, '2026-01-01T00:00:00+00:00')"
        )
    facts = jobs.claim(conn)
    assert facts is not None and facts.kind == "facts"
    jobs.finish(conn, second)
    with conn:
        conn.execute(
            "INSERT INTO generations VALUES "
            "('Q1', 'clues', 'fp', 1, 'gemini', 'm', '{}', 0, 0, '2026-01-01T00:00:00+00:00')"
        )
    summary = jobs.claim(conn)
    assert summary is not None and summary.kind == "summary"


def test_a_failed_dependency_lets_the_dependent_job_run(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "clues")
    clues = jobs.claim(conn)
    assert clues is not None
    jobs.fail(conn, clues, "no backends configured", max_attempts=clues.attempts)
    jobs.enqueue(conn, "Q1", "summary")
    summary = jobs.claim(conn)
    assert summary is not None and summary.kind == "summary"


def test_a_failed_job_is_queued_again_after_a_pause(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "clues")
    job = jobs.claim(conn)
    assert job is not None
    jobs.fail(conn, job, "no backends configured", max_attempts=job.attempts)
    assert jobs.requeue_failed(conn, "Q1", "clues", priority=15) is False
    conn.execute(
        "UPDATE jobs SET updated_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", job.id),
    )
    assert jobs.requeue_failed(conn, "Q1", "clues", priority=15) is True
    again = jobs.claim(conn)
    assert again is not None and again.attempts == 1 and again.kind == "clues"


def test_a_dead_workers_jobs_are_recovered(conn: sqlite3.Connection) -> None:
    jobs.enqueue(conn, "Q1", "wiki")
    assert jobs.claim(conn) is not None
    assert jobs.claim(conn) is None
    assert jobs.recover(conn) == 1
    assert jobs.claim(conn) is not None
