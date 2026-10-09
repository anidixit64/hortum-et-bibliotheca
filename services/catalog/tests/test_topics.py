import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from catalog.config import Settings
from catalog.main import build_app

QUESTIONS = [
    # id, topic, set, year, difficulty, category, text
    ("q1", "Q1784288", "s1", 2024, 3, "Literature", "Bledsoe expels him. For 10 points, name it."),
    ("q2", "Q1784288", "s2", 2010, 7, "Literature", "Ras leads a riot. For 10 points, name it."),
    ("q3", "Q308", "s1", 2024, 3, "Science", "It has a perihelion. For 10 points, name it."),
]  # fmt: skip


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE topics (id TEXT PRIMARY KEY, slug TEXT, display_name TEXT);
        CREATE TABLE topic_snapshots (topic_id TEXT PRIMARY KEY, json TEXT, schema_version INT);
        CREATE TABLE sets (id TEXT PRIMARY KEY, name TEXT, year INTEGER);
        CREATE TABLE tossups (id TEXT PRIMARY KEY, set_id TEXT, difficulty INTEGER,
                              category TEXT, subcategory TEXT, answer_text TEXT,
                              answer_html TEXT);
        CREATE TABLE tossup_topics (tossup_id TEXT PRIMARY KEY, topic_id TEXT);
        CREATE TABLE question_layout (tossup_id TEXT PRIMARY KEY, clean_text TEXT,
                                      power_word INTEGER);
        CREATE TABLE clues (tossup_id TEXT, ordinal INTEGER, kind TEXT, word_start INTEGER,
                            word_end INTEGER, in_power INTEGER);
        CREATE TABLE practice_pool (tossup_id TEXT PRIMARY KEY, topic_id TEXT, category TEXT,
                                    difficulty INTEGER);
        INSERT INTO sets VALUES ('s1', 'ACF Fall', 2024), ('s2', 'NSC', 2010);
        """
    )
    for tid, slug, name in [("Q1784288", "invisible-man", "Invisible Man"),
                            ("Q308", "mercury-planet", "Mercury (planet)")]:  # fmt: skip
        conn.execute("INSERT INTO topics VALUES (?, ?, ?)", (tid, slug, name))
        record = {"topic": {"id": tid, "name": name}, "clues": [], "tossup_ids": []}
        conn.execute("INSERT INTO topic_snapshots VALUES (?, ?, 1)", (tid, json.dumps(record)))
    for qid, topic, set_id, _, difficulty, category, text in QUESTIONS:
        conn.execute(
            "INSERT INTO tossups VALUES (?, ?, ?, ?, NULL, 'answer', NULL)",
            (qid, set_id, difficulty, category),
        )
        conn.execute("INSERT INTO tossup_topics VALUES (?, ?)", (qid, topic))
        conn.execute(
            "INSERT INTO practice_pool VALUES (?, ?, ?, ?)", (qid, topic, category, difficulty)
        )
        conn.execute("INSERT INTO question_layout VALUES (?, ?, 3)", (qid, text))
        conn.execute("INSERT INTO clues VALUES (?, 0, 'clue', 0, 4, 1)", (qid,))
        conn.execute("INSERT INTO clues VALUES (?, 1, 'giveaway', 4, 9, 0)", (qid,))
    conn.commit()
    return TestClient(build_app(Settings(corpus_path=path)))


def get(client: TestClient, url: str, **params: Any) -> Any:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_topic_page_by_id_or_slug(client: TestClient) -> None:
    assert get(client, "/topics/Q1784288")["topic"]["name"] == "Invisible Man"
    assert get(client, "/topics/invisible-man")["topic"]["id"] == "Q1784288"
    assert client.get("/topics/nope").status_code == 404


def test_topic_tossups_newest_first(client: TestClient) -> None:
    page = get(client, "/topics/invisible-man/tossups")
    assert page["total"] == 2
    assert [t["id"] for t in page["items"]] == ["q1", "q2"]
    first = page["items"][0]
    assert first["set_name"] == "ACF Fall" and first["power_word"] == 3
    assert [c["kind"] for c in first["clues"]] == ["clue", "giveaway"]
    assert get(client, "/topics/Q1784288/tossups", limit=1, offset=1)["items"][0]["id"] == "q2"


def test_practice_filters_and_skips_seen_questions(client: TestClient) -> None:
    assert get(client, "/practice/next", topic="Q308")["id"] == "q3"
    assert get(client, "/practice/next", category="Literature", difficulty_min=5)["id"] == "q2"
    assert get(client, "/practice/next", topic="invisible-man", exclude="q1")["id"] == "q2"
    assert (
        client.get("/practice/next", params={"topic": "Q308", "exclude": "q3"}).status_code == 404
    )
