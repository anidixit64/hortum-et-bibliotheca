"""Parses quiz bowl answer lines into structured answers.

An answer line looks like::

    Leo <b><u>Tolstoy</u></b> [or Lev Nikolayevich <b><u>Tolstoy</u></b>; prompt on "Leo"]

The text before the first bracket is the main answer; bracketed groups hold directives
("or", "accept", "prompt on", "do not accept") with optional conditions ("before
'fire' is read"). Underlined text marks the part a player must say.

The parser never raises on odd input. Instead it lowers ``confidence`` and records why
in ``issues``, so low-confidence lines can be reviewed by hand.
"""

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal

PARSER_VERSION = "1"

Directive = Literal["accept", "prompt", "reject"]

_FORMAT_TAGS = {"b", "strong", "u", "i", "em", "span", "sup", "sub", "a", "p", "br", "font", "s"}
_PSEUDO_TAG = re.compile(
    r"<(?!/?(?:b|strong|u|i|em|span|sup|sub|a|p|br|font|s)\b)[^<>]{1,40}>", re.I
)
_TRAILING_JUNK = re.compile(r"(?:\s*(?:\(\d{1,2}\)|\[[A-Z]{1,4}\]))+\s*$")

_REJECT = re.compile(
    r"^(?:but\s+)?(?:do\s+not|don[’']t|not|never)\s+(?:accept|take|prompt)"
    r"(?:\s+or\s+(?:prompt|accept))?(?:\s+on)?\b|^reject(?:ed)?\b|^no\b",
    re.I,
)
_PROMPT = re.compile(r"^(?:also\s+|and\s+)?(?:anti-?\s?prompt|prompt)(?:\s+on)?\b", re.I)
_ACCEPT = re.compile(
    r"^(?:also\s+|and\s+)?(?:accept(?:able)?(?:\s+either)?|or|either|alternate(?:ly)?:?)\b", re.I
)
_DIRECTIVE_WORDS = re.compile(
    r"\b(?:accept|prompt|reject|do\s+not|don[’']t|before|until|anti-?prompt)\b", re.I
)
_CLAUSE_SPLIT = re.compile(
    r",\s*(?=(?:and\s+|also\s+|but\s+)?(?:or|accept|prompt|anti-?prompt|do\s+not|don[’']t|reject)\b)"
    r"|\s+(?:and|but)\s+(?=(?:prompt|accept|do\s+not|don[’']t|reject)\b)",
    re.I,
)
_CONDITION = re.compile(
    r"\s*[,(]?\s*\b(?:before|until|after|if|once|when|only\s+(?:before|after)|by\s+asking)\b.*$",
    re.I,
)
_CONDITION_ONLY = re.compile(r"^(?:before|until|after|once|when)\b", re.I)
# "word forms like combusting", "descriptions of 'banning alcohol'": keep what follows.
_GENERIC_LEAD = re.compile(
    r"^(?:(?:other\s+|any\s+)?(?:more\s+specific\s+)?(?:word\s+forms?|answers?|descriptions?|"
    r"equivalents?|synonyms?|anything|phrases?|terms?)(?:\s+(?:like|such\s+as|of|mentioning|"
    r"indicating|involving|including)|,?\s+e\.g\.,?)|e\.g\.,?)\s+",
    re.I,
)
_GENERIC = re.compile(
    r"\b(?:word\s+forms?|equivalents?|synonyms?|similar|more\s+specific|less\s+specific|"
    r"descriptions?|answers?\s+(?:like|that|indicating|mentioning|involving)|anything|"
    r"any\s+(?:answer|other)|partial|clear[- ]knowledge|other\s+(?:answers|names|forms)|"
    r"specific\s+examples?|indicating|equivalent|underlined|required)\b",
    re.I,
)
_QUOTES = "“”\"‘’'«»`"
_EDGE_PUNCT = " \t\n.,;:" + _QUOTES


@dataclass
class Alternate:
    text: str
    condition: str | None = None

    def as_dict(self) -> dict[str, str]:
        out = {"text": self.text}
        if self.condition:
            out["condition"] = self.condition
        return out


