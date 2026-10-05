"""Typo-tolerant topic search over the aliases in corpus.db."""

import math
import sqlite3
from pathlib import Path

from pydantic import BaseModel
from rapidfuzz import fuzz

from hortum_common.text import normalize

_CANDIDATES = 400
_POPULAR = math.log1p(300)  # a topic with ~300 questions gets the full popularity boost


class SearchResult(BaseModel):
    id: str
    name: str
    category: str | None
    description: str | None
    n_tossups: int
    matched_alias: str
    score: float


def _trigram_query(text: str) -> str:
    grams = {text[i : i + 3] for i in range(len(text) - 2)}
    return " OR ".join(f'"{g}"' for g in sorted(grams))


class SearchIndex:
    def __init__(self, corpus_path: Path) -> None:
        self.corpus_path = corpus_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.corpus_path}?mode=ro", uri=True)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        needle = normalize(query)
        if not needle:
            return []
        with self._connect() as conn:
            if len(needle) >= 3:
                rows = conn.execute(
                    "SELECT topic_id, alias_search FROM topic_aliases_fts "
                    "WHERE topic_aliases_fts MATCH ? ORDER BY bm25(topic_aliases_fts) LIMIT ?",
                    (_trigram_query(needle), _CANDIDATES),
                ).fetchall()
            else:  # trigrams need three characters; fall back to a prefix match
                rows = conn.execute(
                    "SELECT topic_id, alias_search FROM topic_aliases "
                    "WHERE alias_search LIKE ? LIMIT ?",
                    (needle + "%", _CANDIDATES),
                ).fetchall()

            best: dict[str, tuple[float, str]] = {}
            for topic_id, alias in rows:
                similarity = fuzz.WRatio(needle, alias) / 100
                if alias == needle:
                    similarity += 0.15
                elif alias.startswith(needle):
                    similarity += 0.05
                if similarity > best.get(topic_id, (0.0, ""))[0]:
                    best[topic_id] = (similarity, alias)
            if not best:
                return []

            shortlist = sorted(best, key=lambda t: -best[t][0])[: limit * 5]
            placeholders = ",".join("?" * len(shortlist))
            topics = conn.execute(
                f"SELECT id, display_name, primary_category, description, n_tossups "
                f"FROM topics WHERE id IN ({placeholders})",
                shortlist,
            ).fetchall()

        results = []
        for topic_id, name, category, description, n_tossups in topics:
            similarity, alias = best[topic_id]
            popularity = min(1.0, math.log1p(n_tossups) / _POPULAR)
            results.append(
                SearchResult(
                    id=topic_id,
                    name=name,
                    category=category,
                    description=description,
                    n_tossups=n_tossups,
                    matched_alias=alias,
                    score=round(0.8 * similarity + 0.2 * popularity, 4),
                )
            )
        results.sort(key=lambda r: -r.score)
        return results[:limit]
