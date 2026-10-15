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
            "INSERT OR IGNORE INTO cards (card_id, topic_id, kind, front, back, source_ref, "
            "created_at, suspended, category, subcategory, alt_subcategory, difficulty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
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
            conn.execute(
                "UPDATE cards SET suspended = 0, "
                "category = COALESCE(category, ?), subcategory = COALESCE(subcategory, ?), "
                "alt_subcategory = COALESCE(alt_subcategory, ?), "
                "difficulty = COALESCE(difficulty, ?) WHERE card_id = ?",
                (card.category, card.subcategory, card.alt_subcategory, card.difficulty,
                 card.card_id),
            )  # fmt: skip
    return created


# --- Clue flashcards ------------------------------------------------------------------


class ClueCardsBody(BaseModel):
    lines: list[str] = Field(max_length=50)
    answer: str
    clue_label: str


@router.post("/topics/{topic_id}/clue-cards", status_code=201, tags=["topics"])
def create_clue_cards(topic_id: str, body: ClueCardsBody, db: Db) -> dict[str, int]:
    """Create a flashcard for each question line of a clue."""
    filing = _filing_on_topic(db, topic_id)
    new = [
        cards.with_filing(
            cards.NewCard(
                cards.card_id(topic_id, "clue", line),
                topic_id,
                "clue",
                line,
                f"{body.answer}\n{body.clue_label}",
                {"clue_label": body.clue_label},
            ),
            filing,
        )
        for line in body.lines[:50]
    ]
    with db:
        created = _add_cards(db, new)
    return {"created": created, "total": len(new)}


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
        filing = await catalog.filing(topic_id)
        created = _add_cards(db, [cards.with_filing(c, filing) for c in cards.topic_cards(record)])
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
    accuracy: float | None = None


@router.get("/topics", tags=["topics"])
def followed(db: Db) -> list[FollowedTopic]:
    now = _now().isoformat()
    rows = db.execute(
        "SELECT f.topic_id, f.name, COUNT(c.card_id), "
        "SUM(c.card_id IS NOT NULL AND c.suspended = 0 AND s.due <= ?), "
        "(SELECT COUNT(*) FROM buzzes b WHERE b.topic_id = f.topic_id AND b.result != 'no_buzz'), "
        "(SELECT SUM(b.result = 'correct') FROM buzzes b "
        " WHERE b.topic_id = f.topic_id AND b.result != 'no_buzz') "
        "FROM followed_topics f LEFT JOIN cards c ON c.topic_id = f.topic_id "
        "LEFT JOIN card_state s ON s.card_id = c.card_id GROUP BY f.topic_id ORDER BY f.added_at",
        (now,),
    ).fetchall()
    out = []
    for topic_id, name, n_cards, due, judged, correct in rows:
        judged = judged or 0
        out.append(
            FollowedTopic(
                topic_id=topic_id,
                name=name,
                cards=n_cards,
                due=due or 0,
                accuracy=(correct or 0) / judged if judged else None,
            )
        )
    return out


