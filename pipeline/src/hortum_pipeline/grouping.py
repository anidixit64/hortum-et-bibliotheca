"""Stage 3: group answers into candidate topics.

Groups key on the normalized main answer *within a category and subcategory*, so
"Mercury" in Astronomy, Chemistry and Mythology start apart; the link stage merges
groups that resolve to the same Wikidata item, so over-splitting here is harmless.
Accepted alternates never merge groups: "football" is accepted for both soccer and
American football answers.
"""

from collections import Counter, defaultdict

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS tossup_groups;
DROP TABLE IF EXISTS candidate_groups;
CREATE TABLE candidate_groups (
    id INTEGER PRIMARY KEY,
    norm_key TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    display_name TEXT NOT NULL,
    n_tossups INTEGER NOT NULL,
    n_sets INTEGER NOT NULL,
    UNIQUE (norm_key, category, subcategory)
);
CREATE TABLE tossup_groups (
    tossup_id TEXT PRIMARY KEY REFERENCES tossups(id),
    group_id INTEGER NOT NULL REFERENCES candidate_groups(id)
);
CREATE INDEX tossup_groups_group ON tossup_groups(group_id);
"""


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "answer_parses", "parse-answers")
    db.recreate(conn, SCHEMA)

    rows = conn.execute(
        """
        SELECT a.tossup_id, a.main, a.main_norm, COALESCE(t.category, 'Unknown'),
               COALESCE(t.subcategory, ''), t.set_id
        FROM answer_parses a JOIN tossups t ON t.id = a.tossup_id
        WHERE a.source != 'excluded' AND a.main_norm != '' AND a.confidence >= ?
        """,
        (settings.group_min_confidence,),
    ).fetchall()
    reporter.begin("Grouping answers", len(rows))

    members: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    names: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    sets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for tossup_id, main, norm, category, subcategory, set_id in rows:
        key = (norm, category, subcategory)
        members[key].append(tossup_id)
        names[key][main] += 1
        sets[key].add(set_id)
    reporter.advance(len(rows))

    for group_id, key in enumerate(sorted(members, key=lambda k: -len(members[k])), start=1):
        display = names[key].most_common(1)[0][0]
        conn.execute(
            "INSERT INTO candidate_groups VALUES (?, ?, ?, ?, ?, ?, ?)",
            (group_id, *key, display, len(members[key]), len(sets[key])),
        )
        conn.executemany(
            "INSERT INTO tossup_groups VALUES (?, ?)", [(t, group_id) for t in members[key]]
        )
    conn.commit()

    skipped = conn.execute("SELECT COUNT(*) FROM answer_parses").fetchone()[0] - len(rows)
    reporter.stat("Candidate groups", f"{len(members):,}")
    reporter.stat(
        "Groups with ≥3 / ≥10 questions",
        " / ".join(f"{sum(1 for m in members.values() if len(m) >= n):,}" for n in (3, 10)),
    )
    reporter.stat("Questions left out (excluded or very low confidence)", f"{skipped:,}")
    conn.close()
