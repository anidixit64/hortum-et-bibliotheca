from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from service_b.clients import ServiceAClient, get_service_a

router = APIRouter(tags=["summary"])


class Summary(BaseModel):
    item_count: int
    generated_at: datetime


@router.get("/summary")
async def summary(service_a: Annotated[ServiceAClient, Depends(get_service_a)]) -> Summary:
    try:
        count = await service_a.count_items()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "service-a unavailable") from exc
    return Summary(item_count=count, generated_at=datetime.now(UTC))