def _filing_on_topic(db: sqlite3.Connection, topic_id: str) -> dict[str, object] | None:
    """Filing already stored on one of this topic's cards, for cards made later."""
    row = db.execute(
        "SELECT category, subcategory, alt_subcategory, difficulty FROM cards "
        "WHERE topic_id = ? AND category IS NOT NULL LIMIT 1",
        (topic_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "category": row[0],
        "subcategory": row[1],
        "alt_subcategory": row[2],
        "difficulty": row[3],
    }


# --- Reviews ----------------------------------------------------------------------------


class DueCard(BaseModel):
    card_id: str
    topic_id: str
    kind: str
    front: str
    back: str
    due: str
    category: str | None = None
    subcategory: str | None = None
    alt_subcategory: str | None = None
    difficulty: int | None = None


_CARD_COLUMNS = (
    "c.card_id, c.topic_id, c.kind, c.front, c.back, s.due, "
    "c.category, c.subcategory, c.alt_subcategory, c.difficulty"
)


def _card(row: tuple[object, ...]) -> DueCard:
    return DueCard(
        card_id=str(row[0]), topic_id=str(row[1]), kind=str(row[2]), front=str(row[3]),
        back=str(row[4]), due=str(row[5]), category=_opt_str(row[6]), subcategory=_opt_str(row[7]),
        alt_subcategory=_opt_str(row[8]), difficulty=_opt_int(row[9]),
    )  # fmt: skip


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _filing_clause(
    category: str | None,
    subcategory: str | None,
    difficulty_min: int | None,
    difficulty_max: int | None,
) -> tuple[str, list[object]]:
    where = ["c.suspended = 0"]
    args: list[object] = []
    if category:
        where.append("c.category = ?")
        args.append(category)
    if subcategory:
        where.append("(c.subcategory = ? OR c.alt_subcategory = ?)")
        args.extend([subcategory, subcategory])
    if difficulty_min is not None:
        where.append("c.difficulty >= ?")
        args.append(difficulty_min)
    if difficulty_max is not None:
        where.append("c.difficulty <= ?")
        args.append(difficulty_max)
    return " AND ".join(where), args


@router.get("/reviews/due", tags=["reviews"])
def due(
    db: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    category: str | None = None,
    subcategory: str | None = None,
    difficulty_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    difficulty_max: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> list[DueCard]:
    """Cards due now, most overdue first. Filters use the filing stored on each card."""
    clause, args = _filing_clause(category, subcategory, difficulty_min, difficulty_max)
    rows = db.execute(
        f"SELECT {_CARD_COLUMNS} FROM cards c JOIN card_state s ON s.card_id = c.card_id "
        f"WHERE {clause} AND s.due <= ? ORDER BY s.due LIMIT ?",
        (*args, _now().isoformat(), limit),
    ).fetchall()
    return [_card(r) for r in rows]


@router.get("/cards", tags=["reviews"])
def list_cards(
    db: Db,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    category: str | None = None,
    subcategory: str | None = None,
    difficulty_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    difficulty_max: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> list[DueCard]:
    """Every active card, newest first, for the review browser."""
    clause, args = _filing_clause(category, subcategory, difficulty_min, difficulty_max)
    rows = db.execute(
        f"SELECT {_CARD_COLUMNS} FROM cards c JOIN card_state s ON s.card_id = c.card_id "
        f"WHERE {clause} ORDER BY c.created_at DESC LIMIT ?",
        (*args, limit),
    ).fetchall()
    return [_card(r) for r in rows]


class CardEdit(BaseModel):
    front: str = Field(min_length=1, max_length=4000)
    back: str = Field(min_length=1, max_length=4000)


@router.patch("/cards/{card_id}", tags=["reviews"])
def edit_card(card_id: str, body: CardEdit, db: Db) -> DueCard:
    """Rewrite a card's front and back. The id stays, so its review history stays with it."""
    with db:
        cursor = db.execute(
            "UPDATE cards SET front = ?, back = ? WHERE card_id = ? AND suspended = 0",
            (body.front, body.back, card_id),
        )
    if not cursor.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no card {card_id!r}")
    row = db.execute(
        f"SELECT {_CARD_COLUMNS} FROM cards c JOIN card_state s ON s.card_id = c.card_id "
        "WHERE c.card_id = ?",
        (card_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no card {card_id!r}")
    return _card(row)


@router.delete("/cards/{card_id}", status_code=204, tags=["reviews"])
def delete_card(card_id: str, db: Db) -> None:
    """Remove a card and its review history."""
    with db:
        db.execute("DELETE FROM reviews WHERE card_id = ?", (card_id,))
        db.execute("DELETE FROM card_state WHERE card_id = ?", (card_id,))
        cursor = db.execute("DELETE FROM cards WHERE card_id = ?", (card_id,))
    if not cursor.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no card {card_id!r}")


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
    with db:
        cursor = db.execute(
            "INSERT INTO buzzes (tossup_id, topic_id, word_index, position, clue_ordinal, "
            "clue_cluster_id, result, in_power, answer_given, judged_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (body.tossup_id, topic_id, wi, position, reading and reading["ordinal"],
             reading and reading["cluster_id"], result, int(in_power), body.answer_given,
             judged_by, _now().isoformat()),
        )  # fmt: skip
    return BuzzOut(
        buzz_id=cursor.lastrowid,
        result=result,
        recorded=True,
        judged_by=judged_by,
        position=position,
        clue_ordinal=reading and reading["ordinal"],
        in_power=in_power,
        answer=answer,
        missed_cards=0,
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


class RatingCounts(BaseModel):
    again: int
    hard: int
    good: int
    easy: int


class Stats(BaseModel):
    followed_topics: int
    cards: int
    due: int
    reviews_today: int
    reviews_total: int
    ratings: RatingCounts
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

    ratings = {1: 0, 2: 0, 3: 0, 4: 0}
    for rating, count in db.execute("SELECT rating, COUNT(*) FROM reviews GROUP BY rating"):
        if rating in ratings:
            ratings[rating] = count
    return Stats(
        followed_topics=one("SELECT COUNT(*) FROM followed_topics"),
        cards=one("SELECT COUNT(*) FROM cards WHERE suspended = 0"),
        due=one(
            "SELECT COUNT(*) FROM cards c JOIN card_state s ON s.card_id = c.card_id "
            "WHERE c.suspended = 0 AND s.due <= ?",
            now.isoformat(),
        ),
        reviews_today=one("SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ?", today),
        reviews_total=sum(ratings.values()),
        ratings=RatingCounts(
            again=ratings[1], hard=ratings[2], good=ratings[3], easy=ratings[4]
        ),
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
