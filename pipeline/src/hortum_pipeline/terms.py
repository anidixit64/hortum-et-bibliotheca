"""Stage: each topic's clues as terms, ranked by how many of its questions use them.

A clue here is a term a question names: a proper noun or title ("Nelson Miles", "The
Mysterious Affair at Styles"), a quoted term, or a noun phrase ("circumambulation
rituals"). For every clue sentence, and for a giveaway that states a fact, the terms
are taken from the key terms found by the clues stage plus spaCy's noun phrases. spaCy
reads the giveaway without its "for 10 points, name this" frame, so that frame cannot
become a clue. Parsing is cached in data/cache/terms, so re-ranking is quick.

Within a topic, spellings of one clue are merged:
- folded the same way: case, accents, plurals, possessives, a leading article
- titles and middle initials dropped: "General Nelson A. Miles" is "Nelson Miles"
- a shorter form joins a longer clue only as a place or an event: "Cascades" -> "Cascade
  Mountains", "Gaugamela" -> "Battle of Gaugamela". A short name otherwise stays its own
  clue ("Willy" may be another Willy than Willy Wonka); within one sentence, a term inside
  a longer one is dropped ("Saha" in "Saha equation"). Not across a possessive:
  "Burnside" stays apart from "Burnside's Bridge" unless only ever named inside it.
- a longer spelling that only adds lowercase words is the same clue: "Liberty Paints
  factory" -> "Liberty Paints", "innermost womb chamber" -> "womb chamber"
- one spelling apart: "murti" / "murtis", "battle royal" / "battle royale"
- names of the same known topic (Wikidata aliases) are one clue: "Filiki Eteria" and
  "Friendly Society"

Clues are ranked purely by how many questions name them (then sets, then mentions).
Generic words, stand-ins for the answer ("this novel") and the answer's own names are
never clues. For each topic the top ``KEEP`` clues are stored with their spellings,
positions, the clues they share sentences with, and the sentences themselves, so how
they're presented can be tuned later without re-parsing.
"""

import hashlib
import itertools
import json
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any

from hortum_common.text import normalize
from hortum_pipeline import db, labeling, phrases
from hortum_pipeline.clues import giveaway_facts
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.relate import STOPWORDS
from hortum_pipeline.score import difficulty_band, position_hist, trend

SCHEMA = """
DROP TABLE IF EXISTS sentence_clues;
DROP TABLE IF EXISTS topic_clue_sentences;
DROP TABLE IF EXISTS topic_clues;
CREATE TABLE topic_clues (
    id INTEGER PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    rank INTEGER NOT NULL,            -- 1 = named by the most questions
    label TEXT NOT NULL,              -- the clue as questions most often write it
    clue_key TEXT NOT NULL,           -- folded words of its main spelling
    names_topic TEXT,                 -- a known topic this clue is the name of, if any
    n_questions INTEGER NOT NULL,     -- distinct questions naming it, giveaway included
    n_sets INTEGER NOT NULL,
    n_mentions INTEGER NOT NULL,      -- clue sentences naming it
    mean_position REAL NOT NULL,      -- 0 = start of the question, 1 = end
    median_position REAL NOT NULL,
    earliest_position REAL NOT NULL,
    share_in_power REAL NOT NULL,
    share_last_line REAL NOT NULL,    -- share in the last line before the giveaway
    position_hist TEXT NOT NULL,      -- JSON: 10 bins from lead-in to end
    difficulty_hist TEXT NOT NULL,    -- JSON: {unrated, middle_school, high_school, college, open}
    first_year INTEGER,
    last_year INTEGER,
    trend TEXT NOT NULL,              -- rising | steady | fading
    variants TEXT NOT NULL,           -- JSON: {spelling: mentions}
    cooccurs TEXT NOT NULL,            -- JSON: [[clue id, label, shared sentences], ...]
    categories TEXT NOT NULL DEFAULT '{}'  -- JSON: {category: sentence_count}
);
CREATE INDEX topic_clues_topic ON topic_clues(topic_id, rank);
CREATE TABLE topic_clue_sentences (
    topic_clue_id INTEGER NOT NULL REFERENCES topic_clues(id),
    clue_id INTEGER NOT NULL REFERENCES clues(id),
    PRIMARY KEY (topic_clue_id, clue_id)
);
CREATE INDEX topic_clue_sentences_clue ON topic_clue_sentences(clue_id);
CREATE TABLE sentence_clues (            -- each clue sentence's best-ranked clue, for practice
    clue_id INTEGER PRIMARY KEY REFERENCES clues(id),
    topic_clue_id INTEGER NOT NULL REFERENCES topic_clues(id)
);
"""

