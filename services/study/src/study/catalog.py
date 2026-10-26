"""Reads topics and questions from the catalog service: study owns only study.db."""

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY = 0.3


class CatalogError(Exception):
    pass


class Catalog:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def _get(self, path: str) -> dict[str, Any] | None:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await self.client.get(path)
                if response.status_code == 404:
                    return None
                if response.is_error:
                    raise CatalogError(f"catalog answered {response.status_code}")
                data: dict[str, Any] = response.json()
                return data
            except httpx.RequestError as exc:
                last_exc = exc
                log.warning(
                    "catalog unreachable (attempt %d/%d): GET %s — %s",
                    attempt, _MAX_RETRIES, path, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY)
        log.error("catalog failed after %d attempts: GET %s", _MAX_RETRIES, path)
        raise CatalogError("catalog unavailable") from last_exc

    async def topic(self, topic_id: str) -> dict[str, Any] | None:
        return await self._get(f"/topics/{topic_id}")

    async def filing(self, topic_id: str) -> dict[str, Any] | None:
        """Category, the usual subcategory, and typical difficulty for a topic's cards."""
        return await self._get(f"/topics/{topic_id}/filing")

    async def tossup(self, tossup_id: str) -> dict[str, Any] | None:
        return await self._get(f"/tossups/{tossup_id}")
