"""Typo-tolerant topic search over the aliases in corpus.db."""

import math
import sqlite3
from pathlib import Path

from pydantic import BaseModel
from rapidfuzz import fuzz

from hortum_common.text import normalize

_CANDIDATES = 400
_POPULAR = math.log1p(300)  # a topic with ~300 questions gets the full popularity boost
# How much to trust an alias by where it came from. Underlined fragments are the weakest:
# "French <u>Republic</u>" makes "republic" an alias of France.
_SOURCE_WEIGHT = {"title": 1.0, "main": 1.0, "wikidata": 0.97, "accept": 0.93, "required": 0.85}


# Exact names that link to a topic page (lookup): only strong aliases. "required" and
# "accept" fragments are noisy ("aztec" for the Aztec Empire), so they count only for
# names of two words or more.
_STRONG = {"title": 3, "main": 2, "wikidata": 2}
_LOOSE = {"accept": 1}
LINK_MIN_TOSSUPS = 2  # a topic of its own: the answer to at least two questions
_NOT_NAMES = {"the", "a", "an", "this", "that", "these", "its", "his", "her", "their", "it",
              "he", "she", "they", "in", "on", "of", "and", "but", "for", "after", "when"}  # fmt: skip


class TopicLink(BaseModel):
    id: str
    name: str
    n_tossups: int


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
                    "SELECT f.topic_id, f.alias_search, a.source FROM ("
                    "  SELECT topic_id, alias_search FROM topic_aliases_fts"
                    "  WHERE topic_aliases_fts MATCH ? ORDER BY bm25(topic_aliases_fts) LIMIT ?"
                    ") f JOIN topic_aliases a"
                    "  ON a.topic_id = f.topic_id AND a.alias_search = f.alias_search",
                    (_trigram_query(needle), _CANDIDATES),
                ).fetchall()
            else:  # trigrams need three characters; fall back to a prefix match
                rows = conn.execute(
                    "SELECT topic_id, alias_search, source FROM topic_aliases "
                    "WHERE alias_search LIKE ? LIMIT ?",
                    (needle + "%", _CANDIDATES),
                ).fetchall()

            best: dict[str, tuple[float, str]] = {}
            for topic_id, alias, source in rows:
                similarity = fuzz.WRatio(needle, alias) / 100
                if alias == needle:
                    similarity += 0.30
                elif alias.startswith(needle):
                    similarity += 0.20
                elif (" " + needle) in (" " + alias):
                    similarity += 0.05
                similarity *= _SOURCE_WEIGHT.get(source, 0.9)
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

    def lookup(self, names: list[str], exclude: str | None = None) -> dict[str, TopicLink]:
        """Which of these names (proper nouns from a page) are topics with a page of their
        own. Exact alias matches only, the strongest alias first and then the most-asked
        topic; a name two topics share about equally links to neither."""
        out: dict[str, TopicLink] = {}
        with self._connect() as conn:
            for name in dict.fromkeys(names):
                needle = normalize(name)
                needles = [needle] + ([needle[4:]] if needle.startswith("the ") else [])
                if not needle:
                    continue
                one_word = len(needle.split()) == 1
                if one_word and (len(needle) < 4 or needle in _NOT_NAMES):
                    continue
                weights = _STRONG | ({} if one_word else _LOOSE)
                found: dict[str, tuple[int, int, str]] = {}
                own = False
                for alias in needles:
                    for topic_id, source, n, display in conn.execute(
                        "SELECT a.topic_id, a.source, t.n_tossups, t.display_name "
                        "FROM topic_aliases a JOIN topics t ON t.id = a.topic_id "
                        "WHERE a.alias_search = ?",
                        (alias,),
                    ):
                        weight = weights.get(source, 0)
                        # Any of the page's own names, except a one-word "accept" (a question
                        # on the Aztec Empire accepting "Nahuatl" doesn't make it the empire).
                        own = own or (topic_id == exclude and not (one_word and source == "accept"))
                        if not topic_id.startswith("Q"):  # unlinked answer groups ("Spanish")
                            continue
                        # A single word links only as a topic's whole name, a parenthesis
                        # aside: "Cuba", "Hamlet (play)", not "Spanish" for the language.
                        if one_word and normalize(display.split(" (")[0]) != alias:
                            continue
                        if weight and n >= LINK_MIN_TOSSUPS and topic_id != exclude:
                            best = found.get(topic_id, (0, 0, display))
                            found[topic_id] = (max(best[0], weight), n, display)
                if own or not found:  # the page's own topic by another name: no link
                    continue
                ranked = sorted(found.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
                (top_id, (weight, n, display)), rest = ranked[0], ranked[1:]
                if rest and rest[0][1][0] == weight and rest[0][1][1] * 2 > n:
                    continue  # two topics answer to this name: don't guess
                out[name] = TopicLink(id=top_id, name=display, n_tossups=n)
        return out
