"""study.db: the one database that can't be rebuilt from the corpus, so it's backed up."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS followed_topics (
    topic_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY,        -- stable: see cards.card_id
    topic_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- clue | reverse | missed
    front TEXT NOT NULL,             -- cards keep their own text, so rebuilds never break them
    back TEXT NOT NULL,
    source_ref TEXT NOT NULL,        -- JSON: where the card came from (cluster, tossup)
    created_at TEXT NOT NULL,
    suspended INTEGER NOT NULL DEFAULT 0,
    category TEXT,                   -- quizbowl category, copied when the card is made
    subcategory TEXT,
    alt_subcategory TEXT,
    difficulty INTEGER               -- the topic's typical question difficulty, 0–10
);
CREATE INDEX IF NOT EXISTS cards_topic ON cards(topic_id);
CREATE TABLE IF NOT EXISTS card_state (
    card_id TEXT PRIMARY KEY REFERENCES cards(card_id),
    due TEXT NOT NULL,               -- ISO 8601, UTC
    fsrs TEXT NOT NULL               -- JSON: fsrs.Card.to_dict()
);
CREATE INDEX IF NOT EXISTS card_state_due ON card_state(due);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    rating INTEGER NOT NULL,         -- 1 again | 2 hard | 3 good | 4 easy
    reviewed_at TEXT NOT NULL,
    elapsed_days REAL
);
CREATE TABLE IF NOT EXISTS buzzes (
    id INTEGER PRIMARY KEY,
    tossup_id TEXT NOT NULL,
    topic_id TEXT,
    word_index INTEGER,              -- NULL when the question was read to the end
    position REAL,                   -- 0 = first word, 1 = last
    clue_ordinal INTEGER,            -- the clue being read at the buzz
    clue_cluster_id INTEGER,
    result TEXT NOT NULL,            -- correct | incorrect | no_buzz
    in_power INTEGER NOT NULL,
    answer_given TEXT,
    judged_by TEXT NOT NULL,         -- auto | self
    created_at TEXT NOT NULL,
    category TEXT,
    subcategory TEXT,
    difficulty INTEGER,
    answer TEXT,
    topic_name TEXT
);
CREATE INDEX IF NOT EXISTS buzzes_topic ON buzzes(topic_id);
"""


_MIGRATIONS = [
    "ALTER TABLE buzzes ADD COLUMN category TEXT",
    "ALTER TABLE buzzes ADD COLUMN subcategory TEXT",
    "ALTER TABLE buzzes ADD COLUMN difficulty INTEGER",
    "ALTER TABLE buzzes ADD COLUMN answer TEXT",
    "ALTER TABLE buzzes ADD COLUMN topic_name TEXT",
    "ALTER TABLE cards ADD COLUMN category TEXT",
    "ALTER TABLE cards ADD COLUMN subcategory TEXT",
    "ALTER TABLE cards ADD COLUMN alt_subcategory TEXT",
    "ALTER TABLE cards ADD COLUMN difficulty INTEGER",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    return conn
