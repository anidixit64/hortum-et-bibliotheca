import asyncio
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from gateway.config import Settings, get_settings
from hortum_common.context import REQUEST_ID_HEADER, request_id_var

log = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY = 0.3

# Headers that describe a single hop and must not be forwarded.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

router = APIRouter(tags=["proxy"])


def get_http_client(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.http
    return client


@router.api_route(
    "/api/{upstream}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(
    upstream: str,
    path: str,
    request: Request,
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    base_url = settings.upstreams().get(upstream)
    if base_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown upstream {upstream!r}")

    skip = HOP_BY_HOP | {REQUEST_ID_HEADER.lower()}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}
    if request_id := request_id_var.get():
        headers[REQUEST_ID_HEADER] = request_id

    url = f"{base_url.rstrip('/')}/{path}"
    body = await request.body()
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            upstream_resp = await client.request(
                request.method,
                url,
                params=request.query_params,
                headers=headers,
                content=body,
            )
            break
        except httpx.RequestError as exc:
            last_exc = exc
            log.warning(
                "upstream %s unreachable (attempt %d/%d): %s %s — %s",
                upstream, attempt, _MAX_RETRIES, request.method, path, exc,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY)
    else:
        log.error("upstream %s failed after %d attempts: %s %s", upstream, _MAX_RETRIES, request.method, path)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{upstream} unavailable") from last_exc

    # httpx already decoded the body, so drop content-encoding along with hop-by-hop headers.
    resp_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() not in HOP_BY_HOP | {"content-encoding"}
    }
    return Response(upstream_resp.content, upstream_resp.status_code, resp_headers)
