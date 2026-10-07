from fastapi.testclient import TestClient

from study.config import Settings
from study.main import build_app


def test_healthz() -> None:
    client = TestClient(build_app(Settings()))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
