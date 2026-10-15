"""Written sections (Phase 6): clue explanations, and the hook and summary.

Both are written from the topic's *cleaned* clue list (see ``cleanup``), so they run after
it. Clue explanations go to the light tier, five clues per request; the hook and summary
go to the writing tier. The summary marks each clue it mentions as ``[[rank|words]]``;
code checks every mark names a real clue, and the page shows marked words in bold with
the clue's one-line summary on hover and a "See more" link to its explanation.
"""

import re
from typing import Any

EXPLANATIONS_VERSION = 5
SUMMARY_VERSION = 4
BATCH = 5  # clues per explanation request
FIRST_PAGE = 10  # clues the hall shows before "show more"
EXPLANATION_WORDS = (100, 160)
SUMMARY_WORDS = (360, 520)
# What a prompt may carry from the stored article. The full page is what Groq rejected
# for Diocletian (about 16,300 tokens against an 8,000 token free-tier cap).
# Facts quote later sections. The timeline quotes the lead plus the next sections.
# The summary, on the writing models, may see a longer excerpt.
SOURCE_WORDS = 1_500
LEAD_WORDS = 800
SUMMARY_SOURCE_WORDS = 3_000

EXPLAIN_SYSTEM = """You write study notes for quiz bowl players. A clue is a term that \
quiz bowl questions about an answer mention; players learn clues to recognize the answer \
early. You explain each clue so a reader truly understands it: detailed but grounded in \
fundamentals, intuitive rather than jargon-heavy, like a great teacher. \
Accuracy comes first: state a date, number, name, place, quotation or mechanism only if \
the source text gives it or you are certain of it; otherwise describe it in general terms. \
The source can be loosely worded: where your own firm knowledge corrects it, follow your \
knowledge."""

EXPLAIN = """Answer: {name} (category: {category})

For each clue below, write:
- "one_line": one sentence (at most 30 words) whose subject is the clue itself, saying \
what it is and how it ties to {name}. It appears in a hover popup.
- "explanation": {low}-{high} words of plain prose (no headings or lists) in three moves:
  1. What it is, explained from the ground up so it makes intuitive sense (a concrete \
picture, the key fact or mechanism; define any specialist term you use).
  2. Exactly how it connects to {name}: who, what, when, in one or two concrete facts.
  3. Why it matters: what it shows about {name} or why it is remembered.
  Every sentence must carry substance; don't repeat what another clue's explanation covers.

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

Wikipedia lead (CC BY-SA), the article's summary. Use it for names, dates and numbers, \
and add only facts you are sure of:
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

SUMMARY_SYSTEM = """You write the opening essay of a study page about one quiz bowl answer, \
like the first room of a museum exhibit. Your tone is narrative and conversational — you're \
a knowledgeable friend walking someone through a topic they're curious about, not a \
textbook. Use vivid language, tell the story, make connections, and let your enthusiasm \
show. Name specialist terms correctly but explain them in passing, the way a good podcast \
host would. Go beyond a restatement of the Wikipedia excerpt: add descriptions and \
details you can verify. Accuracy comes first: never invent quotations, dates or numbers."""

SUMMARY = """Answer: {name} (category: {category})

Write:
- "hook": two or three punchy sentences that pull a reader in — a striking image, a \
surprising fact, an irresistible tension. Not a dry summary. No questions to the reader.
- "summary": {low}-{high} words telling the story of {name}. Make it gripping and \
explanatory: a narrative the reader feels, with concrete detail they can learn from. \
Add verifiable descriptions beyond the Wikipedia excerpt when you are sure of them. \
Do not retell the excerpt sentence by sentence, and do not pad.

Mark a clue only when it fits this story seamlessly. Leave the others out. Mark each \
mention exactly as [[RANK|the words you write]], e.g. [[3|the Battle Royal]]: RANK is the \
clue's number below, and the words are what the reader sees in bold. Mark a clue only \
once, and only where the text is really about it.

Clues (rank: label — what it is). Use only the ones that belong:
{clues}

Wikipedia excerpt (CC BY-SA). Use it for names, dates and numbers, then add verifiable \
detail you are sure of:
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


_NO_SOURCE = "(no Wikipedia text: use only widely established facts)"


def _words(text: str) -> list[str]:
    return str(text).split()


def lead_text(wiki: dict[str, Any] | None, words: int = LEAD_WORDS) -> str:
    """The Wikipedia lead, for the summary, the feature and clue explanations."""
    if not wiki:
        return _NO_SOURCE
    lead = " ".join(_words(wiki.get("lead", ""))[:words])
    return lead or source_text(wiki, words)


def source_text(wiki: dict[str, Any] | None, words: int = SOURCE_WORDS) -> str:
    """The lead, then the next sections, stopping at ``words``. Facts and the timeline
    quote this, so it has to be text that is actually in the article."""
    if not wiki:
        return _NO_SOURCE
    kept: list[str] = []
    used = 0
    lead = _words(wiki.get("lead", ""))
    if lead and used < words:
        take = lead[: words - used]
        kept.append(" ".join(take))
        used += len(take)
    for section in wiki.get("sections", []):
        if used >= words:
            break
        heading = str(section.get("heading", "")).strip()
        piece = ([f"{heading}:"] if heading else []) + _words(section.get("text", ""))
        if not piece:
            continue
        take = piece[: words - used]
        kept.append(" ".join(take))
        used += len(take)
    return " ".join(kept) if kept else _NO_SOURCE


def later_text(wiki: dict[str, Any] | None, words: int = SOURCE_WORDS) -> str:
    """Sections after the lead, so fun facts are not the opening the summary already told.
    A lead-only article falls back to the lead, which is the only text there is."""
    if not wiki:
        return _NO_SOURCE
    kept: list[str] = []
    used = 0
    for section in wiki.get("sections", []):
        if used >= words:
            break
        heading = str(section.get("heading", "")).strip()
        piece = ([f"{heading}:"] if heading else []) + _words(section.get("text", ""))
        if not piece:
            continue
        take = piece[: words - used]
        kept.append(" ".join(take))
        used += len(take)
    if kept:
        return " ".join(kept)
    return lead_text(wiki, words)


# --- fun facts ---------------------------------------------------------------------------

FACTS_VERSION = 3
FACT_COUNT = 4

FACTS_SYSTEM = """You pick fun facts for a study page: details a person could bring up in \
conversation and enjoy telling. Every fact must rest on a sentence of the source text, \
which you quote exactly. Skip anything that only restates the lead."""

FACTS = """Topic: {name} (category: {category})

Give exactly 4 facts. For each:
- "fact": one or two sentences (at most 40 words) someone could say out loud. Vivid, \
accurate, and entertaining.
- "source_sentence": the sentence of the source text below that the fact rests on, copied \
exactly (word for word).
The source is later in the Wikipedia article, past the lead. Pick details that would not \
make the main summary: odd turns, objects, places, consequences. Skip the famous outline \
and dry dates that only mark it.

Later sections of the Wikipedia article (CC BY-SA). Copy each source_sentence from this \
text word for word:
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
    if len(kept) < FACT_COUNT:
        return (
            f"only {len(kept)} facts quote a sentence that is actually in the source; copy each "
            "source_sentence exactly from the source text"
        )
    return None
