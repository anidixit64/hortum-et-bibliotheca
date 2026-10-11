"""Each clue cluster's label, and which of its clues actually state it.

Clustering groups clues by meaning, so a cluster can hold a neighboring fact or two (a
"Fischer esterification" cluster that also took in other alcohol reactions). The label is
therefore chosen by what the cluster's clues *share*: the key term (then noun phrase)
named by the most of them. The clues naming the label are the cluster's core, and the
score stage counts and charts only those, so a catch-all cluster can't outrank a clean
fact just by being big.

Labels are tidied on the way: pronunciation guides ("ZY-goats") are never candidates,
possessives lose their "'s", bare numbers and long quotations are skipped, and a title
cut off at a small word is completed from the text ("Mysterious Affair" becomes
"Mysterious Affair at Styles").
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from hortum_common.text import normalize
from hortum_pipeline import phrases
from hortum_pipeline.clues import PRONUNCIATION
from hortum_pipeline.relate import STOPWORDS, tokenize

MIN_COVERAGE = 0.5  # a label named by fewer of the clues than this tries noun phrases too
NEAR_BEST = 0.75  # labels named by this share of the best one's clues compete on specificity
STAND_IN_RATE = 0.2  # a one-word label used this often as "this <word>" is a stand-in
MAX_LABEL_WORDS = 5
COMMON_WORD_IDF = 4.0  # a one-word term this common is a capitalized ordinary word ("Write")
GENERIC_IDF = 7.0  # a one-word lowercase label this common is generic ("key", "cities")
GROW_SUPPORT = 0.75  # a longer phrase replaces a label if this share of its clues say it
GROW_MAX_WORDS = 4  # grown labels stay short ("vast image out of Spiritus Mundi" doesn't)
# Small words a title can cross: "House of the Hanged Man", "Mysterious Affair at Styles".
_TITLE_LINKS = frozenset({"of", "the", "at", "on", "de", "la", "del", "du", "von", "van"})
TOKEN = re.compile(r"\w+(?:['’-]\w+)*(?:['’]s)?|[^\w\s]")


def clean(text: str) -> str:
    return PRONUNCIATION.sub(" ", text)


def fold(word: str) -> str:
    return normalize(word, singularize=True)


def word_set(text: str) -> frozenset[str]:
    """Content words of a text, folded (plurals singular) for comparing with labels."""
    return frozenset(fold(t.key) for t in tokenize(text) if t.key not in STOPWORDS)


def label_words(label: str) -> frozenset[str]:
    return word_set(label.rstrip("…"))


def names(words: frozenset[str], label: str) -> bool:
    """Does a clue (as its word set) name every content word of the label?"""
    wanted = label_words(label)
    return bool(wanted) and wanted <= words


def tidy(term: str) -> str | None:
    """A key term fit to be a label, or None: no bare numbers, long quotations or dangling
    fragments ("stream of", "is theft", "SU")."""
    term = term.strip(" \"“”'‘’,;:")
    term = re.sub(r"['’]s?$", "", term).strip()
    if not re.search(r"[^\W\d_]", term):
        return None  # "1420", "615": a number says nothing without its noun
    words = term.split()
    if len(words) > MAX_LABEL_WORDS:
        return None
    # A lowercase phrase can't start or end on a small word ("stream of", "is theft"); a
    # title can ("You Can Call Me Al", "We Were Eight Years in Power").
    if term[:1].islower() and (
        words[0].lower() in STOPWORDS and len(words) > 1 or words[-1].lower() in STOPWORDS
    ):
        return None
    if len(words) == 1 and len(term) <= 2:
        return None
    return term


def _title_word(token: str) -> bool:
    return (
        token[:1].isupper() and not token.endswith(("'s", "’s")) and token not in {"The", "A", "An"}
    )


def _extend(tokens: list[str], start: int, end: int) -> tuple[int, int]:
    """Grow tokens[start:end] over capitalized words, crossing small linking words."""
    while True:
        k = start - 1
        while k > 0 and tokens[k] in _TITLE_LINKS:
            k -= 1
        if k > 0 and _title_word(tokens[k]):  # never the sentence's first word
            start = k
            continue
        break
    while True:
        k = end
        while k < len(tokens) and tokens[k] in _TITLE_LINKS:
            k += 1
        if k < len(tokens) and _title_word(tokens[k]):
            end = k + 1
            continue
        break
    return start, end


def complete_title(term: str, texts: Sequence[str]) -> str:
    """Extend a capitalized term the way most clues naming it do: "Blind Mice" in "Three
    Blind Mice", "Mysterious Affair" in "The Mysterious Affair at Styles"."""
    if not term[:1].isupper():
        return term
    target = TOKEN.findall(term)
    forms: dict[str, int] = {}
    seen = 0
    for text in texts:
        spans = list(TOKEN.finditer(text))
        tokens = [m.group() for m in spans]
        for i in range(len(tokens) - len(target) + 1):
            if tokens[i : i + len(target)] == target:
                seen += 1
                start, end = _extend(tokens, i, i + len(target))
                if (start, end) != (i, i + len(target)) and end - start <= MAX_LABEL_WORDS + 1:
                    form = text[spans[start].start() : spans[end - 1].end()]
                    forms[form] = forms.get(form, 0) + 1
                break
    if not forms:
        return term
    best, count = max(forms.items(), key=lambda kv: (kv[1], len(kv[0])))
    return best if count * 2 > seen else term


