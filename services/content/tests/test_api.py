import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from content import jobs, routes, worker
from content.config import Settings
from content.generate import Reply
from content.main import build_app

RECORD = {
    "topic": {
        "id": "Q1784288",
        "name": "Invisible Man",
        "wikipedia_title": "Invisible Man",
        "wikidata_qid": "Q1784288",
        "category": "Literature",
        "description": "1952 novel",
        "aliases": [],
    }
}


def fake_web(request: httpx.Request) -> Any:
    params = request.url.params
    if params.get("prop") == "extracts|info":
        return {
            "query": {
                "pages": [
                    {
                        "title": "Invisible Man",
                        "extract": "A novel about a man who "
                        "lives underground and steals power.\n\n== Plot ==\n"
                        "He lives underground and steals power from the building.",
                    }
                ]
            }
        }
    if params.get("prop") == "pageimages|images":
        return {"query": {"pages": [{"images": []}]}}
    if params.get("action") == "parse":
        return httpx.Response(503, json={})  # Wikipedia down: books fail on their own
    return {"docs": []}


CANDIDATES = {
    "topic_id": "Q1784288",
    "name": "Invisible Man",
    "category": "Literature",
    "fingerprint": "abc123",
    "candidates": [
        {
            "id": 1,
            "rank": 1,
            "label": "Ras the Exhorter",
            "key": "ras the exhorter",
            "n_questions": 3,
            "spellings": {"Ras the Exhorter": ["q1", "q2", "q3"]},
            "sentences": ["Ras the Exhorter leads a riot."],
        },
        {
            "id": 2,
            "rank": 2,
            "label": "battle royal",
            "key": "battle royal",
            "n_questions": 2,
            "spellings": {"battle royal": ["q1", "q4"]},
            "sentences": ["He fights in a battle royal."],
        },
        {
            "id": 3,
            "rank": 3,
            "label": "Battle Royale",
            "key": "battle royale",
            "n_questions": 2,
            "spellings": {"Battle Royale": ["q5", "q6"]},
            "sentences": ["The Battle Royale is blindfolded."],
        },
        {
            "id": 4,
            "rank": 4,
            "label": "narrator",
            "key": "narrator",
            "n_questions": 2,
            "spellings": {"narrator": ["q2", "q3"]},
            "sentences": ["The narrator lives underground."],
        },
    ],
}


def fake_reply(backends: Any, request: Any, check: Any = None) -> Reply:
    """A model that merges the two battle royals, drops the stand-in, and writes."""
    if request.task == "clue_explanations":
        text = " ".join(["word"] * 180)
        data: dict[str, Any] = {
            "explanations": [
                {"rank": r, "one_line": f"Clue {r} in one line.", "explanation": text}
                for r in (1, 2)
            ]
        }
    elif request.task == "timeline":
        quote = "A novel about a man who lives underground and steals power."
        data = {"events": []}
    elif request.task == "feature":
        text = " ".join(["word"] * 70)
        data = {
            "title": "Six moments",
            "entries": [{"name": f"Moment {i}", "text": text} for i in range(1, 7)],
        }
    elif request.task == "theme":
        light = {t: "#f4ead8" for t in ("bg", "surface", "accent_soft", "header_tint")}
        dark = {t: "#24161f" for t in ("bg", "surface", "accent_soft", "header_tint")}
        data = {
            "light": light | {"text": "#222222", "muted": "#555555", "accent": "#7a3b8f",
                              "accent2": "#b5651d"},
            "dark": dark | {"text": "#eeeeee", "muted": "#aaaaaa", "accent": "#c9a0dc",
                            "accent2": "#e2a160"},
            "font": "classical-serif",
        }  # fmt: skip
    elif request.task == "fun_facts":
        quote = "He lives underground and steals power from the building."
        data = {"facts": [{"fact": f"Fact {i}.", "source_sentence": quote} for i in range(5)]}
    elif request.task == "summary":
        body = "[[1|The battle royal]] opens the novel. " + " ".join(["word"] * 600)
        data = {"hook": "A young man fights blindfolded for a scholarship.", "summary": body}
    else:
        data = {
            "edits": [
                {"id": 1, "action": "keep"},
                {"id": 2, "action": "rename", "label": "battle royal"},
                {"id": 3, "action": "merge", "into": 2},
                {"id": 4, "action": "drop", "reason": "answer_itself"},
            ]
        }
    assert check is None or check(data) is None
    return Reply(data, "fake", "fake-model", 100, 20)


