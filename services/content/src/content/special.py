"""Special sections (Phase 6c): two per topic, chosen by its category.

A. A timeline of dated events (discoveries, for science), from the Wikipedia text. Each
   event quotes the sentence it comes from; code keeps only events whose quote is in the
   article and contains the event's year, so dates can't be invented.
B. A handful: five or six related things (works, species, moments), each explained in a
   short paragraph. Science, social science and philosophy also get a step diagram and a
   100-150 word note about what that diagram shows.
"""

import re
from typing import Any

from content.writing import _squash

SPECIAL_VERSION = 13
TIMELINE_EVENTS = (4, 12)
HANDFUL_COUNT = (5, 6)
ENTRY_WORDS = (100, 150)
BLURB_WORDS = (100, 150)
def is_diagram(category: str | None) -> bool:
    """Every topic gets a step diagram."""
    return True


HANDFUL_INSTRUCTIONS = (
    "List 5 or 6 things in one category that belongs with {name}, the way a fact book "
    "sets out a handful of examples and explains each one. "
    "If {name} is a person who made works (an author, composer, painter, director), "
    "list works. Lead with the most iconic, important, or essential works — the ones "
    "everyone should know, the masterpieces, the career-defining hits. Do NOT cluster "
    "picks from one era, period, or theme; spread them across the creator's career to "
    "show range. Do NOT pick inconsequential or niche works — every entry should be "
    "something a well-read person would recognize or that critics consider essential. "
    "At most 1 entry may be a deeper cut that rewards a curious reader. "
    "For a poet, start with the poems that appear in every anthology; for a director, "
    "the films critics and audiences agree are their best; for a painter, the canvases "
    "people travel to see. "
    "If {name} is a work (a book, play, film, poem, opera), list important "
    "moments in it. If {name} is an event or a battle, list specific moments or turning "
    "points. If {name} is a kind of thing, a place, or a field, list particular examples "
    "(species, places, pieces, people, objects). "
    "Do not retell the overview, the life, or the plot as one essay. "
    "Each entry should add a fact the topic summary does not already tell, and should "
    "not spend itself restating a clue the page already lists. A shared name is fine "
    "when the new fact needs it."
)
DEFAULT_FORM = ("A handful", HANDFUL_INSTRUCTIONS, "events")


def form(category: str | None) -> tuple[str, str, str]:
    """Every category lists a handful. Science timelines are discoveries."""
    title, instructions, _kind = DEFAULT_FORM
    kind = "discoveries" if category == "Science" else "events"
    return title, instructions, kind


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

DIAGRAM = """
- "steps": 3-8 steps that draw one core process, mechanism, or story arc related to \
the topic as a flow. Pick the most complex or fascinating idea tied to the topic — \
something a professor would explain in a lecture — and break it into steps a high-school \
student can follow without losing accuracy. Each step has a "label" (at most 6 words) \
and a "detail" (at most 40 words). The detail should be clear enough that a reader \
understands the step without any separate explanation — say what happens and why it \
leads to the next step. The steps are a diagram, not an essay and not a substitute \
for the entries.
- "diagram_blurb": leave this as an empty string."""

HANDFUL = """Topic: {name} (category: {category})

Write "{title}": {instructions}

- "title": a short heading for the list, naming the set (for example "Six snakes" or \
"Turning points")
- "entries": exactly 5 or 6 objects. Each has:
  - "name": the thing itself, at most 8 words (a species, a work, a moment)
  - "text": {low}-{high} words. Short, concrete and engaging, the way a fact book explains \
one example. No headings inside the text. Do not invent quotations, dates or numbers.
{diagram}
Already on the page. Do not repeat this. The substance of each entry should be new; \
a passing overlap in names is fine.

Summary already shown:
{summary}

Clues already listed:
{clue_labels}

Wikipedia lead (CC BY-SA). Use it for names, dates and numbers, then add widely \
established facts that the summary and the clues do not already cover:
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

STEP_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "detail": {"type": "string"}},
        "required": ["label", "detail"],
    },
}


def handful_schema(diagram: bool) -> dict[str, Any]:
    """The list, plus diagram steps and a short note when this category draws one."""
    if not diagram:
        return HANDFUL_SCHEMA
    return {
        "type": "object",
        "properties": {
            **HANDFUL_SCHEMA["properties"],
            "steps": STEP_SCHEMA,
            "diagram_blurb": {"type": "string"},
        },
        "required": ["title", "entries", "steps"],
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


def entries_problem(data: dict[str, Any], *, diagram: bool = False) -> str | None:
    """A handful is 5 or 6 named things, each a short paragraph. Diagram categories also
    need short steps and a 100-150 word note about the diagram, and no essay."""
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
    if diagram:
        steps = data.get("steps") or []
        if not 3 <= len(steps) <= 8:
            return f"the diagram needs 3-8 steps, not {len(steps)}"
        for step in steps:
            if (
                len(str(step.get("label", "")).split()) > 8
                or len(str(step.get("detail", "")).split()) > 50
            ):
                return "diagram steps must be short: a label of at most 6 words, details of 40"
    return None