KEEP = 100  # clues stored per topic
COOCCURS = 8
PARSE_VERSION = "1"
PARSE_PROCESSES = 3  # spaCy worker processes (each holds its own model in memory)
# Leading titles dropped from names when two or more words follow.
_HONORIFIC_TEXT = (
    "general gen colonel col lieutenant lt captain capt major admiral commander sergeant "
    "dr doctor mr mrs ms sir president senator sen governor gov"
)
HONORIFICS = frozenset(_HONORIFIC_TEXT.split())
# A clue plus one of these is the same clue: "Cascades" / "Cascade Mountains".
_GEOGRAPHIC_TEXT = (
    "mountain range river lake island sea bay valley desert peninsula strait gulf "
    "canyon basin plateau fall forest ocean"
)
GEOGRAPHIC_HEADS = frozenset(_GEOGRAPHIC_TEXT.split())
_ARTICLES = frozenset({"the", "a", "an"})
_LINKS = frozenset({"of", "the", "de", "la", "le", "del", "du", "von", "van", "der", "al"})
OWNED_OVERLAP = 0.6  # "Bredt" joins "Bredt's rule" if this share of its mentions are in it
KEEP_LABEL = 0.8  # a completed label must still be named by this share of the sentences
SINGLE_WORD_IDF = 9.0  # a lowercase one-word clue must be this rare across all clues
PHRASE_WORD_IDF = 8.0  # a lowercase phrase needs one word this rare ("circumambulation")
QUOTE_LABEL_WORDS = 8  # a quotation longer than LONG_LABEL_WORDS shows its opening words
LONG_LABEL_WORDS = 10
CAPITALIZED_WORD_IDF = 7.0  # a one-word capitalized clue this common says little ("German")
GENERIC_NAME_IDF = 6.0  # a name made only of words this common is generic ("United States")
# "Battle of X" and the like name an event at X: the same clue as X.
_EVENT_TEXT = "battle siege treaty sack council massacre fall capture conquest burning"
EVENT_HEADS = frozenset(_EVENT_TEXT.split())


def text_key(text: str) -> str:
    return hashlib.sha1(f"{PARSE_VERSION}|{text}".encode()).hexdigest()


class ParseCache:
    """spaCy's output per clue sentence (see ``phrases.serialize``), kept across runs."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS parses (key TEXT PRIMARY KEY, data TEXT)")

    def missing(self, keys: list[str]) -> list[str]:
        have: set[str] = set()
        for start in range(0, len(keys), 900):
            chunk = keys[start : start + 900]
            have.update(
                k
                for (k,) in self.conn.execute(
                    f"SELECT key FROM parses WHERE key IN ({','.join('?' * len(chunk))})", chunk
                )
            )
        return [k for k in keys if k not in have]

    def put(self, rows: Iterable[tuple[str, dict[str, Any]]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO parses VALUES (?, ?)",
            ((k, json.dumps(v, separators=(",", ":"))) for k, v in rows),
        )
        self.conn.commit()

    def get(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for start in range(0, len(keys), 900):
            chunk = keys[start : start + 900]
            for k, data in self.conn.execute(
                f"SELECT key, data FROM parses WHERE key IN ({','.join('?' * len(chunk))})", chunk
            ):
                out[k] = json.loads(data)
        return out


def key_of(form: str) -> tuple[str, ...]:
    """The folded words of a spelling: "General Nelson A. Miles" -> ("nelson", "miles")."""
    tokens = labeling.TOKEN.findall(form)
    # Initials are single letters written with a period ("A." in "Nelson A. Miles"); a
    # lone letter without one is part of the name ("H II").
    initial = {
        i for i, t in enumerate(tokens[:-1]) if len(t) == 1 and t.isalpha() and tokens[i + 1] == "."
    }
    words: list[str] = []
    is_initial: list[bool] = []
    for i, token in enumerate(tokens):
        if not token[:1].isalnum():
            continue
        token = re.sub(r"['’]s$", "", token)
        # Plurals fold only for ordinary words: "chambers" -> "chamber", "Miles" stays.
        folded = labeling.fold(token) if token[:1].islower() else normalize(token)
        for part in folded.split():  # "alpha-beta" -> alpha, beta
            words.append(part)
            is_initial.append(i in initial)
    while words and words[0] in _ARTICLES:
        words, is_initial = words[1:], is_initial[1:]
    if len(words) >= 3 and words[0] in HONORIFICS:
        words, is_initial = words[1:], is_initial[1:]
    if sum(not x for x in is_initial) >= 2:
        words = [w for w, x in zip(words, is_initial, strict=True) if not x]
    return tuple(words)


def contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> int:
    """Where ``shorter`` sits in ``longer`` as consecutive words, or -1."""
    n = len(shorter)
    for i in range(len(longer) - n + 1):
        if longer[i : i + n] == shorter:
            return i
    return -1


@dataclass
class Sentence:
    clue_id: int
    tossup_id: str
    set_id: str
    position: float
    in_power: int
    last_line: int
    difficulty: int
    year: int | None
    text: str
    category: str | None = None
    parse_text: str | None = None  # giveaway: facts only; None means parse ``text``


@dataclass
class Candidate:
    key: tuple[str, ...]
    sentences: set[int] = field(default_factory=set)
    forms: Counter[str] = field(default_factory=Counter)
    names_topic: Counter[str] = field(default_factory=Counter)


_QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
MAX_QUOTE_WORDS = 25  # a quotation up to this long is one clue ("so much owed by so many")
_AUTHOR_PREFIX = re.compile(r"^(?:[A-Z][\w.-]*\s)*[A-Z][\w.-]*['’]s\s+(?=(?:The\s|A\s)?[A-Z])")
_ROLE_PREFIX = re.compile(r"^(?:[a-z][\w-]*\s)+(?=[A-Z])")


def trim(form: str) -> str:
    """Stray words at a term's edges: an author before a title ("Baldwin's The Fire Next
    Time"), a role before a name ("architect al-Sahili"), unbalanced quote marks."""
    form = re.sub(r"\s+", " ", form)  # gaps left by removed pronunciation guides
    form = re.sub(r"\s+and (?:his|her|their) \w+$", "", form)  # "Spartacus and his followers"
    form = _AUTHOR_PREFIX.sub("", form)
    if " of " not in form and " the " not in form:
        form = _ROLE_PREFIX.sub("", form)  # but "sphincter of Oddi" stays whole
    form = re.sub(r"[\s(\[]+$", "", form)  # "Vade-Mecum (" left by a removed guide
    if form.count("(") != form.count(")"):
        form = form.replace("(", "").replace(")", "")
    if (form.count('"') + form.count("“") + form.count("”")) % 2:
        form = form.replace('"', "").replace("“", "").replace("”", "")
    return form.strip()


