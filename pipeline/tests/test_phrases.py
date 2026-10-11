import pytest

from hortum_pipeline import phrases

CLUES = [
    "Circumambulation rituals in these structures are typically done in a clockwise manner.",
    "Most of these structures follow an 8-by-8 or a 9-by-9 square grid plan.",
    "Trees representing these constructs are often simplified using alpha-beta pruning.",
    "Some amorphous materials undergo a glass transition rather than this process.",
    "This substance is the typical reductant of silver ions.",
]
# Background so common words ("manner", "materials") look common and rare ones rare.
FILLER_CLUES = [f"The manner of the materials in clue {i} is a plan." for i in range(200)]


@pytest.fixture(scope="module")
def parse() -> phrases.Parser:
    pytest.importorskip("en_core_web_sm")
    return phrases.load_parser()


@pytest.fixture(scope="module")
def freq() -> phrases.DocFrequency:
    return phrases.DocFrequency(CLUES + FILLER_CLUES)


@pytest.mark.parametrize(
    ("clue", "phrase"),
    [
        (CLUES[0], "circumambulation rituals"),
        (CLUES[2], "alpha-beta pruning"),
        (CLUES[3], "glass transition"),
    ],
)
def test_candidates(
    parse: phrases.Parser, freq: phrases.DocFrequency, clue: str, phrase: str
) -> None:
    assert phrase in phrases.candidates(next(iter(parse([clue]))), freq)


def test_the_answer_itself_is_never_a_label(
    parse: phrases.Parser, freq: phrases.DocFrequency
) -> None:
    labels = phrases.candidates(next(iter(parse([CLUES[4]]))), freq)
    assert "substance" not in " ".join(labels)
    assert "silver ions" in labels
