"""Builds topics, their aliases and the search index from linked groups."""

import json
import sqlite3
from collections import Counter, defaultdict

from hortum_common.text import normalize, slugify
from hortum_pipeline import db
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS topic_aliases_fts;
DROP TABLE IF EXISTS topic_aliases;
DROP TABLE IF EXISTS tossup_topics;
DROP TABLE IF EXISTS topics;
CREATE TABLE topics (
    id TEXT PRIMARY KEY,          -- Wikidata QID, or "local:<slug>" when unlinked
    slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    wikidata_qid TEXT,
    wikipedia_title TEXT,
    description TEXT,
    primary_category TEXT,
    n_tossups INTEGER NOT NULL,
    n_sets INTEGER NOT NULL,
    difficulty_min INTEGER,
    difficulty_max INTEGER,
    first_year INTEGER,
    last_year INTEGER
);
CREATE TABLE tossup_topics (
    tossup_id TEXT PRIMARY KEY REFERENCES tossups(id),
    topic_id TEXT NOT NULL REFERENCES topics(id)
);
CREATE INDEX tossup_topics_topic ON tossup_topics(topic_id);
CREATE TABLE topic_aliases (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    alias TEXT NOT NULL,
    alias_search TEXT NOT NULL,   -- normalized, not singularized: what search matches on
    source TEXT NOT NULL,         -- main | required | accept | title | wikidata
    weight REAL NOT NULL,
    PRIMARY KEY (topic_id, alias_search)
);
"""

_SOURCE_RANK = {"title": 0, "main": 1, "wikidata": 2, "required": 3, "accept": 4}


def build(conn: sqlite3.Connection, reporter: Reporter) -> None:
    db.recreate(conn, SCHEMA)
    reporter.begin("Building topics", None)

    topic_of_group: dict[int, str] = {}
    info: dict[str, dict[str, str | None]] = {}
    rows = conn.execute(
        """
        SELECT g.id, g.norm_key, g.display_name, g.n_tossups, l.status, l.qid, l.title
        FROM candidate_groups g LEFT JOIN group_links l ON l.group_id = g.id
        ORDER BY g.n_tossups DESC
        """
    )
    for group_id, norm_key, display, _n, status, qid, title in rows:
        if status == "linked" and qid:
            topic_id = qid
            info.setdefault(topic_id, {"name": title, "qid": qid, "title": title})
        else:
            topic_id = f"local:{slugify(norm_key)}"
            info.setdefault(topic_id, {"name": display, "qid": None, "title": None})
        topic_of_group[group_id] = topic_id

    conn.executemany(
        "INSERT INTO tossup_topics SELECT tossup_id, ? FROM tossup_groups WHERE group_id = ?",
        [(t, g) for g, t in topic_of_group.items()],
    )
    stats = conn.execute(
        """
        SELECT tt.topic_id, COUNT(*), COUNT(DISTINCT t.set_id),
               MIN(t.difficulty), MAX(t.difficulty), MIN(s.year), MAX(s.year)
        FROM tossup_topics tt
        JOIN tossups t ON t.id = tt.tossup_id
        JOIN sets s ON s.id = t.set_id
        GROUP BY tt.topic_id
        """
    ).fetchall()
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for topic_id, category in conn.execute(
        "SELECT tt.topic_id, t.category FROM tossup_topics tt JOIN tossups t ON t.id = tt.tossup_id"
    ):
        categories[topic_id][category] += 1
    conn.executemany(
        "INSERT INTO topics VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                topic_id,
                slugify(info[topic_id]["name"] or ""),
                info[topic_id]["name"],
                info[topic_id]["qid"],
                info[topic_id]["title"],
                categories[topic_id].most_common(1)[0][0],
                n,
                n_sets,
                dmin,
                dmax,
                ymin,
                ymax,
            )
            for topic_id, n, n_sets, dmin, dmax, ymin, ymax in stats
        ],
    )

    # Aliases: every answer form seen for the topic, plus its Wikipedia title.
    weights: dict[tuple[str, str], float] = defaultdict(float)
    surface: dict[tuple[str, str], tuple[int, str, str]] = {}

    def add(topic_id: str, alias: str, source: str, weight: float) -> None:
        key = normalize(alias)
        if len(key) < 2:
            return
        weights[(topic_id, key)] += weight
        candidate = (_SOURCE_RANK[source], alias, source)
        if (topic_id, key) not in surface or candidate < surface[(topic_id, key)]:
            surface[(topic_id, key)] = candidate

    for topic_id, main, required, accept in conn.execute(
        "SELECT tt.topic_id, a.main, a.required, a.accept "
        "FROM tossup_topics tt JOIN answer_parses a ON a.tossup_id = tt.tossup_id"
    ):
        add(topic_id, main, "main", 1.0)
        for r in json.loads(required):
            add(topic_id, r, "required", 0.5)
        for a in json.loads(accept):
            add(topic_id, a["text"], "accept", 0.25 if a.get("condition") else 0.5)
    for topic_id, data in info.items():
        if data["title"]:
            add(topic_id, data["title"], "title", 2.0)
            bare = data["title"].split(" (")[0]
            if bare != data["title"]:
                add(topic_id, bare, "title", 2.0)

    conn.executemany(
        "INSERT INTO topic_aliases VALUES (?, ?, ?, ?, ?)",
        [(t, surface[(t, k)][1], k, surface[(t, k)][2], w) for (t, k), w in weights.items()],
    )
    rebuild_search_index(conn)
    conn.commit()
    linked = sum(1 for d in info.values() if d["qid"])
    reporter.stat("Topics (linked to Wikidata / local)", f"{linked:,} / {len(info) - linked:,}")
    reporter.stat("Aliases", f"{len(weights):,}")


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """Trigram full-text index over aliases: substring and typo-tolerant matching."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS topic_aliases_fts;
        CREATE VIRTUAL TABLE topic_aliases_fts USING fts5(
            alias_search, topic_id UNINDEXED, tokenize = 'trigram'
        );
        INSERT INTO topic_aliases_fts (alias_search, topic_id)
            SELECT alias_search, topic_id FROM topic_aliases;
        """
    )
