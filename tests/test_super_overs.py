"""Super overs (innings 3+ of a limited-overs match) stay out of every player stat.

Each check builds the same tiny collection twice — once with only the two main innings, once with a
super over added on top — and asserts the metric comes out identical. A Test match's third innings is
real cricket, so it has to be kept.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import pytest

from cricdesk.metrics import batter, bowler, fielding, matchups
from cricdesk.scout import cohort
from cricdesk.scout.ratings import bayesian

COLUMNS = (
    "match_id VARCHAR, match_type VARCHAR, match_date VARCHAR, venue VARCHAR, phase VARCHAR, "
    "innings_idx INT, over INT, ball_in_over INT, ball_id VARCHAR, batting_team VARCHAR, "
    "bowling_team VARCHAR, batter VARCHAR, non_striker VARCHAR, bowler VARCHAR, runs_batter INT, "
    "runs_extras INT, runs_total INT, extras_type VARCHAR, wicket_kind VARCHAR, player_out VARCHAR, "
    "fielders VARCHAR[]"
)


def _innings(match_id, match_type, idx, batter_, bowler_, runs, wicket_last=False, overs=2):
    """`overs` overs of `batter_` facing `bowler_`, every ball scoring `runs[i % len(runs)]`."""
    rows = []
    for over in range(overs):
        for ball in range(6):
            r = runs[(over * 6 + ball) % len(runs)]
            out = wicket_last and over == overs - 1 and ball == 5
            rows.append(
                (
                    match_id, match_type, "2024-04-01", "Ground", "powerplay", idx, over, ball,
                    f"{match_id}::{idx}::{over}::{ball}", "Home" if idx % 2 == 0 else "Away",
                    "Away" if idx % 2 == 0 else "Home", batter_, "Partner", bowler_, r, 0, r,
                    None, "caught" if out else None, batter_ if out else None,
                    ["Catcher"] if out else [],
                )
            )  # fmt: skip
    return rows


def _main_rows():
    rows = []
    # a T20: A bats first against X, B chases against Y (mix of dots and singles, a four now and then)
    rows += _innings("t1", "T20", 0, "A", "X", [0, 0, 0, 0, 1, 4], wicket_last=True)
    rows += _innings("t1", "T20", 1, "B", "Y", [0, 0, 0, 0, 0, 1], wicket_last=True)
    # a Test: four innings, the third is real cricket
    rows += _innings("m1", "Test", 0, "A", "X", [0, 1, 0, 2, 0, 1])
    rows += _innings("m1", "Test", 1, "B", "Y", [0, 0, 1, 0, 0, 1])
    rows += _innings("m1", "Test", 2, "A", "Y", [0, 0, 0, 0, 2, 1])
    rows += _innings("m1", "Test", 3, "B", "X", [1, 0, 0, 0, 0, 0])
    return rows


def _super_over_rows():
    # the T20 tied: A slogs X for sixes, B blocks Y, and X takes a catch-heavy wicket — none of it counts
    rows = _innings("t1", "T20", 2, "A", "Y", [6, 6, 0, 0, 0, 0], wicket_last=True, overs=1)
    rows += _innings("t1", "T20", 3, "B", "X", [0, 0, 0, 0, 0, 0], wicket_last=True, overs=1)
    rows += _innings(
        "t1", "T20", 3, "C", "Z", [4, 4, 4, 4, 6, 6], overs=1
    )  # someone only in the SO
    return rows


def _build(path: Path, with_super_over: bool) -> Path:
    rows = _main_rows() + (_super_over_rows() if with_super_over else [])
    con = duckdb.connect(str(path))
    con.execute(f"CREATE TABLE balls_t ({COLUMNS})")
    con.executemany(f"INSERT INTO balls_t VALUES ({', '.join(['?'] * 21)})", rows)
    con.execute(
        "CREATE TABLE matches_t AS SELECT DISTINCT match_id, match_type, venue, match_date, "
        "CASE match_type WHEN 'T20' THEN 20 END AS overs FROM balls_t"
    )
    con.execute("CREATE TABLE people (identifier VARCHAR, unique_name VARCHAR)")
    con.execute(
        "INSERT INTO people VALUES ('a','A'),('b','B'),('c','C'),('x','X'),('y','Y'),('z','Z')"
    )
    con.close()
    return path


@pytest.fixture
def dbs(tmp_path):
    return _build(tmp_path / "main.duckdb", False), _build(tmp_path / "so.duckdb", True)


def _same(a: pl.DataFrame, b: pl.DataFrame, key: str | list[str]) -> None:
    assert a.height > 0
    assert a.sort(key).equals(b.sort(key))


def test_batter_metrics_ignore_super_overs(dbs):
    main, so = dbs
    for fn, kw in (
        (batter.boundary_dependency, {"min_runs": 0}),
        (batter.dot_ball_recovery, {"min_dot_balls": 0}),
        (batter.slow_start_cost, {"min_career_balls": 0, "min_setting_balls": 0}),
    ):
        _same(
            fn("t", db_path=main, top_n=None, **kw), fn("t", db_path=so, top_n=None, **kw), "batter"
        )
    # C batted only in the super over, so C isn't on the board at all
    assert "C" not in batter.boundary_dependency("t", db_path=so, min_runs=0)["batter"].to_list()


def test_test_match_third_innings_still_counts(dbs):
    _, so = dbs
    bdr = batter.boundary_dependency("t", db_path=so, min_runs=0, top_n=None)
    a_runs = bdr.filter(pl.col("batter") == "A")["total_runs"].item()
    # A's runs: the T20 first innings + the Test's first and third innings, no super-over sixes
    expected = sum(r[14] for r in _main_rows() if r[11] == "A" and (r[5] <= 1 or r[1] == "Test"))
    test_third = sum(r[14] for r in _main_rows() if r[0] == "m1" and r[5] == 2)
    assert test_third > 0 and a_runs == expected


def test_bowler_and_fielding_metrics_ignore_super_overs(dbs):
    main, so = dbs
    kw = {"min_pressure_balls": 0, "top_n": None}
    _same(
        bowler.pressure_conversion("t", db_path=main, **kw),
        bowler.pressure_conversion("t", db_path=so, **kw),
        "bowler",
    )
    _same(fielding._tally("t", main), fielding._tally("t", so), "fielder")


def test_matchups_ignore_super_overs(dbs):
    main, so = dbs
    assert sorted(matchups.pairwise("t", db_path=main, min_balls=1), key=str) == sorted(
        matchups.pairwise("t", db_path=so, min_balls=1), key=str
    )
    cats = {"X": "seam", "Y": "spin", "Z": "spin"}
    assert matchups.pace_spin_splits("t", cats, db_path=main, min_balls=1) == (
        matchups.pace_spin_splits("t", cats, db_path=so, min_balls=1)
    )


def test_ratings_edges_and_cohort_ignore_super_overs(dbs):
    main, so = dbs
    _same(
        bayesian._load_edges(main, "t"),
        bayesian._load_edges(so, "t"),
        ["batter_id", "bowler_id"],
    )
    with (
        duckdb.connect(str(main), read_only=True) as c1,
        duckdb.connect(str(so), read_only=True) as c2,
    ):
        assert cohort.ball_volumes(c1, "t") == cohort.ball_volumes(c2, "t")
        for name in ("A", "X"):
            assert cohort.co_faced(name, "t", con=c1) == cohort.co_faced(name, "t", con=c2)
