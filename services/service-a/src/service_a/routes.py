from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from service_a.models import Item, ItemCreate
from service_a.repository import InMemoryItemRepository, get_repository

router = APIRouter(prefix="/items", tags=["items"])
Repo = Annotated[InMemoryItemRepository, Depends(get_repository)]


@router.get("")
async def list_items(repo: Repo) -> list[Item]:
    return repo.list()


@router.get("/{item_id}")
async def get_item(item_id: UUID, repo: Repo) -> Item:
    item = repo.get(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return item


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_item(data: ItemCreate, repo: Repo) -> Item:
    return repo.add(data)
