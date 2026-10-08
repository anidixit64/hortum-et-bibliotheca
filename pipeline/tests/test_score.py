from collections import Counter

import pytest

from hortum_pipeline import score
from hortum_pipeline.score import ClusterStats, Weights


def stats(n_sets: int, position: float, terms: list[str] | None = None) -> ClusterStats:
    s = ClusterStats(0, "t", "representative clue text here", terms or [])
    s.positions = [position] * n_sets
    s.in_power = [1] * n_sets
    s.sets = {f"set{i}" for i in range(n_sets)}
    return s


def test_common_mid_question_clue_beats_rare_early_one() -> None:
    """The tracer case: Ras the Exhorter (38 sets, 62%) vs Sybil (6 sets, 0%)."""
    w = Weights()
    assert score.impact(stats(38, 0.62), 1.0, w) > score.impact(stats(6, 0.0), 1.0, w)


def test_earlier_is_better_at_equal_frequency() -> None:
    w = Weights()
    assert score.impact(stats(5, 0.1), 1.0, w) > score.impact(stats(5, 0.7), 1.0, w)


def test_pick_orders_by_sets_then_questions_then_position() -> None:
    a, b, c, d = stats(38, 0.62), stats(6, 0.0), stats(6, 0.5), stats(6, 0.1)
    for cid, s in enumerate((a, b, c, d), start=1):
        s.cluster_id = cid
        s.tossups = {f"q{i}" for i in range(len(s.sets))}
    c.tossups.add("extra")  # same sets as b and d, one more question
    assert score.pick([b, c, d, a], 50) == [1, 3, 2, 4]


@pytest.mark.parametrize(("n", "k"), [(1, 10), (10, 10), (32, 15), (100, 20), (5000, 20)])
def test_pick_count_grows_with_the_topic(n: int, k: int) -> None:
    assert score.pick_count(n) == k


def test_pick_takes_at_most_pick_count() -> None:
    many = []
    for i in range(30):
        s = stats(30 - i, 0.5)
        s.cluster_id = i
        many.append(s)
    assert score.pick(many, 10) == list(range(10))
    assert len(score.pick(many, 1000)) == 20


@pytest.mark.parametrize(
    ("difficulty", "band"),
    [(0, "unrated"), (1, "middle_school"), (3, "high_school"), (8, "college"), (10, "open")],
)
def test_difficulty_bands(difficulty: int, band: str) -> None:
    assert score.difficulty_band(difficulty) == band


def test_position_hist_and_trend() -> None:
    assert score.position_hist([0.0, 0.05, 0.95, 1.0]) == [2, 0, 0, 0, 0, 0, 0, 0, 0, 2]
    topic_years = list(range(2000, 2024))
    assert score.trend([2021, 2022, 2023], topic_years) == "rising"
    assert score.trend([2000, 2001, 2002], topic_years) == "fading"
    assert score.trend([2000, 2012, 2023], topic_years) == "steady"


def test_self_reference_and_display_label() -> None:
    assert score.is_self_reference(["Invisible Man"], {"invisible man", "ralph ellison"})
    assert not score.is_self_reference(["Ras the Exhorter"], {"invisible man"})
    vague = Counter({"peace": 500, "chance for peace": 3})
    assert (
        score.display_label(stats(3, 0.2, ["Peace", "Chance for Peace"]), vague)
        == "Chance for Peace"
    )
    assert score.display_label(stats(3, 0.2, ["Peace"]), vague) == "representative clue text here"
