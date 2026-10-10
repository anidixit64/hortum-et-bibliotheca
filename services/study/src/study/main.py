import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from hortum_common import create_app
from study import db, routes
from study.backup import nightly
from study.catalog import Catalog
from study.config import Settings, get_settings


def build_app(settings: Settings, catalog_client: httpx.AsyncClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = catalog_client or httpx.AsyncClient(
            base_url=settings.catalog_url, timeout=settings.catalog_timeout_seconds
        )
        app.state.catalog = Catalog(client)
        task = None
        if settings.backup_dir is not None:
            task = asyncio.create_task(
                nightly(settings.db_path, settings.backup_dir, settings.backups_kept,
                        settings.backup_hour_utc)
            )  # fmt: skip
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if catalog_client is None:
                await client.aclose()

    app = create_app(settings, [routes.router], lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db.connect(settings.db_path)
    return app


app = build_app(get_settings())
