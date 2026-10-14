from hortum_pipeline.snapshot import _balanced_page, arrange_clues
from hortum_pipeline.terms import rare_early_boost


def clue(rank: int, category: str, n: int = 1) -> dict:
    return {
        "rank": rank,
        "cluster_id": rank,
        "label": f"{category} {rank}",
        "categories": {category: n},
    }


def test_rare_early_clues_get_a_small_boost() -> None:
    assert rare_early_boost(2, 0.1) == 0.5
    assert rare_early_boost(1, 0.0) == 0.5
    assert rare_early_boost(2, 0.5) == 0  # late rare clues stay late
    assert rare_early_boost(8, 0.05) == 0  # common clues aren't boosted


def test_balanced_page_round_robins_categories() -> None:
    clues = [clue(i, "History") for i in range(1, 9)] + [
        clue(9, "Politics"),
        clue(10, "Politics"),
        clue(11, "Geography"),
        clue(12, "Geography"),
    ]
    page = _balanced_page(clues, 6)
    cats = [max(c["categories"]) for c in page]
    assert cats.count("History") == 2
    assert cats.count("Politics") == 2
    assert cats.count("Geography") == 2


def test_single_category_keeps_rank_order() -> None:
    clues = [clue(i, "Literature") for i in range(1, 12)]
    assert [c["rank"] for c in _balanced_page(clues, 10)] == list(range(1, 11))


def test_show_more_does_not_repeat_page_clues() -> None:
    clues = [clue(i, "History") for i in range(1, 8)] + [clue(8, "Politics"), clue(9, "Politics")]
    ordered = arrange_clues(clues, 4)
    page, rest = ordered[:4], ordered[4:]
    assert {c["cluster_id"] for c in page}.isdisjoint({c["cluster_id"] for c in rest})
    assert len(ordered) == len(clues)
