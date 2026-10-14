import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from content import blurbs, cleanup, jobs, special, theme, writing
from content.fetchers import books, images, videos, wiki

router = APIRouter()

PAGE_VIEW_PRIORITY = 10
# Within a page view, what a reader sees first is written first: the quick fetches and the
# clue cleanup the written sections need, then the summary and colors, then the rest.
VIEW_ORDER = {"wiki": 6, "images": 6, "books": 6, "videos": 6, "clues": 5, "summary": 4,
              "theme": 3, "explanations": 2, "blurbs": 1}  # fmt: skip


def view_priority(kind: str) -> int:
    return PAGE_VIEW_PRIORITY + VIEW_ORDER.get(kind, 0)


# Fetched sections stored by an older fetcher are shown while a fresh fetch is queued.
FETCHER_VERSIONS = {
    "wiki": wiki.VERSION,
    "images": images.VERSION,
    "books": books.VERSION,
    "videos": videos.VERSION,
}
PROMPT_VERSIONS = {
    "clues": cleanup.PROMPT_VERSION,
    "explanations": writing.EXPLANATIONS_VERSION,
    "summary": writing.SUMMARY_VERSION,
    "facts": writing.FACTS_VERSION,
    "theme": theme.THEME_VERSION,
    "special": special.SPECIAL_VERSION,
    "blurbs": blurbs.VERSION,
}
# Generated sections written from a fetched one: current while that one is the same.
FROM_FETCHED = {"facts": "wiki", "theme": "images", "special": "wiki", "blurbs": "books"}
DERIVED = ("explanations", "summary")  # written from the clue cleanup


# The open page polls every few seconds. Each poll was asking the catalog for the same
# clue fingerprint, which is what filled the catalog log while Diocletian was generating.
_FINGERPRINT_TTL = 30.0
_fingerprint_cache: dict[str, tuple[float, str]] = {}


def clue_fingerprint(request: Request, topic_id: str, stored: str) -> str:
    """The catalog's current fingerprint of the topic's clue candidates. If the catalog
    can't be reached, the stored one counts as current (better shown than hidden)."""
    now = time.monotonic()
    cached = _fingerprint_cache.get(topic_id)
    if cached is not None and now - cached[0] < _FINGERPRINT_TTL:
        return cached[1]
    settings = request.app.state.settings
    try:
        response = httpx.get(
            f"{settings.catalog_url}/topics/{topic_id}/clue-candidates",
            params={"limit": cleanup.CANDIDATES},
            timeout=2.0,
        )
        response.raise_for_status()
        fingerprint = str(response.json()["fingerprint"])
    except (httpx.HTTPError, KeyError, ValueError):
        return stored  # someone is looking at the page: ahead of batch jobs
    _fingerprint_cache[topic_id] = (now, fingerprint)
    return fingerprint