def _demonym_phrase(form: str, adjectives: set[str]) -> str:
    """ "British forces" is a lowercase phrase that starts with a capitalized adjective."""
    words = form.split()
    if len(words) > 1 and words[0] in adjectives and all(w[:1].islower() for w in words[1:]):
        return words[0].lower() + form[len(words[0]) :]
    return form


def _cut_at_hyphen(form: str, text: str) -> bool:
    """ "fleur-de" out of "fleur-de-lis": the text goes on with a hyphen."""
    at = text.find(form)
    return at >= 0 and text[at + len(form) : at + len(form) + 1] == "-"


def quotations(text: str) -> list[str]:
    return [a or b for a, b in _QUOTED.findall(text)]


def sentence_terms(
    sentence: Sentence, key_terms: list[str], parse: dict[str, Any], freq: phrases.DocFrequency
) -> set[str]:
    """Spellings of the terms one clue sentence names."""
    adjectives = set(parse.get("adj", []))
    quotes = quotations(sentence.text)
    forms = set()
    for term in key_terms:
        bare = term.strip(" ,.;:")
        holder = next((q for q in quotes if bare and bare in q), None)
        if holder is not None:
            # A famous line is one clue, whole: "If Winter comes, can Spring be far
            # behind?", not "If Winter" and "Spring be far behind".
            whole = re.sub(r"\s+", " ", holder).strip(" ,.;:")
            if len(whole) > 2 and len(whole.split()) <= MAX_QUOTE_WORDS:
                forms.add(whole)
            continue
        tidy = labeling.tidy(term)
        if tidy and not (" " not in tidy and tidy in adjectives):  # "Mexican troops"
            forms.add(trim(tidy))
    forms = {f for f in forms if not _cut_at_hyphen(f, sentence.text)}
    forms = {_demonym_phrase(f, adjectives) for f in forms}
    for phrase in phrases.chunk_phrases(parse.get("chunks", []), freq):
        if any(phrase in q or phrase.lower() in q.lower() for q in quotes):
            continue  # a piece of a quotation ("camel" in "very like a camel")
        tidy = labeling.tidy(phrase)
        if tidy and not _cut_at_hyphen(tidy, sentence.text):
            forms.add(trim(tidy))
    for form in list(forms):
        owner = re.match(r"^([A-Z][\w.-]*(?: [A-Z][\w.-]*)*)['’]s [a-z]", form)
        if owner:
            forms.add(owner.group(1))  # "Isabel Bradley's actions" names Isabel Bradley
    forms = {f for f in forms if not labeling.negated(sentence.text, f)}
    return drop_nested({f for f in forms if f})


def drop_nested(forms: set[str]) -> set[str]:
    """Drop a term that's only part of a longer one in the same sentence: "Saha" in "Saha
    equation", "Mexico" in "Robledo Mountains of New Mexico". A possessive owner stays its
    own clue ("Burnside" in "Burnside's Bridge")."""
    loose = {f: tuple(labeling.fold(w) for w in key_of(f)) for f in forms}
    kept = set()
    for form in forms:
        inside = [
            other
            for other in forms
            if len(loose[other]) > len(loose[form])
            and contains(loose[other], loose[form]) >= 0
            and not _possessive_in([other], loose[form])
        ]
        if not inside:
            kept.add(form)
    return kept


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, ...], tuple[str, ...]] = {}

    def find(self, x: tuple[str, ...]) -> tuple[str, ...]:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: tuple[str, ...], b: tuple[str, ...]) -> None:
        self.parent[self.find(a)] = self.find(b)


def _possessive_in(forms: Iterable[str], shorter: tuple[str, ...]) -> bool:
    """Is ``shorter`` (folded words) the possessive part of these spellings ("Burnside's
    Bridge")?"""
    for form in forms:
        tokens = [t for t in labeling.TOKEN.findall(form) if t[:1].isalnum()]
        flat = [labeling.fold(k[0]) if (k := key_of(t)) else "" for t in tokens]
        at = contains(tuple(flat), shorter)
        if at >= 0 and re.search(r"['’]s$", tokens[at + len(shorter) - 1]):
            return True
    return False


