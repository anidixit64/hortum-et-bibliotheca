from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from gateway import proxy
from gateway.config import Settings, get_settings
from gateway.web import web_router
from hortum_common import create_app


def build_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            app.state.http = client
            yield

    routers = [proxy.router]
    if settings.web_dist is not None and (settings.web_dist / "index.html").is_file():
        routers.append(web_router(settings.web_dist))  # last: API and health routes win
    return create_app(settings, routers, lifespan=lifespan)


app = build_app(get_settings())
