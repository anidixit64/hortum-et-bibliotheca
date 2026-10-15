from pathlib import Path

from fastapi.testclient import TestClient

from content.config import Settings
from content.main import build_app


def test_healthz() -> None:
    client = TestClient(build_app(Settings()))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_settings_accepts_pin_9480(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "content.db")  # type: ignore[call-arg]
    assert settings.admin_pin == "9480"
    client = TestClient(build_app(settings))
    assert client.get("/admin/usage").status_code == 403
    opened = client.get("/admin/usage", headers={"X-Admin-Pin": "9480"})
    assert opened.status_code == 200
    assert "providers" in opened.json()
    assert client.get("/admin/usage", headers={"X-Admin-Pin": "0000"}).status_code == 403
