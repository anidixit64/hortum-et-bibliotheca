import pytest

from hortum_common.text import normalize, slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("doctors", "doctor"),
        ("soldiers", "soldier"),
        ("Athens", "athens"),  # capitalized: a name, not a plural
        ("physics", "physics"),
        ("species", "species"),
        ("The Doctors", "doctors"),
        ("La bohème", "la boheme"),
        ("“Get Back”", "get back"),
        ("Saint-Saëns", "saint saens"),
        ("Q&A", "q and a"),
    ],
)
def test_normalize_singularizes_lowercase_plurals_only(text: str, expected: str) -> None:
    assert normalize(text, singularize=True) == expected


def test_normalize_without_singularizing_keeps_plurals() -> None:
    assert normalize("The doctors") == "doctors"


def test_slugify() -> None:
    assert slugify("Association Football (soccer)") == "association-football-soccer"
