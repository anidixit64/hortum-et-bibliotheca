"""Written sections (Phase 6): clue explanations, and the hook and summary.

Both are written from the topic's *cleaned* clue list (see ``cleanup``), so they run after
it. Clue explanations go to the light tier, five clues per request; the hook and summary
go to the writing tier. The summary marks each clue it mentions as ``[[rank|words]]``;
code checks every mark names a real clue, and the page shows marked words in bold with
the clue's one-line summary on hover and a "See more" link to its explanation.
"""

import re
from typing import Any

EXPLANATIONS_VERSION = 3
SUMMARY_VERSION = 1
BATCH = 5  # clues per explanation request
FIRST_PAGE = 10  # clues explained when the topic is first opened
EXPLANATION_WORDS = (200, 300)
SUMMARY_WORDS = (500, 750)
# The whole Wikipedia article goes to every written section (see fetchers.wiki).
SOURCE_WORDS = 80_000

EXPLAIN_SYSTEM = """You write study notes for quiz bowl players. A clue is a term that \
quiz bowl questions about an answer mention; players learn clues to recognize the answer \
early. You explain each clue at the depth of a specialist (graduate level), accurately. \
Accuracy comes first: state a date, number, name, place, quotation or mechanism only if \
the source text gives it or you are certain of it; otherwise describe it in general terms. \
The source can be loosely worded: where your own firm knowledge corrects it, follow your \
knowledge."""

EXPLAIN = """Answer: {name} (category: {category})

For each clue below, write:
- "one_line": one sentence (at most 30 words) whose subject is the clue itself, saying \
what it is and how it ties to {name}. It appears in a hover popup.
- "explanation": {low}-{high} words for an advanced reader: what the clue is, how it \
relates to {name}, its context, and why it matters. Plain prose, no headings or lists. \
Spend every sentence on substance: give at least two concrete facts particular to this clue \
(what happened, who, when, how it works), and don't repeat what another clue's explanation \
covers.

The example sentences show how questions use each clue ("this man", "this work" etc. stand \
for {name}); use them to tell which thing the clue means, but write about the thing itself.

Never:
- mention the examples, questions, question writers, players, "the clue" or "the answer" \
(write "Ellison's narrator", not "the answer is Invisible Man")
- mention the source, the article or the text ("the source notes...", "described above"): \
state facts directly
- write study advice ("recognizing X lets a player...", "studying X shows...", "for \
students...")

Clues (JSON):
{clues}

Source (Wikipedia, CC BY-SA):
{source}"""

EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "one_line": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["rank", "one_line", "explanation"],
            },
        }
    },
    "required": ["explanations"],
}

SUMMARY_SYSTEM = """You write the opening of a study page about one quiz bowl answer. \
Your writing is engaging and vivid, aimed at understanding and curiosity rather than \
technical detail, readable by a high school student, while naming specialist terms \
correctly. You use only facts supported by the source text or widely established; you \
never invent quotations, dates or numbers."""

SUMMARY = """Answer: {name} (category: {category})

Write:
- "hook": two or three short sentences that make a reader want to learn about {name}: a \
striking fact, tension or image. No questions to the reader.
- "summary": {low}-{high} words explaining {name} in an engaging, descriptive way that \
builds understanding and interest. Paragraphs separated by blank lines, no headings.

Weave in as many of the clues below as fit naturally (aim for most of them). Mark each \
mention exactly as [[RANK|the words you write]], e.g. [[3|the Battle Royal]]: RANK is the \
clue's number below, and the words are what the reader sees in bold. Mark a clue only \
where the text is really about it, and only once.

Clues (rank: label — what it is):
{clues}

Source (Wikipedia, CC BY-SA):
{source}"""

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"hook": {"type": "string"}, "summary": {"type": "string"}},
    "required": ["hook", "summary"],
}

MARK = re.compile(r"\[\[(\d+)\|([^\]]+)\]\]")


def word_count(text: str) -> int:
    return len(MARK.sub(lambda m: m.group(2), text).split())


# Notes that talk about the quiz instead of the subject ("the example", "the answer is war").
# Only phrases that are about the quiz in any subject, since a failed check fails the job
# (a sports topic has players; a philosophy topic asks questions).
META = re.compile(
    r"\b(the|this|these|some) (examples?|example sentences?|clues?)\b"
    r"|\b(the|these|some) questions (say|use|ask|mention|attribute|refer|describe)"
    r"|\bquestion ?writers?\b|\bquiz ?bowl\b|\bthe answer (is|here)\b|\bdistractors?\b"
    r"|\bthe (source|excerpt|article)('s)?\b(?! of)|\bdescribed above\b",
    re.I,
)


def meta_phrase(text: str) -> str | None:
    found = META.search(text)
    return found.group(0) if found else None