def get_db(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.db
    return conn


Db = Annotated[sqlite3.Connection, Depends(get_db)]


class Section(BaseModel):
    status: Literal["ok", "empty", "unavailable", "pending", "failed"]
    payload: dict[str, Any] | None = None
    fetched_at: str | None = None
    stale: bool = False  # generated from older inputs; a fresh one is queued


class TopicContent(BaseModel):
    topic_id: str
    status: Literal["ready", "partial"]
    sections: dict[str, Section]


@router.get("/topics/{topic_id}/content", tags=["content"])
def topic_content(
    topic_id: str,
    db: Db,
    request: Request,
    enqueue: Annotated[bool, Query()] = True,
    generate: Annotated[bool, Query()] = True,
) -> TopicContent:
    """What's been fetched for a topic. Anything missing is queued (unless ``enqueue=false``)
    and shows as "pending": the page can poll until the status is "ready".

    ``generate=false`` still fetches Wikipedia, images, books, and videos, and leaves model
    sections unqueued. A Non-AI page uses that. Turning AI on calls again with the default.
    """
    rows = db.execute(
        "SELECT kind, status, payload, fetched_at, source_version FROM enrichments "
        "WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()
    have: dict[str, Section] = {}
    for kind, status, payload, fetched, version in rows:
        old = version < FETCHER_VERSIONS.get(kind, 0)
        have[kind] = Section(status=status, payload=json.loads(payload), fetched_at=fetched,
                             stale=old)  # fmt: skip
        if old and enqueue:
            jobs.enqueue(db, topic_id, kind, view_priority(kind))
    rows = db.execute(
        "SELECT kind, fingerprint, prompt_version, payload, created_at FROM generations "
        "WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()
    # Explanations and the summary are current while they match the cleanup they were
    # written from; the cleanup, while it matches the catalog's clue candidates.
    clues_row = next((r for r in rows if r[0] == "clues"), None)
    cleanup_identity = f"{clues_row[1]}:{clues_row[4]}" if clues_row else None
    fetched_at = dict(
        db.execute("SELECT kind, fetched_at FROM enrichments WHERE topic_id = ?", (topic_id,))
    )
    for kind, fingerprint, version, payload, created in rows:
        if kind in DERIVED:
            matches = fingerprint == cleanup_identity
        elif kind in FROM_FETCHED:
            source = FROM_FETCHED[kind]
            matches = fingerprint == f"{source}:{fetched_at.get(source)}"
        else:
            matches = fingerprint == clue_fingerprint(request, topic_id, fingerprint)
        current = PROMPT_VERSIONS.get(kind) == version and matches
        have[kind] = Section(
            status="ok", payload=json.loads(payload), fetched_at=created, stale=not current
        )
        if not current and enqueue and generate:
            jobs.enqueue(db, topic_id, kind, view_priority(kind))
    open_jobs = jobs.open_kinds(db, topic_id)
    sections: dict[str, Section] = {}
    for kind in jobs.KINDS:
        if kind in have:
            sections[kind] = have[kind]
        elif kind in jobs.GENERATED and not generate:
            sections[kind] = Section(status="unavailable")
        elif open_jobs.get(kind) == "failed":
            sections[kind] = Section(status="failed")
        else:
            if enqueue:
                jobs.enqueue(db, topic_id, kind, view_priority(kind))
            sections[kind] = Section(status="pending")
    for kind in jobs.GENERATED:  # stored, but more is being written ("show more")
        if kind in sections and sections[kind].status == "ok" and kind in open_jobs:
            sections[kind].stale = True
    if enqueue and generate:
        for kind in jobs.GENERATED:
            if sections[kind].status != "failed":
                continue
            if jobs.requeue_failed(db, topic_id, kind, view_priority(kind)):
                sections[kind] = Section(status="pending")
    if generate:
        # The exhibit waits until every model-written section is stored. A failed section stays
        # partial (and is queued again above) so the page does not open on Wikipedia alone.
        generated_done = all(
            sections[kind].status == "ok" and not sections[kind].stale for kind in jobs.GENERATED
        )
        waiting = any(section.status == "pending" or section.stale for section in sections.values())
        ready = generated_done and not waiting
    else:
        ready = not any(
            sections[kind].status == "pending" or sections[kind].stale for kind in jobs.FETCHED
        )
    return TopicContent(
        topic_id=topic_id,
        status="ready" if ready else "partial",
        sections=sections,
    )


@router.post("/topics/{topic_id}/refresh", status_code=202, tags=["content"])
def refresh(
    topic_id: str, db: Db, kinds: Annotated[list[str] | None, Query()] = None
) -> dict[str, Any]:
    """Fetch (or generate) again: drops what's stored and queues new jobs."""
    chosen = [k for k in (kinds or list(jobs.KINDS)) if k in jobs.KINDS]
    with db:
        for table in ("enrichments", "generations"):
            db.executemany(
                f"DELETE FROM {table} WHERE topic_id = ? AND kind = ?",
                [(topic_id, k) for k in chosen],
            )
    queued = [k for k in chosen if jobs.enqueue(db, topic_id, k, view_priority(k))]
    return {"topic_id": topic_id, "queued": queued}


@router.post("/topics/{topic_id}/explain-more", status_code=202, tags=["content"])
def explain_more(
    topic_id: str, db: Db, through: Annotated[int, Query(ge=1, le=cleanup.CANDIDATES)]
) -> dict[str, Any]:
    """Explain the cleaned clues through rank ``through`` (the page asks as "show more"
    reveals them); only the missing ones are written."""
    with db:
        db.execute(
            "INSERT INTO explain_depth VALUES (?, ?) ON CONFLICT(topic_id) "
            "DO UPDATE SET through = MAX(through, excluded.through)",
            (topic_id, through),
        )
    queued = jobs.enqueue(db, topic_id, "explanations", view_priority("explanations"))
    return {"topic_id": topic_id, "through": through, "queued": queued}


class ThumbnailRequest(BaseModel):
    topic_ids: list[str]


@router.post("/thumbnails", tags=["content"])
def thumbnails(body: ThumbnailRequest, db: Db) -> dict[str, str | None]:
    """Return the main image URL for each topic that has one stored."""
    out: dict[str, str | None] = {}
    for tid in body.topic_ids[:50]:
        row = db.execute(
            "SELECT payload FROM enrichments WHERE topic_id = ? AND kind = 'images' AND status = 'ok'",
            (tid,),
        ).fetchone()
        if row:
            imgs = json.loads(row[0]).get("images", [])
            main = next((i["url"] for i in imgs if i.get("is_main")), None)
            out[tid] = main or (imgs[0]["url"] if imgs else None)
        else:
            out[tid] = None
    return out


@router.get("/jobs", tags=["jobs"])
def job_counts(db: Db) -> dict[str, dict[str, int]]:
    """Job counts by kind and status, to watch the worker."""
    out: dict[str, dict[str, int]] = {}
    for kind, status, n in db.execute(
        "SELECT kind, status, COUNT(*) FROM jobs GROUP BY kind, status"
    ):
        out.setdefault(kind, {})[status] = n
    return out


# ---------------------------------------------------------------------------
# Admin: PIN-protected usage tracking
# ---------------------------------------------------------------------------

PROVIDER_INFO: dict[str, dict[str, Any]] = {
    "claude_code": {
        "label": "Claude Code",
        "tier": "subscription",
        "dashboard": None,
        "limits": {},
    },
    "cerebras": {
        "label": "Cerebras",
        "tier": "credit",
        "dashboard": "https://cloud.cerebras.ai",
        "limits": {
            "rpm": 450,
            "tpm": 150_000,
            "rpd": 648_000,
            "credit_usd": 5.0,
            "credit_days": 30,
        },
    },
    "groq": {
        "label": "Groq",
        "tier": "permanent",
        "dashboard": "https://console.groq.com",
        "limits": {"rpm": 30, "rpd": 14_400, "tpm": 8_000, "tpd": 200_000},
    },
    "gemini": {
        "label": "Gemini",
        "tier": "permanent",
        "dashboard": "https://aistudio.google.com",
        "limits": {"rpd_per_model": 20},
    },
    "sambanova": {
        "label": "SambaNova",
        "tier": "credit",
        "dashboard": "https://cloud.sambanova.ai",
        "limits": {"credit_usd": 5.0, "credit_days": 90},
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "tier": "permanent",
        "dashboard": "https://build.nvidia.com",
        "limits": {"rpm": 40},
    },
    "mistral": {
        "label": "Mistral",
        "tier": "permanent",
        "dashboard": "https://console.mistral.ai",
        "limits": {"rps": 1},
    },
    "openrouter": {
        "label": "OpenRouter",
        "tier": "renewable",
        "dashboard": "https://openrouter.ai/settings/credits",
        "limits": {"rpd": 50},
    },
}

# Backends that map to a named provider (the worker logs the backend name from the chain).
BACKEND_PROVIDER = {
    "claude_code": "claude_code",
    "gemini": "gemini",
    **{name: name for name in PROVIDER_INFO if name not in ("claude_code", "gemini")},
}


def _require_admin(request: Request, x_admin_pin: Annotated[str, Header()] = "") -> None:
    pin = request.app.state.settings.admin_pin
    if not pin:
        raise HTTPException(403, "admin PIN not configured")
    if x_admin_pin != pin:
        raise HTTPException(403, "invalid PIN")


AdminAuth = Annotated[None, Depends(_require_admin)]


def _usage_rows(db: sqlite3.Connection, since: str) -> dict[str, dict[str, int]]:
    """Aggregate api_usage rows by backend since a given ISO timestamp."""
    rows = db.execute(
        "SELECT backend, COUNT(*), COALESCE(SUM(input_tokens), 0), "
        "COALESCE(SUM(output_tokens), 0) FROM api_usage "
        "WHERE created_at >= ? GROUP BY backend",
        (since,),
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for backend, count, inp, outp in rows:
        provider = BACKEND_PROVIDER.get(backend, backend)
        prev = out.get(provider, {"requests": 0, "input_tokens": 0, "output_tokens": 0})
        out[provider] = {
            "requests": prev["requests"] + count,
            "input_tokens": prev["input_tokens"] + inp,
            "output_tokens": prev["output_tokens"] + outp,
        }
    return out


def _warnings(provider: str, info: dict[str, Any], today: dict[str, int]) -> list[str]:
    limits = info.get("limits", {})
    warns: list[str] = []
    reqs = today.get("requests", 0)
    tokens = today.get("input_tokens", 0) + today.get("output_tokens", 0)
    if "rpd" in limits and reqs >= limits["rpd"] * 0.8:
        warns.append(f"Daily requests at {reqs}/{limits['rpd']} ({reqs * 100 // limits['rpd']}%)")
    if "tpd" in limits and tokens >= limits["tpd"] * 0.8:
        warns.append(
            f"Daily tokens at {tokens:,}/{limits['tpd']:,} ({tokens * 100 // limits['tpd']}%)"
        )
    if info.get("tier") == "credit":
        credit = limits.get("credit_usd", 0)
        if credit:
            warns.append(f"Credit-based (${credit:.0f}): check balance on dashboard")
    return warns


@router.get("/admin/usage", tags=["admin"])
def admin_usage(db: Db, request: Request, _auth: AdminAuth) -> dict[str, Any]:
    """PIN-protected usage stats for the settings page."""
    settings = request.app.state.settings
    now = datetime.now(ZoneInfo("UTC"))
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()

    today = _usage_rows(db, today_start)
    week = _usage_rows(db, week_start)
    total = _usage_rows(db, "2000-01-01T00:00:00")

    key_attrs = {
        "gemini": "gemini_api_key",
        "claude_code": "claude_code_path",
        **{
            name: f"{name}_api_key"
            for name in PROVIDER_INFO
            if name not in ("gemini", "claude_code")
        },
    }

    providers: dict[str, Any] = {}
    for name, info in PROVIDER_INFO.items():
        attr = key_attrs.get(name, "")
        if name == "claude_code":
            configured = settings.use_claude_code
        else:
            configured = bool(getattr(settings, attr, ""))
        t = today.get(name, {"requests": 0, "input_tokens": 0, "output_tokens": 0})
        w = week.get(name, {"requests": 0, "input_tokens": 0, "output_tokens": 0})
        a = total.get(name, {"requests": 0, "input_tokens": 0, "output_tokens": 0})
        providers[name] = {
            **info,
            "configured": configured,
            "usage": {"today": t, "week": w, "all_time": a},
            "warnings": _warnings(name, info, t),
        }

    job_data: dict[str, dict[str, int]] = {}
    for kind, status, n in db.execute(
        "SELECT kind, status, COUNT(*) FROM jobs GROUP BY kind, status"
    ):
        job_data.setdefault(kind, {})[status] = n

    return {"providers": providers, "jobs": job_data}
