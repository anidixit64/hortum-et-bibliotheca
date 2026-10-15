"""The content worker: takes jobs from content.db and fetches enrichments.

With ``worker_threads > 1`` (the default), independent jobs run in parallel so that
fetches (wiki, images, books, videos) overlap, and generation tasks that depend on
different inputs (theme ← images, facts ← wiki, etc.) don't wait for each other.
Each thread gets its own DB connection and HTTP clients; the chain rotates backends
by task name so concurrent LLM calls spread across providers.
"""

import functools
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, NoReturn

import httpx

from content import blurbs, cleanup, jobs, special, theme, writing
from content.config import Settings, _env_file
from content.fetchers import Topic, Unavailable, books, images, videos, wiki
from content.generate import GenerationError, QuotaExceeded, Reply, Request, chain
from content.http import FetchError, PoliteClient
from content.trace import bind as bind_trace
from content.trace import configure as configure_trace
from content.trace import event as trace_event
from content.trace import reset as reset_trace

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
_ner_lock = threading.Lock()


def ner_entities(settings: Settings, sentences: list[str]) -> list[list[list[str]]]:
    """Thread-safe NER: the subprocess communicates over pipes."""
    with _ner_lock:
        if settings.ner_python not in _NER:
            _NER[settings.ner_python] = cleanup.Ner(settings.ner_python)
        return _NER[settings.ner_python].entities(sentences)


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
    ents = ner_entities(settings, sentences)
    hints: dict[int, str] = {}
    if ents:
        at = 0
        for clue in found["candidates"]:
            mine = ents[at : at + len(clue["sentences"])]
            at += len(clue["sentences"])
            hint = cleanup.ner_hint(clue["label"], mine)
            if hint:
                hints[clue["id"]] = hint
    backends = chain.build(settings.light_chain, settings)
    request = Request("clue_cleanup", cleanup.SYSTEM, cleanup.prompt(found, hints), cleanup.SCHEMA)
    off_topic: list[int] = []
    if found.get("groups"):
        # The group pass reads the same candidates and does not use the cleanup reply.
        with ThreadPoolExecutor(max_workers=2) as pool:
            cleanup_call = pool.submit(
                chain.run, backends, request, lambda d: cleanup.problem(found, d)
            )
            groups_call = pool.submit(
                chain.run,
                backends,
                Request(
                    "answer_groups",
                    cleanup.GROUP_SYSTEM,
                    cleanup.group_prompt(found),
                    cleanup.GROUP_SCHEMA,
                ),
            )
            reply = cleanup_call.result()
            groups_reply = groups_call.result()
        off_topic = list(groups_reply.data.get("off_topic_groups") or [])
    else:
        reply = chain.run(backends, request, lambda d: cleanup.problem(found, d))
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
    now = jobs.now().isoformat()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO generations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                topic_id, kind, fingerprint, prompt_version,
                reply.backend if reply else "none", reply.model if reply else "none",
                json.dumps(payload, ensure_ascii=False),
                reply.input_tokens if reply else 0, reply.output_tokens if reply else 0,
                now,
            ),
        )  # fmt: skip
        if reply and reply.input_tokens + reply.output_tokens > 0:
            conn.execute(
                "INSERT INTO api_usage (backend, model, task, topic_id, "
                "input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reply.backend, reply.model, kind, topic_id,
                 reply.input_tokens, reply.output_tokens, now),
            )  # fmt: skip


class NotReady(Exception):
    """A section this one is written from isn't there yet: try again shortly."""


class Blocked(Exception):
    """A section this one is written from failed for good, so this one can't be written
    either (a refresh queues them all again)."""


def wait_for(conn: sqlite3.Connection, topic_id: str, kind: str, what: str) -> NoReturn:
    """Queue the missing section and wait for it, unless it has already failed."""
    if jobs.open_kinds(conn, topic_id).get(kind) == "failed":
        raise Blocked(f"{what} failed")
    jobs.enqueue(conn, topic_id, kind, 10)
    raise NotReady(f"{what} not done yet")