def near_spellings(
    keys: list[tuple[str, ...]],
) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Pairs that are one spelling apart: a plural "s" ("murti" / "murtis"), or one letter
    in one word of a longer name ("battle royal" / "battle royale")."""
    present = set(keys)
    for key in keys:
        last = key[-1]
        for plural in (last + "s", last + "es"):
            other = (*key[:-1], plural)
            if other in present:
                yield key, other
        if len(key) < 2:
            continue
        for i, word in enumerate(key):
            if len(word) < 5:
                continue
            for other_word in (word + "e", word[:-1]) if word.endswith("e") else (word + "e",):
                other = (*key[:i], other_word, *key[i + 1 :])
                if other != key and other in present:
                    yield key, other
    # One letter off in one word of a two-plus-word name: "Vincente" / "Vicente de
    # Valverde", "Antony" / "Anthony Hewish".
    by_shape: dict[tuple[int, tuple[str, ...]], list[tuple[str, ...]]] = defaultdict(list)
    for key in keys:
        if len(key) >= 2:
            for i in range(len(key)):
                by_shape[(i, key[:i] + key[i + 1 :])].append(key)
    for (i, _), group in by_shape.items():
        for a, b in itertools.combinations(group, 2):
            if min(len(a[i]), len(b[i])) >= 5 and _one_edit(a[i], b[i]):
                yield a, b
    yield from _one_substitution_pairs(keys)


def _hyphen_joined(
    candidates: dict[tuple[str, ...], Candidate], longer: tuple[str, ...], shorter: tuple[str, ...]
) -> bool:
    """Is the short form glued to another word by a hyphen ("Pseudo-Callisthenes")?"""
    form = candidates[longer].forms.most_common(1)[0][0]
    first = candidates[shorter].forms.most_common(1)[0][0].split()[0]
    return re.search(rf"-\s*{re.escape(first)}", form, re.I) is not None


def _one_substitution_pairs(
    keys: list[tuple[str, ...]],
) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """One-word names one letter apart: "Simurgh" / "Simorgh", "Boand" / "Boann"."""
    buckets: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for key in keys:
        if len(key) == 1 and len(key[0]) >= 5 and key[0].isalpha():
            word = key[0]
            for i in range(len(word)):
                buckets[word[:i] + "*" + word[i + 1 :]].append(key)
    for group in buckets.values():
        yield from itertools.combinations(group, 2)


def _one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def merge(candidates: dict[tuple[str, ...], Candidate]) -> list[list[Candidate]]:
    """Group a topic's candidates that are spellings of one clue."""
    uf = UnionFind()
    by_topic: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for key, cand in candidates.items():
        uf.find(key)
        if cand.names_topic:
            by_topic[cand.names_topic.most_common(1)[0][0]].append(key)
    for keys in by_topic.values():
        for a, b in itertools.combinations(keys, 2):
            if not set(a) & set(b):  # "Filiki Eteria" / "Friendly Society", not two Driffields
                uf.union(a, b)

    # Containment compares every word folded: "Cascades" sits in "Cascade Mountains".
    loose = {key: tuple(labeling.fold(w) for w in key) for key in candidates}
    by_word: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for key in candidates:
        for word in loose[key]:
            by_word[word].add(key)

    def known(key: tuple[str, ...]) -> str | None:
        named = candidates[key].names_topic
        return named.most_common(1)[0][0] if named else None

    def adds_only_description(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
        """Does the longer spelling only add lowercase words ("Liberty Paints factory",
        "innermost womb chamber")? Capitalized ones make another name ("New Mexico")."""
        form = candidates[longer].forms.most_common(1)[0][0]
        extra = [
            t
            for t in labeling.TOKEN.findall(form)
            if t[:1].isalnum() and labeling.fold(normalize(t)) not in loose[shorter]
        ]
        return bool(extra) and all(t[:1].islower() or t.isdigit() for t in extra)

    def anchors(key: tuple[str, ...]) -> bool:
        """Only a name or a phrase can take in its described forms: a lone lowercase word
        ("black", "rituals") would swallow every phrase that uses it."""
        form = candidates[key].forms.most_common(1)[0][0]
        return len(key) > 1 or form[:1].isupper()

    def part_of_other(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
        """Is the short form a different thing inside the longer name: after "of" or "the"
        ("Sacred Band of Thebes", "Pliny the Elder"), or joined by a hyphen
        ("Pseudo-Callisthenes")?"""
        at = contains(loose[longer], loose[shorter])
        if at > 0 and longer[at - 1] in _LINKS:
            # "Battle of Gaugamela" is Gaugamela; "Sacred Band of Thebes" isn't Thebes.
            return not (at == 2 and longer[0] in EVENT_HEADS)
        return _hyphen_joined(candidates, longer, shorter)

    for key in sorted(candidates, key=len):
        holders = set.intersection(*(by_word[w] for w in loose[key])) - {key}
        supersets = [s for s in holders if contains(loose[s], loose[key]) >= 0]
        owned = [s for s in supersets if _possessive_in(candidates[s].forms, loose[key])]
        for s in owned:
            # "Bredt" only ever in "Bredt's rule" is that rule; "Burnside", named on his
            # own elsewhere, isn't "Burnside's Bridge".
            mine = candidates[key].sentences
            if len(mine & candidates[s].sentences) >= OWNED_OVERLAP * len(mine):
                uf.union(key, s)
        supersets = [s for s in supersets if s not in owned]
        described = [s for s in supersets if adds_only_description(s, key)]
        # "Liberty Paints factory" is Liberty Paints; but "Gibbs paradox" and "Gibbs free
        # energy" are two things, so neither joins "Gibbs".
        if anchors(key) and len({loose[s] for s in described}) == 1:
            for s in described:
                uf.union(s, key)
        if known(key):  # "Mexico" isn't "Robledo Mountains of New Mexico"
            supersets = [s for s in supersets if known(s) == known(key)]
        # The shortest containing spellings: "nationalist Ras the Exhorter" holds "Ras the
        # Exhorter", so "Exhorter" has one place to go.
        minimal = [
            s
            for s in supersets
            if not any(o != s and contains(loose[s], loose[o]) >= 0 for o in supersets)
        ]
        if not minimal:
            continue
        families = {tuple(w for w in loose[s] if w not in GEOGRAPHIC_HEADS) for s in minimal}
        # A short form commoner than the full name stands on its own ("Mexico" isn't
        # short for "Robledo Mountains of New Mexico"; "Miles" is for "Nelson Miles").
        if len(families) == 1 and anchors(key) and not any(part_of_other(s, key) for s in minimal):
            place = all(set(loose[s]) - set(loose[key]) <= GEOGRAPHIC_HEADS for s in minimal)
            event = all(
                contains(loose[s], loose[key]) == 2 and loose[s][0] in EVENT_HEADS for s in minimal
            )  # "Issus" / "Battle of Issus"
            # Only a place or an event: "Willy" isn't safely "Willy Wonka" (another Willy
            # may be meant), and a split spelling can be merged later, a wrong merge can't.
            if place or event:
                for s in supersets:
                    uf.union(key, s)
    for a, b in near_spellings(list(candidates)):
        uf.union(a, b)
    # "Antony Hewish and Jocelyn Bell": when either person is a clue, the pair is the two
    # of them ("War and Peace", with neither side a clue, stays a title).
    for key in list(candidates):
        if "and" not in key or not 0 < key.index("and") < len(key) - 1:
            continue
        at = key.index("and")
        left, right = key[:at], key[at + 1 :]
        if left not in candidates and right not in candidates:
            continue
        pair = candidates[key]
        form = pair.forms.most_common(1)[0][0]
        parts = re.split(r"\s+and\s+", form, maxsplit=1)
        for side, text in zip((left, right), parts if len(parts) == 2 else ("", ""), strict=True):
            if side not in candidates:
                if not text:
                    continue
                candidates[side] = Candidate(side, set(), Counter({text: 1}))
                uf.find(side)
            candidates[side].sentences |= pair.sentences
        del candidates[
            key
        ]  # credited to each person; "Perelandra" isn't "Out of the Silent Planet"
    groups: dict[tuple[str, ...], list[Candidate]] = defaultdict(list)
    for key, cand in candidates.items():
        groups[uf.find(key)].append(cand)
    return list(groups.values())


def choose_label(group: list[Candidate], texts: list[str]) -> tuple[str, tuple[str, ...]]:
    """The spelling to show: the most-mentioned key's most common form, or a fuller name
    that covers a third as many mentions ("Nelson Miles" over "Miles")."""
    main = max(group, key=lambda c: (len(c.sentences), len(c.key)))  # ties: the fuller
    for cand in sorted(group, key=lambda c: -len(c.key)):
        form = cand.forms.most_common(1)[0][0]
        added = [w for w in form.split() if labeling.fold(normalize(w)) not in main.key]
        owner = re.search(r"['’]s\b", form) is not None  # "Bredt's rule" over "Bredt"
        if (
            len(cand.key) > len(main.key)
            and contains(cand.key, main.key) >= 0
            and added
            and (owner or all(w[:1].isupper() for w in added))  # not "Chiricahua branch"
            and len(cand.sentences) * 3 >= len(main.sentences)
        ):
            main = cand
            break
    label = main.forms.most_common(1)[0][0]
    if len(label.split()) > LONG_LABEL_WORDS:  # a quotation: its opening words
        return " ".join(label.split()[:QUOTE_LABEL_WORDS]) + "…", main.key
    words = [labeling.word_set(labeling.clean(t)) for t in texts]
    said = [t for t, w in zip(texts, words, strict=True) if labeling.names(w, label)]
    if said:
        # Complete a cut title ("Mysterious Affair" -> "... at Styles") only if nearly
        # every sentence naming the spelling names the completion too: "France" must
        # not become "Marie de France" for sentences about the country.
        full = labeling.complete_title(label, said)
        if full != label and sum(labeling.names(w, full) for w in words) < KEEP_LABEL * len(said):
            full = label
        label = labeling.surface(full, said)
    return label, main.key


def _distinct_questions(sentences: list[Sentence], idx: set[int]) -> set[frozenset[str]]:
    """The questions naming a clue, with reused wording counted once: two questions whose
    sentences about the clue are word for word the same are one source."""
    by_question: dict[str, set[str]] = defaultdict(set)
    for i in idx:
        by_question[sentences[i].tossup_id].add(normalize(sentences[i].text))
    return {frozenset(texts) for texts in by_question.values()}


def _capitalized_inside(form: str, texts: list[str]) -> bool:
    """Is the form capitalized somewhere other than a sentence's start ("Viruses ...")?"""
    pattern = re.compile(rf"[^\s.!?\"“(]\s+{re.escape(form)}")
    return any(pattern.search(t) for t in texts)


def make_usable(own: frozenset[str], freq: phrases.DocFrequency) -> Callable[[str], bool]:
    """Can this spelling be a clue at all? Not the answer's own name (``own``: its words),
    an ordinary word or stand-in, a common one-word name ("German") or a name made only of
    common words ("United States")."""

    def usable(form: str) -> bool:
        words = labeling.label_words(form)
        if not words or words <= own or labeling.plain_word(form, freq):
            return False
        if " " not in form and form[:1].isupper() and not form.isupper():
            return freq.idf(form.lower()) >= CAPITALIZED_WORD_IDF
        plain = [w for w in phrases.WORD.findall(form.lower()) if w not in STOPWORDS]
        if form[:1].isupper() and len(plain) > 1:
            return max(freq.idf(w) for w in plain) >= GENERIC_NAME_IDF
        return True

    return usable


def specific(
    form: str, n_questions: int, n_sentences: int, topic_sentences: int, freq: phrases.DocFrequency
) -> bool:
    """Is a lowercase clue specific enough to teach something? Names, titles and quotes
    always are. A common word ("radius", "premiere") has to be rare across all clues or
    concentrated in this topic; any lowercase clue needs two questions."""
    descriptive = re.match(r"^[A-Z][^']*['’]s [a-z]", form)  # "Isabel Bradley's actions"
    if form[:1].isdigit():
        return n_questions >= 3  # "1,369 light bulbs" yes, "48 different species" no
    if not form[:1].islower() and not descriptive:
        return True
    if n_questions < 2:
        return False
    if descriptive:
        return True
    words = [w for w in phrases.WORD.findall(form.lower()) if w not in STOPWORDS]
    if not words:
        return False
    if len(words) > 1:
        return max(freq.idf(w) for w in words) >= PHRASE_WORD_IDF
    return freq.idf(words[0]) >= SINGLE_WORD_IDF  # "signal", "virtue" aren't; "murti" is


def rank_topic(
    topic_id: str,
    sentences: list[Sentence],
    terms: list[set[str]],
    usable: Callable[[str], bool],
    alias_topics: dict[str, str],
    freq: phrases.DocFrequency | None = None,
    own_names: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The topic's clues, most questions first, with their statistics."""
    candidates: dict[tuple[str, ...], Candidate] = {}
    for index, forms in enumerate(terms):
        for form in forms:
            if not usable(form):
                continue
            key = key_of(form)
            if not key or all(w in STOPWORDS for w in key):
                continue
            cand = candidates.setdefault(key, Candidate(key))
            cand.sentences.add(index)
            cand.forms[form] += 1
            known = alias_topics.get(normalize(form))
            if known:
                cand.names_topic[known] += 1
    for key in [
        k
        for k, c in candidates.items()
        if topic_id in c.names_topic
        and any(normalize(f) in own_names for f in c.forms)  # Wikidata lists side names too
    ]:
        del candidates[key]  # the answer's own name
    clues = []
    for group in merge(candidates):
        idx = set().union(*(c.sentences for c in group))
        tossups = _distinct_questions(sentences, idx)
        if freq is not None:
            # Judged by its capitalized spelling if it has one: "Battle Royal" is a name
            # even where questions write "battle royal".
            spellings = [f for c in group for f in c.forms]
            said = [sentences[i].text for i in idx]
            capitalized = [f for f in spellings if f[:1].isupper() and _capitalized_inside(f, said)]
            main = capitalized[0] if capitalized else max(spellings, key=len).lower()
            if not specific(main, len(tossups), len(idx), len(sentences), freq):
                continue
        clues.append((len(tossups), len({sentences[i].set_id for i in idx}), len(idx), group, idx))
    clues.sort(key=lambda c: (-c[0], -c[1], -c[2], min(sentences[i].position for i in c[4])))
    # Label the leaders, then join clues whose labels came out the same ("direct analysis"
    # and "real time" both grow into "direct analysis in real time").
    labeled: dict[tuple[str, ...], tuple[str, tuple[str, ...], list[Candidate], set[int]]] = {}
    for *_, group, idx in clues[: KEEP + KEEP // 2]:
        label, key = choose_label(group, [sentences[i].text for i in sorted(idx)])
        same = tuple(sorted(labeling.label_words(label)))
        if same in labeled:
            first_label, first_key, first_group, first_idx = labeled[same]
            labeled[same] = (first_label, first_key, first_group + group, first_idx | idx)
        else:
            labeled[same] = (label, key, group, set(idx))
    merged = []
    for label, key, group, idx in labeled.values():
        tossups = _distinct_questions(sentences, idx)
        sets = {sentences[i].set_id for i in idx}
        merged.append((len(tossups), len(sets), len(idx), label, key, group, idx))

    def rank_key(c):
        n_q, n_sets, n_ment, label, _key, _group, idx = c
        earliest = min(sentences[i].position for i in idx)
        boost = 0.5 if n_q <= 2 and earliest < 0.2 else 0
        return (-(n_q + boost), -n_sets, label[:1].islower(), -n_ment, earliest)

    merged.sort(key=rank_key)
    out = []
    for n_q, n_sets, n_mentions, label, key, group, idx in merged[:KEEP]:
        rows = [sentences[i] for i in sorted(idx)]
        positions = [r.position for r in rows]
        variants: Counter[str] = Counter()
        named: Counter[str] = Counter()
        cats: Counter[str] = Counter()
        for cand in group:
            variants.update(cand.forms)
            named.update(cand.names_topic)
        for i in idx:
            cat = sentences[i].category
            if cat:
                cats[cat] += 1
        out.append(
            {
                "topic_id": topic_id,
                "label": label,
                "key": " ".join(key),
                "names_topic": named.most_common(1)[0][0] if named else None,
                "n_questions": n_q,
                "n_sets": n_sets,
                "n_mentions": n_mentions,
                "mean_position": mean(positions),
                "median_position": median(positions),
                "earliest_position": min(positions),
                "share_in_power": sum(r.in_power for r in rows) / len(rows),
                "share_last_line": sum(r.last_line for r in rows) / len(rows),
                "position_hist": position_hist(positions),
                "difficulty_hist": dict(Counter(difficulty_band(r.difficulty) for r in rows)),
                "years": [r.year for r in rows if r.year],
                "variants": dict(variants.most_common()),
                "categories": dict(cats.most_common()),
                "sentences": idx,
            }
        )
    return out


def mined_text(sentence: Sentence) -> str:
    """What spaCy should read. A giveaway is mined without its for-10-points frame."""
    if sentence.parse_text is not None:
        return sentence.parse_text
    return sentence.text


def load_sentences(
    conn: sqlite3.Connection,
) -> Iterator[tuple[str, list[tuple[Sentence, list[str]]]]]:
    """Clue sentences plus giveaways that state a fact, topic by topic, with key terms.

    ``last_line`` is still the last clue before the giveaway. A giveaway's ``parse_text``
    is the factual part, so noun phrases are not taken from "for 10 points".
    """
    rows = conn.execute(
        "SELECT c.topic_id, c.id, c.tossup_id, t.set_id, c.position, c.in_power, "
        "COALESCE(c.ordinal = l.last_ordinal, 0), COALESCE(t.difficulty, 0), s.year, c.text, "
        "t.category, c.key_terms, c.kind "
        "FROM clues c JOIN tossups t ON t.id = c.tossup_id JOIN sets s ON s.id = t.set_id "
        "LEFT JOIN (SELECT tossup_id, MAX(ordinal) AS last_ordinal FROM clues "
        "      WHERE kind = 'clue' GROUP BY tossup_id) l ON l.tossup_id = c.tossup_id "
        "WHERE c.kind IN ('clue', 'giveaway') AND c.topic_id IS NOT NULL "
        "ORDER BY c.topic_id, c.id"
    )
    for topic_id, group in itertools.groupby(rows, key=lambda r: r[0]):
        items: list[tuple[Sentence, list[str]]] = []
        for row in group:
            terms = json.loads(row[11])
            sentence = Sentence(*row[1:11])
            if row[12] == "giveaway":
                facts = giveaway_facts(sentence.text)
                if not facts and not terms:
                    continue
                sentence.parse_text = facts
            items.append((sentence, terms))
        if items:
            yield topic_id, items


def parse_all(
    conn: sqlite3.Connection, cache: ParseCache, reporter: Reporter, processes: int
) -> None:
    """Parse every clue sentence spaCy hasn't seen yet (the slow part, done once)."""
    texts: dict[str, str] = {}
    for text, kind in conn.execute(
        "SELECT text, kind FROM clues WHERE kind IN ('clue', 'giveaway') AND topic_id IS NOT NULL"
    ):
        if kind == "giveaway":
            text = giveaway_facts(text)
        if not str(text).strip():
            continue
        cleaned = labeling.clean(text)
        texts[text_key(cleaned)] = cleaned
    todo = cache.missing(list(texts))
    reporter.begin("Parsing clue sentences (spaCy)", len(todo))
    reporter.stat(
        "Sentences to parse / already cached", f"{len(todo):,} / {len(texts) - len(todo):,}"
    )
    if not todo:
        return
    import spacy  # imported lazily: loading the model takes a second

    nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    batch: list[tuple[str, dict[str, Any]]] = []
    docs = nlp.pipe((texts[k] for k in todo), batch_size=256, n_process=processes)
    for key, doc in zip(todo, docs, strict=True):
        batch.append((key, phrases.serialize(doc)))
        if len(batch) == 2000:
            cache.put(batch)
            reporter.advance(len(batch))
            batch.clear()
    cache.put(batch)
    reporter.advance(len(batch))


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "clues", "clues")
    cache = ParseCache(settings.data_dir / "cache" / "terms" / "parses.db")
    parse_all(conn, cache, reporter, PARSE_PROCESSES)

    reporter.begin("Counting words across all clues", None)
    freq = phrases.DocFrequency.from_corpus(conn)
    aliases: dict[str, set[str]] = defaultdict(set)
    topics_of_alias: dict[str, set[str]] = defaultdict(set)
    for topic_id, alias in conn.execute("SELECT topic_id, alias_search FROM topic_aliases"):
        aliases[topic_id].add(alias)
        topics_of_alias[alias].add(topic_id)
    # A name of exactly one known topic, long enough not to be a stray word.
    alias_topics = {
        a: next(iter(t)) for a, t in topics_of_alias.items() if len(t) == 1 and len(a) >= 4
    }
    # The answer's own names: its title, and aliases sharing a word with it. Wikidata
    # also lists side names ("Operation Sea Lion" for the Battle of Britain), which are clues.
    titles = {
        tid: labeling.word_set(re.sub(r"\s*\(.*\)$", "", name))
        for tid, name in conn.execute("SELECT id, display_name FROM topics")
    }
    own_names = {
        t: frozenset(a for a in names if labeling.word_set(a) & titles.get(t, frozenset()))
        for t, names in aliases.items()
    }
    name_words = {
        t: frozenset().union(titles.get(t, frozenset()), *(labeling.word_set(a) for a in own))
        for t, own in own_names.items()
    }
    topic_years: dict[str, list[int]] = defaultdict(list)
    for topic_id, year in conn.execute(
        "SELECT tt.topic_id, s.year FROM tossup_topics tt JOIN tossups t ON t.id = tt.tossup_id "
        "JOIN sets s ON s.id = t.set_id WHERE s.year IS NOT NULL"
    ):
        topic_years[topic_id].append(year)
    n_topics = conn.execute(
        "SELECT COUNT(DISTINCT topic_id) FROM clues WHERE topic_id IS NOT NULL"
    ).fetchone()[0]

    db.recreate(conn, SCHEMA)
    reporter.begin("Ranking each topic's clues", n_topics)
    next_id = 0
    clue_rows: list[tuple[object, ...]] = []
    link_rows: list[tuple[int, int]] = []
    primary_rows: list[tuple[int, int]] = []
    ranked = stored = 0
    for topic_id, items in load_sentences(conn):
        sentences = [s for s, _ in items]
        mined = [mined_text(s) for s in sentences]
        parse_keys = [text_key(labeling.clean(text)) if text.strip() else "" for text in mined]
        parses = cache.get([key for key in parse_keys if key])
        terms = [
            sentence_terms(s, keys, parses.get(parse_key, {}) if parse_key else {}, freq)
            for (s, keys), parse_key in zip(items, parse_keys, strict=True)
        ]
        own = name_words.get(topic_id, frozenset())

        usable = make_usable(own, freq)
        clues = rank_topic(
            topic_id,
            sentences,
            terms,
            usable,
            alias_topics,
            freq,
            own_names.get(topic_id, frozenset()),
        )
        ids = list(range(next_id + 1, next_id + 1 + len(clues)))
        next_id += len(clues)
        by_sentence: dict[int, list[int]] = defaultdict(list)
        for rank, clue in enumerate(clues, start=1):
            for i in clue["sentences"]:
                by_sentence[i].append(rank)
        for rank, (cid, clue) in enumerate(zip(ids, clues, strict=True), start=1):
            shared: Counter[int] = Counter()
            for i in clue["sentences"]:
                shared.update(r for r in by_sentence[i] if r != rank)
            cooccurs = [
                [ids[r - 1], clues[r - 1]["label"], n] for r, n in shared.most_common(COOCCURS)
            ]
            years = clue["years"]
            clue_rows.append(
                (cid, topic_id, rank, clue["label"], clue["key"], clue["names_topic"],
                 clue["n_questions"], clue["n_sets"], clue["n_mentions"],
                 clue["mean_position"], clue["median_position"], clue["earliest_position"],
                 clue["share_in_power"], clue["share_last_line"],
                 json.dumps(clue["position_hist"]), json.dumps(clue["difficulty_hist"]),
                 min(years, default=None), max(years, default=None),
                 trend(years, topic_years.get(topic_id, [])),
                 json.dumps(clue["variants"], ensure_ascii=False),
                 json.dumps(cooccurs, ensure_ascii=False),
                 json.dumps(clue["categories"], ensure_ascii=False))
            )  # fmt: skip
            link_rows.extend((cid, sentences[i].clue_id) for i in clue["sentences"])
        for i, ranks in by_sentence.items():
            primary_rows.append((sentences[i].clue_id, ids[min(ranks) - 1]))
        ranked += bool(clues)
        stored += len(clues)
        reporter.advance()
        if len(link_rows) > 100_000:
            _flush(conn, clue_rows, link_rows, primary_rows)
    _flush(conn, clue_rows, link_rows, primary_rows)
    conn.commit()
    reporter.stat("Topics with clues", f"{ranked:,} of {n_topics:,}")
    reporter.stat("Clues stored", f"{stored:,}")
    conn.close()


def _flush(
    conn: sqlite3.Connection,
    clues: list[tuple[object, ...]],
    links: list[tuple[int, int]],
    primary: list[tuple[int, int]],
) -> None:
    conn.executemany(f"INSERT INTO topic_clues VALUES ({','.join('?' * 22)})", clues)
    conn.executemany("INSERT INTO topic_clue_sentences VALUES (?, ?)", links)
    conn.executemany("INSERT INTO sentence_clues VALUES (?, ?)", primary)
    clues.clear()
    links.clear()
    primary.clear()
