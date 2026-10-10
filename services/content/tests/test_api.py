import sqlite3
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from content import jobs, worker
from content.config import Settings
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
            "query": {"pages": [{"title": "Invisible Man", "extract": "A novel.\n\n== Plot ==\nX"}]}
        }
    if params.get("prop") == "pageimages|images":
        return {"query": {"pages": [{"images": []}]}}
    if params.get("action") == "parse":
        return httpx.Response(503, json={})  # Wikipedia down: books fail on their own
    return {"docs": []}


def catalog() -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/topics/Q1784288":
            return httpx.Response(200, json=RECORD)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(respond), base_url="http://catalog")


def test_page_view_queues_then_the_worker_fills_in(tmp_path: Path, web: Any) -> None:
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
    }
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
