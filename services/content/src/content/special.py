"""Special sections (Phase 6c): two per topic, chosen by its category.

A. A timeline of dated events (discoveries, for science), from the Wikipedia text. Each
   event quotes the sentence it comes from; code keeps only events whose quote is in the
   article and contains the event's year, so dates can't be invented.
B. A feature. Science, social science and philosophy keep a short essay plus a step
   diagram the page draws. Every other category gets a handful: five or six related
   things (works, species, moments), each explained in a short paragraph.
"""

import re
from typing import Any

from content.writing import _squash

SPECIAL_VERSION = 5
TIMELINE_EVENTS = (4, 12)
FEATURE_WORDS = (600, 900)
# Diagram essays stay short so the scrolling box can hold the steps as well.
SHORT_FEATURE_WORDS = (300, 450)
SHORT_FEATURES = {"Science", "Social Science"}
HANDFUL_COUNT = (5, 6)
ENTRY_WORDS = (50, 100)


def feature_words(category: str | None) -> tuple[int, int]:
    return SHORT_FEATURE_WORDS if category in SHORT_FEATURES else FEATURE_WORDS


def is_diagram(category: str | None) -> bool:
    """Science, social science and philosophy keep the step diagram. Everyone else lists."""
    return (category or "") in DIAGRAM_CATEGORIES


# Diagram categories only. The page draws ``steps`` as a flow.
FORMS: dict[str, tuple[str, str, str]] = {
    # category: (title, what to write, timeline kind)
    "Science": (
        "Deep dive",
        "Take one core concept of {name} and explain it in great detail "
        "at an intuitive high-school level: build it from everyday experience, one "
        "step at a time, with concrete examples and analogies, until the reader "
        "really understands how and why it works.",
        "discoveries",
    ),
    "Social Science": (
        "Deep dive",
        "Take one core idea, model or experiment of {name} and "
        "explain it in great detail at an intuitive level: setup, how it "
        "works, what it shows, and how it has held up.",
        "events",
    ),
    "Philosophy": (
        "The argument",
        "Lay out the central argument of {name} step by step: the "
        "question, the premises, the reasoning, the conclusion, the strongest "
        "objection and the reply, in plain language.",
        "events",
    ),
}
HANDFUL_INSTRUCTIONS = (
    "List 5 or 6 things in one category that belongs with {name}, the way a fact book "
    "sets out a handful of examples and explains each one. "
    "If {name} is a person who made works (an author, composer, painter, director), "
    "list works. If {name} is a work (a book, play, film, poem, opera), list important "
    "moments in it. If {name} is an event or a battle, list specific moments or turning "
    "points. If {name} is a kind of thing, a place, or a field, list particular examples "
    "(species, places, pieces, people, objects). "
    "Do not retell the overview, the life, or the plot as one essay."
)
DEFAULT_FORM = ("A handful", HANDFUL_INSTRUCTIONS, "events")
DIAGRAM_CATEGORIES = {"Science", "Social Science", "Philosophy"}


def form(category: str | None) -> tuple[str, str, str]:
    if is_diagram(category):
        return FORMS[category or ""]
    return DEFAULT_FORM


TIMELINE_SYSTEM = """You extract a timeline from a source text. Every event must be stated \
in the source; you quote the sentence it comes from."""

TIMELINE = """Topic: {name}

From the source below, list {low}-{high} {kind} that matter for understanding {name}, \
oldest first. For each:
- "year": the year as a number (negative for BCE)
- "label": what happened, at most 12 words
- "source_sentence": the sentence of the source stating it, copied exactly; it must contain \
the year
Skip anything the source doesn't date.

Opening of the Wikipedia article (CC BY-SA). Copy each source_sentence from this text \
word for word:
{source}"""

TIMELINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "label": {"type": "string"},
                    "source_sentence": {"type": "string"},
                },
                "required": ["year", "label", "source_sentence"],
            },
        }
    },
    "required": ["events"],
}

FEATURE_SYSTEM = """You write the centerpiece of a study page about one quiz bowl answer, \
like the main room of a museum exhibit: immersive, vivid and accurate. You never invent \
facts, quotations, dates or numbers: they come from the source or are widely established."""

