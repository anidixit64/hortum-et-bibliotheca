"""Spaced repetition with FSRS, the algorithm Anki uses (the ``fsrs`` package)."""

import json
from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler

_scheduler = Scheduler()


def new_state(now: datetime | None = None) -> Card:
    """A fresh card, due now."""
    card = Card()
    card.due = now or datetime.now(UTC)
    return card


def review(state: Card, rating: int, now: datetime | None = None) -> Card:
    """The card after a review rated 1 (again) to 4 (easy)."""
    updated, _ = _scheduler.review_card(state, Rating(rating), review_datetime=now)
    return updated


def dumps(card: Card) -> str:
    return json.dumps(card.to_dict())


def loads(text: str) -> Card:
    return Card.from_dict(json.loads(text))
