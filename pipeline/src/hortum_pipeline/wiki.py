"""Polite, cached access to the Wikipedia, Wikidata and Wikidata Query Service APIs."""

import gzip
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


class HttpCache:
    """Stores JSON responses on disk so re-runs never repeat a request."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(key TEXT PRIMARY KEY, body BLOB, fetched_at REAL)"
        )

    def get(self, key: str) -> Any | None:
        row = self.conn.execute("SELECT body FROM responses WHERE key = ?", (key,)).fetchone()
        return json.loads(gzip.decompress(row[0])) if row else None

    def put(self, key: str, value: Any) -> None:
        body = gzip.compress(json.dumps(value).encode())
        self.conn.execute(
            "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)", (key, body, time.time())
        )
        self.conn.commit()

    def __contains__(self, key: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM responses WHERE key = ?", (key,)).fetchone()
            is not None
        )


class NotCached(Exception):
    """Raised in cache-only mode when a request would need the network."""


class WikiClient:
    """Serial requests with a minimum gap, retries on 429/503/maxlag, and a disk cache.

    Wikimedia's API etiquette asks for a descriptive User-Agent with contact details,
    serial requests, and backing off when told to; this client does all three.
    """

    def __init__(
        self,
        cache: HttpCache,
        user_agent: str,
        min_interval: float = 0.1,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.cache = cache
        self.min_interval = min_interval
        self.http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
            timeout=timeout,
            transport=transport,
        )
        self.network_requests = 0
        self._last_request = 0.0

    @staticmethod
    def cache_key(url: str, params: dict[str, Any]) -> str:
        return f"{url}?{urlencode(sorted(params.items()))}"

    def is_cached(self, url: str, params: dict[str, Any]) -> bool:
        return self.cache_key(url, params) in self.cache

    def get_json(self, url: str, params: dict[str, Any], *, cache_only: bool = False) -> Any:
        key = self.cache_key(url, params)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if cache_only:
            raise NotCached(key)

        for attempt in range(6):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self.http.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 5:
                    raise
                time.sleep(2**attempt)
                continue
            self.network_requests += 1
            if response.status_code in (429, 503):
                time.sleep(float(response.headers.get("Retry-After", 2**attempt)))
                continue
            if response.status_code == 403 and "robot policy" in response.text:
                raise RuntimeError(
                    "Wikimedia refused the request under its robot policy: check that "
                    "PIPELINE_WIKIMEDIA_USER_AGENT has contact details. " + response.text[:200]
                )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag":
                time.sleep(float(response.headers.get("Retry-After", 5)))
                continue
            self.cache.put(key, data)
            return data
        raise RuntimeError(f"gave up after repeated throttling: {url}")


def search_params(query: str, limit: int = 5) -> dict[str, Any]:
    """One request returns the top search hits with their intro text and Wikidata ID."""
    return {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": str(limit),
        "gsrnamespace": "0",
        "prop": "extracts|pageprops",
        "exintro": "1",
        "explaintext": "1",
        "exchars": "1200",
        "exlimit": str(limit),
        "ppprop": "wikibase_item|disambiguation",
        "redirects": "1",
        "maxlag": "5",
    }


def sparql_params(query: str) -> dict[str, Any]:
    return {"query": " ".join(query.split()), "format": "json"}
