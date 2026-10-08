import pytest

from hortum_pipeline.clues import clean_question, key_terms, split_question


def texts(question: str) -> list[str]:
    return [c.text for c in split_question(question).clues]


def test_power_mark_is_removed_and_located() -> None:
    clean, power = clean_question("He was expelled by Dr. (*) Bledsoe. For 10 points, name him.")
    assert clean == "He was expelled by Dr. Bledsoe. For 10 points, name him."
    assert power is not None and clean[power:].startswith("Bledsoe")


@pytest.mark.parametrize(
    "question",
    [
        "He studied under T. H. Morgan at Columbia. For 10 points, name this fly.",
        "He met W.E.B. Du Bois in Atlanta. For 10 points, name this man.",
        "It premiered in St. Petersburg in 1890. For 10 points, name this ballet.",
        "He wrote Symphony No. 3 in Vienna. For 10 points, name this composer.",
        'Victor sings "Ah! Si tu savais!" in the third act. For 10 points, name this opera.',
    ],
)
def test_abbreviations_initials_and_quoted_exclamations_do_not_split(question: str) -> None:
    assert len(texts(question)) == 2


def test_single_letter_ends_a_sentence_before_a_clear_starter() -> None:
    parts = texts(
        "It is a cofactor of vitamin K. This element clots blood. For 10 points, name it."
    )
    assert parts[0] == "It is a cofactor of vitamin K."
    assert parts[1] == "This element clots blood."


def test_giveaway_and_everything_after_it() -> None:
    layout = split_question("Clue one is here. For 10 points, name this. Extra sentence here.")
    assert [c.kind for c in layout.clues] == ["clue", "giveaway", "giveaway"]


def test_mid_sentence_giveaway_takes_the_whole_sentence() -> None:
    layout = split_question(
        'Its narrator lives underground. A "Battle Royale" scene occurs in, for 10 points, '
        "what novel?"
    )
    assert [c.kind for c in layout.clues] == ["clue", "giveaway"]
    assert layout.clues[1].text.startswith('A "Battle Royale"')


def test_one_sentence_question_keeps_the_clue_before_the_giveaway() -> None:
    layout = split_question('A "Battle Royale" scene occurs in, for 10 points, what novel?')
    assert [(c.kind, c.text) for c in layout.clues] == [
        ("clue", 'A "Battle Royale" scene occurs in'),
        ("giveaway", "for 10 points, what novel?"),
    ]


@pytest.mark.parametrize("phrase", ["For 15 points", "For the point", "For ten points", "FTP"])
def test_other_giveaway_phrases(phrase: str) -> None:
    layout = split_question(f"Clue one is here. Clue two is here. {phrase}, name this man.")
    assert [c.kind for c in layout.clues] == ["clue", "clue", "giveaway"]


def test_without_a_giveaway_phrase_the_last_sentence_gives_it_away() -> None:
    layout = split_question("Clue one is here. Name this Italian artist who painted it.")
    assert [c.kind for c in layout.clues] == ["clue", "giveaway"]


def test_moderator_notes_and_instructions_are_notes() -> None:
    layout = split_question(
        'NOTE TO MODERATOR: "Hox" rhymes with "socks". Two answers required. '
        "This gene is famous. For 10 points, name it."
    )
    assert [c.kind for c in layout.clues] == ["note", "note", "clue", "giveaway"]


def test_long_sentences_split_at_semicolons() -> None:
    half = " ".join(["word"] * 25)
    layout = split_question(f"{half}; {half}. For 10 points, name it.")
    assert [c.kind for c in layout.clues] == ["clue", "clue", "giveaway"]


def test_spans_word_indices_and_power_flags() -> None:
    question = "First clue sits here. Second (*) clue sits here. For 10 points, name it."
    layout = split_question(question)
    for clue in layout.clues:
        assert layout.clean_text[clue.char_start : clue.char_end] == clue.text
        words = layout.clean_text.split(" ")[clue.word_start : clue.word_end]
        assert " ".join(words) == clue.text
    assert layout.power_word == 5  # "clue" in "Second clue sits here."
    assert [c.in_power for c in layout.clues] == [True, True, False]


def test_key_terms() -> None:
    terms = key_terms(
        'Alfred Sturtevant ("STUR-tuh-vant") worked in a "room" at Columbia run by T. H. '
        "Morgan, burning 1,369 bulbs."
    )
    assert terms == ["room", "Alfred Sturtevant", "Columbia", "T. H. Morgan", "1,369"]
    assert key_terms("Mutagenesis in this organism uses P elements.") == []


def test_pronunciation_guides_are_not_key_terms() -> None:
    assert "oh-oh-cyte" not in key_terms('Bicoid is unequal in the oocytes ["oh-oh-cyte"] of it.')
    assert "STUR-tuh-vant" not in key_terms('Alfred Sturtevant ("STUR-tuh-vant") drew a map.')
    assert "Battle Royale" in key_terms('A "Battle Royale" scene occurs in it.')