def cleaned(conn: sqlite3.Connection, topic_id: str) -> tuple[dict[str, Any], str]:
    """The topic's clue cleanup and its identity (what derived sections are written from)."""
    row = conn.execute(
        "SELECT payload, fingerprint, created_at FROM generations "
        "WHERE topic_id = ? AND kind = 'clues'",
        (topic_id,),
    ).fetchone()
    if row is None:
        wait_for(conn, topic_id, "clues", "clue cleanup")
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
    """One-line summaries and explanations for every cleaned clue. The hall can then sort
    the whole list. Ones already written for the same cleanup are kept."""
    clean, identity = cleaned(conn, topic_id)
    clues = clean["clues"]
    have = conn.execute(
        "SELECT fingerprint, payload FROM generations WHERE topic_id = ? AND kind = 'explanations'",
        (topic_id,),
    ).fetchone()
    out: dict[int, dict[str, str]] = {}
    if have and have[0] == identity:
        out = {
            c["rank"]: {"one_line": c["one_line"], "explanation": c["explanation"]}
            for c in json.loads(have[1])["clues"]
        }
    todo = [c for c in clues if c["rank"] not in out]
    wiki_row = conn.execute(
        "SELECT status, payload FROM enrichments WHERE topic_id = ? AND kind = 'wiki'",
        (topic_id,),
    ).fetchone()
    if todo and wiki_row is None:
        wait_for(conn, topic_id, "wiki", "Wikipedia text")
    wiki = json.loads(wiki_row[1]) if wiki_row and wiki_row[0] == "ok" else None
    source = writing.lead_text(wiki)
    found, examples = clue_inputs(catalog, topic_id, todo)
    backends = chain.build(settings.light_chain, settings)
    total: Reply | None = None
    for start in range(0, len(todo), writing.BATCH):
        batch = todo[start : start + writing.BATCH]
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
            source=source,
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
    clues = clean["clues"]
    wiki_row = conn.execute(
        "SELECT status, payload FROM enrichments WHERE topic_id = ? AND kind = 'wiki'",
        (topic_id,),
    ).fetchone()
    if wiki_row is None:
        wait_for(conn, topic_id, "wiki", "Wikipedia text")
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
        source=writing.source_text(wiki, writing.SUMMARY_SOURCE_WORDS),
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


