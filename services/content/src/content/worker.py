"""The content worker: takes jobs from content.db and fetches enrichments, one at a time."""

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import httpx

from content import jobs
from content.config import Settings
from content.fetchers import Topic, Unavailable, books, images, videos, wiki
from content.http import FetchError, PoliteClient

log = logging.getLogger("content.worker")


class TopicNotFound(Exception):
    pass


def fetchers(settings: Settings) -> dict[str, tuple[int, Callable[[Topic, PoliteClient], Any]]]:
    """Kind -> (version, fetch function)."""
    return {
        "wiki": (wiki.VERSION, wiki.fetch),
        "images": (images.VERSION, images.fetch),
        "books": (books.VERSION, books.fetch),
        "videos": (
            videos.VERSION,
            lambda topic, http: videos.fetch(
                topic, http, settings.youtube_api_key, settings.video_channels
            ),
        ),
    }


def make_http(
    conn: sqlite3.Connection, settings: Settings, transport: httpx.BaseTransport | None = None
) -> PoliteClient:
    wikimedia = settings.wikimedia_user_agent or settings.user_agent
    return PoliteClient(
        conn,
        {"en.wikipedia.org": wikimedia, "commons.wikimedia.org": wikimedia},
        settings.user_agent,
        timeout=settings.request_timeout_seconds,
        transport=transport,
    )


def load_topic(catalog: httpx.Client, topic_id: str) -> Topic:
    response = catalog.get(f"/topics/{topic_id}")
    if response.status_code == 404:
        raise TopicNotFound(topic_id)
    response.raise_for_status()
    return Topic.from_record(response.json())


def store(
    conn: sqlite3.Connection, topic_id: str, kind: str, status: str, payload: Any, version: int
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO enrichments VALUES (?, ?, ?, ?, ?, ?)",
            (
                topic_id,
                kind,
                status,
                json.dumps(payload, ensure_ascii=False),
                version,
                jobs.now().isoformat(),
            ),
        )


def is_empty(payload: dict[str, Any]) -> bool:
    return all(not v for k, v in payload.items() if isinstance(v, list))


def run_once(
    conn: sqlite3.Connection, settings: Settings, http: PoliteClient, catalog: httpx.Client
) -> jobs.Job | None:
    """Does one job, if any is ready. Each kind succeeds or fails on its own."""
    job = jobs.claim(conn)
    if job is None:
        return None
    version, fetch = fetchers(settings)[job.kind]
    try:
        topic = load_topic(catalog, job.topic_id)
        payload = fetch(topic, http)
        store(
            conn, job.topic_id, job.kind, "empty" if is_empty(payload) else "ok", payload, version
        )
        jobs.finish(conn, job)
        log.info("fetched %s for %s", job.kind, job.topic_id)
    except Unavailable as exc:
        store(conn, job.topic_id, job.kind, "unavailable", {"reason": str(exc)}, version)
        jobs.finish(conn, job)
    except TopicNotFound:
        jobs.fail(conn, job, "topic not in the catalog", max_attempts=job.attempts)
    except (FetchError, httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("%s for %s failed (attempt %d): %s", job.kind, job.topic_id, job.attempts, exc)
        jobs.fail(conn, job, f"{type(exc).__name__}: {exc}", settings.job_max_attempts)
    return job


def run_forever(conn: sqlite3.Connection, settings: Settings) -> None:
    jobs.recover(conn)
    http = make_http(conn, settings)
    with httpx.Client(base_url=settings.catalog_url, timeout=30) as catalog:
        while True:
            if run_once(conn, settings, http, catalog) is None:
                time.sleep(settings.worker_poll_seconds)
