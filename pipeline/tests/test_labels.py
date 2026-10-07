from pathlib import Path

from hortum_pipeline.labels import LabeledClue, load

LABELS = Path(__file__).parents[1] / "eval" / "labeled_clues.yaml"


def test_label_file_is_well_formed() -> None:
    topics = load(LABELS)
    assert len(topics) == 30
    assert len({t.id for t in topics}) == 30
    for topic in topics:
        assert 5 <= len(topic.clues) <= 15, topic.name
        for clue in topic.clues:
            assert clue.fact and clue.match, (topic.name, clue)


def test_matching_is_whole_word_and_case_insensitive() -> None:
    ras = LabeledClue("Ras the Exhorter", ("Ras",))
    assert ras.found_in("a riot led by ras the Destroyer")
    assert not ras.found_in("he walks across the grass")
    year = LabeledClue("1,369 bulbs", ("1,369",))
    assert year.found_in("burning 1,369 light bulbs")
