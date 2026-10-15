"""Topic pages, their questions, and practice questions, read from corpus.db."""

import hashlib
import json
import random
import re
import sqlite3
import statistics
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from pydantic import BaseModel

_MAX_EXCLUDE = 500


class ClueSpan(BaseModel):
    ordinal: int
    kind: str  # clue | giveaway | note
    word_start: int
    word_end: int
    in_power: bool
    cluster_id: int | None  # the topic's best-ranked clue this sentence names, if any


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
    # The answer's Wikipedia article, or a Wikipedia search for it when it isn't linked.
    wikipedia_url: str


class TossupPage(BaseModel):
    total: int
    items: list[Tossup]


_TOSSUP_COLUMNS = (
    "t.id, s.name, s.year, t.difficulty, t.category, t.subcategory, q.clean_text, "
    "q.power_word, t.answer_text, t.answer_html, tt.topic_id, tp.wikipedia_title"
)
_TOSSUP_FIELDS = (
    "id", "set_name", "year", "difficulty", "category", "subcategory", "question",
    "power_word", "answer", "answer_html", "topic_id", "wikipedia_title",
)  # fmt: skip
_TOSSUP_FROM = (
    "FROM tossups t JOIN question_layout q ON q.tossup_id = t.id "
    "LEFT JOIN sets s ON s.id = t.set_id LEFT JOIN tossup_topics tt ON tt.tossup_id = t.id "
    "LEFT JOIN topics tp ON tp.id = tt.topic_id"
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

    def filing(self, key: str) -> dict[str, object] | None:
        """The category a topic is usually asked in, plus its typical difficulty.

        Subcategory is the most common one on the topic's questions. Difficulty is the
        median question difficulty, so a flashcard can be filtered the way a tossup is.
        """
        with self._connect() as conn:
            topic_id = self._resolve(conn, key)
            if topic_id is None:
                return None
            try:
                rows = conn.execute(
                    "SELECT t.category, t.subcategory, t.alt_subcategory, t.difficulty "
                    "FROM tossups t JOIN tossup_topics tt ON tt.tossup_id = t.id "
                    "WHERE tt.topic_id = ?",
                    (topic_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                # A partial corpus may not have question rows yet.
                rows = []
            try:
                stored = conn.execute(
                    "SELECT primary_category FROM topics WHERE id = ?", (topic_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                stored = None

            def mode(index: int) -> str | None:
                counts = Counter(row[index] for row in rows if row[index])
                return counts.most_common(1)[0][0] if counts else None

            difficulties = [row[3] for row in rows if isinstance(row[3], int)]
            difficulty = int(round(statistics.median(difficulties))) if difficulties else None
            return {
                "topic_id": topic_id,
                "category": mode(0) or (stored[0] if stored else None),
                "subcategory": mode(1),
                "alt_subcategory": mode(2),
                "difficulty": difficulty,
            }

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

    def clues(self, key: str, offset: int, limit: int) -> list[str] | None:
        """The topic's clue records ranked offset+1 onward, as stored JSON ("show more")."""
        with self._connect() as conn:
            topic_id = self._resolve(conn, key)
            if topic_id is None:
                return None
            return [
                r[0]
                for r in conn.execute(
                    "SELECT json FROM topic_clue_records WHERE topic_id = ? AND rank > ? "
                    "ORDER BY rank LIMIT ?",
                    (topic_id, offset, limit),
                )
            ]

    def clue_candidates(self, key: str, limit: int) -> dict[str, object] | None:
        """The topic's top clues as the cleanup pass sees them: each spelling with the
        questions that use it (so merges and removed spellings can be recounted exactly),
        a few example sentences, and a fingerprint of the list. A rebuild that leaves the
        fingerprint alone keeps the stored cleanup."""
        with self._connect() as conn:
            topic_id = self._resolve(conn, key)
            if topic_id is None:
                return None
            clues = conn.execute(
                "SELECT id, rank, label, clue_key, n_questions, variants FROM topic_clues "
                "WHERE topic_id = ? AND rank <= ? ORDER BY rank",
                (topic_id, limit),
            ).fetchall()
            candidates = []
            for cid, rank, label, clue_key, n_questions, variants in clues:
                spellings = list(json.loads(variants))
                rows = conn.execute(
                    "SELECT c.tossup_id, c.text FROM topic_clue_sentences l "
                    "JOIN clues c ON c.id = l.clue_id WHERE l.topic_clue_id = ? ORDER BY c.id",
                    (cid,),
                ).fetchall()
                by_spelling: dict[str, set[str]] = {s: set() for s in spellings}
                for tossup, text in rows:
                    low = text.lower()
                    hit = [s for s in spellings if s.lower() in low]
                    for s in hit or spellings[:1]:  # a folded match ("Battle Royale")
                        by_spelling[s].add(tossup)
                candidates.append(
                    {
                        "id": cid,
                        "rank": rank,
                        "label": label,
                        "key": clue_key,
                        "n_questions": n_questions,
                        "spellings": {s: sorted(t) for s, t in by_spelling.items()},
                        "sentences": [text for _, text in rows[:4]],
                    }
                )
            name = conn.execute(
                "SELECT display_name, primary_category FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            groups = self._answer_groups(conn, topic_id)
            fingerprint = hashlib.sha1(
                json.dumps([(c["key"], c["n_questions"]) for c in candidates]).encode()
            ).hexdigest()[:16]
            return {
                "topic_id": topic_id,
                "name": name[0],
                "category": name[1],
                "fingerprint": fingerprint,
                "candidates": candidates,
                "groups": groups,
            }

    @staticmethod
    def _answer_groups(conn: sqlite3.Connection, topic_id: str) -> list[dict[str, object]]:
        """The answer lines the topic's questions were filed under, when there are several:
        one may name a different thing ("rings" for Koji Suzuki's Ring novels under The
        Lord of the Rings). ``key`` and ``category`` identify a group across rebuilds."""
        rows = conn.execute(
            "SELECT g.id, g.norm_key, g.category, g.display_name, tg.tossup_id "
            "FROM tossup_topics tt JOIN tossup_groups tg ON tg.tossup_id = tt.tossup_id "
            "JOIN candidate_groups g ON g.id = tg.group_id WHERE tt.topic_id = ? "
            "ORDER BY g.id, tg.tossup_id",
            (topic_id,),
        ).fetchall()
        groups: dict[int, dict[str, Any]] = {}
        for gid, key, category, display, tossup in rows:
            group = groups.setdefault(
                gid,
                {"id": gid, "key": key, "category": category, "answer": display, "tossups": []},
            )
            group["tossups"].append(tossup)
        if len(groups) < 2:
            return []
        for group in groups.values():
            row = conn.execute(
                "SELECT text FROM clues WHERE tossup_id = ? AND kind = 'giveaway' LIMIT 1",
                (group["tossups"][0],),
            ).fetchone()
            group["example"] = row[0] if row else ""
        return sorted(groups.values(), key=lambda g: -len(g["tossups"]))

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
        subcategory: str | None,
        difficulty_min: int | None,
        difficulty_max: int | None,
        exclude: list[str],
    ) -> Tossup | None:
        """A random question matching the filters, skipping ones already seen."""
        where: list[str] = []
        args: list[str | int] = []
        join = ""
        with self._connect() as conn:
            if topic is not None:
                topic_id = self._resolve(conn, topic)
                if topic_id is None:
                    return None
                where.append("p.topic_id = ?")
                args.append(topic_id)
            if category is not None:
                where.append("p.category = ?")
                args.append(category)
            if subcategory is not None:
                join = "JOIN tossups t2 ON t2.id = p.tossup_id"
                where.append("t2.subcategory = ?")
                args.append(subcategory)
            if difficulty_min is not None:
                where.append("p.difficulty >= ?")
                args.append(difficulty_min)
            if difficulty_max is not None:
                where.append("p.difficulty <= ?")
                args.append(difficulty_max)
            if exclude:
                seen = exclude[:_MAX_EXCLUDE]
                where.append(f"p.tossup_id NOT IN ({','.join('?' * len(seen))})")
                args.extend(seen)
            clause = f"WHERE {' AND '.join(where)}" if where else ""
            ids = [
                r[0] for r in conn.execute(
                    f"SELECT p.tossup_id FROM practice_pool p {join} {clause}", args
                )
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
        title = fields.pop("wikipedia_title")
        spans = conn.execute(
            "SELECT c.ordinal, c.kind, c.word_start, c.word_end, c.in_power, m.topic_clue_id "
            "FROM clues c LEFT JOIN sentence_clues m ON m.clue_id = c.id "
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
        main = parse[0] if parse else str(fields["answer"])
        fields["wikipedia_url"] = wikipedia_url(title if isinstance(title, str) else None, main)
        return Tossup.model_validate(fields)


    def explore_top(
        self,
        category: str,
        subcategory: str | None,
        alt_subcategory: str | None,
        difficulty_min: int | None,
        difficulty_max: int | None,
        limit: int,
    ) -> list[dict[str, object]]:
        where = ["t.category = ?"]
        args: list[str | int] = [category]
        if subcategory is not None:
            where.append("t.subcategory = ?")
            args.append(subcategory)
        if alt_subcategory is not None:
            where.append("t.alt_subcategory = ?")
            args.append(alt_subcategory)
        if difficulty_min is not None:
            where.append("t.difficulty >= ?")
            args.append(difficulty_min)
        if difficulty_max is not None:
            where.append("t.difficulty <= ?")
            args.append(difficulty_max)
        clause = " AND ".join(where)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT tp.id, tp.display_name, tp.primary_category, COUNT(*) AS cnt "
                f"FROM tossups t JOIN tossup_topics tt ON tt.tossup_id = t.id "
                f"JOIN topics tp ON tp.id = tt.topic_id WHERE {clause} "
                f"GROUP BY tp.id ORDER BY cnt DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
        return [
            {"topic_id": r[0], "name": r[1], "category": r[2], "count": r[3]}
            for r in rows
        ]

    def roulette(self, limit: int) -> list[dict[str, object]]:
        """A random draw of topics that have been asked at least once, for the explore wheel."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, display_name, primary_category, description, n_tossups "
                "FROM topics WHERE n_tossups >= 1 ORDER BY RANDOM() LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "topic_id": r[0],
                "name": r[1],
                "category": r[2],
                "description": r[3],
                "count": r[4],
            }
            for r in rows
        ]

    def topic_clues_brief(self, topic_id: str, limit: int) -> list[dict[str, object]] | None:
        with self._connect() as conn:
            if self._resolve(conn, topic_id) is None:
                return None
            rows = conn.execute(
                "SELECT label, n_questions FROM topic_clues "
                "WHERE topic_id = ? ORDER BY rank LIMIT ?",
                (topic_id, limit),
            ).fetchall()
        return [{"label": r[0], "count": r[1]} for r in rows]


def wikipedia_url(title: str | None, answer: str) -> str:
    """The linked article, or a Wikipedia search for the answer without its brackets."""
    if title:
        return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_(),'")
    plain = re.sub(r"\s+", " ", re.sub(r"[\[(].*?[\])]", " ", answer)).strip() or answer
    return "https://en.wikipedia.org/w/index.php?search=" + quote_plus(plain)
