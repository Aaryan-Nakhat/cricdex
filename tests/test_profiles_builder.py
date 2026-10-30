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
    (d / "ngi_test.json").write_text(
        json.dumps([{"name": "A", "cricsheet_id": "id-a", "ngi_per_match": 0.05}])
    )
    # some metric files wrap their rows in {"rows": [...]}
    (d / "keeping_test.json").write_text(
        json.dumps(
            {"rows": [{"fielder": "A", "cricsheet_id": "id-a", "dismissals": 7, "catches": 5}]}
        )
    )
    (d / "hand_split_test.json").write_text(
        json.dumps([{"bowler": "B", "cricsheet_id": "id-b", "left_edge": 12.5}])
    )
    (d / "intent_curve_test.json").write_text(
        json.dumps(
            [
                {
                    "batter": "A",
                    "cricsheet_id": "id-a",
                    "ball_bucket": "01_0-5",
                    "balls": 10,
                    "runs": 10,
                    "sr": 100.0,
                },
                {
                    "batter": "A",
                    "cricsheet_id": "id-a",
                    "ball_bucket": "02_6-10",
                    "balls": 10,
                    "runs": 20,
                    "sr": 200.0,
                },
                {
                    "batter": "A",
                    "cricsheet_id": "id-a",
                    "ball_bucket": "04_21-30",
                    "balls": 5,
                    "runs": 9,
                    "sr": 180.0,
                },
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
    # rows are keyed by the player's registry id (two players can share a scorecard name)
    assert tables["keeping"]["id-a"]["dismissals"] == 7
    assert tables["hand_split"]["id-b"]["left_edge"] == 12.5
    intent = tables["intent_curve"]["id-a"]
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


def test_standard_stat_line():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE balls_s (match_id TEXT, innings_idx INTEGER, match_type TEXT, batter TEXT, "
        "bowler TEXT, runs_batter INTEGER, runs_extras INTEGER, extras_type TEXT, player_out TEXT, "
        "wicket_kind TEXT)"
    )
    rows = []
    # m1: A makes 60 (10 sixes) and is out; m2: A makes 104 not out; super over (idx 2) ignored
    rows += [("m1", 0, "T20", "A", "B", 6, 0, None, None, None)] * 10
    rows += [("m1", 0, "T20", "A", "B", 0, 0, None, "A", "caught")]
    rows += [("m2", 0, "T20", "A", "B", 4, 0, None, None, None)] * 26
    rows += [("m2", 2, "T20", "A", "B", 6, 0, None, None, None)] * 5
    # B takes 3 wickets for 10 in m3 (a run out isn't his)
    rows += [("m3", 1, "T20", f"X{i}", "B", 0, 0, None, f"X{i}", "bowled") for i in range(3)]
    rows += [("m3", 1, "T20", "X9", "B", 10, 0, None, None, None)]
    rows += [("m3", 1, "T20", "X8", "B", 0, 0, None, "X8", "run out")]
    con.executemany("INSERT INTO balls_s VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    a = builder.career_standard(con, "s", "A")
    assert (a["career_fifties"], a["career_hundreds"]) == (1, 1)
    assert a["career_highest_score"] == 104 and a["career_highest_score_not_out"] is True
    assert a["career_dismissals"] == 1 and a["career_dots_faced"] == 1
    b = builder.career_standard(con, "s", "B")
    assert (b["career_best_bowling_wickets"], b["career_best_bowling_runs"]) == (3, 10)
    assert (b["career_three_wkt_hauls"], b["career_four_wkt_hauls"]) == (1, 0)
    assert b["career_dots_bowled"] == 5  # the wicket ball in m1, four in m3
