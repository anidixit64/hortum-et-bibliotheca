from collections import Counter

import numpy as np
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


def test_last_line_bonus_lifts_clues_just_before_the_giveaway() -> None:
    lead_in, last_line = stats(5, 0.1), stats(5, 0.7)
    last_line.last_line = [1] * 5
    assert score.impact(last_line, 1.0, Weights()) < score.impact(lead_in, 1.0, Weights())
    w = Weights(last_line_bonus=0.5)
    assert score.impact(last_line, 1.0, w) > score.impact(lead_in, 1.0, w)


def test_pick_measures_redundancy_against_the_topic_baseline() -> None:
    # Three clusters all fairly alike (same topic); 1 and 2 are near-duplicates.
    v = {1: np.array([1.0, 0.0]), 2: np.array([0.999, 0.045]), 3: np.array([0.8, 0.6])}
    v = {k: x / np.linalg.norm(x) for k, x in v.items()}
    picks = score.pick([(1, 3.0), (2, 2.9), (3, 2.0)], v, Weights(mmr_lambda=0.5))
    assert picks[:2] == [1, 3]  # the near-duplicate waits


def test_pick_returns_at_most_ten() -> None:
    v = {i: np.eye(12)[i] for i in range(12)}
    assert len(score.pick([(i, 1.0) for i in range(12)], v, Weights())) == 10


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
