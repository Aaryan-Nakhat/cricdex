"""Smoke test for the bowler Wicket Quality metric."""

from __future__ import annotations

import json

import duckdb

from cricdex.metrics import bowler_wicket_quality as wq


def _seed_db(path):
    con = duckdb.connect(path)
    con.execute(
        """
        CREATE TABLE people (
            identifier VARCHAR, name VARCHAR, unique_name VARCHAR,
            key_bcci VARCHAR, key_bcci_2 VARCHAR, key_bigbash VARCHAR,
            key_cricbuzz VARCHAR, key_cricheroes VARCHAR, key_crichq VARCHAR,
            key_cricinfo VARCHAR, key_cricinfo_2 VARCHAR, key_cricinfo_3 VARCHAR,
            key_cricingif VARCHAR, key_cricketarchive VARCHAR,
            key_cricketarchive_2 VARCHAR, key_cricketworld VARCHAR,
            key_nvplay VARCHAR, key_nvplay_2 VARCHAR, key_opta VARCHAR,
            key_opta_2 VARCHAR, key_pulse VARCHAR, key_pulse_2 VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO people (identifier, name, unique_name) VALUES
        ('kohli_id', 'V Kohli', 'V Kohli'),
        ('pant_id', 'RR Pant', 'RR Pant'),
        ('tail_id', 'Mr Tail', 'Mr Tail')
        """
    )
    con.execute(
        """
        CREATE TABLE balls_t (
            ball_id VARCHAR, match_id VARCHAR, batter VARCHAR, bowler VARCHAR,
            wicket_kind VARCHAR, player_out VARCHAR
        )
        """
    )
    rows = [
        ("1", "M1", "V Kohli", "Bumrah", "bowled", "V Kohli"),
        ("2", "M1", "RR Pant", "Bumrah", "lbw", "RR Pant"),
        ("3", "M1", "Mr Tail", "Bumrah", "caught", "Mr Tail"),
        ("4", "M2", "Mr Tail", "Generic", "caught", "Mr Tail"),
        ("5", "M2", "Mr Tail", "Generic", "bowled", "Mr Tail"),
    ]
    con.executemany(
        "INSERT INTO balls_t (ball_id, match_id, batter, bowler, wicket_kind, player_out) VALUES (?,?,?,?,?,?)",
        rows,
    )
    con.close()


def test_wicket_quality_uses_opponent_skill(tmp_path, monkeypatch):
    db_path = tmp_path / "wq.duckdb"
    _seed_db(str(db_path))

    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    ratings_path = metrics_dir / "scout_ratings_t.json"
    ratings_path.write_text(
        json.dumps(
            [
                {"cricsheet_id": "kohli_id", "role": "batter", "skill": 1.0},
                {"cricsheet_id": "pant_id", "role": "batter", "skill": 0.5},
                {"cricsheet_id": "tail_id", "role": "batter", "skill": -0.5},
            ]
        )
    )
    monkeypatch.setattr(wq, "DATA_DIR", tmp_path)

    df = wq.wicket_quality(collection="t", db_path=db_path, min_wickets=1)
    rows = {r["bowler"]: r for r in df.to_dicts()}
    # Bumrah: skills (1.0 + 0.5 + -0.5) / 3 = 0.333…
    assert abs(rows["Bumrah"]["wicket_quality"] - (1.0 + 0.5 - 0.5) / 3) < 1e-6
    # Generic only dismissed the tail-ender twice.
    assert abs(rows["Generic"]["wicket_quality"] - (-0.5)) < 1e-6
    assert rows["Bumrah"]["wickets"] == 3
    assert rows["Bumrah"]["opponents_seen"] == 3
