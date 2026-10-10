import sqlite3
import statistics
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from study import answers, cards, scheduler
from study.backup import backup
from study.catalog import Catalog, CatalogError
from study.config import Settings

router = APIRouter()


def get_db(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.db
    return conn


def get_catalog(request: Request) -> Catalog:
    catalog: Catalog = request.app.state.catalog
    return catalog


Db = Annotated[sqlite3.Connection, Depends(get_db)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]


def _now() -> datetime:
    return datetime.now(UTC)


async def _fetch(call: Any) -> dict[str, Any] | None:
    try:
        result: dict[str, Any] | None = await call
    except CatalogError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return result


def _add_cards(conn: sqlite3.Connection, new: list[cards.NewCard]) -> int:
    """Inserts cards (due now) that don't exist yet; revives suspended ones. Returns new."""
    now = _now()
    created = 0
    for card in new:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO cards VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            cards.to_row(card, now.isoformat()),
        )
        if cursor.rowcount:
            state = scheduler.new_state(now)
            conn.execute(
                "INSERT INTO card_state VALUES (?, ?, ?)",
                (card.card_id, state.due.isoformat(), scheduler.dumps(state)),
            )
            created += 1
        else:
            conn.execute("UPDATE cards SET suspended = 0 WHERE card_id = ?", (card.card_id,))
    return created


# --- Following topics ------------------------------------------------------------------


class Followed(BaseModel):
    topic_id: str
    name: str
    cards_created: int
    cards_total: int


@router.post("/topics/{topic_id}/follow", status_code=201, tags=["topics"])
async def follow(topic_id: str, db: Db, catalog: CatalogDep) -> Followed:
    """Follow a topic: creates a card for each ranked clue and one 'name 3 clues' card."""
    record = await _fetch(catalog.topic(topic_id))
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {topic_id!r}")
    tid, name = record["topic"]["id"], record["topic"]["name"]
    with db:
        db.execute(
            "INSERT OR IGNORE INTO followed_topics VALUES (?, ?, ?)",
            (tid, name, _now().isoformat()),
        )
        created = _add_cards(db, cards.topic_cards(record))
    total = db.execute("SELECT COUNT(*) FROM cards WHERE topic_id = ?", (tid,)).fetchone()[0]
    return Followed(topic_id=tid, name=name, cards_created=created, cards_total=total)


@router.delete("/topics/{topic_id}/follow", status_code=204, tags=["topics"])
def unfollow(topic_id: str, db: Db) -> None:
    """Stop following: the topic's cards are suspended, not deleted, so history stays."""
    with db:
        db.execute("DELETE FROM followed_topics WHERE topic_id = ?", (topic_id,))
        db.execute("UPDATE cards SET suspended = 1 WHERE topic_id = ?", (topic_id,))


class FollowedTopic(BaseModel):
    topic_id: str
    name: str
    cards: int
    due: int


@router.get("/topics", tags=["topics"])
def followed(db: Db) -> list[FollowedTopic]:
    now = _now().isoformat()
    rows = db.execute(
        "SELECT f.topic_id, f.name, COUNT(c.card_id), "
        "SUM(c.card_id IS NOT NULL AND c.suspended = 0 AND s.due <= ?) "
        "FROM followed_topics f LEFT JOIN cards c ON c.topic_id = f.topic_id "
        "LEFT JOIN card_state s ON s.card_id = c.card_id GROUP BY f.topic_id ORDER BY f.added_at",
        (now,),
    ).fetchall()
    return [FollowedTopic(topic_id=t, name=n, cards=c, due=d or 0) for t, n, c, d in rows]


# --- Reviews ----------------------------------------------------------------------------


class DueCard(BaseModel):
    card_id: str
    topic_id: str
    kind: str
    front: str
    back: str
    due: str


