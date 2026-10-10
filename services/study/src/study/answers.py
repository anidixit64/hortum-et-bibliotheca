"""Judging a typed answer against the parsed answer line, as a moderator would."""

import re
import unicodedata
from typing import Literal

from rapidfuzz import fuzz
from unidecode import unidecode

from hortum_common.text import normalize

Verdict = Literal["correct", "prompt", "incorrect"]
FUZZY = 85  # rapidfuzz ratio: "Dostoyevsky" for "Dostoevsky", not "Austria" for "Australia"
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _exact(text: str) -> str:
    """Folded but keeping a leading article: "The Invisible Man" != "Invisible Man"."""
    folded = unidecode(unicodedata.normalize("NFKC", text)).lower().replace("&", " and ")
    return _NON_WORD.sub(" ", folded).strip()


def _loose(values: list[str]) -> set[str]:
    return {f for v in values if (f := normalize(v, singularize=True))}


def judge(
    given: str,
    main: str,
    required: list[str],
    accept: list[str],
    prompt: list[str],
    reject: list[str],
) -> Verdict:
    """Correct, prompt or incorrect.

    Exact matches first, keeping articles, so "Invisible Man" is right and "The Invisible
    Man" (Wells's novel, rejected) is wrong. Then looser matches (articles, plurals): a
    reject wins over everything, except a reject that only differs from a right answer by
    its article, which only the exact form triggers. Then the required (underlined) part
    anywhere in the answer ("Johannes Brahms" for "Brahms"), then fuzzy matches.
    """
    if not normalize(given):
        return "incorrect"
    right_values = [main, *required, *accept]
    exact = _exact(given)
    if exact in {_exact(v) for v in reject}:
        return "incorrect"
    if exact in {_exact(v) for v in right_values}:
        return "correct"
    if exact in {_exact(v) for v in prompt}:
        return "prompt"

    answer = normalize(given, singularize=True)
    right, asks = _loose(right_values), _loose(prompt)
    wrong = _loose(reject) - right  # "the invisible man" loosely is "invisible man": exact only
    if answer in wrong:
        return "incorrect"
    if answer in right:
        return "correct"
    if answer in asks:
        return "prompt"
    padded = f" {answer} "
    if any(f" {part} " in padded for part in _loose(required)):
        return "correct"
    if any(fuzz.ratio(answer, form) >= FUZZY for form in wrong):
        return "incorrect"
    if any(fuzz.ratio(answer, form) >= FUZZY for form in right):
        return "correct"
    if any(fuzz.ratio(answer, form) >= FUZZY for form in asks):
        return "prompt"
    return "incorrect"
