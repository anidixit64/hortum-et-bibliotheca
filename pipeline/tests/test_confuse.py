import pytest

from hortum_pipeline import confuse
from hortum_pipeline.relate import Alias, AliasMatcher

LIT = "Literature"


def owner(topic: str, category: str = LIT, *, own_name: bool = True) -> Alias:
    return Alias(topic, category, True, False, False, title=own_name, own_name=own_name)


def test_base_name_drops_the_parenthetical() -> None:
    assert confuse.base_name("Mercury (planet)") == confuse.base_name("Mercury (element)")
    assert confuse.base_name("The Invisible Man") == "invisible man"


@pytest.mark.parametrize(
    ("a", "b", "alike"),
    [
        ("monet", "manet", True),
        ("iran", "iraq", True),
        ("henry i of england", "henry ii of england", True),
        ("austria", "australia", True),
        ("1870s", "1890s", False),  # differ only in digits
        ("16th century", "19th century", False),
        ("shale", "whale", True),  # by name; the clue-similarity gate rejects it
        ("ras", "rap", False),  # too short
        ("invisible man", "the invisible man", False),  # one contains the other
    ],
)
def test_is_lookalike(a: str, b: str, alike: bool) -> None:
    assert confuse.is_lookalike(a, b) is alike


def test_a_reject_never_names_the_questions_own_topic() -> None:
    matcher = AliasMatcher({"invisible man": [owner("ellison"), owner("wells")]}, name_like=set())
    assert confuse.reject_targets("The Invisible Man", matcher, LIT, "ellison") == ["wells"]
    text = "The Invisible Man which is a different novel"
    assert confuse.reject_targets(text, matcher, LIT, "ellison") == ["wells"]


def test_a_name_buried_in_an_explanation_is_not_a_reject() -> None:
    matcher = AliasMatcher({"giovanni s room": [owner("baldwin novel")]}, name_like=set())
    text = "the city he lives in afterwards. First Giovanni's Room is set there"
    assert confuse.reject_targets(text, matcher, LIT, "paris") == []
    assert confuse.reject_targets("Giovanni's Room", matcher, LIT, "paris") == ["baldwin novel"]
