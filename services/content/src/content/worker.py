"""The content worker: takes jobs from content.db and fetches enrichments, one at a time."""

import functools
import json
import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx

from content import cleanup, jobs, writing
from content.config import Settings
from content.fetchers import Topic, Unavailable, books, images, videos, wiki
from content.generate import GenerationError, QuotaExceeded, Reply, Request, chain
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


_NER: dict[str, cleanup.Ner] = {}


def ner_for(settings: Settings) -> cleanup.Ner:
    """One NER process per worker, kept between topics."""
    if settings.ner_python not in _NER:
        _NER[settings.ner_python] = cleanup.Ner(settings.ner_python)
    return _NER[settings.ner_python]


def clean_clues(
    settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """The topic's cleaned clue list, its input fingerprint and the model's reply."""
    response = catalog.get(
        f"/topics/{topic_id}/clue-candidates", params={"limit": cleanup.CANDIDATES}
    )
    if response.status_code == 404:
        raise TopicNotFound(topic_id)
    response.raise_for_status()
    found = response.json()
    if not found["candidates"]:
        return {"clues": [], "edits": [], "rejected": []}, found["fingerprint"], None
    sentences = [s for c in found["candidates"] for s in c["sentences"]]
    ents = ner_for(settings).entities(sentences)
    hints: dict[int, str] = {}
    if ents:
        at = 0
        for clue in found["candidates"]:
            mine = ents[at : at + len(clue["sentences"])]
            at += len(clue["sentences"])
            hint = cleanup.ner_hint(clue["label"], mine)
            if hint:
                hints[clue["id"]] = hint
    request = Request("clue_cleanup", cleanup.SYSTEM, cleanup.prompt(found, hints), cleanup.SCHEMA)
    reply = chain.run(
        chain.build(settings.light_chain, settings), request, lambda d: cleanup.problem(found, d)
    )
    off_topic: list[int] = []
    if found.get("groups"):
        groups_reply = chain.run(
            chain.build(settings.light_chain, settings),
            Request("answer_groups", cleanup.GROUP_SYSTEM, cleanup.group_prompt(found),
                    cleanup.GROUP_SCHEMA),
        )  # fmt: skip
        off_topic = list(groups_reply.data.get("off_topic_groups") or [])
    checked = cleanup.check(found, reply.data, hints, off_topic)
    payload = {
        "clues": cleanup.apply(found, checked),
        "edits": reply.data.get("edits", []),
        "excluded_groups": [
            {k: g[k] for k in ("id", "key", "category", "answer", "tossups")}
            for g in checked.excluded_groups
        ],
        "rejected": checked.rejected,
        "hints": hints,
    }
    return payload, found["fingerprint"], reply


def store_generation(
    conn: sqlite3.Connection,
    topic_id: str,
    kind: str,
    fingerprint: str,
    prompt_version: int,
    payload: Any,
    reply: Reply | None,
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                topic_id, kind, fingerprint, prompt_version,
                reply.backend if reply else "none", reply.model if reply else "none",
                json.dumps(payload, ensure_ascii=False),
                reply.input_tokens if reply else 0, reply.output_tokens if reply else 0,
                jobs.now().isoformat(),
            ),
        )  # fmt: skip


class NotReady(Exception):
    """A section this one is written from isn't there yet: try again shortly."""


def cleaned(conn: sqlite3.Connection, topic_id: str) -> tuple[dict[str, Any], str]:
    """The topic's clue cleanup and its identity (what derived sections are written from)."""
    row = conn.execute(
        "SELECT payload, fingerprint, created_at FROM generations "
        "WHERE topic_id = ? AND kind = 'clues'",
        (topic_id,),
    ).fetchone()
    if row is None:
        jobs.enqueue(conn, topic_id, "clues", 10)
        raise NotReady("clue cleanup not done yet")
    return json.loads(row[0]), f"{row[1]}:{row[2]}"


def clue_inputs(
    catalog: httpx.Client, topic_id: str, clues: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[int, list[str]]]:
    """The catalog's view of the topic and each cleaned clue's example sentences."""
    found = catalog.get(
        f"/topics/{topic_id}/clue-candidates", params={"limit": cleanup.CANDIDATES}
    ).json()
    by_id = {c["id"]: c for c in found["candidates"]}
    examples = {
        clue["rank"]: [
            s for cid in clue["clue_ids"] for s in by_id.get(cid, {}).get("sentences", [])
        ][:3]
        for clue in clues
    }
    return found, examples


def add(total: Reply | None, reply: Reply) -> Reply:
    if total is None:
        return reply
    total.input_tokens += reply.input_tokens
    total.output_tokens += reply.output_tokens
    return total


