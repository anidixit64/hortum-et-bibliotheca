"""Text normalization shared by the pipeline, search and answer checking."""

import re
import unicodedata
from functools import lru_cache

import inflect
from unidecode import unidecode

_inflect = inflect.engine()
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_NON_WORD = re.compile(r"[^a-z0-9]+")
# Plural-looking endings that are usually not plurals ("physics", "Mars", "virus", "class").
_NOT_PLURAL = ("ss", "us", "is", "ics", "os")


@lru_cache(maxsize=200_000)
def _singular(word: str) -> str:
    if len(word) < 4 or not word.endswith("s") or word.endswith(_NOT_PLURAL):
        return word
    singular = _inflect.singular_noun(word)
    return singular if isinstance(singular, str) and singular else word


def normalize(text: str, *, singularize: bool = False) -> str:
    """Folds text to a comparison key: ASCII, lowercase, no punctuation or leading article.

    With ``singularize``, a lowercase final word is made singular ("doctors" -> "doctor").
    Capitalized words are left alone, since they are usually names ("Athens", "Mars").
    """
    text = unicodedata.normalize("NFKC", text)
    last_word = text.strip().split(" ")[-1] if text.strip() else ""
    folded = _NON_WORD.sub(" ", unidecode(text).lower().replace("&", " and ")).strip()
    folded = _LEADING_ARTICLE.sub("", folded)
    if singularize and folded and last_word[:1].islower():
        head, _, tail = folded.rpartition(" ")
        folded = f"{head} {_singular(tail)}".strip()
    return folded


def slugify(text: str) -> str:
    return normalize(text).replace(" ", "-")
