import pytest

from study.answers import judge

# Real answer lines, as the pipeline parses them.
INVISIBLE_MAN = {"main": "Invisible Man", "required": [], "accept": [], "prompt": [],
                 "reject": ["The Invisible Man"]}  # fmt: skip
BRAHMS = {"main": "Johannes Brahms", "required": ["Brahms"], "accept": [], "prompt": [],
          "reject": []}  # fmt: skip
DROSOPHILA = {"main": "Drosophila melanogaster", "required": [],
              "accept": ["D. melanogaster", "fruit fly"], "prompt": ["fly"],
              "reject": []}  # fmt: skip


@pytest.mark.parametrize(
    ("line", "given", "verdict"),
    [
        (INVISIBLE_MAN, "Invisible Man", "correct"),
        (INVISIBLE_MAN, "the invisible man", "incorrect"),  # a reject wins
        (INVISIBLE_MAN, "Invisable Man", "correct"),  # spelling slip
        (BRAHMS, "Brahms", "correct"),
        (BRAHMS, "Johannes Brahms", "correct"),
        (BRAHMS, "Johannes", "incorrect"),
        (DROSOPHILA, "fruit flies", "correct"),
        (DROSOPHILA, "fly", "prompt"),
        (DROSOPHILA, "mosquito", "incorrect"),
        (DROSOPHILA, "", "incorrect"),
    ],
)
def test_judge(line: dict, given: str, verdict: str) -> None:  # type: ignore[type-arg]
    assert judge(given, **line) == verdict