def write_explanations(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """One-line summaries and explanations for the cleaned first page of clues."""
    clean, identity = cleaned(conn, topic_id)
    clues = clean["clues"][: writing.FIRST_PAGE]
    found, examples = clue_inputs(catalog, topic_id, clues)
    backends = chain.build(settings.light_chain, settings)
    total: Reply | None = None
    out: dict[int, dict[str, str]] = {}
    for start in range(0, len(clues), writing.BATCH):
        batch = clues[start : start + writing.BATCH]
        ranks = [c["rank"] for c in batch]
        listed = [
            {"rank": c["rank"], "clue": c["label"], "questions": c["n_questions"],
             "examples": examples[c["rank"]]}
            for c in batch
        ]  # fmt: skip
        prompt = writing.EXPLAIN.format(
            name=found["name"],
            category=found.get("category") or "unknown",
            low=writing.EXPLANATION_WORDS[0],
            high=writing.EXPLANATION_WORDS[1],
            clues=json.dumps(listed, ensure_ascii=False, indent=1),
        )
        reply = chain.run(
            backends,
            Request("clue_explanations", writing.EXPLAIN_SYSTEM, prompt, writing.EXPLAIN_SCHEMA),
            functools.partial(writing.explain_problem, ranks=ranks),
        )
        total = add(total, reply)
        for entry in reply.data["explanations"]:
            if entry["rank"] in ranks:
                out[entry["rank"]] = {
                    "one_line": entry["one_line"].strip(),
                    "explanation": entry["explanation"].strip(),
                }
    explained = [
        {"rank": c["rank"], "label": c["label"], **out[c["rank"]]}
        for c in clues
        if c["rank"] in out
    ]
    return {"clues": explained}, identity, total


def write_summary(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """The hook and summary, with the cleaned clues marked."""
    clean, identity = cleaned(conn, topic_id)
    clues = clean["clues"][: writing.FIRST_PAGE]
    wiki_row = conn.execute(
        "SELECT status, payload FROM enrichments WHERE topic_id = ? AND kind = 'wiki'",
        (topic_id,),
    ).fetchone()
    if wiki_row is None:
        jobs.enqueue(conn, topic_id, "wiki", 10)
        raise NotReady("Wikipedia text not fetched yet")
    wiki = json.loads(wiki_row[1]) if wiki_row[0] == "ok" else None
    explained = conn.execute(
        "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'explanations'",
        (topic_id,),
    ).fetchone()
    lines = (
        {c["rank"]: c["one_line"] for c in json.loads(explained[0])["clues"]} if explained else {}
    )
    topic = catalog.get(f"/topics/{topic_id}/clue-candidates", params={"limit": 1}).json()
    ranks = [c["rank"] for c in clues]
    listing = "\n".join(
        f"{c['rank']}: {c['label']}" + (f" — {lines[c['rank']]}" if c["rank"] in lines else "")
        for c in clues
    )
    prompt = writing.SUMMARY.format(
        name=topic["name"],
        category=topic.get("category") or "unknown",
        low=writing.SUMMARY_WORDS[0],
        high=writing.SUMMARY_WORDS[1],
        clues=listing,
        source=writing.source_text(wiki),
    )
    reply = chain.run(
        chain.build(settings.writing_chain, settings),
        Request("summary", writing.SUMMARY_SYSTEM, prompt, writing.SUMMARY_SCHEMA),
        lambda d: writing.summary_problem(d, ranks),
    )
    text, marked = writing.clean_summary(reply.data["summary"].strip(), ranks)
    source = (
        {"title": wiki["title"], "url": wiki["url"], "license": wiki["license"]} if wiki else None
    )
    payload = {"hook": reply.data["hook"].strip(), "summary": text, "marked": marked,
               "source": source}  # fmt: skip
    return payload, identity, reply


Generator = Callable[
    [sqlite3.Connection, Settings, httpx.Client, str], tuple[dict[str, Any], str, Reply | None]
]


def write_cleanup(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    return clean_clues(settings, catalog, topic_id)


GENERATORS: dict[str, tuple[Generator, int]] = {
    "clues": (write_cleanup, cleanup.PROMPT_VERSION),
    "explanations": (write_explanations, writing.EXPLANATIONS_VERSION),
    "summary": (write_summary, writing.SUMMARY_VERSION),
}  # fmt: skip


def run_generation(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, job: jobs.Job
) -> None:
    generate, version = GENERATORS[job.kind]
    try:
        payload, fingerprint, reply = generate(conn, settings, catalog, job.topic_id)
        store_generation(conn, job.topic_id, job.kind, fingerprint, version, payload, reply)
        jobs.finish(conn, job)
        log.info("wrote %s for %s (%s)", job.kind, job.topic_id, reply.model if reply else "none")
    except NotReady as exc:
        jobs.defer(conn, job, jobs.now() + timedelta(seconds=20), str(exc))
    except QuotaExceeded as exc:
        until = exc.retry_at or jobs.now() + timedelta(hours=1)
        log.warning("%s for %s waits until %s: %s", job.kind, job.topic_id, until, exc)
        jobs.defer(conn, job, until, str(exc))
    except TopicNotFound:
        jobs.fail(conn, job, "topic not in the catalog", max_attempts=job.attempts)
    except (GenerationError, httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("%s for %s failed (attempt %d): %s", job.kind, job.topic_id, job.attempts, exc)
        jobs.fail(conn, job, f"{type(exc).__name__}: {exc}", settings.job_max_attempts)


def run_once(
    conn: sqlite3.Connection, settings: Settings, http: PoliteClient, catalog: httpx.Client
) -> jobs.Job | None:
    """Does one job, if any is ready. Each kind succeeds or fails on its own."""
    job = jobs.claim(conn)
    if job is None:
        return None
    if job.kind in jobs.GENERATED:
        run_generation(conn, settings, catalog, job)
        return job
    if job.kind not in fetchers(settings):  # a newer worker's kind: put it back, don't crash
        jobs.defer(conn, job, jobs.now() + timedelta(minutes=1), f"unknown kind {job.kind!r}")
        return job
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
