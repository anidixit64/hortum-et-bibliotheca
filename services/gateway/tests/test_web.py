from pathlib import Path

from fastapi.testclient import TestClient

from gateway.config import Settings
from gateway.main import build_app


def test_serves_the_built_frontend_with_client_side_routes(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    with TestClient(build_app(Settings(web_dist=tmp_path))) as client:
        assert client.get("/").text == "<div id=root></div>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/topic/Q1784288").text == "<div id=root></div>"
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/nope/x").status_code == 404
        assert client.get("/../pyproject.toml").text == "<div id=root></div>"


def test_without_a_build_the_gateway_is_api_only() -> None:
    with TestClient(build_app(Settings(web_dist=None))) as client:
        assert client.get("/topic/Q1").status_code == 404