@dataclass
class ParsedAnswer:
    main: str
    required: list[str] = field(default_factory=list)
    accept: list[Alternate] = field(default_factory=list)
    prompt: list[Alternate] = field(default_factory=list)
    reject: list[Alternate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0


def line_key(answer_html: str) -> str:
    """Identifies an answer line, so one hand fix covers every identical copy."""
    return hashlib.sha1(" ".join(answer_html.split()).encode()).hexdigest()[:16]


# --- HTML to text with a "marked" (underlined/bold) mask --------------------------------


class _Flattener(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chars: list[str] = []
        self.under: list[bool] = []
        self.bold: list[bool] = []
        self._u = 0
        self._b = 0
        self._after_italic = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "u":
            self._u += 1
        elif tag in ("b", "strong"):
            self._b += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "u":
            self._u = max(0, self._u - 1)
        elif tag in ("b", "strong"):
            self._b = max(0, self._b - 1)
        elif tag in ("i", "em"):
            self._after_italic = True

    def handle_data(self, data: str) -> None:
        # "<i>Republic</i>Book X": a title closing straight into a word needs a space.
        if self._after_italic and data[:1].isalnum() and self.chars and self.chars[-1].isalnum():
            data = " " + data
        self._after_italic = False
        self.chars.extend(data)
        self.under.extend([self._u > 0] * len(data))
        self.bold.extend([self._b > 0] * len(data))


@dataclass
class _Marked:
    text: str
    mask: list[bool]

    def spans(self, start: int, end: int) -> list[str]:
        """Contiguous marked substrings in [start, end), joined across whitespace-only gaps."""
        out: list[str] = []
        current: list[str] = []
        gap: list[str] = []
        for i in range(start, end):
            ch = self.text[i]
            if self.mask[i]:
                if gap and current:
                    current.extend(gap)
                gap = []
                current.append(ch)
            elif ch.isspace() and current:
                gap.append(ch)
            else:
                if current:
                    out.append("".join(current))
                current, gap = [], []
        if current:
            out.append("".join(current))
        return [s.strip(_EDGE_PUNCT) for s in out if len(s.strip(_EDGE_PUNCT)) >= 2]

    def word_spans(self, start: int, end: int) -> list[str]:
        """Like ``spans`` but only marked runs that are whole words ("fir" in "fire" is not)."""
        out = []
        i = start
        while i < end:
            if not self.mask[i]:
                i += 1
                continue
            j = i
            while j < end and (
                self.mask[j] or (self.text[j].isspace() and j + 1 < end and self.mask[j + 1])
            ):
                j += 1
            before = self.text[i - 1] if i > 0 else " "
            after = self.text[j] if j < len(self.text) else " "
            span = self.text[i:j].strip(_EDGE_PUNCT)
            if not before.isalnum() and not after.isalnum() and len(span) >= 2:
                out.append(span)
            i = j
        return out


def _flatten(answer_html: str) -> _Marked:
    html = _PSEUDO_TAG.sub(" ", answer_html)
    parser = _Flattener()
    parser.feed(html)
    parser.close()
    text = "".join(parser.chars).replace("\xa0", " ")
    mask = parser.under if any(parser.under) else parser.bold
    # Drop trailing author tags / numbering, keeping the mask aligned.
    match = _TRAILING_JUNK.search(text)
    if match:
        text, mask = text[: match.start()], mask[: match.start()]
    return _Marked(text, list(mask))


# --- Bracket structure ------------------------------------------------------------------

_OPEN = {"[": "]", "(": ")"}


@dataclass
class _Segment:
    kind: Literal["text", "group"]
    start: int  # content start (inside the brackets for groups)
    end: int
    bracket: str = ""


def _segments(text: str) -> tuple[list[_Segment], bool]:
    """Splits text into top-level plain-text runs and bracketed groups."""
    segments: list[_Segment] = []
    stack: list[str] = []
    seg_start = 0
    group_open = 0
    balanced = True
    for i, ch in enumerate(text):
        if ch in _OPEN:
            if not stack:
                if i > seg_start:
                    segments.append(_Segment("text", seg_start, i))
                group_open = i
            stack.append(_OPEN[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                segments.append(_Segment("group", group_open + 1, i, text[group_open]))
                seg_start = i + 1
        elif ch in ")]" and not stack:
            balanced = False
    if stack:
        balanced = False
        segments.append(_Segment("group", group_open + 1, len(text), text[group_open]))
    elif seg_start < len(text):
        segments.append(_Segment("text", seg_start, len(text)))
    return segments, balanced


def _split_top(text: str, sep: str) -> list[tuple[int, int]]:
    """Splits on a separator character outside nested brackets; returns (start, end) pairs."""
    parts: list[tuple[int, int]] = []
    depth, start = 0, 0
    for i, ch in enumerate(text):
        if ch in "[(":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            parts.append((start, i))
            start = i + 1
    parts.append((start, len(text)))
    return parts


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text)  # trailing parenthetical note
    abbreviation = text.rstrip().endswith(".") and text.count(".") > 1  # "G.I."
    text = text.strip(_EDGE_PUNCT).strip()
    return text + "." if abbreviation and text else text


_JUNK = re.compile(
    r"^(?:category\s*:|copyright|©|the\s+round|end\s+of|note\b[^:]{0,20}:|moderator)", re.I
)


def _is_optional(content: str) -> bool:
    """Short non-directive bracket text inside a name: middle names, nicknames."""
    words = content.split()
    return (
        0 < len(words) <= 4
        and not _DIRECTIVE_WORDS.search(content)
        and not re.match(r"\s*or\b", content, re.I)
        and not any(ch.isdigit() for ch in content)
    )


def _directive(clause: str) -> tuple[Directive | None, int]:
    for kind, pattern in (("reject", _REJECT), ("prompt", _PROMPT), ("accept", _ACCEPT)):
        match = pattern.match(clause)
        if match:
            return kind, match.end()  # type: ignore[return-value]
    return None, 0


def _items(marked: _Marked, start: int, end: int) -> list[tuple[str, str | None, int, int]]:
    """Splits a clause body into alternates: (text, condition, start, end)."""
    body = marked.text[start:end]
    # Split on " or " and on commas, but only split a comma when both sides carry marked
    # text; otherwise "accept X-ray, neutron or electron diffraction" falls apart.
    pieces: list[tuple[int, int]] = []
    for s0, e0 in _split_top(body, ";"):
        cursor = s0
        for match in re.finditer(r"\s+or\s+|,\s+", body[s0:e0]):
            cut_start, cut_end = s0 + match.start(), s0 + match.end()
            if match.group().strip() == ",":
                left = any(marked.mask[start + cursor : start + cut_start])
                right = any(marked.mask[start + cut_end : start + e0])
                if not (left and right):
                    continue
            pieces.append((cursor, cut_start))
            cursor = cut_end
        pieces.append((cursor, e0))

    items = []
    for p0, p1 in pieces:
        raw = body[p0:p1]
        condition = None
        cond = _CONDITION.search(raw)
        if cond and cond.start() > 0:
            condition = _clean(raw[cond.start() :]) or None
            p1 = p0 + cond.start()
            raw = body[p0:p1]
        text = _clean(raw)
        lead = _GENERIC_LEAD.match(text)
        if lead:
            text = _clean(text[lead.end() :])
        if text and not _CONDITION_ONLY.match(text):
            items.append((text, condition, start + p0, start + p1))
    # "fire or flame before 'fire' is read": a condition at the end covers the whole clause.
    if items and items[-1][1]:
        shared = items[-1][1]
        items = [(t, c or shared, a, b) for t, c, a, b in items]
    return items


def parse_answer(answer_html: str) -> ParsedAnswer:
    marked = _flatten(answer_html)
    text = marked.text
    segments, balanced = _segments(text)
    issues: list[str] = []
    if not balanced:
        issues.append("unbalanced_brackets")

    accept: list[Alternate] = []
    prompt: list[Alternate] = []
    reject: list[Alternate] = []
    notes: list[str] = []
    required: list[str] = []

    # Leading optional words: "(Sultanate of) Oman".
    prefix = ""
    if len(segments) >= 2 and segments[0].kind == "group" and segments[0].bracket == "(":
        prefix = _clean(text[segments[0].start : segments[0].end])
        segments = segments[1:]

    segments = [s for s in segments if s.kind == "group" or text[s.start : s.end].strip()]

    # The main answer is the first text run, continued across short optional groups:
    # "Rembrandt (Harmenszoon) van Rijn", "Nikolai [Vasilievich] Gogol".
    main_segs: list[_Segment] = []
    optional: list[_Segment] = []
    index = 0
    if segments and segments[0].kind == "text":
        main_segs.append(segments[0])
        index = 1
        while (
            index + 1 < len(segments)
            and segments[index].kind == "group"
            and _is_optional(text[segments[index].start : segments[index].end])
            and segments[index + 1].kind == "text"
        ):
            optional.append(segments[index])
            main_segs.append(segments[index + 1])
            index += 2
    rest = segments[index:]
    groups = [seg for seg in rest if seg.kind == "group"]
    trailing_text = []
    for seg in rest:
        if seg.kind != "text":
            continue
        chunk = _clean(text[seg.start : seg.end])
        if chunk in ("", "and", "&"):
            continue
        if _JUNK.match(chunk) or (chunk.isupper() and len(chunk.split()) >= 3):
            notes.append(chunk)  # "Copyright 2016 ...", "THE ROUND IS NOW OVER", "Category: ..."
        else:
            trailing_text.append(seg)

    main = _clean(" ".join(text[seg.start : seg.end] for seg in main_segs))
    if optional:
        pieces = sorted(main_segs + optional, key=lambda seg: seg.start)
        full = _clean(" ".join(text[seg.start : seg.end] for seg in pieces))
        accept.append(Alternate(full))
    if trailing_text:
        issues.append("multi_part")
        main = _clean(" ".join(text[seg.start : seg.end] for seg in main_segs + trailing_text))

    main_marked = any(any(marked.mask[seg.start : seg.end]) for seg in main_segs)
    for seg in main_segs:
        required.extend(marked.word_spans(seg.start, seg.end))
    if main_segs and not main_marked:
        issues.append("no_marked_text")

    # "retinoic acid or RA": an "or" in the main line introduces alternates.
    if main_segs and not trailing_text:
        alt_match = re.search(r"\s+or\s+", main)
        if alt_match and main_marked:
            first, others = main[: alt_match.start()], main[alt_match.end() :]
            if first and others:
                main = _clean(first)
                accept.extend(
                    Alternate(_clean(r)) for r in re.split(r"\s+or\s+", others) if _clean(r)
                )

    if prefix and main:
        accept.append(Alternate(f"{prefix} {main}"))

    unrecognized = 0
    for group in groups:
        content = text[group.start : group.end]
        clauses: list[tuple[int, int]] = []
        for c0, c1 in _split_top(content, ";"):
            sub = content[c0:c1]
            cursor = 0
            for match in _CLAUSE_SPLIT.finditer(sub):
                clauses.append((c0 + cursor, c0 + match.start()))
                cursor = match.end()
            clauses.append((c0 + cursor, c1))

        is_directive_group = (
            bool(_DIRECTIVE_WORDS.search(content))
            or bool(re.match(r"\s*or\b", content, re.I))
            or (group.bracket == "[" and any(marked.mask[group.start : group.end]))
        )
        if not is_directive_group:
            if note := _clean(content):
                notes.append(note)
            continue

        current: Directive | None = None
        for index, (c0, c1) in enumerate(clauses):
            raw = content[c0:c1]
            lead = len(raw) - len(raw.lstrip())
            clause = raw.strip()
            if not clause:
                continue
            kind, consumed = _directive(clause)
            body_start = group.start + c0 + lead + consumed
            body_end = group.start + c1
            if kind is None:
                if index == 0 and group.bracket == "[":
                    kind = "accept"  # "[Treaty of Westphalia; ...]" starts with a bare alternate
                elif current is not None:
                    kind = current
                elif len(clause.split()) > 12 or not any(marked.mask[body_start:body_end]):
                    notes.append(_clean(clause))
                    continue
                else:
                    kind = "accept"
                    unrecognized += 1
            current = kind
            for item_text, condition, i0, i1 in _items(marked, body_start, body_end):
                if _GENERIC.search(item_text) and not any(marked.mask[i0:i1]):
                    notes.append(f"{kind}: {item_text}")
                    continue
                alt = Alternate(item_text, condition)
                if kind == "accept":
                    accept.append(alt)
                    required.extend(s for s in marked.word_spans(i0, i1) if s != item_text)
                elif kind == "prompt":
                    prompt.append(alt)
                else:
                    reject.append(alt)

    if not main:
        issues.append("empty_main")
    if _DIRECTIVE_WORDS.search(main):
        issues.append("directive_in_main")
    if len(main.split()) > 10:
        issues.append("long_main")
    if "/" in main:
        issues.append("slash_in_main")
    if unrecognized:
        issues.append("unrecognized_clause")

    penalties = {
        "empty_main": 1.0,
        "directive_in_main": 0.5,
        "multi_part": 0.4,
        "long_main": 0.15,
        "unbalanced_brackets": 0.3,
        "slash_in_main": 0.2,
        "no_marked_text": 0.15,
        "unrecognized_clause": 0.1,
    }
    confidence = max(0.0, 1.0 - sum(penalties[i] for i in issues))

    return ParsedAnswer(
        main=main,
        required=_dedupe([r for r in required if r.lower() != main.lower()]),
        accept=_dedupe_alts(accept, main),
        prompt=_dedupe_alts(prompt, main),
        reject=_dedupe_alts(reject, main),
        notes=notes,
        issues=issues,
        confidence=round(confidence, 2),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _dedupe_alts(values: list[Alternate], main: str) -> list[Alternate]:
    seen = {main.lower()}
    out = []
    for alt in values:
        key = alt.text.lower()
        if key not in seen:
            seen.add(key)
            out.append(alt)
    return out
