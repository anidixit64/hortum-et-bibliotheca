from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status

ReadinessCheck = Callable[[], Awaitable[bool]]


def health_router(readiness_checks: list[ReadinessCheck] | None = None) -> APIRouter:
    """Liveness (/healthz) and readiness (/readyz) probes for orchestrators."""
    router = APIRouter(tags=["health"])
    checks = readiness_checks or []

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz(response: Response) -> dict[str, str]:
        for check in checks:
            if not await check():
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"status": "unavailable"}
        return {"status": "ready"}

    return router
