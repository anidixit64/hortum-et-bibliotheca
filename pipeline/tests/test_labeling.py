import pytest

from hortum_pipeline import labeling, phrases


def always(term: str) -> bool:
    return True


BACKGROUND = (
    [f"The manner of the idol in clue {i}." for i in range(200)]
    + [f"This planet orbits a star in clue {i}." for i in range(50)]
    + [f"Mexican food was served in clue {i}." for i in range(100)]
)
FREQ = phrases.DocFrequency(BACKGROUND)


def test_tidy_rejects_numbers_long_quotes_and_fragments() -> None:
    assert labeling.tidy("Hammond's") == "Hammond"
    assert labeling.tidy("1420") is None
    assert labeling.tidy("there is no Hindu, there is no Muslim") is None
    assert labeling.tidy("stream of") is None
    assert labeling.tidy("is theft") is None
    assert labeling.tidy("SU") is None
    assert labeling.tidy("“Spiritus Mundi”") == "Spiritus Mundi"


@pytest.mark.parametrize(
    ("term", "texts", "title"),
    [
        (
            "Mysterious Affair",
            ["Her first was The Mysterious Affair at Styles."],
            "Mysterious Affair at Styles",
        ),
        (
            "Hanged Man",
            ["He painted The House of the Hanged Man in Auvers."],
            "House of the Hanged Man",
        ),
        ("Blind Mice", ["She wrote Three Blind Mice, later The Mousetrap."], "Three Blind Mice"),
        ("Edict", ["Diocletian issued the Edict on Maximum Prices."], "Edict on Maximum Prices"),
        ("Nelson Miles", ["Nelson Miles accepted his surrender."], "Nelson Miles"),
        (
            "Mysterious Affair",
            ["In Christie's The Mysterious Affair at Styles, a man dies."],
            "Mysterious Affair at Styles",
        ),
    ],
)
def test_complete_title(term: str, texts: list[str], title: str) -> None:
    assert labeling.complete_title(term, texts) == title


def test_the_label_is_what_most_clues_share() -> None:
    """Mitsunobu tops one clue's terms but the cluster is about alkyl halides via Lucas."""
    texts = [
        "Treating this compound with the Lucas reagent gives an alkyl halide.",
        "The Lucas test distinguishes classes of these compounds by turbidity.",
        "The Mitsunobu reaction inverts these compounds' stereocenters.",
    ]
    terms = [["Lucas"], ["Lucas"], ["Mitsunobu"]]
    choice = labeling.choose(texts, terms, always, FREQ)
    assert choice is not None and choice.label == "Lucas" and choice.core == [0, 1]


def test_plurals_and_pronunciations_dont_split_a_label() -> None:
    words = labeling.word_set(labeling.clean("The womb chambers [WOOM CHAYM-burz] of these"))
    assert labeling.names(words, "womb chamber")


def test_without_a_shared_term_it_asks_for_noun_phrases() -> None:
    texts = [
        "Circumambulation rituals in these structures are done clockwise.",
        "Pilgrims perform circumambulation rituals around these structures.",
    ]
    assert labeling.choose(texts, [[], []], always, FREQ) is None


@pytest.fixture(scope="module")
def parse() -> phrases.Parser:
    pytest.importorskip("en_core_web_sm")
    return phrases.load_parser()


def test_noun_phrase_label_and_core(parse: phrases.Parser) -> None:
    texts = [
        "The innermost womb chamber of these buildings holds the idol.",
        "Offerings are made inside the womb chamber of these buildings.",
        "Pilgrims walk around these buildings in a clockwise manner.",
    ]
    freq = phrases.DocFrequency(
        texts + [f"The manner of the idol in clue {i}." for i in range(200)]
    )
    choice = labeling.choose(texts, [[], [], []], always, freq, list(parse(texts)))
    assert choice is not None
    assert (choice.label, choice.core, choice.source) == ("womb chamber", [0, 1], "phrase")


def test_a_specific_label_beats_a_slightly_commoner_vague_one() -> None:
    """Geronimo: "Casa Grande" (3 clues) over "Mexicans" (4)."""
    texts = [
        "His followers were massacred at Casa Grande by Mexican troops.",
        "Mexican soldiers attacked his camp at Casa Grande.",
        "His family was killed at Casa Grande by Mexican forces.",
        "Mexican troops pursued him into the Sierra Madre.",
    ]
    terms = [["Casa Grande", "Mexican"], ["Mexican", "Casa Grande"], ["Casa Grande"], ["Mexican"]]
    choice = labeling.choose(texts, terms, always, FREQ)
    assert choice is not None and choice.label == "Casa Grande"


def test_stand_ins_are_not_labels() -> None:
    assert labeling.plain_word("planet", FREQ)  # "this planet" in 50 clues
    assert not labeling.plain_word("Caloris Basin", FREQ)


@pytest.mark.parametrize(
    ("texts", "label", "grown"),
    [
        (
            ["Batesian mimicry protects prey.", "Batesian mimicry and aposematism."],
            "Batesian",
            "Batesian mimicry",
        ),
        (["In Buck v. Bell, he wrote.", "He wrote Buck v. Bell."], "Buck", "Buck v. Bell"),
        (
            [
                "He led the Commission for Relief in Belgium.",
                "The Commission for Relief in Belgium fed millions.",
            ],
            "Relief",
            "Commission for Relief in Belgium",
        ),
        (
            ["Nelson Miles accepted it.", "He surrendered to Nelson Miles."],
            "Nelson Miles",
            "Nelson Miles",
        ),
        (["Batesian mimicry protects prey."], "Batesian", "Batesian"),  # one clue isn't enough
    ],
)
def test_grow(texts: list[str], label: str, grown: str) -> None:
    assert labeling.grow(texts, label) == grown


def test_surface_prefers_the_singular() -> None:
    texts = [
        "A trophic cascade results.",
        "Trophic cascades occur.",
        "This causes a trophic cascade.",
    ]
    assert labeling.surface("trophic cascades", texts) == "trophic cascade"


def test_negated_clues_dont_count() -> None:
    assert labeling.negated("It's not serine, but it is a substrate.", "serine")
    assert not labeling.negated("Serine is converted to it.", "serine")


def test_generic_lowercase_words_are_plain() -> None:
    freq = phrases.DocFrequency([f"the key to the cities of clue {i}" for i in range(2000)])
    assert labeling.plain_word("cities", freq)
    assert not labeling.plain_word("LIGO", freq)