@dataclass
class Choice:
    label: str
    core: list[int]  # indices of the clues that name the label
    source: str  # "term" | "phrase" | "opening"


def _specific_choice(
    options: list[tuple[str, list[int], int]], freq: phrases.DocFrequency
) -> tuple[str, list[int]] | None:
    """Among labels named by nearly as many clues as the best, the most specific: "Casa
    Grande" (3 clues) over "Mexicans" (4). ``options``: (label, core, tie-break rank)."""
    if not options:
        return None
    top = max(len(core) for _, core, _ in options)
    close = [o for o in options if len(o[1]) >= NEAR_BEST * top and o[1]]
    if not close:
        return None
    label, core, _ = max(
        close, key=lambda o: (phrases.specificity(o[0], freq), len(o[1]), o[2], o[0])
    )
    return label, core


def plain_word(label: str, freq: phrases.DocFrequency) -> bool:
    """A one-word label that's an ordinary word, a generic noun or an answer's stand-in
    ("Write", "cities", "planet")."""
    if " " in label.strip() or label.isupper():
        return False
    word = label.lower()
    if freq.idf(word) < COMMON_WORD_IDF or freq.stand_in_rate(word) >= STAND_IN_RATE:
        return True
    return label.islower() and freq.idf(word) < GENERIC_IDF


def best_term(
    texts: Sequence[str],
    words: Sequence[frozenset[str]],
    terms: Sequence[Sequence[str]],
    usable: Callable[[str], bool],
    freq: phrases.DocFrequency,
) -> tuple[str, list[int]] | None:
    """The usable key term named by the most clues, preferring the more specific of
    near ties."""
    as_key: dict[str, int] = {}
    for clue_terms in terms:
        for term in dict.fromkeys(filter(None, map(tidy, clue_terms))):
            as_key[term] = as_key.get(term, 0) + 1
    options = []
    for term, n_key in as_key.items():
        if not usable(term):
            continue
        core = [i for i, w in enumerate(words) if names(w, term)]
        if plain_word(term, freq):
            # "Relief" alone says nothing; "Commission for Relief in Belgium" does.
            term = grow([texts[i] for i in core], complete_title(term, [texts[i] for i in core]))
            if plain_word(term, freq) or not usable(term):
                continue
        options.append((term, core, n_key))
    return _specific_choice(options, freq)


def best_phrase(
    docs: Sequence[Any],
    words: Sequence[frozenset[str]],
    usable: Callable[[str], bool],
    freq: phrases.DocFrequency,
) -> tuple[str, list[int]] | None:
    """The noun phrase named by the most clues, preferring the more specific of near ties."""
    found = {p for doc in docs for p in phrases.candidates(doc, freq)}
    options = [
        (phrase, [i for i, w in enumerate(words) if names(w, phrase)], len(phrase.split()))
        for phrase in sorted(found)
        if phrases.specificity(phrase, freq) >= phrases.MIN_IDF
        and usable(phrase)
        and not plain_word(phrase, freq)
    ]
    return _specific_choice(options, freq)


def choose(
    texts: Sequence[str],
    terms: Sequence[Sequence[str]],
    usable: Callable[[str], bool],
    freq: phrases.DocFrequency,
    docs: Sequence[Any] | None = None,
) -> Choice | None:
    """The cluster's label from its key terms, or None if noun phrases should be tried
    (``docs`` not given and no term is named by at least half the clues)."""
    words = [word_set(clean(t)) for t in texts]
    term = best_term(texts, words, terms, usable, freq)
    if term and len(term[1]) >= MIN_COVERAGE * len(texts):
        return _final(term[0], term[1], texts, "term")
    if docs is None:
        return None
    phrase = best_phrase(docs, words, usable, freq)
    options = [c for c in (term, phrase) if c and c[1]]
    if not options:
        opening = texts[0].split()
        label = " ".join(opening[:8]) + ("…" if len(opening) > 8 else "")
        return Choice(label, list(range(len(texts))), "opening")
    label, core = max(options, key=lambda c: len(c[1]))  # the term wins ties (listed first)
    return _final(label, core, texts, "term" if term and label == term[0] else "phrase")