def catalog() -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/topics/Q1784288":
            return httpx.Response(200, json=RECORD)
        if request.url.path == "/topics/Q1784288/clue-candidates":
            return httpx.Response(200, json=CANDIDATES)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(respond), base_url="http://catalog")


def test_page_view_queues_then_the_worker_fills_in(
    tmp_path: Path, web: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker.chain, "run", fake_reply)
    monkeypatch.setattr(routes, "clue_fingerprint", lambda request, topic_id, stored: stored)
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    api = TestClient(app)
    first = api.get("/topics/Q1784288/content").json()
    assert first["status"] == "partial"
    assert {k: s["status"] for k, s in first["sections"].items()} == dict.fromkeys(
        jobs.KINDS, "pending"
    )

    conn: sqlite3.Connection = app.state.db
    http, cat = web(conn, fake_web), catalog()
    while worker.run_once(conn, settings, http, cat):
        pass
    second = api.get("/topics/Q1784288/content").json()
    sections = {k: s["status"] for k, s in second["sections"].items()}
    # wiki ok; images found nothing; videos need a key; books failed and wait to retry.
    assert sections == {
        "wiki": "ok",
        "images": "empty",
        "videos": "unavailable",
        "books": "pending",
        "clues": "ok",
        "explanations": "ok",
        "summary": "ok",
        "facts": "ok",
        "theme": "ok",
        "special": "ok",
        "blurbs": "pending",
    }
    explained = second["sections"]["explanations"]["payload"]["clues"]
    assert [c["one_line"] for c in explained] == ["Clue 1 in one line.", "Clue 2 in one line."]
    summary = second["sections"]["summary"]["payload"]
    assert summary["marked"] == [1] and summary["hook"].startswith("A young man")
    # Recounted from the questions behind each spelling: q1 counts once.
    cleaned = second["sections"]["clues"]["payload"]["clues"]
    assert [(c["label"], c["n_questions"], c["clue_ids"]) for c in cleaned] == [
        ("battle royal", 4, [2, 3]),
        ("Ras the Exhorter", 3, [1]),
    ]
    assert second["sections"]["wiki"]["payload"]["sections"][0]["heading"] == "Plot"
    assert api.get("/jobs").json()["books"] == {"queued": 1}

    refreshed = api.post("/topics/Q1784288/refresh", params={"kinds": ["wiki"]}).json()
    assert refreshed["queued"] == ["wiki"]
    assert (
        api.get("/topics/Q1784288/content", params={"enqueue": False}).json()["sections"]["wiki"][
            "status"
        ]
        == "pending"
    )


def test_unknown_topic_fails_without_retrying(tmp_path: Path, web: Any) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    conn: sqlite3.Connection = app.state.db
    jobs.enqueue(conn, "nope", "wiki")
    worker.run_once(conn, settings, web(conn, fake_web), catalog())
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "failed"


