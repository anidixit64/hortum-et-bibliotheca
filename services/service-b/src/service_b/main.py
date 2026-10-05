from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from hortum_common import create_app
from service_b import routes
from service_b.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(
        base_url=settings.service_a_url, timeout=settings.http_timeout_seconds
    ) as client:
        app.state.service_a_http = client
        yield


app = create_app(settings, [routes.router], lifespan=lifespan)
