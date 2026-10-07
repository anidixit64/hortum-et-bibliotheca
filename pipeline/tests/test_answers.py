"""Real answer lines from the dump, with the parse we expect."""

import pytest

from hortum_pipeline.answers import line_key, parse_answer


def texts(alts: list) -> list[str]:
    return [a.text for a in alts]


@pytest.mark.parametrize(
    ("line", "main", "accept", "prompt", "reject"),
    [
        ("<b><u>Bali</u></b>", "Bali", [], [], []),
        ("<b><u>Tilted Arc</u></b> <MS>", "Tilted Arc", [], [], []),
        ("<b><u>Olympus Mons</u></b> (1) [AU]", "Olympus Mons", [], [], []),
        (
            "Leo <b><u>Tolstoy</u></b> [or Lev Nikolayevich <b><u>Tolstoy</u></b>] (The essay "
            "mentioned in the first line is Elif Batuman’s essay, which is a chapter.)",
            "Leo Tolstoy",
            ["Lev Nikolayevich Tolstoy"],
            [],
            [],
        ),
        (
            "<b><u>soldier</u></b>s [or member of the <b><u>military</u></b>; "
            "or <b><u>G.I.</u></b>]",
            "soldiers",
            ["member of the military", "G.I."],
            [],
            [],
        ),
        (
            "<b><u>Charlemagne</u></b> (accept <b><u>Charles The Great</u></b> or "
            "<b><u>Charles I</u></b> and prompt on “Charles” before “Charles”)",
            "Charlemagne",
            ["Charles The Great", "Charles I"],
            ["Charles"],
            [],
        ),
        (
            "<b><u>retinoic acid</u></b> or <b><u>RA</u></b> [do not accept “vitamin A”; "
            "do not accept “retinol”]",
            "retinoic acid",
            ["RA"],
            [],
            ["vitamin A", "retinol"],
        ),
        (
            "Peace of <b><u>Westphalia</u></b> [Treaty of <b><u>Westphalia</u></b>; or "
            "<b><u>Westfalischer</u></b> Friede]",
            "Peace of Westphalia",
            ["Treaty of Westphalia", "Westfalischer Friede"],
            [],
            [],
        ),
        (
            '<b><u>arousal</u></b> [or <b><u>being aroused</u></b>, prompt on "alertness"]',
            "arousal",
            ["being aroused"],
            ["alertness"],
            [],
        ),
        (
            "(Sultanate of) <b><u>Oman</u></b> [or Imamate of <b><u>Oman</u></b>] <Edited>",
            "Oman",
            ["Sultanate of Oman", "Imamate of Oman"],
            [],
            [],
        ),
        (
            "<b><u>Prohibition</u></b> (prompt on descriptions of “banning alcohol” or "
            "“banning drinking” before “alcohol” is read)",
            "Prohibition",
            [],
            ["banning alcohol", "banning drinking"],
            [],
        ),
        (
            "<b><u>E</u></b>lizabeth Barrett <b><u>Browning</u></b> [or Elizabeth "
            "<b><u>Barrett</u></b> Browning; prompt on <u>Browning</u>; reject “Robert Browning”]",
            "Elizabeth Barrett Browning",
            [],
            ["Browning"],
            ["Robert Browning"],
        ),
        (
            '"<b><u>Get Back</u></b>" [accept<i> The Beatles:</i> <i><b><u>Get Back</u></b></i>]',
            "Get Back",
            ["The Beatles: Get Back"],
            [],
            [],
        ),
        ("<i><b><u>The King and I</u> </b></i>", "The King and I", [], [], []),
        (
            "<b><u>dot product</u></b> [accept <b><u>scalar product</u></b>; accept "
            "<b><u>inner product</u></b> before mentioned]",
            "dot product",
            ["scalar product", "inner product"],
            [],
            [],
        ),
        (
            "Rembrandt (Harmenszoon) van Rijn [accept either underlined name]",
            "Rembrandt van Rijn",
            ["Rembrandt Harmenszoon van Rijn"],
            [],
            [],
        ),
        ("Nikolai [Vasilievich] Gogol", "Nikolai Gogol", ["Nikolai Vasilievich Gogol"], [], []),
        (
            "Patrick (Aloysius) Ewing (YOO-wing)",
            "Patrick Ewing",
            ["Patrick Aloysius Ewing"],
            [],
            [],
        ),
        (
            'ellipse [prompt on "oval"] Copyright 2016 SAGES Quizbowl Questions. '
            "All rights reserved.",
            "ellipse",
            [],
            ["oval"],
            [],
        ),
        (
            "field [accept rational domain until mentioned, prompt on commutative division algebra "
            "until mentioned]",
            "field",
            ["rational domain"],
            ["commutative division algebra"],
            [],
        ),
        (
            "<b><u>soccer</u></b> [or association <b><u>football</u></b>; "
            "accept football or futbol; "
            'prompt on World Cup by asking "of what sport?"]',
            "soccer",
            ["association football", "football", "futbol"],
            ["World Cup"],
            [],
        ),
    ],
)
def test_parse_real_lines(
    line: str, main: str, accept: list[str], prompt: list[str], reject: list[str]
) -> None:
    parsed = parse_answer(line)
    assert parsed.main == main
    assert texts(parsed.accept) == accept
    assert texts(parsed.prompt) == prompt
    assert texts(parsed.reject) == reject
    assert parsed.confidence >= 0.8, parsed.issues


def test_conditions_cover_the_whole_clause() -> None:
    parsed = parse_answer(
        "<b><u>combust</u></b>ion (accept <b><u>fir</u></b>e or <b><u>flam</u></b>e before "
        "“fire” is read)"
    )
    assert [(a.text, a.condition) for a in parsed.accept] == [
        ("fire", "before “fire” is read"),
        ("flame", "before “fire” is read"),
    ]


def test_required_parts_are_whole_words_only() -> None:
    assert parse_answer("Leo <b><u>Tolstoy</u></b>").required == ["Tolstoy"]
    assert parse_answer("<b><u>combust</u></b>ion").required == []  # partial word


@pytest.mark.parametrize(
    ("line", "issue"),
    [
        ("<b><u>temperature</u></b> [or <b><u>T</u></b>] AND <b><u>entropy</u></b>", "multi_part"),
        ("pilgrimages; do not accept or prompt on Hajj", "directive_in_main"),
        ("Catherine the Great (or Catherine II, prompt on “Catherine”]", "unbalanced_brackets"),
        ("", "empty_main"),
    ],
)
def test_odd_lines_get_low_confidence(line: str, issue: str) -> None:
    parsed = parse_answer(line)
    assert issue in parsed.issues
    assert parsed.confidence < 0.8


def test_line_key_ignores_whitespace() -> None:
    assert line_key("<b>X</b>  [or Y]") == line_key("<b>X</b> [or Y]")
