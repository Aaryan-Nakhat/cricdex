"""Smoke test for the Pressure Runs SQL pipeline.

Builds a tiny in-memory ball table that fakes a 2-innings T20 chase so
the SQL can be exercised without depending on the full Cricsheet
ingest. Asserts the leaderboard's headline batter shows up with
non-zero pressure runs.
"""

from __future__ import annotations

import duckdb
import polars as pl

from cricdex.metrics.batter import pressure_runs


def _seed_duckdb(db_path: str) -> None:
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE matches_synthetic AS SELECT * FROM (
            SELECT 'M1' AS match_id, DATE '2026-04-15' AS match_date,
                   'T20' AS match_type, 'IPL' AS event_name,
                   'IPL' AS league, 'Wankhede' AS venue,
                   'Mumbai' AS city, 'MI' AS team_home, 'CSK' AS team_away,
                   20 AS overs, 'MI' AS toss_winner, 'bowl' AS toss_decision,
                   'CSK' AS outcome_winner, NULL::INT AS outcome_by_runs,
                   3 AS outcome_by_wickets, NULL AS result
        )
    """)
    rows = []
    # Innings 0 — 180 all out off 19 balls (synthetic, abnormally short for the test).
    for over in range(2):
        for ball in range(1, 7):
            rows.append(
                (
                    f"M1::0::{over}::{ball}",
                    "M1",
                    "2026-04-15",
                    "T20",
                    "IPL",
                    "Wankhede",
                    0,
                    "MI",
                    "CSK",
                    over,
                    ball,
                    "powerplay",
                    "ROHIT",
                    "ISHAN",
                    "BUMRAH",
                    15,
                    0,
                    15,
                    None,
                    None,
                    None,
                    [],
                )
            )
    # Innings 1 — chase. Hero batter scores all runs late on hard required RPB.
    for over in range(2):
        for ball in range(1, 7):
            rows.append(
                (
                    f"M1::1::{over}::{ball}",
                    "M1",
                    "2026-04-15",
                    "T20",
                    "IPL",
                    "Wankhede",
                    1,
                    "CSK",
                    "MI",
                    over,
                    ball,
                    "powerplay" if over == 0 else "middle",
                    "HERO" if over == 1 else "FILLER",
                    "OTHER",
                    "BOLT",
                    20 if over == 1 else 1,
                    0,
                    20 if over == 1 else 1,
                    None,
                    None,
                    None,
                    [],
                )
            )

    columns = (
        "ball_id, match_id, match_date, match_type, league, venue, innings_idx, "
        "batting_team, bowling_team, over, ball_in_over, phase, batter, "
        "non_striker, bowler, runs_batter, runs_extras, runs_total, extras_type, "
        "wicket_kind, player_out, fielders"
    )
    con.execute(f"CREATE TABLE balls_synthetic ({columns.replace(', ', ' VARCHAR, ')} VARCHAR)")
    # The blanket VARCHAR cast above is wrong — recreate with proper types.
    con.execute("DROP TABLE balls_synthetic")
    con.execute(
        """
        CREATE TABLE balls_synthetic (
            ball_id VARCHAR, match_id VARCHAR, match_date DATE, match_type VARCHAR,
            league VARCHAR, venue VARCHAR, innings_idx INT,
            batting_team VARCHAR, bowling_team VARCHAR,
            over INT, ball_in_over INT, phase VARCHAR,
            batter VARCHAR, non_striker VARCHAR, bowler VARCHAR,
            runs_batter INT, runs_extras INT, runs_total INT,
            extras_type VARCHAR, wicket_kind VARCHAR, player_out VARCHAR,
            fielders VARCHAR[]
        )
        """
    )
    con.executemany(
        """
        INSERT INTO balls_synthetic VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.close()


def test_pressure_runs_returns_qualifying_batters(tmp_path):
    db_path = tmp_path / "synthetic.duckdb"
    _seed_duckdb(str(db_path))

    df = pressure_runs(
        collection="synthetic",
        db_path=db_path,
        pressure_multiplier=1.5,
        min_balls_faced=1,
        top_n=10,
    )

    assert isinstance(df, pl.DataFrame)
    assert df.height >= 1
    expected_cols = {
        "batter",
        "chase_balls_faced",
        "chase_runs",
        "pressure_balls",
        "pressure_runs",
        "pressure_sr_per_100_balls",
        "pct_balls_under_pressure",
    }
    assert expected_cols.issubset(set(df.columns))
    # HERO must appear in the leaderboard and have non-zero chase runs.
    hero = df.filter(pl.col("batter") == "HERO")
    assert hero.height == 1
    assert hero["chase_runs"][0] > 0