def explain_problem(
    data: dict[str, Any], ranks: list[int], words: tuple[int, int] = EXPLANATION_WORDS
) -> str | None:
    """Why an explanation reply can't be used (it's asked again once), or None."""
    got = {e.get("rank"): e for e in data.get("explanations", []) if isinstance(e, dict)}
    missing = [r for r in ranks if r not in got]
    if missing:
        return f"missing explanations for clues {missing}"
    low, high = words
    for rank in ranks:
        entry = got[rank]
        n = len(str(entry.get("explanation", "")).split())
        if not low * 0.9 <= n <= high * 1.3:
            return f"clue {rank}'s explanation has {n} words, not {low}-{high}"
        if len(str(entry.get("one_line", "")).split()) > 45:
            return f"clue {rank}'s one_line is longer than one sentence"
        for field in ("one_line", "explanation"):
            if phrase := meta_phrase(str(entry.get(field, ""))):
                return (
                    f'clue {rank}\'s {field} says "{phrase}": write about the subject itself, '
                    "never about examples, questions, players, clues or the answer"
                )
    return None


def summary_problem(
    data: dict[str, Any], ranks: list[int], words: tuple[int, int] = SUMMARY_WORDS
) -> str | None:
    """Why a summary reply can't be used (it's asked again once), or None. Marks must name
    real clues; the summary must be about the right length; the hook short."""
    summary, hook = str(data.get("summary", "")), str(data.get("hook", ""))
    n = word_count(summary)
    low, high = words
    if not low * 0.85 <= n <= high * 1.2:
        return f"the summary has {n} words, not {low}-{high}"
    if not 8 <= len(hook.split()) <= 90:
        return "the hook should be two or three short sentences"
    unknown = sorted({int(m.group(1)) for m in MARK.finditer(summary)} - set(ranks))
    if unknown:
        return f"marks for clues that aren't in the list: {unknown}"
    return None


def clean_summary(summary: str, ranks: list[int]) -> tuple[str, list[int]]:
    """Unknown or repeated marks become plain words; returns the text and the ranks marked."""
    seen: list[int] = []

    def keep(m: re.Match[str]) -> str:
        rank = int(m.group(1))
        if rank in ranks and rank not in seen:
            seen.append(rank)
            return m.group(0)
        return m.group(2)

    return MARK.sub(keep, summary), seen


def source_text(wiki: dict[str, Any] | None, words: int = SOURCE_WORDS) -> str:
    """The Wikipedia lead and sections, cut to ``words``."""
    if not wiki:
        return "(no Wikipedia text: use only widely established facts)"
    parts = [wiki.get("lead", "")] + [
        f"{s.get('heading', '')}: {s.get('text', '')}" for s in wiki.get("sections", [])
    ]
    return " ".join(" ".join(parts).split()[:words])


# --- fun facts ---------------------------------------------------------------------------

FACTS_VERSION = 1
FACT_COUNT = (5, 8)

FACTS_SYSTEM = """You pick fun facts for a study page: surprising, memorable facts that \
teach something real about the topic and show why it matters. Every fact must rest on a \
sentence of the source text, which you quote exactly."""

FACTS = """Topic: {name} (category: {category})

Give {low}-{high} facts. For each:
- "fact": one or two sentences (at most 40 words), vivid and accurate, in your own words.
- "source_sentence": the sentence of the source text below that the fact rests on, copied \
exactly (word for word).
Prefer facts that surprise, connect to something familiar, or explain why {name} matters; \
avoid dry dates and lists.

Source (Wikipedia, CC BY-SA):
{source}"""

FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source_sentence": {"type": "string"}},
                "required": ["fact", "source_sentence"],
            },
        }
    },
    "required": ["facts"],
}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def grounded(facts: list[dict[str, Any]], source: str) -> list[dict[str, str]]:
    """Facts whose quoted sentence really is in the source (ignoring case, punctuation and
    spacing), at most 45 words each."""
    haystack = _squash(source)
    out = []
    for item in facts:
        fact = str(item.get("fact", "")).strip()
        quote = str(item.get("source_sentence", "")).strip()
        quoted = len(quote.split()) >= 5 and _squash(quote) in haystack
        if fact and quoted and len(fact.split()) <= 45:
            out.append({"fact": fact, "source_sentence": quote})
    return out


def facts_problem(data: dict[str, Any], source: str) -> str | None:
    """Too few facts survive the grounding check: ask again once."""
    kept = grounded(data.get("facts", []), source)
    if len(kept) < FACT_COUNT[0] - 1:
        return (
            f"only {len(kept)} facts quote a sentence that is actually in the source; copy each "
            "source_sentence exactly from the source text"
        )
    return None
