import pytest

from hortum_pipeline import relate
from hortum_pipeline.relate import Alias, AliasMatcher, tokenize

LIT, SCI = "Literature", "Science"


def alias(
    topic: str,
    category: str = LIT,
    *,
    proper: bool = True,
    weak: bool = False,
    single: bool = False,
    title: bool = False,
    own_name: bool = True,
    usable: bool = True,
) -> Alias:
    return Alias(topic, category, proper, weak, single, title, own_name, usable)


def find(aliases: dict[str, list[Alias]], text: str, category: str = LIT) -> list[str]:
    matcher = AliasMatcher(aliases, name_like={"alfred", "dr"})
    return [topic for _, topic, _, _ in matcher.find(tokenize(text), category)]


def test_tokenize_keys_like_aliases_and_keeps_spans() -> None:
    tokens = tokenize("T. H. Morgan's Fly Room & Dantès")
    assert [t.key for t in tokens] == ["t", "h", "morgan", "s", "fly", "room", "and", "dantes"]
    text = "T. H. Morgan's Fly Room & Dantès"
    assert text[tokens[-1].start : tokens[-1].end] == "Dantès"
    assert [t.capitalized for t in tokens[:4]] == [True, True, True, False]


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("fifa", True),
        ("world war i", True),  # ends in "I", a real name
        ("vitamin a", True),
        ("ras", False),  # too short
        ("1984", False),  # a year as often as a novel
        ("existence of", False),
        ("river s", False),
        ("a markov", False),
    ],
)
def test_usable_alias(name: str, ok: bool) -> None:
    assert relate.usable_alias(name) is ok


def test_is_proper() -> None:
    assert relate.is_proper("Your Name")
    assert relate.is_proper("The Count of Monte Cristo")
    assert not relate.is_proper("Calvin cycle")
    assert not relate.is_proper("model organism")


def test_longest_name_wins() -> None:
    aliases = {"fifa world cup": [alias("cup")], "world cup": [alias("other")]}
    assert find(aliases, "It is played at the FIFA World Cup.") == ["cup"]


def test_capitalized_name_must_appear_capitalized() -> None:
    aliases = {"your name": [alias("film")]}
    assert find(aliases, 'He is asked "What is your name?" after the shock.') == []
    assert find(aliases, "He watched Your Name twice.") == ["film"]


def test_one_word_name_inside_a_longer_name_is_not_a_mention() -> None:
    aliases = {"bledsoe": [alias("qb", single=True)], "sturtevant": [alias("actor", single=True)]}
    assert find(aliases, "He is expelled by Dr. Bledsoe.") == []
    assert find(aliases, "Alfred Sturtevant drew the first map.") == []
    assert find(aliases, "He is expelled by Bledsoe.") == ["qb"]


def test_weak_name_needs_the_same_category() -> None:
    aliases = {"sybil": [alias("fawlty", "Pop Culture", weak=True, single=True)]}
    assert find(aliases, "He writes a note to Sybil.", LIT) == []
    assert find(aliases, "He writes a note to Sybil.", "Pop Culture") == ["fawlty"]


def test_shared_name_resolved_by_category() -> None:
    owners = [alias("film", "Pop Culture", title=True), alias("battle royal", LIT)]
    aliases = {"battle royale": owners}
    assert find(aliases, 'He boxes in a "Battle Royale" scene.', LIT) == ["battle royal"]
    assert find(aliases, 'He boxes in a "Battle Royale" scene.', "Pop Culture") == ["film"]


def test_own_name_beats_a_side_alias_in_the_same_category() -> None:
    owners = [
        alias("photosynthesis", SCI, proper=False, own_name=False),
        alias("calvin", SCI, proper=False, title=True),
    ]
    assert find({"calvin cycle": owners}, "It feeds the Calvin cycle.", SCI) == ["calvin"]


def test_shared_one_word_name() -> None:
    columbia = [
        alias("shuttle", SCI, weak=True, single=True, own_name=False),
        alias("university", "Social Science", weak=True, single=True),
    ]
    assert find({"columbia": columbia}, "He worked at Columbia.", SCI) == []
    brotherhood = [
        alias("local:brotherhood", LIT, weak=True, single=True),
        alias("order", "History", weak=True, single=True, own_name=False),
    ]
    assert find({"brotherhood": brotherhood}, "He joins the Brotherhood.") == ["local:brotherhood"]
    fifa = [
        alias("fifa", "Current Events", single=True, title=True),
        alias("tournament", "Pop Culture", weak=True, single=True, own_name=False),
    ]
    assert find({"fifa": fifa}, "It is run by FIFA.", "Sports") == ["fifa"]


def test_score_edges_discounts_topics_named_everywhere() -> None:
    forward = {
        ("soccer", "fifa"): {"q1", "q2"},
        ("soccer", "france"): {"q1", "q2"},
        ("wine", "france"): {"q3"},
        ("art", "france"): {"q4"},
    }
    edges = relate.score_edges(forward, n_topics=100, reverse_weight=0.5)
    assert edges[("soccer", "fifa")][0] > edges[("soccer", "france")][0]
    assert edges[("fifa", "soccer")] == (pytest.approx(0.5 * 1.0986 * 4.6052, rel=1e-3), 0, 2)


def test_hub_topics_must_earn_their_place() -> None:
    assert not relate.is_strong_hub_link(2, 5)  # "American" in two questions of a novel
    assert not relate.is_strong_hub_link(5, 100)
    assert relate.is_strong_hub_link(30, 100)  # France in Napoleon's questions
