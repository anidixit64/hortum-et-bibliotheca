"""Reads topics and questions from the catalog service: study owns only study.db."""

from typing import Any

import httpx


class CatalogError(Exception):
    pass


class Catalog:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def _get(self, path: str) -> dict[str, Any] | None:
        try:
            response = await self.client.get(path)
        except httpx.RequestError as exc:
            raise CatalogError("catalog unavailable") from exc
        if response.status_code == 404:
            return None
        if response.is_error:
            raise CatalogError(f"catalog answered {response.status_code}")
        data: dict[str, Any] = response.json()
        return data

    async def topic(self, topic_id: str) -> dict[str, Any] | None:
        return await self._get(f"/topics/{topic_id}")

    async def tossup(self, tossup_id: str) -> dict[str, Any] | None:
        return await self._get(f"/tossups/{tossup_id}")
