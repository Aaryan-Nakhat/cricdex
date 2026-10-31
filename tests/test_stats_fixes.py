"""Regression tests for the stat fixes: per-innings records, bowler runs, super overs, dismissals, safe names."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from cricdesk.common.sql import BOWLER_RUNS, MAIN_INNINGS, table_suffix
from cricdesk.config import DATA_DIR
from cricdesk.records import queries as q

DB = (
    DATA_DIR / "cricsheet" / "cricsheet.duckdb"
)  # same lookup as the code (honours CRICDESK_DATA_DIR)
needs_data = pytest.mark.skipif(not DB.exists(), reason="needs data/cricsheet/cricsheet.duckdb")


def test_table_suffix_only_lets_plain_names_through():
    assert table_suffix("ipl") == "ipl"
    assert table_suffix("t20s-male") == "t20s_male"
    for bad in ("ipl; SELECT 1", "ipl' --", "../x", "IPL", "", "ipl/*"):
        with pytest.raises(ValueError):
            table_suffix(bad)


def test_bowler_runs_leave_out_byes_and_leg_byes():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t AS SELECT * FROM (VALUES (4, 0, NULL), (0, 1, 'wides'), (0, 4, 'byes'), "
        "(0, 2, 'legbyes'), (1, 1, 'noballs')) v(runs_batter, runs_extras, extras_type)"
    )
    assert con.execute(f"SELECT SUM({BOWLER_RUNS}) FROM t").fetchone()[0] == 4 + 1 + 0 + 0 + 2


@needs_data
def test_records_are_per_innings_and_skip_super_overs():
    with duckdb.connect(str(DB), read_only=True) as con:
        # a team's highest total can't beat its best real (non-super-over) innings
        best = con.execute(
            f"SELECT MAX(r) FROM (SELECT SUM(runs_total) r FROM balls_ipl WHERE {MAIN_INNINGS} "
            "GROUP BY match_id, innings_idx)"
        ).fetchone()[0]
    totals = q.highest_team_totals("ipl", top_n=5)
    assert int(totals["total_runs"].max()) == int(best)
    # one row per bowler-over, not split by batter
    overs = q.highest_runs_in_over("ipl", top_n=50)
    assert overs.select(["bowler", "match_id", "over"]).is_duplicated().sum() == 0
    assert "batters" in overs.columns


@needs_data
def test_on_this_day_keeps_bowling_rows():
    rows = q.on_this_day(4, 18, "ipl", top_n=20)
    if rows.height:
        assert set(rows["role"].unique().to_list()) <= {"batter", "bowler"}
        assert rows.filter(pl.col("role") == "batter").height <= 10


@needs_data
def test_crease_longevity_counts_run_outs_at_the_other_end():
    from cricdesk.metrics import batter

    with duckdb.connect(str(DB), read_only=True) as con:
        # someone run out as the non-striker at least once
        name = con.execute(
            "SELECT player_out FROM balls_ipl WHERE wicket_kind = 'run out' AND player_out = non_striker "
            "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        striker_outs = con.execute(
            "SELECT COUNT(DISTINCT (match_id, innings_idx)) FROM balls_ipl WHERE player_out = ? AND player_out = batter "
            "AND wicket_kind NOT IN ('retired hurt', 'retired not out') AND innings_idx <= 1",
            [name],
        ).fetchone()[0]
    row = batter.crease_longevity("ipl", min_dismissals=1, top_n=None).filter(
        pl.col("batter") == name
    )
    assert row.height == 1 and int(row["dismissals"][0]) > striker_outs
