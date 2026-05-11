from fastapi.testclient import TestClient

from cricdex import __version__
from cricdex.api.main import app


def test_version_is_string():
    assert isinstance(__version__, str)


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
