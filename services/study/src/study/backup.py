"""Nightly copies of study.db: the only data that can't be rebuilt."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    """A consistent copy (SQLite's online backup) named by date; keeps the newest ``keep``."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"study-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
    for old in sorted(backup_dir.glob("study-*.db"))[:-keep]:
        old.unlink()
    return target


def seconds_until(hour: int, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if run <= now:
        run += timedelta(days=1)
    return (run - now).total_seconds()


async def nightly(db_path: Path, backup_dir: Path, keep: int, hour: int) -> None:
    while True:
        await asyncio.sleep(seconds_until(hour))
        await asyncio.to_thread(backup, db_path, backup_dir, keep)
