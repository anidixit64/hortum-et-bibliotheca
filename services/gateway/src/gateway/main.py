from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from gateway import proxy
from gateway.config import get_settings
from hortum_common import create_app

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        app.state.http = client
        yield


app = create_app(settings, [proxy.router], lifespan=lifespan)
