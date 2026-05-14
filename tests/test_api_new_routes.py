"""Smoke tests for the new API routes: NGI, auction recommend, scout twins,
scout find-replacement.

Graph-backed routes skip if Neo4j isn't reachable; NGI uses the cached
JSON if present, falls back to a live fit otherwise.
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


def _neo4j_alive() -> bool:
    try:
        from neo4j.exceptions import ServiceUnavailable

        from cricdex.scout.graph.schema import driver

        drv = driver()
        try:
            with drv.session() as s:
                s.run("RETURN 1").consume()
            return True
        finally:
            drv.close()
    except ServiceUnavailable:
        return False
    except Exception:
        return False


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


@pytest.mark.skipif(not _neo4j_alive(), reason="needs populated Neo4j")
def test_scout_twins_co_faced(client):
    r = client.get("/v1/scout/twins/V Kohli", params={"mode": "co_faced", "top_k": 5})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows
    expected = {"RG Sharma", "S Dhawan", "MS Dhoni", "RA Jadeja", "AM Rahane"}
    assert {row["name"] for row in rows} & expected


@pytest.mark.skipif(not _neo4j_alive(), reason="needs populated Neo4j")
def test_scout_twins_teammates(client):
    r = client.get("/v1/scout/twins/MS Dhoni", params={"mode": "teammates", "top_k": 3})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows and rows[0]["name"] == "RA Jadeja"


@pytest.mark.skipif(not _neo4j_alive(), reason="needs populated Neo4j")
def test_scout_find_replacement(client):
    r = client.get(
        "/v1/scout/find-replacement/JJ Bumrah",
        params={
            "role": "bowler",
            "max_balls_bowled": 2000,
            "min_last_match_date": "2023-01-01",
            "top_k": 5,
        },
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows
    for row in rows:
        assert row["role"] == "bowler"
        assert row["balls_bowled"] <= 2000


@pytest.mark.skipif(
    not (_neo4j_alive() and Path("data/metrics/scout_ratings_ipl.json").exists()),
    reason="needs Neo4j + Bayes ratings",
)
def test_auction_recommend(client):
    r = client.post(
        "/v1/auction/recommend",
        json={"target": "JJ Bumrah", "budget": 8.0, "role": "bowler", "n": 5},
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows
    for row in rows:
        assert row["role"] == "bowler"
        assert row["price"] <= 8.0