@router.get("/reviews/due", tags=["reviews"])
def due(db: Db, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[DueCard]:
    """Cards due now across every followed topic, most overdue first."""
    rows = db.execute(
        "SELECT c.card_id, c.topic_id, c.kind, c.front, c.back, s.due FROM cards c "
        "JOIN card_state s ON s.card_id = c.card_id "
        "WHERE c.suspended = 0 AND s.due <= ? ORDER BY s.due LIMIT ?",
        (_now().isoformat(), limit),
    ).fetchall()
    return [DueCard(card_id=r[0], topic_id=r[1], kind=r[2], front=r[3], back=r[4], due=r[5])
            for r in rows]  # fmt: skip


class ReviewIn(BaseModel):
    card_id: str
    rating: int = Field(ge=1, le=4, description="1 again, 2 hard, 3 good, 4 easy")


class ReviewOut(BaseModel):
    card_id: str
    due: str
    stability: float | None
    difficulty: float | None


@router.post("/reviews", tags=["reviews"])
def submit_review(body: ReviewIn, db: Db) -> ReviewOut:
    row = db.execute("SELECT fsrs FROM card_state WHERE card_id = ?", (body.card_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no card {body.card_id!r}")
    now = _now()
    before = scheduler.loads(row[0])
    after = scheduler.review(before, body.rating, now)
    elapsed = (now - before.last_review).total_seconds() / 86400 if before.last_review else None
    with db:
        db.execute(
            "UPDATE card_state SET due = ?, fsrs = ? WHERE card_id = ?",
            (after.due.isoformat(), scheduler.dumps(after), body.card_id),
        )
        db.execute(
            "INSERT INTO reviews (card_id, rating, reviewed_at, elapsed_days) VALUES (?, ?, ?, ?)",
            (body.card_id, body.rating, now.isoformat(), elapsed),
        )
    return ReviewOut(card_id=body.card_id, due=after.due.isoformat(),
                     stability=after.stability, difficulty=after.difficulty)  # fmt: skip


# --- Buzzes -----------------------------------------------------------------------------


class BuzzIn(BaseModel):
    tossup_id: str
    word_index: int | None = Field(None, ge=0, description="None: read to the end")
    answer_given: str | None = None
    self_judgment: Literal["correct", "incorrect"] | None = Field(
        None, description='"I was right" / "I was wrong": overrides the automatic judgment'
    )


class BuzzOut(BaseModel):
    buzz_id: int | None  # None for a prompt, which isn't recorded
    result: Literal["correct", "incorrect", "no_buzz", "prompt"]
    recorded: bool
    judged_by: Literal["auto", "self"]
    position: float | None
    clue_ordinal: int | None
    in_power: bool
    answer: str
    missed_cards: int


@router.post("/buzzes", tags=["buzzes"])
async def buzz(body: BuzzIn, db: Db, catalog: CatalogDep) -> BuzzOut:
    """Record a buzz on a question. A prompt isn't recorded: answer again.

    A wrong buzz (or none), or a right one after the topic's top clues were already read,
    turns those clues into "missed" cards.
    """
    tossup = await _fetch(catalog.tossup(body.tossup_id))
    if tossup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no question {body.tossup_id!r}")
    words = tossup["question"].split()
    line = tossup.get("answer_line") or {}
    answer = line.get("main") or tossup["answer"]
    wi = None if body.word_index is None else min(body.word_index, max(len(words) - 1, 0))
    reading = None
    if wi is not None:
        reading = next((c for c in tossup["clues"] if c["word_start"] <= wi < c["word_end"]), None)
    power = tossup.get("power_word")
    in_power = wi is not None and power is not None and wi < power

    judged_by: Literal["auto", "self"] = "auto"
    if body.self_judgment:
        result: Literal["correct", "incorrect", "no_buzz", "prompt"] = body.self_judgment
        judged_by = "self"
    elif wi is None:
        result = "no_buzz"
    else:
        result = answers.judge(
            body.answer_given or "", answer, line.get("required", []), line.get("accept", []),
            line.get("prompt", []), line.get("reject", []),
        )  # fmt: skip
    position = wi / max(len(words) - 1, 1) if wi is not None else None
    if result == "prompt":
        return BuzzOut(
            buzz_id=None,
            result="prompt",
            recorded=False,
            judged_by=judged_by,
            position=position,
            clue_ordinal=reading and reading["ordinal"],
            in_power=in_power,
            answer=answer,
            missed_cards=0,
        )

    topic_id = tossup.get("topic_id")
    missed = 0
    with db:
        cursor = db.execute(
            "INSERT INTO buzzes (tossup_id, topic_id, word_index, position, clue_ordinal, "
            "clue_cluster_id, result, in_power, answer_given, judged_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (body.tossup_id, topic_id, wi, position, reading and reading["ordinal"],
             reading and reading["cluster_id"], result, int(in_power), body.answer_given,
             judged_by, _now().isoformat()),
        )  # fmt: skip
        if topic_id:
            missed = await _missed_cards(db, catalog, tossup, topic_id, answer, wi, result, reading)
    return BuzzOut(
        buzz_id=cursor.lastrowid,
        result=result,
        recorded=True,
        judged_by=judged_by,
        position=position,
        clue_ordinal=reading and reading["ordinal"],
        in_power=in_power,
        answer=answer,
        missed_cards=missed,
    )


class BuzzOverride(BaseModel):
    result: Literal["correct", "incorrect"]


@router.patch("/buzzes/{buzz_id}", tags=["buzzes"])
def override_buzz(buzz_id: int, body: BuzzOverride, db: Db) -> dict[str, object]:
    """'I was right' / 'I was wrong': corrects the automatic judgment of a recorded buzz."""
    with db:
        cursor = db.execute(
            "UPDATE buzzes SET result = ?, judged_by = 'self' "
            "WHERE id = ? AND word_index IS NOT NULL",
            (body.result, buzz_id),
        )
    if not cursor.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no buzz {buzz_id}")
    return {"buzz_id": buzz_id, "result": body.result, "judged_by": "self"}


async def _missed_cards(
    db: sqlite3.Connection,
    catalog: Catalog,
    tossup: dict[str, Any],
    topic_id: str,
    answer: str,
    wi: int | None,
    result: str,
    reading: dict[str, Any] | None,
) -> int:
    """Cards for the topic's top clues that were read before a wrong or late buzz."""
    record = await _fetch(catalog.topic(topic_id))
    top = {c["cluster_id"] for c in record["clues"]} if record else set()
    words = tossup["question"].split()
    end = len(words) if wi is None else wi
    passed = [
        c for c in tossup["clues"]
        if c["kind"] == "clue" and c["cluster_id"] in top and c["word_start"] < end
        and c is not reading
    ]  # fmt: skip
    if result == "correct" and not passed:
        return 0
    new = [
        cards.missed_card(
            topic_id, answer, " ".join(words[c["word_start"] : c["word_end"]]),
            {"tossup_id": tossup["id"], "cluster_id": c["cluster_id"]},
        )
        for c in passed
    ]  # fmt: skip
    return _add_cards(db, new)


# --- Stats ------------------------------------------------------------------------------


class BuzzStats(BaseModel):
    buzzes: int
    correct: int
    accuracy: float | None
    median_correct_position: float | None
    power_rate: float | None  # correct buzzes before the power mark


class Stats(BaseModel):
    followed_topics: int
    cards: int
    due: int
    reviews_today: int
    buzzing: BuzzStats


def _buzz_stats(rows: list[tuple[str, float | None, int]]) -> BuzzStats:
    judged = [r for r in rows if r[0] != "no_buzz"]
    right = [r for r in rows if r[0] == "correct"]
    positions = [r[1] for r in right if r[1] is not None]
    return BuzzStats(
        buzzes=len(rows),
        correct=len(right),
        accuracy=len(right) / len(judged) if judged else None,
        median_correct_position=statistics.median(positions) if positions else None,
        power_rate=sum(r[2] for r in right) / len(right) if right else None,
    )


@router.get("/stats", tags=["stats"])
def stats(db: Db) -> Stats:
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    def one(sql: str, *args: object) -> int:
        value: int = db.execute(sql, args).fetchone()[0]
        return value

    return Stats(
        followed_topics=one("SELECT COUNT(*) FROM followed_topics"),
        cards=one("SELECT COUNT(*) FROM cards WHERE suspended = 0"),
        due=one(
            "SELECT COUNT(*) FROM cards c JOIN card_state s ON s.card_id = c.card_id "
            "WHERE c.suspended = 0 AND s.due <= ?",
            now.isoformat(),
        ),
        reviews_today=one("SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ?", today),
        buzzing=_buzz_stats(db.execute("SELECT result, position, in_power FROM buzzes").fetchall()),
    )


class TopicStats(BaseModel):
    topic_id: str
    followed: bool
    cards: int
    due: int
    buzzing: BuzzStats
    buzzed_clusters: dict[str, int]  # cluster id -> buzzes on it, for the heatmap markers


@router.get("/topics/{topic_id}/stats", tags=["stats"])
def topic_stats(topic_id: str, db: Db) -> TopicStats:
    now = _now().isoformat()
    rows = db.execute(
        "SELECT result, position, in_power, clue_cluster_id FROM buzzes WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()
    clusters: dict[str, int] = {}
    for *_, cluster in rows:
        if cluster is not None:
            clusters[str(cluster)] = clusters.get(str(cluster), 0) + 1
    card_count, due_count = db.execute(
        "SELECT COUNT(*), SUM(s.due <= ?) FROM cards c JOIN card_state s "
        "ON s.card_id = c.card_id WHERE c.topic_id = ? AND c.suspended = 0",
        (now, topic_id),
    ).fetchone()
    return TopicStats(
        topic_id=topic_id,
        followed=db.execute(
            "SELECT 1 FROM followed_topics WHERE topic_id = ?", (topic_id,)
        ).fetchone()
        is not None,
        cards=card_count,
        due=due_count or 0,
        buzzing=_buzz_stats([(r[0], r[1], r[2]) for r in rows]),
        buzzed_clusters=clusters,
    )


# --- Backup -----------------------------------------------------------------------------


@router.post("/admin/backup", tags=["admin"])
def backup_now(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    if settings.backup_dir is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "STUDY_BACKUP_DIR is not set")
    path = backup(settings.db_path, settings.backup_dir, settings.backups_kept)
    return {"backup": str(path)}
