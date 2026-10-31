"""API error codes: unknown players are 404, missing data is 503, bad collections stay 400."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from fastapi.testclient import TestClient  # noqa: E402

import cricdesk.api.main as api  # noqa: E402

client = TestClient(api.app)


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """Pretend a DuckDB exists that knows two players (no real database touched)."""
    db = tmp_path / "cricsheet.duckdb"
    db.write_bytes(b"")
    monkeypatch.setattr(api, "_DB_PATH", db)
    monkeypatch.setattr(api, "_player_names", lambda *a: frozenset({"V Kohli", "JJ Bumrah"}))
    monkeypatch.setattr(api.identity, "resolve_name", lambda q, collection, db_path: (None, []))
    monkeypatch.setattr(api.profiles, "build", lambda name, collection: {"name": name})
    return db


def test_unknown_player_profile_is_404(fake_db):
    r = client.get("/v1/players/Nobody%20Here", params={"collection": "ipl"})
    assert r.status_code == 404
    assert "unknown player" in r.json()["detail"]


def test_known_player_profile_is_200(fake_db):
    r = client.get("/v1/players/V%20Kohli")
    assert r.status_code == 200 and r.json()["name"] == "V Kohli"


def test_unknown_player_style_twins_is_404(fake_db):
    assert client.get("/v1/players/Nobody/style-twins").status_code == 404


def test_compare_with_an_unknown_player_is_404(fake_db):
    r = client.post("/v1/compare", json={"players": ["V Kohli", "Nobody"]})
    assert r.status_code == 404 and "Nobody" in r.json()["detail"]


def test_bad_collection_is_still_400(fake_db):
    assert client.get("/v1/players/V%20Kohli", params={"collection": "x;drop"}).status_code == 400
    assert client.get("/v1/metrics/ngi", params={"collection": "x;drop"}).status_code == 400


def test_player_routes_without_a_duckdb_are_503(tmp_path, monkeypatch):
    # fresh clone: no DuckDB at all
    monkeypatch.setattr(api, "_DB_PATH", tmp_path / "missing.duckdb")
    r = client.get("/v1/players/V%20Kohli")
    assert r.status_code == 503 and "data ingest cricsheet" in r.json()["detail"]


def test_ngi_cache_miss_is_503_not_a_live_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)  # empty, like a fresh clone

    def _boom(*a, **k):
        raise AssertionError("must not fit NGI inside a GET")

    import cricdesk.metrics.ngi as ngi

    monkeypatch.setattr(ngi, "compute", _boom)
    r = client.get("/v1/metrics/ngi", params={"collection": "ipl"})
    assert r.status_code == 503
    assert "cricdesk data ingest metrics" in r.json()["detail"]


def test_unknown_collection_is_400_listing_the_registry(fake_db):
    r = client.get("/v1/players/V%20Kohli", params={"collection": "not_a_league"})
    assert r.status_code == 400
    assert "Valid: ipl" in r.json()["detail"] and "psl" in r.json()["detail"]


def test_time_window_of_a_registry_league_passes_the_check(fake_db):
    assert (
        client.get("/v1/players/V%20Kohli", params={"collection": "ipl_last1y"}).status_code == 200
    )


def test_leagues_endpoint_serves_the_registry():
    from cricdesk import leagues

    r = client.get("/v1/leagues")
    assert r.status_code == 200
    assert [lg["key"] for lg in r.json()["leagues"]] == leagues.keys()
