from fastapi.testclient import TestClient

from hortum_common import ServiceSettings, create_app


async def _not_ready() -> bool:
    return False


def test_healthz_and_request_id() -> None:
    client = TestClient(create_app(ServiceSettings(service_name="t")))
    resp = client.get("/healthz", headers={"X-Request-ID": "abc"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "abc"


def test_readyz_fails_when_check_fails() -> None:
    app = create_app(ServiceSettings(service_name="t"), readiness_checks=[_not_ready])
    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 503
