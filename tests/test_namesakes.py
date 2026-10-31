"""Two different players who share a scorecard name in one collection stay two players (roadmap F1).

Cricsheet's ball data names players by their scorecard name; each match's registry maps that name to
a stable id. Every metric, rating, board and profile is keyed by the id, resolved per match, so a
"J Smith" of one team and a different "J Smith" of another are never merged.
"""

from __future__ import annotations

import json

import duckdb
import polars as pl
import pytest

from cricdesk.common import sql
from cricdesk.metrics import batter as batter_metrics
from cricdesk.metrics import matchups, ngi, phase
from cricdesk.scout import cohort
from cricdesk.scout.ingest import cricsheet
from cricdesk.scout.ratings import bayesian


def _over(over: int, batter: str, bowler: str, non_striker: str, runs: int) -> dict:
    return {
        "over": over,
        "deliveries": [
            {
                "batter": batter,
                "bowler": bowler,
                "non_striker": non_striker,
                "runs": {"batter": runs, "extras": 0, "total": runs},
            }
            for _ in range(6)
        ],
    }


def _match(date: str, teams: list[str], people: dict[str, str], bat1: tuple, bat2: tuple) -> dict:
    """Team 1 bats two overs (batter, non-striker, bowler, runs per ball), then team 2."""
    return {
        "info": {
            "dates": [date],
            "season": date[:4],
            "match_type": "T20",
            "event": {"name": "Namesake League"},
            "venue": "Ground, City",
            "teams": teams,
            "overs": 20,
            "outcome": {"winner": teams[0], "by": {"runs": 1}},
            "toss": {"winner": teams[0], "decision": "bat"},
            "players": {
                teams[0]: [bat1[0], bat1[1], bat2[2]],
                teams[1]: [bat2[0], bat2[1], bat1[2]],
            },
            "registry": {"people": people},
        },
        "innings": [
            {
                "team": teams[0],
                "overs": [_over(o, bat1[0], bat1[2], bat1[1], bat1[3]) for o in (0, 1)],
            },
            {
                "team": teams[1],
                "overs": [_over(o, bat2[0], bat2[2], bat2[1], bat2[3]) for o in (0, 1)],
            },
        ],
    }


@pytest.fixture
def namesake_db(tmp_path):
    """Match 1: Reds' J Smith (id smith001) hits 4s. Match 2: Greens' J Smith (smith002), a
    different player with the same scorecard name, scores 1s."""
    d = tmp_path / "extracted"
    d.mkdir()
    m1 = _match(
        "2024-04-01",
        ["Reds", "Blues"],
        {
            "J Smith": "smith001",
            "A Partner": "part0001",
            "B Bowler": "bowl0001",
            "C Other": "oth00001",
            "D Mate": "mate0001",
            "E Seamer": "seam0001",
        },
        ("J Smith", "A Partner", "B Bowler", 4),
        ("C Other", "D Mate", "E Seamer", 1),
    )
    m2 = _match(
        "2024-04-08",
        ["Greens", "Blues"],
        {
            "J Smith": "smith002",
            "F Friend": "frnd0001",
            "B Bowler": "bowl0001",
            "C Other": "oth00001",
            "D Mate": "mate0001",
            "G Spinner": "spin0001",
        },
        ("J Smith", "F Friend", "B Bowler", 1),
        ("C Other", "D Mate", "G Spinner", 2),
    )
    for i, m in enumerate((m1, m2), 1):
        (d / f"{1000 + i}.json").write_text(json.dumps(m), encoding="utf-8")
    parsed = cricsheet.parse_collection(d)
    extra = {
        k: getattr(parsed, k)
        for k in ("innings", "replacements", "match_players")
        if getattr(parsed, k, None) is not None
    }
    m_path, b_path = cricsheet.write_parquet(
        parsed.matches,
        parsed.balls,
        tmp_path / "pq",
        "nsk",
        players=parsed.players,
        wickets=parsed.wickets,
        **extra,
    )
    db = tmp_path / "n.duckdb"
    cricsheet.load_to_duckdb(m_path, b_path, "nsk", db)
    return db


def test_keyed_balls_resolve_the_name_per_match(namesake_db):
    with duckdb.connect(str(namesake_db), read_only=True) as con:
        kb = sql.keyed_balls(con, "nsk")
        rows = con.execute(
            f"SELECT DISTINCT match_id, batter, batter_name FROM {kb} WHERE batter_name = 'J Smith' "
            "ORDER BY match_id"
        ).fetchall()
        assert [r[1] for r in rows] == ["smith001", "smith002"]
        labels = sql.label_map(con, "nsk")
    assert labels["smith001"] == labels["smith002"] == "J Smith"


def test_metric_boards_keep_namesakes_apart(namesake_db):
    bdr = batter_metrics.boundary_dependency("nsk", db_path=namesake_db, min_runs=1)
    smiths = bdr.filter(pl.col("batter") == "J Smith")
    assert smiths.height == 2
    assert set(smiths["cricsheet_id"]) == {"smith001", "smith002"}
    # one hit only fours, the other only singles: merged they'd be one middling row
    by_id = {r["cricsheet_id"]: r["bdr_pct"] for r in smiths.to_dicts()}
    assert by_id == {"smith001": 100.0, "smith002": 0.0}


def test_phase_matchups_cohort_and_appearances_keep_namesakes_apart(namesake_db):
    boards = phase.phase_leaders("nsk", db_path=namesake_db, min_bat_balls=1, min_bowl_balls=1)
    pp = [r for r in boards["powerplay"]["batters"] if r["name"] == "J Smith"]
    assert {r["cricsheet_id"] for r in pp} == {"smith001", "smith002"}

    pairs = matchups.pairwise("nsk", db_path=namesake_db, min_balls=1)
    vs_bowler = [p for p in pairs if p["batter"] == "J Smith" and p["bowler"] == "B Bowler"]
    assert {p["batter_id"] for p in vs_bowler} == {"smith001", "smith002"}
    assert {p["runs"] for p in vs_bowler} == {48, 12}

    with duckdb.connect(str(namesake_db), read_only=True) as con:
        vol = cohort.ball_volumes(con, "nsk")
        assert vol["smith001"][0] == vol["smith002"][0] == 12
        apps = ngi.appearances(con, "nsk")
    assert apps["smith001"] == apps["smith002"] == 1
    assert apps["bowl0001"] == 2  # the same bowler in both matches is one player


def test_rating_edges_and_fit_keep_namesakes_apart(namesake_db):
    edges = bayesian._load_edges(namesake_db, "nsk")
    smith = edges.filter(pl.col("batter_id").is_in(["smith001", "smith002"]))
    assert smith.group_by("batter_id").agg(pl.col("runs").sum()).sort("batter_id")[
        "runs"
    ].to_list() == [48, 12]
    df = bayesian.fit("nsk", db_path=namesake_db, advi_steps=30)
    rated = df.filter((pl.col("role") == "batter") & (pl.col("unique_name") == "J Smith"))
    assert set(rated["cricsheet_id"]) == {"smith001", "smith002"}
