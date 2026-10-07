from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, FastAPI

from hortum_common.health import ReadinessCheck, health_router
from hortum_common.logging import configure_logging
from hortum_common.middleware import RequestContextMiddleware
from hortum_common.settings import ServiceSettings

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[Any]]


def create_app(
    settings: ServiceSettings,
    routers: Sequence[APIRouter] = (),
    *,
    version: str = "0.1.0",
    lifespan: Lifespan | None = None,
    readiness_checks: list[ReadinessCheck] | None = None,
) -> FastAPI:
    """Builds a FastAPI app with the conventions every service shares."""
    configure_logging(settings.service_name, settings.log_level, settings.log_json)

    app = FastAPI(title=settings.service_name, version=version, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router(readiness_checks))
    for router in routers:
        app.include_router(router)
    return app
