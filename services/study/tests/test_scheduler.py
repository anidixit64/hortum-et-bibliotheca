from datetime import UTC, datetime, timedelta

from study import scheduler

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_better_ratings_push_the_card_further_out() -> None:
    dues = [scheduler.review(scheduler.new_state(NOW), r, NOW).due for r in (1, 2, 3, 4)]
    assert dues == sorted(dues)
    assert dues[3] - NOW >= timedelta(days=1)  # "easy" graduates the card


def test_repeated_good_reviews_grow_the_interval() -> None:
    card, when, gaps = scheduler.new_state(NOW), NOW, []
    for _ in range(5):
        card = scheduler.review(card, 3, when)
        gaps.append(card.due - when)
        when = card.due
    assert gaps[-1] > gaps[1] > timedelta(0)


def test_state_round_trips_through_json() -> None:
    card = scheduler.review(scheduler.new_state(NOW), 3, NOW)
    assert scheduler.loads(scheduler.dumps(card)).due == card.due
