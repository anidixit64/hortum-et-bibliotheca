import httpx
from fastapi.testclient import TestClient

from service_b.clients import get_service_a
from service_b.main import app


class FakeServiceA:
    def __init__(self, count: int | None) -> None:
        self.count = count

    async def count_items(self) -> int:
        if self.count is None:
            raise httpx.ConnectError("down")
        return self.count


def test_summary_counts_items() -> None:
    app.dependency_overrides[get_service_a] = lambda: FakeServiceA(3)
    with TestClient(app) as client:
        assert client.get("/summary").json()["item_count"] == 3


def test_summary_502_when_service_a_down() -> None:
    app.dependency_overrides[get_service_a] = lambda: FakeServiceA(None)
    with TestClient(app) as client:
        assert client.get("/summary").status_code == 502
