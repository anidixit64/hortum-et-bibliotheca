from pathlib import Path

from fastapi.testclient import TestClient

from catalog.config import Settings
from catalog.main import build_app


def test_live_but_not_ready_without_corpus(tmp_path: Path) -> None:
    client = TestClient(build_app(Settings(corpus_path=tmp_path / "missing.db")))
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_ready_once_corpus_exists(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.db"
    corpus.touch()
    client = TestClient(build_app(Settings(corpus_path=corpus)))
    assert client.get("/readyz").status_code == 200
