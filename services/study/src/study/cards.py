"""Flashcards built from a topic's record and from missed buzzes."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hortum_common.text import normalize

REVERSE_CLUES = 3  # "Name 3 clues for Invisible Man"


@dataclass(frozen=True)
class NewCard:
    card_id: str
    topic_id: str
    kind: str  # clue | reverse | missed
    front: str
    back: str
    source_ref: dict[str, Any]


def card_id(topic_id: str, kind: str, text: str) -> str:
    """Stable across corpus rebuilds: the topic and the card's own normalized text."""
    key = f"{topic_id}|{kind}|{normalize(text)}"
    return hashlib.sha1(key.encode()).hexdigest()


def topic_cards(record: dict[str, Any]) -> list[NewCard]:
    """Clue -> answer for each ranked clue, plus one answer -> clues card."""
    topic = record["topic"]
    tid, name = topic["id"], topic["name"]
    out = [
        NewCard(
            card_id(tid, "clue", clue["text"]),
            tid,
            "clue",
            clue["text"],
            f"{name}\n{clue['label']}",
            {"cluster_id": clue["cluster_id"], "rank": clue["rank"]},
        )
        for clue in record["clues"]
    ]
    labels = [clue["label"] for clue in record["clues"][:REVERSE_CLUES]]
    if len(labels) == REVERSE_CLUES:
        front = f"Name {REVERSE_CLUES} clues for {name}"
        out.append(
            NewCard(card_id(tid, "reverse", front), tid, "reverse", front, "\n".join(labels),
                    {"clusters": [c["cluster_id"] for c in record["clues"][:REVERSE_CLUES]]})
        )  # fmt: skip
    return out


def missed_card(topic_id: str, answer: str, clue_text: str, ref: dict[str, Any]) -> NewCard:
    """A clue read before a wrong or late buzz: front is the clue as it was read."""
    return NewCard(
        card_id(topic_id, "missed", clue_text), topic_id, "missed", clue_text, answer, ref
    )


def to_row(card: NewCard, now: str) -> tuple[object, ...]:
    return (
        card.card_id, card.topic_id, card.kind, card.front, card.back,
        json.dumps(card.source_ref), now,
    )  # fmt: skip
