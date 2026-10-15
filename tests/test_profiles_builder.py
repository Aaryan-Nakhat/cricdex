"""Profile builder: every catalog metric, loaded once, one shared connection."""

from __future__ import annotations

import json

import duckdb
import pytest

from cricdex.common.metrics import METRICS
from cricdex.comparator import compare as cmp
from cricdex.profiles import builder


@pytest.fixture
def metric_dir(tmp_path, monkeypatch):
    d = tmp_path / "metrics"
    d.mkdir()
    (d / "ngi_test.json").write_text(json.dumps([{"name": "A", "ngi_per_match": 0.05}]))
    # some metric files wrap their rows in {"rows": [...]}
    (d / "keeping_test.json").write_text(
        json.dumps({"rows": [{"fielder": "A", "dismissals": 7, "catches": 5}]})
    )
    (d / "pressure_conversion_test.json").write_text(
        json.dumps([{"bowler": "B", "wicket_rate_pct": 12.5}])
    )
    (d / "intent_curve_test.json").write_text(
        json.dumps(
            [
                {"batter": "A", "ball_bucket": "01_0-5", "balls": 10, "runs": 10, "sr": 100.0},
                {"batter": "A", "ball_bucket": "02_6-10", "balls": 10, "runs": 20, "sr": 200.0},
                {"batter": "A", "ball_bucket": "04_21-30", "balls": 5, "runs": 9, "sr": 180.0},
            ]
        )
    )
    (d / "scout_ratings_test.json").write_text(
        json.dumps([{"cricsheet_id": "id-a", "role": "batter", "skill": 0.1, "skill_sd": 0.02}])
    )
    monkeypatch.setattr(builder, "METRIC_DIR", d)
    return d


@pytest.fixture
def mini_db(tmp_path, monkeypatch):
    path = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE balls_test (
            match_id TEXT, innings_idx INTEGER, match_type TEXT,
            batter TEXT, bowler TEXT, runs_batter INTEGER, runs_extras INTEGER,
            extras_type TEXT, player_out TEXT, wicket_kind TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO balls_test VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("m1", 0, "T20", "A", "B", 4, 0, None, None, None),
            ("m1", 0, "T20", "A", "B", 6, 0, None, None, None),
            ("m1", 0, "T20", "A", "B", 0, 1, "wides", None, None),
            ("m2", 1, "T20", "A", "B", 1, 0, None, "A", "caught"),
        ],
    )
    con.execute(
        "CREATE TABLE people (identifier TEXT, unique_name TEXT, key_cricinfo INTEGER, "
        "key_cricbuzz TEXT, key_cricheroes TEXT, key_bigbash TEXT)"
    )
    con.execute("INSERT INTO people (identifier, unique_name) VALUES ('id-a', 'A'), ('id-b', 'B')")
    con.close()
    monkeypatch.setattr(builder, "DUCKDB_PATH", path)
    return path


def test_metric_tables_cover_every_catalog_metric(metric_dir):
    tables = builder.load_metric_tables("test")
    assert set(tables) == {m.slug for m in METRICS}
    assert tables["keeping"]["A"]["dismissals"] == 7
    assert tables["pressure_conversion"]["B"]["wicket_rate_pct"] == 12.5
    intent = tables["intent_curve"]["A"]
    assert intent["curve"] == [100.0, 200.0, None, 180.0, None, None]
    assert intent["early_sr"] == 150.0  # 30 runs off the first 20 balls
    assert intent["balls"] == 25


def test_build_shares_connection_and_carries_all_metrics(metric_dir, mini_db):
    sources = builder.Sources("test")
    con = duckdb.connect(str(mini_db), read_only=True)
    try:
        prof = builder.build("A", "test", con=con, sources=sources)
        assert con.execute("SELECT 1").fetchone() == (1,)  # caller's connection left open
    finally:
        con.close()
    assert list(prof["metrics"]) == [m.slug for m in METRICS]
    assert prof["metrics"]["ngi"]["ngi_per_match"] == 0.05
    assert prof["metrics"]["intent_curve"]["early_sr"] == 150.0
    assert prof["metrics"]["fielding"] is None
    assert prof["cricsheet_id"] == "id-a"
    assert prof["bayes"]["bayes_batter"]["skill"] == 0.1
    assert prof["career"]["career_runs"] == 11
    assert prof["career"]["career_balls_faced"] == 3  # the wide isn't a ball faced
    assert prof["career"]["career_innings"] == 2
    assert prof["dismissal_fingerprint"]["batter"]["total"] == 1
    # without a shared connection / sources the result is the same
    assert builder.build("A", "test") == prof


def test_compare_keeps_its_career_keys(mini_db):
    con = duckdb.connect(str(mini_db), read_only=True)
    try:
        row = cmp._career_totals(con, "test", "A")
    finally:
        con.close()
    assert row == {
        "career_runs": 11,
        "career_balls": 3,
        "career_sixes": 1,
        "career_fours": 1,
        "career_matches": 2,
        "career_wickets": 0,
        "career_runs_conceded": 0,
        "career_legal_balls_bowled": 0,
    }
