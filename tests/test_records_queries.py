"""Smoke tests for the records SQL queries.

Builds a tiny synthetic balls+matches table per test to keep this
hermetic.
"""

from __future__ import annotations

import datetime as dt

import duckdb

from cricdex.records import queries


def _seed_db(path):
    con = duckdb.connect(path)
    con.execute(
        """
        CREATE TABLE matches_t (
            match_id VARCHAR, match_date VARCHAR, match_type VARCHAR,
            event_name VARCHAR, league VARCHAR, venue VARCHAR, city VARCHAR,
            team_home VARCHAR, team_away VARCHAR, overs INT,
            toss_winner VARCHAR, toss_decision VARCHAR,
            outcome_winner VARCHAR, outcome_by_runs INT, outcome_by_wickets INT,
            result VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO matches_t VALUES
        ('M1', '2024-05-12', 'T20', 'IPL', 'IPL', 'Wankhede', 'Mumbai',
         'MI', 'CSK', 20, 'MI', 'bowl', 'CSK', NULL, 5, NULL),
        ('M2', '2023-05-12', 'T20', 'IPL', 'IPL', 'Wankhede', 'Mumbai',
         'MI', 'GT', 20, 'GT', 'bat', 'GT', 10, NULL, NULL)
        """
    )
    con.execute(
        """
        CREATE TABLE balls_t (
            ball_id VARCHAR, match_id VARCHAR, match_date VARCHAR,
            match_type VARCHAR, league VARCHAR, venue VARCHAR,
            innings_idx INT, batting_team VARCHAR, bowling_team VARCHAR,
            over INT, ball_in_over INT, phase VARCHAR,
            batter VARCHAR, non_striker VARCHAR, bowler VARCHAR,
            runs_batter INT, runs_extras INT, runs_total INT,
            extras_type VARCHAR, wicket_kind VARCHAR, player_out VARCHAR,
            fielders VARCHAR[]
        )
        """
    )
    rows = [
        (
            "M1-1",
            "M1",
            "2024-05-12",
            "T20",
            "IPL",
            "Wankhede",
            0,
            "MI",
            "CSK",
            0,
            1,
            "powerplay",
            "ROHIT",
            "ISHAN",
            "BUMRAH",
            50,
            0,
            50,
            None,
            None,
            None,
            [],
        ),
        (
            "M1-2",
            "M1",
            "2024-05-12",
            "T20",
            "IPL",
            "Wankhede",
            0,
            "MI",
            "CSK",
            0,
            2,
            "powerplay",
            "ISHAN",
            "ROHIT",
            "BUMRAH",
            10,
            0,
            10,
            None,
            None,
            None,
            [],
        ),
        (
            "M2-1",
            "M2",
            "2023-05-12",
            "T20",
            "IPL",
            "Wankhede",
            0,
            "GT",
            "MI",
            0,
            1,
            "powerplay",
            "GILL",
            "BUTTLER",
            "BOULT",
            75,
            0,
            75,
            None,
            None,
            None,
            [],
        ),
    ]
    con.executemany(
        "INSERT INTO balls_t VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    con.close()


def test_on_this_day_handles_varchar_match_date(tmp_path):
    db_path = tmp_path / "rec.duckdb"
    _seed_db(str(db_path))
    df = queries.on_this_day(5, 12, "t", db_path=db_path, top_n=10)
    players = df["player"].to_list()
    # Both 50+ rows should surface — 75 (GILL) and 50 (ROHIT).
    assert "GILL" in players
    assert "ROHIT" in players


def test_career_run_leaders(tmp_path):
    db_path = tmp_path / "rec.duckdb"
    _seed_db(str(db_path))
    df = queries.career_run_leaders("t", db_path=db_path, top_n=5)
    top = df["batter"].to_list()
    assert top[0] == "GILL"
    assert df["career_runs"].sum() == 50 + 10 + 75


def test_on_this_day_no_match(tmp_path):
    db_path = tmp_path / "rec.duckdb"
    _seed_db(str(db_path))
    df = queries.on_this_day(1, 1, "t", db_path=db_path, top_n=10)
    assert df.height == 0


# Reference dt so the import isn't flagged as unused in case future
# parametrised tests use it for date construction.
_ = dt
