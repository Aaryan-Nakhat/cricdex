"""Smoke tests for the API routes: health + NGI metrics.

NGI uses the cached JSON if present, otherwise skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from fastapi.testclient import TestClient  # noqa: E402

from cricdex.api.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_metrics_ngi_returns_rows_if_cached(client):
    cached = Path("data/metrics/ngi_ipl.json")
    if not cached.exists():
        pytest.skip("no cached NGI JSON")
    r = client.get("/v1/metrics/ngi", params={"collection": "ipl", "top_n": 5, "min_matches": 20})
    assert r.status_code == 200
    payload = r.json()
    assert payload["collection"] == "ipl"
    assert len(payload["rows"]) == 5
    for row in payload["rows"]:
        assert "name" in row
        assert "ngi_per_match" in row
