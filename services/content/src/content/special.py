"""Special sections (Phase 6c): two per topic, chosen by its category.

A. A timeline of dated events (discoveries, for science), from the Wikipedia text. Each
   event quotes the sentence it comes from; code keeps only events whose quote is in the
   article and contains the event's year, so dates can't be invented.
B. A feature: the long, immersive piece, its form set by the category ("Be there" for
   history, a deep dive into one core concept for science...). Facts come from the source
   or are widely established; scenes are labeled dramatized. Science and math features may
   include a step diagram, drawn by the page from a fixed template.
"""

import re
from typing import Any

from content.writing import _squash

SPECIAL_VERSION = 3
TIMELINE_EVENTS = (4, 12)
FEATURE_WORDS = (600, 900)
# History and science pieces read better short: one vivid scene, one concept.
SHORT_FEATURE_WORDS = (300, 450)
SHORT_FEATURES = {"History", "Current Events", "Science", "Social Science"}


def feature_words(category: str | None) -> tuple[int, int]:
    return SHORT_FEATURE_WORDS if category in SHORT_FEATURES else FEATURE_WORDS


FORMS: dict[str, tuple[str, str, str]] = {
    # category: (title, what to write, timeline kind)
    "History": (
        "Be there",
        "Choose one pivotal moment of {name} and put the reader on the ground for that "
        "moment only. Do not retell the life, the career, or the overview. "
        "Give the sights and a few sounds — what someone present saw and heard — "
        "in a poetic, concrete way. Every event, person and place must be real; "
        "only the sensory atmosphere is imagined. Stay inside that one scene.",
        "events",
    ),
    "Current Events": (
        "Be there",
        "Choose one pivotal moment of {name} and put the reader on the ground for that "
        "moment only. Do not retell the overview. Give the sights and a few sounds — "
        "what someone present saw and heard — in a poetic, concrete way. "
        "Every event, person and place must be real; only the sensory atmosphere is "
        "imagined. Stay inside that one scene.",
        "events",
    ),
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
    "Literature": (
        "Walk through the work",
        "Walk the reader through {name} as if through "
        "the rooms of an exhibit: the key scenes, characters and turns in order, "
        "and what each reveals. For an author, walk through their life's work.",
        "events",
    ),
    "Mythology": (
        "The story",
        "Tell the central myth of {name} as a vivid story, keeping to "
        "the versions in the sources and naming the figures a reader should know.",
        "events",
    ),
    "Religion": (
        "Inside the tradition",
        "Take the reader inside {name}: a central practice "
        "or text, what a participant experiences, and what it means.",
        "events",
    ),
    "Fine Arts": (
        "Look closer",
        "Guide the reader around {name} as a museum docent would: "
        "what to look at (or listen for) first, the details that reward attention, "
        "and what they mean.",
        "events",
    ),
    "Geography": (
        "A traveller's route",
        "Take the reader on a journey through {name}: a "
        "route from place to place, what each looks and feels like, and why it "
        "matters.",
        "events",
    ),
}
DEFAULT_FORM = ("Deep dive", "Take one central aspect of {name} and explain it in depth, "
                "vividly and accurately, for a curious high-school reader.", "events")  # fmt: skip
DIAGRAM_CATEGORIES = {"Science", "Social Science", "Philosophy"}


def form(category: str | None) -> tuple[str, str, str]:
    return FORMS.get(category or "", DEFAULT_FORM)


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
