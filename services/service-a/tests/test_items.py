from fastapi.testclient import TestClient

from service_a.main import app
from service_a.repository import InMemoryItemRepository, get_repository


def make_client() -> TestClient:
    repo = InMemoryItemRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def test_create_then_fetch_item() -> None:
    client = make_client()
    created = client.post("/items", json={"name": "widget"})
    assert created.status_code == 201

    item_id = created.json()["id"]
    assert client.get(f"/items/{item_id}").json()["name"] == "widget"
    assert len(client.get("/items").json()) == 1


def test_missing_item_is_404() -> None:
    client = make_client()
    assert client.get("/items/00000000-0000-0000-0000-000000000000").status_code == 404


def test_rejects_empty_name() -> None:
    assert make_client().post("/items", json={"name": ""}).status_code == 422
