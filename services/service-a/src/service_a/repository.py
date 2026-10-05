from functools import lru_cache
from uuid import UUID

from service_a.models import Item, ItemCreate


class InMemoryItemRepository:
    """Placeholder storage. Swap for a real database-backed repository."""

    def __init__(self) -> None:
        self._items: dict[UUID, Item] = {}

    def list(self) -> list[Item]:
        return list(self._items.values())

    def get(self, item_id: UUID) -> Item | None:
        return self._items.get(item_id)

    def add(self, data: ItemCreate) -> Item:
        item = Item(**data.model_dump())
        self._items[item.id] = item
        return item


@lru_cache
def get_repository() -> InMemoryItemRepository:
    return InMemoryItemRepository()
