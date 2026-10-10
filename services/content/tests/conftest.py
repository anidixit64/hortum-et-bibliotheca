import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from content import db
from content.config import Settings
from content.http import PoliteClient


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(tmp_path / "content.db")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]


FakeWeb = Callable[[sqlite3.Connection, Callable[[httpx.Request], Any]], PoliteClient]


def _fake_web(conn: sqlite3.Connection, handler: Callable[[httpx.Request], Any]) -> PoliteClient:
    """A PoliteClient whose requests go to ``handler`` (returning JSON) instead of the web."""

    def respond(request: httpx.Request) -> httpx.Response:
        body = handler(request)
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    return PoliteClient(conn, {}, "test-agent", transport=httpx.MockTransport(respond), retries=0)


@pytest.fixture
def web() -> FakeWeb:
    return _fake_web