def test_explanations_cover_every_cleaned_clue(
    tmp_path: Path, web: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[list[int]] = []

    def fake(backends: Any, request: Any, check: Any = None) -> Reply:
        if request.task == "clue_explanations":
            ranks = [int(r) for r in re.findall(r'"rank": (\d+)', request.prompt)]
            asked.append(ranks)
            text = " ".join(["word"] * 180)
            data = {"explanations": [{"rank": r, "one_line": f"Clue {r}.", "explanation": text}
                                     for r in ranks]}  # fmt: skip
            return Reply(data, "fake", "fake-model", 1, 1)
        return fake_reply(backends, request, check)

    monkeypatch.setattr(worker.chain, "run", fake)
    monkeypatch.setattr(routes, "clue_fingerprint", lambda request, topic_id, stored: stored)
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    api, conn = TestClient(app), app.state.db
    http, cat = web(conn, fake_web), catalog()
    for kind in ("wiki", "clues", "explanations"):  # explanations are written from the text
        jobs.enqueue(conn, "Q1784288", kind)
    while worker.run_once(conn, settings, http, cat):
        pass
    assert asked == [[1, 2]]
    explained = api.get("/topics/Q1784288/content", params={"enqueue": False}).json()
    assert [c["rank"] for c in explained["sections"]["explanations"]["payload"]["clues"]] == [1, 2]


def test_a_section_from_an_older_fetcher_is_shown_and_fetched_again(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    conn: sqlite3.Connection = app.state.db
    with conn:
        conn.execute(
            "INSERT INTO enrichments VALUES ('Q1', 'wiki', 'ok', '{\"lead\": \"Old.\"}', 1, "
            "'2026-01-01T00:00:00+00:00')"
        )
    content = TestClient(app).get("/topics/Q1/content").json()
    wiki = content["sections"]["wiki"]
    assert wiki["payload"]["lead"] == "Old." and wiki["stale"] and content["status"] == "partial"
    assert jobs.open_kinds(conn, "Q1").get("wiki") == "queued"


def test_missing_model_keys_fail_writing_instead_of_deferring(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    conn: sqlite3.Connection = app.state.db
    jobs.enqueue(conn, "Q1784288", "clues")
    job = jobs.claim(conn)
    assert job is not None
    worker.run_generation(conn, settings, catalog(), job)
    status, error = conn.execute(
        "SELECT status, last_error FROM jobs WHERE kind = 'clues'"
    ).fetchone()
    assert status == "failed"
    assert error == "no backends configured"
    content = TestClient(app).get("/topics/Q1784288/content", params={"enqueue": False}).json()
    assert content["sections"]["clues"]["status"] == "failed"


def test_sections_needing_a_failed_section_fail_instead_of_waiting_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    conn = build_app(settings).state.db
    jobs.enqueue(conn, "Q1", "clues")
    clues = jobs.claim(conn)
    assert clues is not None
    jobs.fail(conn, clues, "the model kept failing", max_attempts=clues.attempts)
    jobs.enqueue(conn, "Q1", "summary")
    summary = jobs.claim(conn)
    assert summary is not None
    worker.run_generation(conn, settings, catalog(), summary)
    assert jobs.open_kinds(conn, "Q1") == {"clues": "failed", "summary": "failed"}


def test_a_page_view_holds_dependents_until_their_inputs_exist(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    conn = app.state.db
    TestClient(app).get("/topics/Q1/content")
    first: list[str] = []
    while job := jobs.claim(conn):
        first.append(job.kind)
        jobs.finish(conn, job)
    assert set(first) == {"wiki", "images", "books", "videos", "clues"}
    with conn:
        conn.execute(
            "INSERT INTO enrichments VALUES "
            "('Q1', 'wiki', 'ok', '{}', 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO enrichments VALUES "
            "('Q1', 'images', 'ok', '{}', 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO generations VALUES "
            "('Q1', 'clues', 'fp', 1, 'gemini', 'm', '{}', 0, 0, '2026-01-01T00:00:00+00:00')"
        )
    rest: list[str] = []
    while job := jobs.claim(conn):
        rest.append(job.kind)
        jobs.finish(conn, job)
    assert rest == ["summary", "theme", "explanations", "facts"]
    with conn:
        conn.execute(
            "INSERT INTO generations VALUES "
            "('Q1', 'summary', 'fp', 1, 'gemini', 'm', '{}', 0, 0, '2026-01-01T00:00:00+00:00')"
        )
    special = jobs.claim(conn)
    assert special is not None and special.kind == "special"


def test_failed_writing_stays_partial_until_it_is_stored(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    conn: sqlite3.Connection = app.state.db
    jobs.enqueue(conn, "Q1", "clues")
    job = jobs.claim(conn)
    assert job is not None
    jobs.fail(conn, job, "no backends configured", max_attempts=job.attempts)
    conn.execute(
        "UPDATE jobs SET updated_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", job.id)
    )
    client = TestClient(app)
    content = client.get("/topics/Q1/content").json()
    assert content["status"] == "partial"
    assert content["sections"]["clues"]["status"] == "pending"
    assert jobs.open_kinds(conn, "Q1")["clues"] == "queued"


def test_non_ai_view_fetches_sources_and_skips_generation(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    app = build_app(settings)
    client = TestClient(app)
    body = client.get("/topics/Q1/content", params={"generate": False}).json()
    assert body["status"] == "partial"
    conn = app.state.db
    assert set(jobs.open_kinds(conn, "Q1")) == set(jobs.FETCHED)
    for kind in jobs.GENERATED:
        assert body["sections"][kind]["status"] == "unavailable"
    started = client.get("/topics/Q1/content", params={"generate": True}).json()
    assert set(jobs.open_kinds(conn, "Q1")) == set(jobs.KINDS)
    assert started["sections"]["summary"]["status"] == "pending"
