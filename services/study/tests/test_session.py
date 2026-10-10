"""The Phase 3 'done when': a scripted session follows a topic, reviews, and buzzes."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from study import cards
from study.config import Settings
from study.main import build_app

QUESTION = (
    "His narrator lives underground. He is expelled by Dr. Bledsoe. Ras leads a riot. "
    "For 10 points, name this Ralph Ellison novel."
)
TOSSUP = {
    "id": "q1",
    "question": QUESTION,
    "power_word": 9,
    "answer": "Invisible Man [reject The Invisible Man]",
    "topic_id": "Q1784288",
    "answer_line": {
        "main": "Invisible Man",
        "required": [],
        "accept": [],
        "prompt": [],
        "reject": ["The Invisible Man"],
    },  # fmt: skip
    "clues": [
        {
            "ordinal": 0,
            "kind": "clue",
            "word_start": 0,
            "word_end": 4,
            "in_power": True,
            "cluster_id": 11,
        },
        {
            "ordinal": 1,
            "kind": "clue",
            "word_start": 4,
            "word_end": 9,
            "in_power": True,
            "cluster_id": 12,
        },
        {
            "ordinal": 2,
            "kind": "clue",
            "word_start": 9,
            "word_end": 13,
            "in_power": False,
            "cluster_id": 13,
        },
        {
            "ordinal": 3,
            "kind": "giveaway",
            "word_start": 13,
            "word_end": 20,
            "in_power": False,
            "cluster_id": None,
        },
    ],  # fmt: skip
}
RECORD = {
    "topic": {"id": "Q1784288", "name": "Invisible Man"},
    "clues": [
        {"rank": 1, "cluster_id": 13, "label": "Ras the Exhorter", "text": "Ras leads a riot."},
        {"rank": 2, "cluster_id": 12, "label": "Dr. Bledsoe", "text": "Bledsoe expels him."},
        {"rank": 3, "cluster_id": 11, "label": "1,369", "text": "He lives underground."},
    ],
}


def fake_catalog(request: httpx.Request) -> httpx.Response:
    data: dict[str, Any] = {"/topics/Q1784288": RECORD, "/tossups/q1": TOSSUP}
    body = data.get(request.url.path)
    return httpx.Response(200, json=body) if body else httpx.Response(404, json={})


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    catalog = httpx.AsyncClient(
        transport=httpx.MockTransport(fake_catalog), base_url="http://catalog"
    )
    settings = Settings(db_path=tmp_path / "study.db", backup_dir=tmp_path / "backups")
    with TestClient(build_app(settings, catalog)) as c:
        yield c


def post(client: TestClient, url: str, **body: Any) -> Any:
    response = client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_scripted_session(client: TestClient) -> None:
    # Follow: a card per ranked clue plus "Name 3 clues for Invisible Man".
    followed = post(client, "/topics/Q1784288/follow")
    assert followed["cards_created"] == 4
    assert post(client, "/topics/Q1784288/follow")["cards_created"] == 0  # idempotent
    assert client.post("/topics/nope/follow").status_code == 404

    due = client.get("/reviews/due").json()
    assert {c["kind"] for c in due} == {"clue", "reverse"} and len(due) == 4

    # Review everything "good": nothing is due any more.
    for card in due:
        reviewed = post(client, "/reviews", card_id=card["card_id"], rating=3)
        assert reviewed["due"] > card["due"]
    assert client.get("/reviews/due").json() == []
    assert client.post("/reviews", json={"card_id": "x", "rating": 3}).status_code == 404
    assert (
        client.post("/reviews", json={"card_id": due[0]["card_id"], "rating": 5}).status_code == 422
    )

    # A rejected answer at word 10 (third clue, after power): wrong, and the two top clues
    # already read become "missed" cards.
    wrong = post(client, "/buzzes", tossup_id="q1", word_index=10, answer_given="The Invisible Man")
    assert wrong["result"] == "incorrect" and wrong["clue_ordinal"] == 2
    assert not wrong["in_power"] and wrong["missed_cards"] == 2
    assert {c["kind"] for c in client.get("/reviews/due").json()} == {"missed"}

    # A prompt isn't recorded; a self-judged override is.
    assert (
        client.post(
            "/buzzes", json={"tossup_id": "q1", "word_index": 2, "answer_given": ""}
        ).json()["result"]
        == "incorrect"
    )
    right = post(client, "/buzzes", tossup_id="q1", word_index=2, answer_given="Invisable Man")
    assert right["result"] == "correct" and right["in_power"] and right["missed_cards"] == 0
    override = post(client, "/buzzes", tossup_id="q1", word_index=15, answer_given="Ellison",
                    self_judgment="correct")  # fmt: skip
    assert override["judged_by"] == "self" and override["result"] == "correct"
    fixed = client.patch(f"/buzzes/{wrong['buzz_id']}", json={"result": "correct"})
    assert fixed.json() == {"buzz_id": wrong["buzz_id"], "result": "correct", "judged_by": "self"}
    assert client.patch("/buzzes/999", json={"result": "correct"}).status_code == 404
    silent = post(client, "/buzzes", tossup_id="q1")
    assert silent["result"] == "no_buzz" and silent["missed_cards"] == 0  # cards exist already

    stats = client.get("/stats").json()
    assert stats["followed_topics"] == 1 and stats["reviews_today"] == 4
    assert stats["buzzing"]["buzzes"] == 5 and stats["buzzing"]["correct"] == 3
    topic = client.get("/topics/Q1784288/stats").json()
    assert topic["followed"] and topic["buzzing"]["accuracy"] == pytest.approx(3 / 4)
    assert topic["buzzed_clusters"] == {"13": 1, "11": 2}  # the override was in the giveaway

    # Unfollow suspends the topic's cards; history stays.
    assert client.delete("/topics/Q1784288/follow").status_code == 204
    assert client.get("/reviews/due").json() == [] and client.get("/topics").json() == []

    assert Path(post(client, "/admin/backup")["backup"]).is_file()


def test_prompt_is_not_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    TOSSUP["answer_line"]["prompt"].append("novel")  # type: ignore[index]
    try:
        out = post(client, "/buzzes", tossup_id="q1", word_index=3, answer_given="novel")
    finally:
        TOSSUP["answer_line"]["prompt"].remove("novel")  # type: ignore[index]
    assert out["result"] == "prompt" and not out["recorded"]
    assert client.get("/stats").json()["buzzing"]["buzzes"] == 0


def test_card_ids_are_stable_across_rebuilds() -> None:
    a = cards.card_id("Q1784288", "clue", "Ras leads a riot.")
    assert a == cards.card_id("Q1784288", "clue", "ras  leads a RIOT")
    assert a != cards.card_id("Q1784288", "missed", "Ras leads a riot.")
