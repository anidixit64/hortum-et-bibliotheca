"""Serves the built frontend: files as they are, every other path as index.html."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse


def web_router(dist: Path) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    root = dist.resolve()

    @router.get("/{path:path}")
    def frontend(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        # A client-side route (/topic/Q1784288): the app decides what to show.
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return router
