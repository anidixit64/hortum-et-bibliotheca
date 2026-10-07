"""Review logic for low-confidence answer lines (the window in gui/ only draws this)."""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from hortum_common.text import normalize
from hortum_pipeline.answer_stage import apply_overrides, revert_override
from hortum_pipeline.overrides import AnswerOverride, OverrideStore

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


@dataclass
class ReviewItem:
    line_key: str
    n_questions: int
    confidence: float
    guess: str
    answer_text: str
    issues: str
    category: str
    fixed: bool  # saved in the overrides file
    applied: bool  # already written to corpus.db


@dataclass
class Suggestion:
    name: str
    n_questions: int
    score: float


class ReviewModel:
    def __init__(self, corpus_path: Path, overrides_path: Path) -> None:
        self.conn = sqlite3.connect(corpus_path, check_same_thread=False)
        self.store = OverrideStore(overrides_path)
        self._choices: dict[str, tuple[str, int]] | None = None

    # -- listing ----------------------------------------------------------------------

    def categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM tossups WHERE category IS NOT NULL ORDER BY 1"
        )
        return [r[0] for r in rows]

    def items(
        self,
        threshold: float,
        category: str | None = None,
        search: str = "",
        include_fixed: bool = False,
    ) -> list[ReviewItem]:
        """Distinct low-confidence answer lines, most questions affected first."""
        rows = self.conn.execute(
            """
            SELECT a.line_key, COUNT(*), MIN(a.parser_confidence), MAX(a.parser_main),
                   MAX(t.answer_text),
                   MAX(a.issues), MAX(t.category), MAX(a.source)
            FROM answer_parses a JOIN tossups t ON t.id = a.tossup_id
            WHERE a.parser_confidence < ?
            GROUP BY a.line_key
            ORDER BY COUNT(*) DESC, MAX(t.answer_text)
            """,
            (threshold,),
        ).fetchall()
        needle = search.lower().strip()
        out = []
        for key, n, conf, guess, answer, issues, cat, source in rows:
            fixed = key in self.store
            if fixed and not include_fixed:
                continue
            if category and cat != category:
                continue
            if needle and needle not in answer.lower() and needle not in guess.lower():
                continue
            out.append(
                ReviewItem(
                    key, n, conf, guess, answer, issues, cat or "", fixed, source != "parser"
                )
            )
        return out

    def counts(self, threshold: float) -> dict[str, int]:
        lines, questions = self.conn.execute(
            "SELECT COUNT(DISTINCT line_key), COUNT(*) FROM answer_parses "
            "WHERE parser_confidence < ?",
            (threshold,),
        ).fetchone()
        return {
            "lines": lines,
            "questions": questions,
            "fixed": len(self.store),
            "pending": len(self.pending()),
        }

    # -- detail and suggestions -------------------------------------------------------

    def giveaways(self, key: str, limit: int = 3) -> list[str]:
        """The last sentence of a few questions with this answer line ("...name this X.")."""
        rows = self.conn.execute(
            "SELECT t.question_text FROM answer_parses a JOIN tossups t ON t.id = a.tossup_id "
            "WHERE a.line_key = ? LIMIT ?",
            (key, limit),
        )
        out = []
        for (question,) in rows:
            sentences = _SENTENCE_END.split(question.strip())
            out.append(sentences[-1] if sentences else question)
        return out

    def suggestions(self, text: str, limit: int = 8) -> list[Suggestion]:
        """Confidently parsed answers that look like ``text``, with how often they occur."""
        if self._choices is None:
            self._choices = {}
            rows = self.conn.execute(
                "SELECT main_norm, main, COUNT(*) FROM answer_parses "
                "WHERE confidence >= 0.8 AND source != 'excluded' AND main_norm != '' "
                "GROUP BY main_norm, main"
            )
            for norm, main, n in rows:
                best = self._choices.get(norm)
                total = n + (best[1] if best else 0)
                name = main if best is None or n > best[1] else best[0]
                self._choices[norm] = (name, total)
        query = normalize(text)
        if not query:
            return []
        matches = process.extract(
            query, list(self._choices), scorer=fuzz.WRatio, limit=limit * 3, score_cutoff=60
        )
        ranked = sorted(
            (Suggestion(*self._choices[norm], score) for norm, score, _ in matches),
            key=lambda s: (-round(s.score / 5), -s.n_questions),
        )
        return ranked[:limit]

    # -- saving and re-running --------------------------------------------------------

    def save(self, item: ReviewItem, main: str, exclude: bool = False) -> None:
        self.store.save(AnswerOverride(item.line_key, item.answer_text, main.strip(), exclude))

    def undo(self, key: str) -> None:
        """Forgets a fix and restores the parser's answer in corpus.db."""
        self.store.remove(key)
        revert_override(self.conn, key)
        self._choices = None

    def pending(self) -> list[AnswerOverride]:
        """Saved fixes not yet written to corpus.db."""
        fixes = {o.line_key: o for o in self.store.all()}
        if not fixes:
            return []
        placeholders = ",".join("?" * len(fixes))
        rows = self.conn.execute(
            "SELECT DISTINCT line_key, main, source FROM answer_parses "
            f"WHERE line_key IN ({placeholders})",
            list(fixes),
        )
        stale = set()
        for key, main, source in rows:
            fix = fixes[key]
            want = "excluded" if fix.exclude else "override"
            if source != want or (not fix.exclude and main != fix.main):
                stale.add(key)
        return [fixes[k] for k in stale]

    def rerun_pending(self) -> int:
        """Re-parses only the fixed lines into corpus.db; returns questions updated."""
        changed = apply_overrides(self.conn, self.pending())
        self._choices = None
        return changed
