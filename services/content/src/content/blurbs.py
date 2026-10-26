"""Short recommendations for two or three books on the public bibliography."""

import re
from typing import Any

VERSION = 2

SYSTEM = """You recommend books to a quiz bowl student. From the list you are given, choose \
the most important or interesting books: highly regarded, readable, or about a fascinating \
part of the topic. For each, write one sentence explaining why this book matters or what \
makes it worth reading. Use only titles from the list, copied exactly."""

PROMPT = """Topic: {name} (category: {category})

Pick {low} to {high} books from this list — choose the most important, acclaimed, or \
interesting ones. For each:
- "title": the title copied exactly from the list.
- "blurb": ONE sentence explaining why this book is worth reading — what it does \
uniquely well, why it matters, or what a reader will get from it. Be specific, not generic.

Books:
{books}"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "blurb": {"type": "string"}},
                "required": ["title", "blurb"],
            },
        }
    },
    "required": ["picks"],
}


def how_many(count: int) -> tuple[int, int]:
    """One book gets one blurb. Four or more get three or four, never more than the shelf."""
    if count <= 1:
        return 1, 1
    if count <= 3:
        return 2, min(3, count)
    return 3, min(4, count)


def _fold(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def kept(data: dict[str, Any], titles: list[str]) -> list[dict[str, str]]:
    """Picks whose title is on the shelf, in the model's order, at most three."""
    by_fold = {_fold(title): title for title in titles}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data.get("picks") or []:
        title = str(item.get("title", "")).strip()
        blurb = str(item.get("blurb", "")).strip()
        folded = _fold(title)
        if folded not in by_fold or folded in seen or not blurb or len(blurb.split()) > 50:
            continue
        seen.add(folded)
        out.append({"title": by_fold[folded], "blurb": blurb})
    _low, high = how_many(len(titles))
    return out[:high]


def problem(data: dict[str, Any], titles: list[str]) -> str | None:
    """Too few of the picks are real titles from the shelf: ask again once."""
    low, high = how_many(len(titles))
    found = kept(data, titles)
    if len(found) < low:
        return (
            f"pick {low} to {high} titles copied exactly from the list; "
            f"only {len(found)} matched"
        )
    return None
