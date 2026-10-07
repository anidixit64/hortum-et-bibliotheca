import httpx
import respx
from fastapi.testclient import TestClient

from gateway.main import app


@respx.mock
def test_routes_to_catalog_and_forwards_request_id() -> None:
    route = respx.get("http://localhost:8001/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    with TestClient(app) as client:
        resp = client.get("/api/catalog/search", headers={"X-Request-ID": "rid-1"})

    assert resp.status_code == 200
    assert resp.json() == []
    assert route.calls.last.request.headers["X-Request-ID"] == "rid-1"


def test_unknown_upstream_is_404() -> None:
    with TestClient(app) as client:
        assert client.get("/api/nope/x").status_code == 404


@respx.mock
def test_unreachable_upstream_is_502() -> None:
    respx.get("http://localhost:8003/stats").mock(side_effect=httpx.ConnectError("down"))
    with TestClient(app) as client:
        assert client.get("/api/study/stats").status_code == 502
