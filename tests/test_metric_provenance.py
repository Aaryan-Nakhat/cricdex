"""A metric cache carries what it was computed from; the export refuses one whose data or code moved
on (cricdesk.metrics.provenance)."""

from __future__ import annotations

import duckdb

from cricdesk.metrics import provenance


def _con(n_matches: int) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE matches_demo (match_id VARCHAR, match_date VARCHAR)")
    for i in range(n_matches):
        con.execute("INSERT INTO matches_demo VALUES (?, ?)", [f"m{i}", f"2026-05-{i + 1:02d}"])
    return con


def test_a_cache_without_a_stamp_is_stale(tmp_path):
    cache = tmp_path / "ngi_demo.json"
    cache.write_text("[]")
    assert provenance.stale_reason(cache, provenance.fingerprint(_con(3), "demo", "ngi"))


def test_a_stamped_cache_is_current_until_the_data_changes(tmp_path):
    cache = tmp_path / "ngi_demo.json"
    cache.write_text("[]")
    provenance.write_stamp(cache, provenance.fingerprint(_con(3), "demo", "ngi"))
    assert provenance.stale_reason(cache, provenance.fingerprint(_con(3), "demo", "ngi")) is None
    why = provenance.stale_reason(cache, provenance.fingerprint(_con(4), "demo", "ngi"))
    assert why and "matches" in why and "last_match" in why


def test_a_code_change_makes_every_cache_stale(tmp_path):
    cache = tmp_path / "ngi_demo.json"
    cache.write_text("[]")
    fp = provenance.fingerprint(_con(3), "demo", "ngi")
    provenance.write_stamp(cache, {**fp, "code": "0" * 16})
    assert "code" in provenance.stale_reason(cache, fp)


def test_only_the_keeper_boards_read_the_player_master():
    con = _con(2)
    assert "player_master" in provenance.fingerprint(con, "demo", "keeping")
    assert "player_master" in provenance.fingerprint(con, "demo", "fielding")
    assert "player_master" not in provenance.fingerprint(con, "demo", "ngi")