def _final(label: str, core: list[int], texts: Sequence[str], source: str) -> Choice:
    """Complete the label from its clues' wording and drop clues that negate it."""
    said = [texts[i] for i in core]
    label = surface(grow(said, complete_title(label, said)), said)
    kept = [i for i in core if not negated(texts[i], label)]
    return Choice(label, kept or core, source)


def _tokens(text: str) -> list[re.Match[str]]:
    return list(TOKEN.finditer(text))


def _key(token: str) -> str:
    return fold(token.lower()) if token[:1].isalnum() else token


def _content(token: str) -> bool:
    return token[:1].isalnum() and token.lower() not in STOPWORDS


def grow(texts: Sequence[str], label: str) -> str:
    """The longest phrase around the label that most of its clues share: "Batesian" ->
    "Batesian mimicry", "Buck" -> "Buck v. Bell". Needs two clues to agree."""
    if len(texts) < 2:
        return label
    target = [_key(t.group()) for t in _tokens(label)]
    need = max(2, GROW_SUPPORT * len(texts))
    spans: dict[tuple[str, ...], str] = {}
    support: dict[tuple[str, ...], int] = {}
    for text in texts:
        found = _tokens(text)
        keys = [_key(t.group()) for t in found]
        seen: set[tuple[str, ...]] = set()
        for i in range(len(keys) - len(target) + 1):
            if keys[i : i + len(target)] != target:
                continue
            for left in range(0, 4):
                for right in range(0, 4):
                    start, end = i - left, i + len(target) + right
                    if start < 0 or end > len(keys):
                        continue
                    if right + left and sum(_content(t.group()) for t in found[start:end]) > max(
                        GROW_MAX_WORDS, len(target)
                    ):
                        continue
                    inner = [t.group() for t in found[start:end]]
                    if not (_content(inner[0]) and _content(inner[-1])):
                        continue
                    if right and len(inner[-1]) == 1:
                        continue  # "photographer C" of "photographer C. S. Fly"
                    if left and not all(t[:1].isupper() for t in inner[:left] if _content(t)):
                        continue  # no "member Prescott Bush", "architect al-Sahili"
                    if any(t.lower() in phrases.DEMONSTRATIVE for t in inner) or (
                        inner[-1].lower() in phrases.FILLER or inner[0].lower() in phrases.FILLER
                    ):
                        continue  # "womb chamber of these buildings": the answer's stand-in
                    if any(
                        not tok[:1].isalnum() and not _abbreviation(inner, j)
                        for j, tok in enumerate(inner)
                    ):
                        continue  # never across punctuation, save "v." in "Buck v. Bell"
                    span = tuple(keys[start:end])
                    if span not in seen:
                        seen.add(span)
                        support[span] = support.get(span, 0) + 1
                        spans.setdefault(span, text[found[start].start() : found[end - 1].end()])
            break
    agreed = [span for span, n in support.items() if n >= need]
    if not agreed:
        return label
    best = max(agreed, key=lambda span: (len(span), support[span]))
    return spans[best] if len(best) > len(target) else label


def _abbreviation(tokens: list[str], j: int) -> bool:
    return tokens[j] == "." and j > 0 and tokens[j - 1].lower() in {"v", "vs", "st", "dr", "mr"}


def surface(label: str, texts: Sequence[str]) -> str:
    """The label as its clues most often write it, singular winning ties ("trophic
    cascade", not "trophic cascades")."""
    target = [_key(t.group()) for t in _tokens(label)]
    forms: dict[str, int] = {}
    for text in texts:
        found = _tokens(text)
        keys = [_key(t.group()) for t in found]
        for i in range(len(keys) - len(target) + 1):
            if keys[i : i + len(target)] == target:
                form = text[found[i].start() : found[i + len(target) - 1].end()]
                forms[form] = forms.get(form, 0) + 1
    if not forms:
        return label
    singular = {f for f in forms if not re.search(r"s$", f.split()[-1])}
    top = max(forms.values())
    preferred = [f for f in singular if forms[f] * 3 >= top] or list(forms)
    best = max(preferred, key=lambda f: (forms[f], -len(f)))
    rest = best.split()[1:]
    if best[:1].isupper() and not label[:1].isupper() and all(w[:1].islower() for w in rest):
        best = best[0].lower() + best[1:]  # capitalized only at a sentence start
    return best


def negated(text: str, label: str) -> bool:
    """ "It's not serine": a clue ruling the label out doesn't state it."""
    if not re.search(r"\bnot\b", text, re.I):
        return False  # most clues: skip building a pattern
    first = re.escape(label.split()[0])
    return bool(re.search(rf"\bnot\s+(?:an?\s+|the\s+)?{first}", text, re.I))
