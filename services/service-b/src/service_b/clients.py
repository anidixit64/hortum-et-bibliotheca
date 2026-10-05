import httpx
from fastapi import Request

from hortum_common.context import REQUEST_ID_HEADER, request_id_var


class ServiceAClient:
    """Typed client for service-a. Keeps HTTP details out of route handlers."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def count_items(self) -> int:
        headers = {}
        if request_id := request_id_var.get():
            headers[REQUEST_ID_HEADER] = request_id
        resp = await self._http.get("/items", headers=headers)
        resp.raise_for_status()
        return len(resp.json())


def get_service_a(request: Request) -> ServiceAClient:
    return ServiceAClient(request.app.state.service_a_http)
