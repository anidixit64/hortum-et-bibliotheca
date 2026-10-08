"""Stage 10: write one ready-made JSON record per topic.

Everything the topic page needs from the pipeline, joined once here, so the catalog serves
a page with a single primary-key read:

* ``topic``: names, ids, description, category, aliases and how often it's asked;
* ``clues``: the ranked high-impact clues, each with example wordings and heatmap numbers;
* ``related``: related topics, each with the clue that links them;
* ``confusions``: "don't confuse with", each with its evidence and distinguishing clues;
* ``timeline`` and ``map``: Wikidata dates and places for the topic and its related topics;
* ``tossup_ids``: the topic's questions, newest first, for practice and flashcards.

It also writes ``practice_pool``: one small indexed row per question, so practice can
filter by category and difficulty without scanning the question text.

Generated sections (summary, story, clue write-ups, theme) aren't here: the content
service adds them on top, cached separately. A topic asked once or twice still gets a
record, marked ``thin``, so any answer found by search has a page.
"""

import json
import sqlite3
from collections import defaultdict
from typing import Any

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.relate import STOPWORDS, is_proper, tokenize

SCHEMA_VERSION = 1

SCHEMA = """
DROP TABLE IF EXISTS topic_snapshots;
DROP TABLE IF EXISTS practice_pool;
CREATE TABLE topic_snapshots (
    topic_id TEXT PRIMARY KEY REFERENCES topics(id),
    json TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);
-- Small and indexed, so practice can filter 186k questions without scanning their text.
CREATE TABLE practice_pool (
    tossup_id TEXT PRIMARY KEY REFERENCES tossups(id),
    topic_id TEXT REFERENCES topics(id),
    category TEXT,
    difficulty INTEGER
);
"""

THIN_BELOW = 3  # topics asked fewer times than this get a thin page
_ALIASES = 8
_EXAMPLES = 3
_DISTINGUISHING = 3

DATE_PROPERTIES = {
    "P569": "born",
    "P570": "died",
    "P571": "founded",
    "P576": "dissolved",
    "P577": "published",
    "P580": "began",
    "P582": "ended",
    "P585": "date",
}
PLACE_PROPERTIES = {
    "P625": "location",
    "P276": "location",
    "P131": "located in",
    "P19": "birthplace",
    "P20": "place of death",
    "P17": "country",
}


def _load_clues(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """The ranked clues of every topic, with example wordings from other sets."""
    picks: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT s.cluster_id, s.topic_id, s.rank, s.display_label, c.text, s.n_sets, "
        "k.n_tossups, s.impact, s.median_position, s.share_in_power, s.share_last_line, "
        "s.position_hist, s.difficulty_hist, s.first_year, s.last_year, s.trend "
        "FROM cluster_scores s JOIN clue_clusters k ON k.id = s.cluster_id "
        "JOIN clues c ON c.id = k.representative_clue_id WHERE s.rank IS NOT NULL"
    ):
        (cid, topic_id, rank, label, text, n_sets, n_tossups, impact, median, power, last,
         hist, bands, first, last_year, trend) = row  # fmt: skip
        picks[cid] = {
            "topic_id": topic_id,
            "clue": {
                "rank": rank,
                "cluster_id": cid,
                "label": label,
                "text": text,
                "examples": [],
                "n_sets": n_sets,
                "n_tossups": n_tossups,
                "impact": round(impact, 4),
                "median_position": round(median, 4),
                "heatmap": {
                    "position_hist": json.loads(hist),
                    "share_in_power": round(power, 4),
                    "share_last_line": round(last, 4),
                    "difficulty": json.loads(bands),
                    "years": [first, last_year],
                    "trend": trend,
                },
            },
        }
    # The card's text and examples should name its label: a big cluster can hold a
    # neighboring fact ("Ras the Exhorter" merged with Brotherhood clues). Wordings that
    # name the label come first, then the newest, one per set.
    members: dict[int, list[tuple[bool, int, int, str, str]]] = defaultdict(list)
    for cid, clue_id, text, set_id, year in conn.execute(
        "SELECT m.cluster_id, c.id, c.text, t.set_id, COALESCE(st.year, 0) FROM cluster_scores s "
        "JOIN clue_cluster_members m ON m.cluster_id = s.cluster_id "
        "JOIN clues c ON c.id = m.clue_id JOIN tossups t ON t.id = c.tossup_id "
        "JOIN sets st ON st.id = t.set_id WHERE s.rank IS NOT NULL"
    ):
        label = picks[cid]["clue"]["label"]
        members[cid].append((not names_label(text, label), -year, clue_id, text, set_id))
    for cid, candidates in members.items():
        clue = picks[cid]["clue"]
        candidates.sort()
        if not names_label(clue["text"], clue["label"]) and not candidates[0][0]:
            clue["text"] = candidates[0][3]  # the representative doesn't name the label
        examples = clue["examples"]
        seen_sets: set[str] = set()
        for _, _, _, text, set_id in candidates:
            if len(examples) == _EXAMPLES:
                break
            if set_id not in seen_sets and text != clue["text"] and text not in examples:
                examples.append(text)
                seen_sets.add(set_id)
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pick in picks.values():
        by_topic[pick["topic_id"]].append(pick["clue"])
    for clues in by_topic.values():
        clues.sort(key=lambda c: c["rank"])
    return by_topic


