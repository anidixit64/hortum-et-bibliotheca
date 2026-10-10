"""Topic pages, their questions, and practice questions, read from corpus.db."""

import json
import random
import sqlite3
from pathlib import Path

from pydantic import BaseModel

_MAX_EXCLUDE = 500


class ClueSpan(BaseModel):
    ordinal: int
    kind: str  # clue | giveaway | note
    word_start: int
    word_end: int
    in_power: bool
    cluster_id: int | None  # the clue cluster (same fact across questions), if any


class AnswerLine(BaseModel):
    """The parsed answer line, for judging a typed answer."""

    main: str
    required: list[str]  # the underlined part(s) of the main answer
    accept: list[str]
    prompt: list[str]
    reject: list[str]


class Tossup(BaseModel):
    id: str
    set_name: str | None
    year: int | None
    difficulty: int | None
    category: str | None
    subcategory: str | None
    question: str  # clean text: the power mark removed, see power_word
    power_word: int | None  # words before the power mark, if the question has one
    answer: str
    answer_html: str | None
    topic_id: str | None
    clues: list[ClueSpan]
    answer_line: AnswerLine | None


class TossupPage(BaseModel):
    total: int
    items: list[Tossup]


_TOSSUP_COLUMNS = (
    "t.id, s.name, s.year, t.difficulty, t.category, t.subcategory, q.clean_text, "
    "q.power_word, t.answer_text, t.answer_html, tt.topic_id"
)
_TOSSUP_FIELDS = (
    "id", "set_name", "year", "difficulty", "category", "subcategory", "question",
    "power_word", "answer", "answer_html", "topic_id",
)  # fmt: skip
_TOSSUP_FROM = (
    "FROM tossups t JOIN question_layout q ON q.tossup_id = t.id "
    "LEFT JOIN sets s ON s.id = t.set_id LEFT JOIN tossup_topics tt ON tt.tossup_id = t.id"
)


class TopicStore:
    def __init__(self, corpus_path: Path) -> None:
        self.corpus_path = corpus_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.corpus_path}?mode=ro", uri=True)

    def _resolve(self, conn: sqlite3.Connection, key: str) -> str | None:
        """A topic id, or the id behind a slug ("invisible-man")."""
        row = conn.execute("SELECT id FROM topics WHERE id = ?", (key,)).fetchone()
        row = row or conn.execute("SELECT id FROM topics WHERE slug = ?", (key,)).fetchone()
        return row[0] if row else None

    def snapshot(self, key: str) -> str | None:
        """The topic's ready-made page JSON, as stored: one primary-key read."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT json FROM topic_snapshots WHERE topic_id = ?", (key,)
            ).fetchone()
            if row is None and (topic_id := self._resolve(conn, key)):
                row = conn.execute(
                    "SELECT json FROM topic_snapshots WHERE topic_id = ?", (topic_id,)
                ).fetchone()
            return row[0] if row else None

    def tossups(self, key: str, limit: int, offset: int) -> TossupPage | None:
        with self._connect() as conn:
            topic_id = self._resolve(conn, key)
            if topic_id is None:
                return None
            total = conn.execute(
                "SELECT COUNT(*) FROM tossup_topics WHERE topic_id = ?", (topic_id,)
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT {_TOSSUP_COLUMNS} {_TOSSUP_FROM} WHERE tt.topic_id = ? "
                "ORDER BY s.year DESC, t.id LIMIT ? OFFSET ?",
                (topic_id, limit, offset),
            ).fetchall()
            return TossupPage(total=total, items=[self._tossup(conn, row) for row in rows])

    def practice(
        self,
        topic: str | None,
        category: str | None,
        difficulty_min: int | None,
        difficulty_max: int | None,
        exclude: list[str],
    ) -> Tossup | None:
        """A random question matching the filters, skipping ones already seen."""
        where: list[str] = []
        args: list[str | int] = []
        with self._connect() as conn:
            if topic is not None:
                topic_id = self._resolve(conn, topic)
                if topic_id is None:
                    return None
                where.append("topic_id = ?")
                args.append(topic_id)
            if category is not None:
                where.append("category = ?")
                args.append(category)
            if difficulty_min is not None:
                where.append("difficulty >= ?")
                args.append(difficulty_min)
            if difficulty_max is not None:
                where.append("difficulty <= ?")
                args.append(difficulty_max)
            if exclude:
                seen = exclude[:_MAX_EXCLUDE]
                where.append(f"tossup_id NOT IN ({','.join('?' * len(seen))})")
                args.extend(seen)
            clause = f"WHERE {' AND '.join(where)}" if where else ""
            # Filter the small indexed pool, then read one row: scanning the questions
            # themselves took seconds for a whole category.
            ids = [
                r[0] for r in conn.execute(f"SELECT tossup_id FROM practice_pool {clause}", args)
            ]
            if not ids:
                return None
            row = conn.execute(
                f"SELECT {_TOSSUP_COLUMNS} {_TOSSUP_FROM} WHERE t.id = ?", (random.choice(ids),)
            ).fetchone()
            return self._tossup(conn, row)

    def tossup(self, tossup_id: str) -> Tossup | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_TOSSUP_COLUMNS} {_TOSSUP_FROM} WHERE t.id = ?", (tossup_id,)
            ).fetchone()
            return self._tossup(conn, row) if row else None

    @staticmethod
    def _tossup(conn: sqlite3.Connection, row: tuple[object, ...]) -> Tossup:
        fields: dict[str, object] = dict(zip(_TOSSUP_FIELDS, row, strict=True))
        spans = conn.execute(
            "SELECT c.ordinal, c.kind, c.word_start, c.word_end, c.in_power, m.cluster_id "
            "FROM clues c LEFT JOIN clue_cluster_members m ON m.clue_id = c.id "
            "WHERE c.tossup_id = ? ORDER BY c.ordinal",
            (fields["id"],),
        ).fetchall()
        fields["clues"] = [
            {"ordinal": o, "kind": k, "word_start": a, "word_end": b, "in_power": bool(p),
             "cluster_id": cluster}
            for o, k, a, b, p, cluster in spans
        ]  # fmt: skip
        parse = conn.execute(
            "SELECT main, required, accept, prompt, reject FROM answer_parses WHERE tossup_id = ?",
            (fields["id"],),
        ).fetchone()
        fields["answer_line"] = (
            {
                "main": parse[0],
                "required": json.loads(parse[1]),
                "accept": [a["text"] for a in json.loads(parse[2])],
                "prompt": [a["text"] for a in json.loads(parse[3])],
                "reject": [a["text"] for a in json.loads(parse[4])],
            }
            if parse
            else None
        )
        return Tossup.model_validate(fields)
