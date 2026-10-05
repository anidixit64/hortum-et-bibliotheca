import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    """Opens corpus.db for writing, creating its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def recreate(conn: sqlite3.Connection, ddl: str) -> None:
    """Runs a stage's schema script; each script drops and recreates the tables it owns.

    REFERENCES clauses document relationships but aren't enforced: stages rebuild in
    order, so a re-run of an early stage must be able to drop tables later ones point at.
    """
    conn.executescript(ddl)


def require_table(conn: sqlite3.Connection, table: str, stage: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"table '{table}' is missing; run the '{stage}' stage first")
