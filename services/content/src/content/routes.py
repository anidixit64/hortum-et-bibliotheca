import json
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from content import jobs

router = APIRouter()

PAGE_VIEW_PRIORITY = 10  # someone is looking at the page: ahead of batch jobs


def get_db(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.db
    return conn


Db = Annotated[sqlite3.Connection, Depends(get_db)]


class Section(BaseModel):
    status: Literal["ok", "empty", "unavailable", "pending", "failed"]
    payload: dict[str, Any] | None = None
    fetched_at: str | None = None


class TopicContent(BaseModel):
    topic_id: str
    status: Literal["ready", "partial"]
    sections: dict[str, Section]


@router.get("/topics/{topic_id}/content", tags=["content"])
def topic_content(topic_id: str, db: Db, enqueue: Annotated[bool, Query()] = True) -> TopicContent:
    """What's been fetched for a topic. Anything missing is queued (unless ``enqueue=false``)
    and shows as "pending": the page can poll until the status is "ready"."""
    rows = db.execute(
        "SELECT kind, status, payload, fetched_at FROM enrichments WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()
    have = {kind: Section(status=s, payload=json.loads(p), fetched_at=f) for kind, s, p, f in rows}
    open_jobs = jobs.open_kinds(db, topic_id)
    sections: dict[str, Section] = {}
    for kind in jobs.KINDS:
        if kind in have:
            sections[kind] = have[kind]
        elif open_jobs.get(kind) == "failed":
            sections[kind] = Section(status="failed")
        else:
            if enqueue:
                jobs.enqueue(db, topic_id, kind, PAGE_VIEW_PRIORITY)
            sections[kind] = Section(status="pending")
    pending = any(s.status == "pending" for s in sections.values())
    return TopicContent(
        topic_id=topic_id, status="partial" if pending else "ready", sections=sections
    )


@router.post("/topics/{topic_id}/refresh", status_code=202, tags=["content"])
def refresh(
    topic_id: str, db: Db, kinds: Annotated[list[str] | None, Query()] = None
) -> dict[str, Any]:
    """Fetch again: drops what's stored and queues new jobs."""
    chosen = [k for k in (kinds or list(jobs.KINDS)) if k in jobs.KINDS]
    with db:
        db.executemany(
            "DELETE FROM enrichments WHERE topic_id = ? AND kind = ?",
            [(topic_id, k) for k in chosen],
        )
    queued = [k for k in chosen if jobs.enqueue(db, topic_id, k, PAGE_VIEW_PRIORITY)]
    return {"topic_id": topic_id, "queued": queued}


@router.get("/jobs", tags=["jobs"])
def job_counts(db: Db) -> dict[str, dict[str, int]]:
    """Job counts by kind and status, to watch the worker."""
    out: dict[str, dict[str, int]] = {}
    for kind, status, n in db.execute(
        "SELECT kind, status, COUNT(*) FROM jobs GROUP BY kind, status"
    ):
        out.setdefault(kind, {})[status] = n
    return out