def write_facts(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """Fun facts, each resting on a sentence of the Wikipedia text it quotes."""
    row = conn.execute(
        "SELECT status, payload, fetched_at FROM enrichments WHERE topic_id = ? AND kind = 'wiki'",
        (topic_id,),
    ).fetchone()
    if row is None:
        wait_for(conn, topic_id, "wiki", "Wikipedia text")
    identity = f"wiki:{row[2]}"
    if row[0] != "ok":
        return {"facts": []}, identity, None  # nothing to ground facts in
    wiki = json.loads(row[1])
    source = writing.later_text(wiki)
    topic = catalog.get(f"/topics/{topic_id}/clue-candidates", params={"limit": 1}).json()
    prompt = writing.FACTS.format(
        name=topic["name"],
        category=topic.get("category") or "unknown",
        source=source,
    )
    reply = chain.run(
        chain.build(settings.light_chain, settings),
        Request("fun_facts", writing.FACTS_SYSTEM, prompt, writing.FACTS_SCHEMA),
        functools.partial(writing.facts_problem, source=source),
    )
    facts = writing.grounded(reply.data.get("facts", []), source)[: writing.FACT_COUNT]
    return {"facts": facts, "source": {"title": wiki["title"], "url": wiki["url"]}}, identity, reply


def header_image(images: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The image to open the page with: the article's main image, else the largest
    landscape one, else the largest."""
    if not images:
        return None
    main = [i for i in images if i.get("is_main")]
    wide = [i for i in images if i.get("width", 0) >= i.get("height", 0)]
    pool = main or wide or images
    return max(pool, key=lambda i: i.get("width", 0) * i.get("height", 0))


def _related_theme(conn: sqlite3.Connection, catalog: httpx.Client, topic_id: str) -> str:
    """If a closely related topic already has a theme, describe it so the AI can harmonise.
    Uses the catalog's lookup endpoint to find which clue labels are themselves topics, then
    checks if any of those topics already have a theme in content.db."""
    clues_row = conn.execute(
        "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'clues'", (topic_id,)
    ).fetchone()
    if not clues_row:
        return ""
    clues = json.loads(clues_row[0]).get("clues", [])
    labels = [c.get("label", "") for c in clues[:10]]
    if not labels:
        return ""
    try:
        resp = catalog.post(
            "/topics/lookup", json={"names": labels, "exclude": topic_id}, timeout=2.0
        )
        if resp.status_code != 200:
            return ""
        linked: dict[str, dict[str, Any]] = resp.json()
    except (httpx.HTTPError, ValueError):
        return ""
    # Check which linked topics already have a theme.
    for name, info in linked.items():
        row = conn.execute(
            "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'theme'",
            (info["id"],),
        ).fetchone()
        if not row:
            continue
        other = json.loads(row[0])
        light = other.get("light", {})
        dark = other.get("dark", {})
        font = other.get("font", "")
        return (
            f'The related topic "{name}" already uses these colors — you may harmonise '
            f"with or reuse them: accent {light.get('accent', '?')}/{dark.get('accent', '?')}, "
            f"accent2 {light.get('accent2', '?')}/{dark.get('accent2', '?')}, "
            f"bg {light.get('bg', '?')}/{dark.get('bg', '?')}, font: {font}"
        )
    return ""


def write_theme(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """The topic's colors and font, chosen to suit it and blend with its header image."""
    row = conn.execute(
        "SELECT status, payload, fetched_at FROM enrichments "
        "WHERE topic_id = ? AND kind = 'images'",
        (topic_id,),
    ).fetchone()
    if row is None:
        wait_for(conn, topic_id, "images", "images")
    images = json.loads(row[1]).get("images", []) if row[0] == "ok" else []
    header = header_image(images)
    colors: list[dict[str, Any]] = []
    if header:
        response = httpx.get(
            header["url"],
            headers={"User-Agent": settings.wikimedia_user_agent or settings.user_agent},
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
        )
        if response.status_code == 200:
            colors = theme.palette(response.content)
    topic = catalog.get(f"/topics/{topic_id}/clue-candidates", params={"limit": 1}).json()
    hook_row = conn.execute(
        "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'summary'", (topic_id,)
    ).fetchone()
    related = _related_theme(conn, catalog, topic_id)
    prompt = theme.PROMPT.format(
        name=topic["name"],
        category=topic.get("category") or "unknown",
        hook=json.loads(hook_row[0])["hook"] if hook_row else "(not written yet)",
        caption=(header or {}).get("caption") or (header or {}).get("file") or "(no image)",
        palette=", ".join(f"{c['hex']} ({c['share']:.0%})" for c in colors) or "(no image)",
        related_colors=related,
        fonts="; ".join(f"{k}: {v}" for k, v in theme.FONT_PAIRINGS.items()),
        default=", ".join(f"{mode} {color}" for mode, color in theme.DEFAULT_ACCENT.items()),
    )
    reply = chain.run(
        chain.build(settings.light_chain, settings),
        Request("theme", theme.SYSTEM, prompt, theme.SCHEMA),
        theme.problem,
    )
    payload = {**theme.finish(reply.data), "header": header, "palette": colors}
    return payload, f"images:{row[2]}", reply


def _already_shown(conn: sqlite3.Connection, topic_id: str) -> tuple[str, str]:
    """The summary and clue labels already on the page, so the examples can avoid them."""
    summary_row = conn.execute(
        "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'summary'", (topic_id,)
    ).fetchone()
    summary = "(no summary stored)"
    if summary_row:
        data = json.loads(summary_row[0])
        text = writing.MARK.sub(lambda m: m.group(2), str(data.get("summary", "")))
        if text.strip():
            summary = text.strip()
    clues_row = conn.execute(
        "SELECT payload FROM generations WHERE topic_id = ? AND kind = 'clues'", (topic_id,)
    ).fetchone()
    labels = "(no clues stored)"
    if clues_row:
        names = [
            str(clue.get("label", "")).strip()
            for clue in json.loads(clues_row[0]).get("clues", [])
            if str(clue.get("label", "")).strip()
        ]
        if names:
            labels = ", ".join(names[:40])
    return summary, labels


def write_special(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """A grounded timeline, a handful of examples, and a diagram of one hard idea."""
    row = conn.execute(
        "SELECT status, payload, fetched_at FROM enrichments WHERE topic_id = ? AND kind = 'wiki'",
        (topic_id,),
    ).fetchone()
    if row is None:
        wait_for(conn, topic_id, "wiki", "Wikipedia text")
    wiki = json.loads(row[1]) if row[0] == "ok" else None
    excerpt = writing.source_text(wiki)
    lead = writing.lead_text(wiki)
    topic = catalog.get(f"/topics/{topic_id}/clue-candidates", params={"limit": 1}).json()
    name, category = topic["name"], topic.get("category")
    title, instructions, kind = special.form(category)
    diagram = special.is_diagram(category)
    summary_text, clue_labels = _already_shown(conn, topic_id)
    diagram_text = (
        special.DIAGRAM.format(
            name=name,
            blur_low=special.BLURB_WORDS[0],
            blur_high=special.BLURB_WORDS[1],
        )
        if diagram
        else ""
    )
    feature_prompt = special.HANDFUL.format(
        name=name,
        category=category or "unknown",
        title=title,
        instructions=instructions.format(name=name),
        low=special.ENTRY_WORDS[0],
        high=special.ENTRY_WORDS[1],
        diagram=diagram_text,
        summary=summary_text,
        clue_labels=clue_labels,
        source=lead,
    )
    feature_schema = special.handful_schema(diagram)
    feature_check = functools.partial(special.entries_problem, diagram=diagram)

    def write_timeline() -> tuple[list[dict[str, Any]], Reply | None]:
        if not wiki:
            return [], None
        timeline_reply = chain.run(
            chain.build(settings.light_chain, settings),
            Request(
                "timeline",
                special.TIMELINE_SYSTEM,
                special.TIMELINE.format(
                    name=name,
                    kind=kind,
                    source=excerpt,
                    low=special.TIMELINE_EVENTS[0],
                    high=special.TIMELINE_EVENTS[1],
                ),
                special.TIMELINE_SCHEMA,
            ),
            functools.partial(special.timeline_problem, source=excerpt),
        )
        return special.timeline(timeline_reply.data.get("events", []), excerpt), timeline_reply

    def write_feature() -> Reply:
        return chain.run(
            chain.build(settings.writing_chain, settings),
            Request("feature", special.FEATURE_SYSTEM, feature_prompt, feature_schema),
            feature_check,
        )

    # The timeline quotes the excerpt. The feature reads the lead. They can run together.
    with ThreadPoolExecutor(max_workers=2) as pool:
        timeline_call = pool.submit(write_timeline)
        feature_call = pool.submit(write_feature)
        events, timeline_reply = timeline_call.result()
        reply = feature_call.result()
    total = reply if timeline_reply is None else add(reply, timeline_reply)
    payload = {
        "timeline": {"kind": kind, "events": events},
        "feature": {
            "form": title,
            "title": reply.data["title"].strip(),
            "body": "",
            "diagram_title": (
                str(reply.data.get("diagram_title") or "").strip() if diagram else ""
            ),
            "steps": (reply.data.get("steps") or []) if diagram else [],
            "diagram_blurb": (
                str(reply.data.get("diagram_blurb") or "").strip() if diagram else ""
            ),
            "entries": [
                {
                    "name": str(entry.get("name", "")).strip(),
                    "text": str(entry.get("text", "")).strip(),
                }
                for entry in reply.data.get("entries") or []
            ],
            "dramatized": False,
        },
        "source": {"title": wiki["title"], "url": wiki["url"]} if wiki else None,
    }
    return payload, f"wiki:{row[2]}", total


def write_blurbs(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    """Two or three short recommendations, chosen from the public bibliography."""
    row = conn.execute(
        "SELECT status, payload, fetched_at FROM enrichments WHERE topic_id = ? AND kind = 'books'",
        (topic_id,),
    ).fetchone()
    if row is None:
        wait_for(conn, topic_id, "books", "books")
    identity = f"books:{row[2]}"
    if row[0] != "ok":
        return {"blurbs": []}, identity, None
    shelf = [b for b in json.loads(row[1]).get("books", []) if b.get("title")]
    if not shelf:
        return {"blurbs": []}, identity, None
    topic = catalog.get(f"/topics/{topic_id}/clue-candidates", params={"limit": 1}).json()
    low, high = blurbs.how_many(len(shelf))
    listing = "\n".join(
        "- {title} | {author} | {year} | {publisher}".format(
            title=b["title"],
            author=b.get("author") or "unknown",
            year=b.get("year") or "n.d.",
            publisher=b.get("publisher") or "unknown",
        )
        for b in shelf
    )
    reply = chain.run(
        chain.build(settings.light_chain, settings),
        Request(
            "book_blurbs",
            blurbs.SYSTEM,
            blurbs.PROMPT.format(
                name=topic["name"],
                category=topic.get("category") or "unknown",
                low=low,
                high=high,
                books=listing,
            ),
            blurbs.SCHEMA,
        ),
        functools.partial(blurbs.problem, titles=[str(b["title"]) for b in shelf]),
    )
    return {"blurbs": blurbs.kept(reply.data, [str(b["title"]) for b in shelf])}, identity, reply


def write_cleanup(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, topic_id: str
) -> tuple[dict[str, Any], str, Reply | None]:
    return clean_clues(settings, catalog, topic_id)


GENERATORS: dict[str, tuple[Generator, int]] = {
    "clues": (write_cleanup, cleanup.PROMPT_VERSION),
    "explanations": (write_explanations, writing.EXPLANATIONS_VERSION),
    "summary": (write_summary, writing.SUMMARY_VERSION),
    "facts": (write_facts, writing.FACTS_VERSION),
    "theme": (write_theme, theme.THEME_VERSION),
    "special": (write_special, special.SPECIAL_VERSION),
    "blurbs": (write_blurbs, blurbs.VERSION),
}  # fmt: skip


def loaded_for(conn: sqlite3.Connection, topic_id: str) -> dict[str, Any]:
    """What is already stored for this topic, before a model call."""
    enrichments = {
        kind: {"status": status, "chars": len(payload)}
        for kind, status, payload in conn.execute(
            "SELECT kind, status, payload FROM enrichments WHERE topic_id = ?", (topic_id,)
        )
    }
    generations = {
        kind: {"model": model, "chars": len(payload)}
        for kind, model, payload in conn.execute(
            "SELECT kind, model, payload FROM generations WHERE topic_id = ?", (topic_id,)
        )
    }
    return {"enrichments": enrichments, "generations": generations}


def run_generation(
    conn: sqlite3.Connection, settings: Settings, catalog: httpx.Client, job: jobs.Job
) -> None:
    generate, version = GENERATORS[job.kind]
    tokens = bind_trace(job.topic_id, job.kind)
    trace_event("job.start", loaded=loaded_for(conn, job.topic_id))
    try:
        payload, fingerprint, reply = generate(conn, settings, catalog, job.topic_id)
        store_generation(conn, job.topic_id, job.kind, fingerprint, version, payload, reply)
        jobs.finish(conn, job)
        trace_event(
            "job.stored",
            provider=reply.backend if reply else None,
            model=reply.model if reply else None,
            output=payload,
        )
        log.info("wrote %s for %s (%s)", job.kind, job.topic_id, reply.model if reply else "none")
    except NotReady as exc:
        trace_event("job.waiting", error=str(exc), output=None)
        jobs.defer(conn, job, jobs.now() + timedelta(seconds=20), str(exc))
    except Blocked as exc:
        trace_event("job.blocked", error=str(exc), output=None)
        jobs.fail(conn, job, str(exc), max_attempts=job.attempts)
    except QuotaExceeded as exc:
        until = exc.retry_at or jobs.now() + timedelta(hours=1)
        trace_event("job.quota", error=str(exc), output=None)
        log.warning("%s for %s waits until %s: %s", job.kind, job.topic_id, until, exc)
        jobs.defer(conn, job, until, str(exc))
    except TopicNotFound:
        trace_event("job.failed", error="topic not in the catalog", output=None)
        jobs.fail(conn, job, "topic not in the catalog", max_attempts=job.attempts)
    except GenerationError as exc:
        # No model is configured. Retrying on a backoff would hide that for an hour;
        # the page view queues the section again once a key is present.
        give_up = str(exc) == "no backends configured"
        trace_event("job.failed", error=str(exc), output=None)
        log.warning("%s for %s failed (attempt %d): %s", job.kind, job.topic_id, job.attempts, exc)
        jobs.fail(
            conn,
            job,
            str(exc),
            max_attempts=job.attempts if give_up else settings.job_max_attempts,
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        trace_event("job.failed", error=message, output=None)
        log.warning("%s for %s failed (attempt %d): %s", job.kind, job.topic_id, job.attempts, exc)
        jobs.fail(conn, job, message, settings.job_max_attempts)
    finally:
        reset_trace(tokens)


def process_job(
    conn: sqlite3.Connection,
    settings: Settings,
    http: PoliteClient,
    catalog: httpx.Client,
    job: jobs.Job,
) -> None:
    """Process a single claimed job.  Each kind succeeds or fails on its own."""
    if job.kind in jobs.GENERATED:
        run_generation(conn, settings, catalog, job)
        return
    if job.kind not in fetchers(settings):
        jobs.defer(conn, job, jobs.now() + timedelta(minutes=1), f"unknown kind {job.kind!r}")
        return
    version, fetch = fetchers(settings)[job.kind]
    tokens = bind_trace(job.topic_id, job.kind)
    trace_event("job.start", loaded=loaded_for(conn, job.topic_id))
    try:
        topic = load_topic(catalog, job.topic_id)
        payload = fetch(topic, http)
        store(
            conn, job.topic_id, job.kind, "empty" if is_empty(payload) else "ok", payload, version
        )
        jobs.finish(conn, job)
        trace_event("job.stored", output=payload)
        log.info("fetched %s for %s", job.kind, job.topic_id)
    except Unavailable as exc:
        stored = {"reason": str(exc)}
        store(conn, job.topic_id, job.kind, "unavailable", stored, version)
        jobs.finish(conn, job)
        trace_event("job.stored", output=stored, error=str(exc))
    except TopicNotFound:
        trace_event("job.failed", error="topic not in the catalog", output=None)
        jobs.fail(conn, job, "topic not in the catalog", max_attempts=job.attempts)
    except (FetchError, httpx.HTTPError, KeyError, ValueError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        trace_event("job.failed", error=message, output=None)
        log.warning("%s for %s failed (attempt %d): %s", job.kind, job.topic_id, job.attempts, exc)
        jobs.fail(conn, job, message, settings.job_max_attempts)
    finally:
        reset_trace(tokens)


def run_once(
    conn: sqlite3.Connection, settings: Settings, http: PoliteClient, catalog: httpx.Client
) -> jobs.Job | None:
    """Does one job, if any is ready."""
    job = jobs.claim(conn)
    if job is None:
        return None
    process_job(conn, settings, http, catalog, job)
    return job


def log_providers(settings: Settings) -> None:
    """Which model keys the worker can see. Values stay out of the log."""
    configure_trace(settings.db_path.parent / "generation-trace.jsonl")
    env_path = _env_file()
    found = env_path.is_file()
    trace_event(
        "worker.start",
        topic_id="",
        kind="",
        loaded={
            "env_file": str(env_path),
            "env_file_found": found,
            "call_timeout_seconds": settings.generation_timeout_seconds,
            "providers": {
                name: "configured" if getattr(settings, f"{name}_api_key", "") else "missing"
                for name in ("gemini", "groq", "cerebras")
            },
        },
    )
    for name in ("gemini", "groq", "cerebras"):
        present = bool(getattr(settings, f"{name}_api_key", ""))
        log.info("provider %s %s", name, "configured" if present else "missing")


def run_forever(conn: sqlite3.Connection, settings: Settings) -> None:
    jobs.recover(conn)
    log_providers(settings)
    n = max(1, settings.worker_threads)

    if n == 1:
        http = make_http(conn, settings)
        with httpx.Client(base_url=settings.catalog_url, timeout=30) as catalog:
            while True:
                if run_once(conn, settings, http, catalog) is None:
                    time.sleep(settings.worker_poll_seconds)
        return  # pragma: no cover

    # --- Parallel mode: independent jobs run in separate threads ---
    log.info("worker: %d threads", n)
    db_path: str = conn.execute("PRAGMA database_list").fetchone()[2]

    _local = threading.local()

    def _resources() -> tuple[sqlite3.Connection, PoliteClient, httpx.Client]:
        if not hasattr(_local, "conn"):
            _local.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA busy_timeout=5000")
            _local.http = make_http(_local.conn, settings)
            _local.catalog = httpx.Client(base_url=settings.catalog_url, timeout=30)
        return _local.conn, _local.http, _local.catalog

    slots = threading.BoundedSemaphore(n)

    def _do(job: jobs.Job) -> None:
        try:
            tc, th, tcat = _resources()
            process_job(tc, settings, th, tcat, job)
        except Exception:
            log.exception("unhandled error: %s/%s", job.kind, job.topic_id)
            try:
                tc, _, _ = _resources()
                jobs.fail(tc, job, "unhandled worker error", max_attempts=job.attempts)
            except Exception:
                pass
        finally:
            slots.release()

    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="w") as pool:
        while True:
            slots.acquire()
            job = jobs.claim(conn)
            if job is None:
                slots.release()
                time.sleep(settings.worker_poll_seconds)
                continue
            pool.submit(_do, job)
