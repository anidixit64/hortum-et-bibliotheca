"""Stage 5: split every question into clues.

A clue is usually a sentence; very long sentences are split again at semicolons. Each
clue records its exact span in the question (characters and words), where it falls
(0 = lead-in, 1 = end), whether it comes before the power mark "(*)", and its kind:

* ``clue``: something a player could buzz on;
* ``giveaway``: the whole sentence holding "For 10 points, name this..." and anything after
  it. A question with no giveaway phrase gives its last sentence away. Only a one-sentence
  question keeps the part before the phrase as a clue, so it still has one;
* ``note``: moderator or player notes ("NOTE TO MODERATOR: ...").

The splitter knows quiz bowl text: abbreviations ("Dr.", "St.", "No. 9") and initials
("T. H. Morgan") don't end sentences, and the power mark is removed before splitting, so
"Dr. (*) Bledsoe" stays one sentence.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

Kind = Literal["clue", "giveaway", "note"]

SCHEMA = """
DROP TABLE IF EXISTS clues;
DROP TABLE IF EXISTS question_layout;
CREATE TABLE question_layout (
    tossup_id TEXT PRIMARY KEY REFERENCES tossups(id),
    clean_text TEXT NOT NULL,      -- question text without the power mark
    power_char INTEGER,            -- index in clean_text where (*) was; NULL if none
    power_word INTEGER,            -- index of the first word after (*); NULL if none
    n_words INTEGER NOT NULL,
    n_clues INTEGER NOT NULL
);
CREATE TABLE clues (
    id INTEGER PRIMARY KEY,
    tossup_id TEXT NOT NULL REFERENCES tossups(id),
    topic_id TEXT REFERENCES topics(id),
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    word_start INTEGER NOT NULL,
    word_end INTEGER NOT NULL,     -- exclusive
    position REAL NOT NULL,        -- char_start / len(clean_text)
    in_power INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- clue | giveaway | note
    key_terms TEXT NOT NULL        -- JSON list
);
CREATE INDEX clues_tossup ON clues(tossup_id);
CREATE INDEX clues_topic ON clues(topic_id);
"""

_POWER = re.compile(r"\s*\(\*\)\s*")
_SPACES = re.compile(r"\s+")
# A sentence may end at . ! ? possibly followed by closing quotes or brackets.
_END = re.compile(r"[.!?][\"”’')\]]*(?=\s)")
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "mt", "ft", "jr", "sr", "vs", "no", "nos", "vol", "gen",
    "col", "lt", "capt", "sgt", "rev", "prof", "gov", "sen", "rep", "pres", "adm", "ca",
    "fl", "op", "ave", "approx", "fig", "cf", "al", "inc", "co", "corp", "ltd", "bros",
    "dept", "univ", "mme", "mlle", "messrs", "hon", "esp", "viz", "pp", "ch", "sec", "ed",
    "eds", "trans", "e.g", "i.e", "u.s", "u.k", "a.k.a", "b.c", "a.d", "b.c.e", "c.e",
}  # fmt: skip
# Words that start a new sentence even after a single capital letter ("vitamin K. This...").
_STARTERS = {
    "this", "these", "that", "those", "the", "a", "an", "in", "for", "ftp", "after",
    "before", "one", "another", "its", "his", "her", "their", "he", "she", "it", "they",
    "when", "while", "during", "name", "identify", "give", "some", "many", "according",
    "although", "like", "unlike", "with", "at", "on", "by", "from", "to", "as", "despite",
    "members", "what", "which", "who", "if", "once", "later", "earlier", "two", "three",
}  # fmt: skip
_GIVEAWAY = re.compile(r"\b(?:for\s+(?:\d+|ten|fifteen|twenty|the)\s+(?:points?|pts)|ftp)\b", re.I)
_NOTE = re.compile(
    r"^(?:note\s+to\s+(?:the\s+)?(?:moderators?|players|readers?)|moderator(?:'s)?\s+note|"
    r"(?:descriptive\s+answers?|description)\s+acceptable|pronunciation\s+guide|"
    r"(?:two|three|four|both|all)\s+(?:answers|parts)\s+(?:are\s+)?required|"
    r"specific\s+(?:term|answer)\s+required)",
    re.I,
)
_INITIALS = re.compile(r"^(?:[a-z]\.)+[a-z]$")  # "h.p", "w.e.b"
_LONG_SENTENCE_WORDS = 40

# Key terms: capitalized runs (allowing "of", "de", "van"...), quoted phrases, long numbers.
_CAPITALIZED = re.compile(
    r"(?<![\w'’])(?:[A-Z][\w'’\-]*\.?)"
    r"(?:\s+(?:(?:of|the|de|la|le|du|des|von|van|der|den|y|al|bin|ibn|di|da|and)\s+)?"
    r"[A-Z][\w'’\-]*\.?)*"
)
_QUOTED = re.compile(r"[\"“]([^\"”]{3,80})[\"”]")
_NUMBER = re.compile(r"\b\d[\d,]{2,}\b")
_NOT_TERMS = _STARTERS | {"for", "10", "points", "name", "i", "ii", "iii", "x", "s"}


@dataclass
class Clue:
    text: str
    char_start: int
    char_end: int
    word_start: int
    word_end: int
    position: float
    in_power: bool
    kind: Kind
    key_terms: list[str] = field(default_factory=list)


@dataclass
class Layout:
    clean_text: str
    power_char: int | None
    power_word: int | None
    clues: list[Clue]

    @property
    def n_words(self) -> int:
        return len(self.clean_text.split()) if self.clean_text else 0


def clean_question(text: str) -> tuple[str, int | None]:
    """Collapses whitespace and removes the power mark, returning where it was."""
    text = _SPACES.sub(" ", text).strip()
    match = _POWER.search(text)
    if not match:
        return text, None
    before = text[: match.start()].rstrip()
    after = text[match.end() :].lstrip()
    joined = f"{before} {after}" if before and after else before + after
    power_char = len(before) + (1 if before and after else 0)
    return _POWER.sub(" ", joined).strip(), power_char


def _inside_quote(text: str, start: int, end: int) -> bool:
    """Whether an opened quotation is still open just before ``end``."""
    span = text[start : end - 1]
    return span.count('"') % 2 == 1 or span.count("“") > span.count("”")


def _is_boundary(text: str, end: int, sentence_start: int = 0) -> bool:
    """Whether the punctuation ending at ``end`` really ends a sentence."""
    tail = text[end:].lstrip()
    if not tail:
        return True
    next_word = re.match(r"[\"“'(\[]*([\w’']+)", tail)
    following = next_word.group(1).lower() if next_word else ""
    if not (tail[0].isupper() or tail[0].isdigit() or tail[0] in "\"“'(["):
        return False
    stop = text.rfind(" ", 0, end) + 1
    token = text[stop:end].rstrip(".!?\"”’')]").lower()
    if text[end - 1] in "!?" and _inside_quote(text, sentence_start, end):
        return False  # 'sings "Ah! Si tu savais!"' goes on
    if text[end - 1] in "!?" or text[end - 1] in "\"”’')]":
        return True
    if token in _ABBREVIATIONS:
        return False
    if (len(token) == 1 and token.isalpha()) or _INITIALS.match(token) or token.isdigit():
        # an initial ("T. H."), run-together initials ("T.S."), or a number ("No. 3."),
        # unless a new sentence clearly starts
        return following in _STARTERS
    return True


def _sentences(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for match in _END.finditer(text):
        end = match.end()
        if _is_boundary(text, end, start):
            yield start, end
            start = end + 1  # skip the single space
    if start < len(text):
        yield start, len(text)


def _split_long(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    """Splits a very long sentence at top-level semicolons."""
    if len(text[start:end].split()) <= _LONG_SENTENCE_WORDS:
        yield start, end
        return
    cursor = start
    for match in re.finditer(r";\s", text[start:end]):
        cut = start + match.start() + 1
        if cut - cursor > 20:
            yield cursor, cut
            cursor = start + match.end()
    yield cursor, end


_PRONUNCIATION = re.compile(r"\(\s*[\"“][^)]*\)")


def key_terms(text: str) -> list[str]:
    text = _PRONUNCIATION.sub(" ", text)  # ("STUR-tuh-vant") is how to say it, not a term
    terms: list[str] = []
    for match in _QUOTED.finditer(text):
        if text[: match.start()].rstrip().endswith("("):
            continue  # a pronunciation guide: ("STUR-tuh-vant")
        terms.append(match.group(1).strip())
    for match in _CAPITALIZED.finditer(text):
        term = match.group().rstrip(".")
        words = term.split()
        while words and words[0].lower() in _NOT_TERMS:
            words = words[1:]
        if not words or (len(words) == 1 and words[0].lower() in _NOT_TERMS):
            continue
        if len(words) == 1 and match.start() == 0:
            continue  # capitalized only because it starts the clue: "Mutagenesis in..."
        terms.append(" ".join(words))
    terms.extend(match.group() for match in _NUMBER.finditer(text))
    seen: set[str] = set()
    out = []
    for term in terms:
        if len(term) > 1 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def split_question(question_text: str) -> Layout:
    clean, power_char = clean_question(question_text)
    sentences = [(s0, s1, bool(_NOTE.match(clean[s0:s1]))) for s0, s1 in _sentences(clean)]
    body = [i for i, (_, _, note) in enumerate(sentences) if not note]
    giveaway = next((i for i in body if _GIVEAWAY.search(clean[slice(*sentences[i][:2])])), None)
    if giveaway is None and len(body) > 1:
        giveaway = body[-1]
    spans: list[tuple[int, int, Kind]] = []
    for i, (s0, s1, note) in enumerate(sentences):
        if note:
            spans.append((s0, s1, "note"))
        elif giveaway is not None and i > giveaway:
            spans.append((s0, s1, "giveaway"))
        elif i == giveaway:
            hit = _GIVEAWAY.search(clean[s0:s1])
            pre_end = s0 + len(clean[s0:s1][: hit.start()].rstrip(" ,;-–—")) if hit else s0
            if hit and body == [i] and pre_end - s0 > 25:
                # "A 'Battle Royale' scene occurs in, for 10 points, what novel?" as the
                # whole question: the part before the phrase is its only clue.
                spans.extend((a, b, "clue") for a, b in _split_long(clean, s0, pre_end))
                spans.append((s0 + hit.start(), s1, "giveaway"))
            else:
                spans.append((s0, s1, "giveaway"))
        else:
            spans.extend((a, b, "clue") for a, b in _split_long(clean, s0, s1))

    power_word = clean.count(" ", 0, power_char) if power_char is not None else None
    length = max(len(clean), 1)
    clues = []
    for a, b, kind in spans:
        text = clean[a:b]
        if not text.strip():
            continue
        clues.append(
            Clue(
                text=text,
                char_start=a,
                char_end=b,
                word_start=clean.count(" ", 0, a),
                word_end=clean.count(" ", 0, b) + 1,
                position=round(a / length, 4),
                in_power=power_char is not None and a < power_char,
                kind=kind,
                key_terms=key_terms(text) if kind == "clue" else [],
            )
        )
    return Layout(clean, power_char, power_word, clues)


_BATCH = 5_000


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "tossups", "ingest")
    has_topics = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tossup_topics'"
    ).fetchone()
    db.recreate(conn, SCHEMA)
    total = conn.execute("SELECT COUNT(*) FROM tossups").fetchone()[0]
    reporter.begin("Splitting questions into clues", total)

    layouts: list[tuple[object, ...]] = []
    clue_rows: list[tuple[object, ...]] = []
    n_clues = n_power = 0
    rows = conn.execute(
        "SELECT t.id, t.question_text, tt.topic_id FROM tossups t "
        "LEFT JOIN tossup_topics tt ON tt.tossup_id = t.id ORDER BY t.id"
        if has_topics
        else "SELECT id, question_text, NULL FROM tossups ORDER BY id"
    )

    def flush() -> None:
        conn.executemany("INSERT INTO question_layout VALUES (?, ?, ?, ?, ?, ?)", layouts)
        conn.executemany(
            "INSERT INTO clues (tossup_id, topic_id, ordinal, text, char_start, char_end, "
            "word_start, word_end, position, in_power, kind, key_terms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            clue_rows,
        )
        reporter.advance(len(layouts))
        layouts.clear()
        clue_rows.clear()

    for tossup_id, question_text, topic_id in rows:
        layout = split_question(question_text)
        layouts.append(
            (tossup_id, layout.clean_text, layout.power_char, layout.power_word,
             layout.n_words, len(layout.clues))
        )  # fmt: skip
        n_power += layout.power_char is not None
        for ordinal, clue in enumerate(layout.clues):
            clue_rows.append(
                (tossup_id, topic_id, ordinal, clue.text, clue.char_start, clue.char_end,
                 clue.word_start, clue.word_end, clue.position, int(clue.in_power),
                 clue.kind, json.dumps(clue.key_terms, ensure_ascii=False))
            )  # fmt: skip
            n_clues += 1
        if len(layouts) >= _BATCH:
            flush()
            reporter.stat("Clues so far", f"{n_clues:,}")
    flush()
    conn.commit()

    kinds = dict(conn.execute("SELECT kind, COUNT(*) FROM clues GROUP BY kind"))
    reporter.stat("Clues / giveaways / notes", " / ".join(
        f"{kinds.get(k, 0):,}" for k in ("clue", "giveaway", "note")
    ))  # fmt: skip
    reporter.stat("Questions with a power mark", f"{n_power:,} of {total:,}")
    conn.close()
