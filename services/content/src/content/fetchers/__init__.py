"""Fetchers: each turns a topic into one kind of enrichment, independently of the others."""

from dataclasses import dataclass, field
from typing import Any


class Unavailable(Exception):
    """This kind can't be fetched for this topic (no article, no API key): not a failure."""


@dataclass
class Topic:
    id: str
    name: str
    wikipedia_title: str | None
    wikidata_qid: str | None
    category: str | None
    description: str | None
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Topic":
        t = record["topic"]
        return cls(
            t["id"],
            t["name"],
            t.get("wikipedia_title"),
            t.get("wikidata_qid"),
            t.get("category"),
            t.get("description"),
            t.get("aliases", []),
        )
