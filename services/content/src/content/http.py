"""Polite, cached HTTP for the fetchers: one request at a time per host, with retries."""

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

MIN_INTERVAL = {"en.wikipedia.org": 0.2, "commons.wikimedia.org": 0.2, "openlibrary.org": 1.0}
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


class PoliteClient:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_agents: dict[str, str],
        default_user_agent: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        retries: int = 3,
    ) -> None:
        self.conn = conn
        self.user_agents = user_agents  # host -> User-Agent
        self.default_user_agent = default_user_agent
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)
        self.retries = retries
        self.last_request: dict[str, float] = {}
        self.network_requests = 0

    def get_json(self, url: str, params: dict[str, Any] | None = None, cache: bool = True) -> Any:
        """GET ``url`` as JSON, from the cache when possible (keyed by the full URL)."""
        full = f"{url}?{urlencode(sorted((params or {}).items()))}" if params else url
        if cache:
            row = self.conn.execute(
                "SELECT status, body FROM http_cache WHERE url = ?", (full,)
            ).fetchone()
            if row:
                return json.loads(row[1])
        host = urlsplit(url).netloc
        headers = {"User-Agent": self.user_agents.get(host, self.default_user_agent)}
        for attempt in range(self.retries + 1):
            wait = MIN_INTERVAL.get(host, 0.0) - (time.monotonic() - self.last_request.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self.last_request[host] = time.monotonic()
            try:
                response = self.client.get(url, params=params, headers=headers)
            except httpx.RequestError as exc:
                if attempt == self.retries:
                    raise FetchError(f"{host}: {exc}") from exc
                time.sleep(2**attempt)
                continue
            self.network_requests += 1
            if response.status_code in RETRY_STATUSES and attempt < self.retries:
                time.sleep(float(response.headers.get("Retry-After", 2**attempt)))
                continue
            if response.status_code >= 400:
                raise FetchError(f"{host} answered {response.status_code}: {response.text[:200]}")
            data = response.json()
            if cache:
                with self.conn:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?)",
                        (full, response.status_code, response.text, datetime.now(UTC).isoformat()),
                    )
            return data
        raise FetchError(f"{host}: gave up after {self.retries} retries")
