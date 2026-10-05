from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class Item(ItemCreate):
    id: UUID = Field(default_factory=uuid4)