def names_label(text: str, label: str) -> bool:
    """Does the clue name the label: every content word of it, as whole words?"""
    words = {t.key for t in tokenize(label.rstrip("…"))} - STOPWORDS
    return bool(words) and words <= {t.key for t in tokenize(text)}


def _best_dates(rows: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    """One value per property: the most precise (Wikidata often has a year and a day)."""
    best: dict[str, dict[str, Any]] = {}
    for prop, value in rows:
        if prop not in best or value.get("precision", 0) > best[prop].get("precision", 0):
            best[prop] = value
    return sorted(best.items(), key=lambda kv: kv[1].get("time", ""))


def build_snapshot(
    topic: dict[str, Any],
    clues: list[dict[str, Any]],
    related: list[dict[str, Any]],
    confusions: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    places: list[dict[str, Any]],
    tossup_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "topic": topic,
        "clues": clues,
        "related": related,
        "confusions": confusions,
        "timeline": timeline,
        "map": places,
        "tossup_ids": tossup_ids,
    }


def distinguishing(this: list[dict[str, Any]], other: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each side's top clue labels that the other side doesn't share."""
    this_labels = [c["label"] for c in this]
    other_labels = [c["label"] for c in other]
    this_set = {label.lower() for label in this_labels}
    other_set = {label.lower() for label in other_labels}
    return {
        "this": [label for label in this_labels if label.lower() not in other_set][
            :_DISTINGUISHING
        ],
        "other": [label for label in other_labels if label.lower() not in this_set][
            :_DISTINGUISHING
        ],
    }


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "confusions", "confuse")
    db.recreate(conn, SCHEMA)

    reporter.begin("Loading everything the pages need", None)
    topics = {
        row[0]: row
        for row in conn.execute(
            "SELECT id, slug, display_name, wikidata_qid, wikipedia_title, description, "
            "primary_category, n_tossups, n_sets, difficulty_min, difficulty_max, "
            "first_year, last_year FROM topics"
        )
    }
    names = {tid: row[2] for tid, row in topics.items()}
    # Display aliases are other names for the topic: Wikipedia and Wikidata names first,
    # then answer-line names that are capitalized and seen more than once. Answer lines also
    # accept descriptions ("main character", "the protagonist of Invisible Man").
    aliases: dict[str, list[str]] = defaultdict(list)
    for topic_id, alias, source, weight in conn.execute(
        "SELECT topic_id, alias, source, weight FROM topic_aliases "
        "ORDER BY topic_id, source NOT IN ('title', 'main', 'wikidata'), weight DESC, alias"
    ):
        listed = aliases[topic_id]
        name = names[topic_id]
        if len(listed) >= _ALIASES or alias == name or alias in listed:
            continue
        if source in ("accept", "required") and (weight < 2.0 or not is_proper(alias)):
            continue
        if name.lower() in alias.lower() and alias.lower() != name.lower():
            continue  # "Invisible Man (novel)", "the narrator of Invisible Man"
        listed.append(alias)
    clues = _load_clues(conn)
    reporter.stat("Topics with ranked clues", f"{len(clues):,}")

    clue_text = {}
    related: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a, b, rank, score, fwd, rev, clue_id, text, tossup_id in conn.execute(
        "SELECT r.topic_id, r.related_topic_id, r.rank, r.score, r.n_questions, r.n_reverse, "
        "r.example_clue_id, c.text, c.tossup_id FROM related_topics r "
        "JOIN clues c ON c.id = r.example_clue_id ORDER BY r.topic_id, r.rank"
    ):
        clue_text[clue_id] = text
        if fwd:
            why = f"named in {fwd} of its question{'s' if fwd > 1 else ''}"
        else:
            why = f"its questions name this topic {rev} time{'s' if rev > 1 else ''}"
        related[a].append(
            {"id": b, "name": names[b], "rank": rank, "score": score, "n_questions": fwd,
             "n_reverse": rev, "why": why,
             "example": {"clue_id": clue_id, "tossup_id": tossup_id, "text": text}}
        )  # fmt: skip

    confusions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a, b, rank, score, reasons, evidence in conn.execute(
        "SELECT topic_id, other_topic_id, rank, score, reasons, evidence FROM confusions "
        "ORDER BY topic_id, rank"
    ):
        confusions[a].append(
            {"id": b, "name": names[b], "rank": rank, "score": score,
             "reasons": json.loads(reasons), "evidence": json.loads(evidence),
             "distinguishing_clues": distinguishing(clues.get(a, []), clues.get(b, []))}
        )  # fmt: skip

    dates: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    places: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for topic_id, kind, prop, value in conn.execute(
        "SELECT topic_id, kind, property, value FROM topic_facts WHERE kind IN ('date', 'place')"
    ):
        if kind == "date" and prop in DATE_PROPERTIES:
            dates[topic_id].append((prop, json.loads(value)))
        elif kind == "place" and prop in PLACE_PROPERTIES:
            places[topic_id].append((prop, json.loads(value)))

    tossups: dict[str, list[str]] = defaultdict(list)
    for topic_id, tossup_id in conn.execute(
        "SELECT tt.topic_id, tt.tossup_id FROM tossup_topics tt "
        "JOIN tossups t ON t.id = tt.tossup_id JOIN sets s ON s.id = t.set_id "
        "ORDER BY tt.topic_id, s.year DESC, t.id"
    ):
        tossups[topic_id].append(tossup_id)

    reporter.begin("Writing one record per topic", len(topics))
    rows: list[tuple[str, str, int]] = []
    thin = 0
    for tid, row in topics.items():
        (_, slug, name, qid, title, description, category, n, n_sets, d_min, d_max,
         first, last) = row  # fmt: skip
        thin += n < THIN_BELOW
        topic = {
            "id": tid,
            "slug": slug,
            "name": name,
            "wikidata_qid": qid,
            "wikipedia_title": title,
            "description": description,
            "category": category,
            "aliases": aliases.get(tid, []),
            "stats": {
                "n_tossups": n,
                "n_sets": n_sets,
                "difficulty": [d_min, d_max],
                "years": [first, last],
            },
            "thin": n < THIN_BELOW,
        }
        topic_related = related.get(tid, [])
        timeline = []
        point_set = []
        for owner, is_topic in [(tid, True), *((r["id"], False) for r in topic_related)]:
            for prop, value in _best_dates(dates.get(owner, [])):
                timeline.append(
                    {"id": owner, "label": names[owner], "event": DATE_PROPERTIES[prop],
                     "time": value.get("time"), "precision": value.get("precision"),
                     "is_topic": is_topic}
                )  # fmt: skip
            for prop, value in places.get(owner, []):
                if value.get("lat") is None or value.get("lon") is None:
                    continue
                point_set.append(
                    {"id": owner, "label": names[owner],
                     "place": value.get("label") or names[owner],
                     "kind": PLACE_PROPERTIES[prop], "lat": value["lat"], "lon": value["lon"],
                     "role": "topic" if is_topic else "related"}
                )  # fmt: skip
        timeline.sort(key=lambda e: (e["time"] or "", not e["is_topic"]))
        snapshot = build_snapshot(
            topic,
            clues.get(tid, []),
            topic_related,
            confusions.get(tid, []),
            timeline,
            point_set,
            tossups.get(tid, []),
        )
        rows.append((tid, json.dumps(snapshot, ensure_ascii=False), SCHEMA_VERSION))
        reporter.advance()
        if len(rows) >= 5_000:
            conn.executemany("INSERT INTO topic_snapshots VALUES (?, ?, ?)", rows)
            rows.clear()
    conn.executemany("INSERT INTO topic_snapshots VALUES (?, ?, ?)", rows)
    conn.execute(
        "INSERT INTO practice_pool SELECT t.id, tt.topic_id, t.category, t.difficulty "
        "FROM tossups t LEFT JOIN tossup_topics tt ON tt.tossup_id = t.id"
    )
    conn.execute("CREATE INDEX practice_pool_filter ON practice_pool(category, difficulty)")
    conn.execute("CREATE INDEX practice_pool_topic ON practice_pool(topic_id)")
    conn.commit()
    size = conn.execute("SELECT SUM(LENGTH(json)) FROM topic_snapshots").fetchone()[0] or 0
    reporter.stat("Topic records", f"{len(topics):,} ({thin:,} thin: asked fewer than 3 times)")
    reporter.stat("Total size", f"{size / 1e6:,.0f} MB")
    conn.close()
