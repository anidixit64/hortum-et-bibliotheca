"""Noun phrases for labeling clues that name nothing (see ``labeling``).

A clue like "Circumambulation rituals in these structures are typically done in a
clockwise manner" has no capitalized or quoted term. spaCy's noun chunks give candidate
labels ("circumambulation rituals"), and how rare their words are across all clues says
how specific each is. Phrases pointing at the answer itself ("this substance", "these
structures") are skipped, since they describe the topic rather than the clue.
"""

import math
import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from hortum_pipeline.relate import STOPWORDS

WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
# Stand-ins for the answer and question boilerplate: never a label on their own.
_FILLER_TEXT = """this these that those one ones man woman person people work works figure
    figures thing things entity entities structure structures building buildings place
    places term terms
    object objects concept concepts phenomenon type types kind kinds name named called known
    often typically usually also may can many several some such other another first second
    each every two three title character characters author authors writer poem novel play
    story book event events country city nation group groups"""
FILLER = frozenset(_FILLER_TEXT.split())
DEMONSTRATIVE = frozenset({"this", "these", "that", "those"})
SKIP_POS = frozenset({"DET", "PRON", "PUNCT", "CCONJ", "ADP", "PART", "SYM", "ADV"})
HEAD_POS = frozenset({"NOUN", "PROPN", "X"})
MAX_WORDS = 5
COMMON_ADJECTIVE_IDF = 4.0  # "own", "typical": dropped from the front of a phrase
MIN_IDF = 3.5  # a best phrase vaguer than this ("painting") isn't worth showing

Parser = Callable[[Iterable[str]], Iterator[Any]]  # texts -> spaCy Docs


def load_parser() -> Parser:
    import spacy  # imported lazily: loading the model takes a second

    nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    return lambda texts: nlp.pipe(texts, batch_size=256)


class DocFrequency:
    """Inverse document frequency of words across every clue."""

    def __init__(self, texts: Iterable[str]) -> None:
        self.df: Counter[str] = Counter()
        self.uses: Counter[str] = Counter()
        self.stand_in: Counter[str] = Counter()  # uses right after this/these/that/those
        self.n = 0
        for text in texts:
            self.n += 1
            words = WORD.findall(text.lower())
            self.df.update(set(words))
            self.uses.update(words)
            self.stand_in.update(
                w for prev, w in zip(words, words[1:], strict=False) if prev in DEMONSTRATIVE
            )

    @classmethod
    def from_corpus(cls, conn: sqlite3.Connection) -> "DocFrequency":
        return cls(text for (text,) in conn.execute("SELECT text FROM clues WHERE kind = 'clue'"))

    def idf(self, word: str) -> float:
        return math.log(max(self.n, 1) / (1 + self.df[word]))

    def stand_in_rate(self, word: str) -> float:
        """How often a word follows "this"/"these": "planet", "hormone" and "novel" mostly
        stand in for an answer ("this planet"), so they say nothing as a label."""
        return self.stand_in[word] / self.uses[word] if self.uses[word] else 0.0


def candidates(doc: Any, freq: DocFrequency) -> set[str]:
    """Noun phrases of one parsed clue, trimmed to their content words."""
    out = set()
    for chunk in doc.noun_chunks:
        if any(t.lower_ in DEMONSTRATIVE for t in chunk):
            continue  # "this substance": the answer itself
        tokens = list(chunk)
        while tokens and (
            tokens[0].pos_ in SKIP_POS
            or tokens[0].lower_ in FILLER
            or tokens[0].lower_ in STOPWORDS
            or (tokens[0].pos_ == "ADJ" and freq.idf(tokens[0].lower_) < COMMON_ADJECTIVE_IDF)
        ):
            tokens = tokens[1:]
        if not tokens or tokens[-1].pos_ not in HEAD_POS or tokens[-1].lower_ in FILLER:
            continue
        # The phrase and its shorter endings: "innermost womb chamber" also counts as
        # "womb chamber", so a cluster's shared core can win.
        for start in range(len(tokens)):
            first = tokens[start]
            if first.pos_ in SKIP_POS or first.lower_ in FILLER or first.lower_ in STOPWORDS:
                continue
            if start and not doc[first.i - 1].whitespace_:
                continue  # inside a hyphenated word: "beta" of "alpha-beta"
            span = doc[first.i : tokens[-1].i + 1]
            if len(span) > MAX_WORDS or span.text.endswith("'s") or span[0].is_punct:
                continue
            text = span.text
            if span[0].pos_ != "PROPN" and text[1:2].islower():
                text = text[0].lower() + text[1:]  # "Circumambulation rituals" -> lowercase
            out.add(text)
    return out


def specificity(phrase: str, freq: DocFrequency) -> float:
    """Mean inverse document frequency of the phrase's content words."""
    words = [w for w in WORD.findall(phrase.lower()) if w not in STOPWORDS]
    return sum(freq.idf(w) for w in words) / len(words) if words else 0.0