FEATURE = """Topic: {name} (category: {category})

Write "{title}": {instructions}

- "title": a short, specific title for the piece
- "body": {low}-{high} words, paragraphs separated by blank lines, no headings{diagram}

Wikipedia lead (CC BY-SA), the article's summary. Write from it and from widely \
established facts:
{source}"""

DIAGRAM = """
- "steps": 3-8 steps that summarize the concept as a flow the page will draw, each with a \
"label" (at most 6 words) and a "detail" (at most 30 words); [] if a flow doesn't fit"""

HANDFUL = """Topic: {name} (category: {category})

Write "{title}": {instructions}

- "title": a short heading for the list, naming the set (for example "Six snakes" or \
"Turning points")
- "entries": exactly 5 or 6 objects. Each has:
  - "name": the thing itself, at most 8 words (a species, a work, a moment)
  - "text": {low}-{high} words. Short, concrete and engaging, the way a fact book explains \
one example. No headings inside the text. Do not invent quotations, dates or numbers.

Wikipedia lead (CC BY-SA), the article's summary. Write from it and from widely \
established facts:
{source}"""

HANDFUL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
                "required": ["name", "text"],
            },
        },
    },
    "required": ["title", "entries"],
}

FEATURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["label", "detail"],
            },
        },
    },
    "required": ["title", "body"],
}


def _year_in(year: int, quote: str) -> bool:
    """The quote names the year: "1863", "1863-65", "500 BC" for -500, "5th century" won't do."""
    if year < 0:
        return re.search(rf"\b{-year}\s*(BCE?|B\.C\.)", quote, re.I) is not None
    return re.search(rf"(?<!\d){year}(?!\d)", quote) is not None


def timeline(events: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """Events whose quote is in the source and names their year, oldest first, deduplicated."""
    haystack = _squash(source)
    kept: dict[tuple[int, str], dict[str, Any]] = {}
    for event in events:
        quote = str(event.get("source_sentence", "")).strip()
        label = str(event.get("label", "")).strip()
        year = event.get("year")
        if not (isinstance(year, int) and label and quote) or len(label.split()) > 16:
            continue
        if _squash(quote) in haystack and _year_in(year, quote):
            kept.setdefault((year, _squash(label)), {"year": year, "label": label, "source": quote})
    return sorted(kept.values(), key=lambda e: e["year"])


def timeline_problem(data: dict[str, Any], source: str) -> str | None:
    kept = timeline(data.get("events", []), source)
    if len(data.get("events", [])) >= TIMELINE_EVENTS[0] and len(kept) < 3:
        return (
            "most events don't quote a sentence of the source that contains their year; copy "
            "each source_sentence exactly"
        )
    return None


def feature_problem(data: dict[str, Any], words: tuple[int, int] = FEATURE_WORDS) -> str | None:
    n = len(str(data.get("body", "")).split())
    low, high = words
    if not low * 0.85 <= n <= high * 1.2:
        return f"the body has {n} words, not {low}-{high}"
    if not str(data.get("title", "")).strip():
        return "missing title"
    for step in data.get("steps") or []:
        if (
            len(str(step.get("label", "")).split()) > 8
            or len(str(step.get("detail", "")).split()) > 40
        ):
            return "diagram steps must be short: a label of at most 6 words, details of 30"
    return None


def entries_problem(data: dict[str, Any]) -> str | None:
    """A handful is 5 or 6 named things, each a short paragraph."""
    entries = data.get("entries") or []
    low_n, high_n = HANDFUL_COUNT
    if not low_n <= len(entries) <= high_n:
        return f"need {low_n} or {high_n} entries, not {len(entries)}"
    if not str(data.get("title", "")).strip():
        return "missing title"
    low, high = ENTRY_WORDS
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not name or len(name.split()) > 10:
            return "each entry needs a short name"
        n = len(text.split())
        if not low * 0.8 <= n <= high * 1.2:
            return f"{name} has {n} words, not {low}-{high}"
    return None
