"""The schema-2 Cricsheet parser: every JSON field lands in a table, end to end into DuckDB, and the
chase metrics use the recorded (DLS-revised) target — with a fallback for a DB built before it."""

from __future__ import annotations

import json

import duckdb
import pytest

from cricdex.metrics import ngi
from cricdex.metrics.batter import pressure_runs
from cricdex.scout.ingest import cricsheet

PEOPLE = {n: f"id-{n}" for n in ("a1", "a2", "a3", "a4", "a12", "b1", "b2", "b3", "b4", "sub1")}


def _d(batter, bowler, r=0, **extra):
    d = {
        "batter": batter,
        "bowler": bowler,
        "non_striker": "a4" if batter != "a4" else "a3",
        "runs": {"batter": r, "extras": 0, "total": r},
    }
    d.update(extra)
    return d


def _match() -> dict:
    """A rain-hit T20: team A sets 20, team B chases a DLS target of 15 in 5 overs."""
    first = [
        # 0: a 4 that was all run — not a boundary
        _d("a1", "b2", 4, runs={"batter": 4, "extras": 0, "total": 4, "non_boundary": True}),
        # 1: two extras keys on one ball (a no-ball the keeper let through for 2 byes)
        _d(
            "a1",
            "b2",
            extras={"noballs": 1, "byes": 2},
            runs={"batter": 0, "extras": 3, "total": 3},
        ),
        # 2: two wickets on one ball, the catch by a substitute fielder
        _d(
            "a1",
            "b2",
            wickets=[
                {
                    "kind": "caught",
                    "player_out": "a1",
                    "fielders": [{"name": "sub1", "substitute": True}],
                },
                {"kind": "retired out", "player_out": "a2"},
            ],
        ),
        # 3: a DRS review struck down on umpire's call
        _d(
            "a3",
            "b2",
            review={
                "by": "A",
                "umpire": "U One",
                "batter": "a3",
                "decision": "struck down",
                "umpires_call": True,
                "type": "wicket",
            },
        ),
        # 4: an Impact Player comes in before this ball
        _d(
            "a3",
            "b2",
            13,
            runs={"batter": 13, "extras": 0, "total": 13},
            replacements={
                "match": [{"in": "a12", "out": "a2", "reason": "impact_player", "team": "A"}]
            },
        ),
        _d("a3", "b2", 0),
    ]
    second = [
        _d("b1", "a4", 6),
        # a bowler replaced mid-over (role replacement names no team)
        _d(
            "b1",
            "a4",
            4,
            replacements={
                "role": [{"in": "a3", "out": "a4", "reason": "injury", "role": "bowler"}]
            },
        ),
        _d("b1", "a3", 6),
    ]
    return {
        "meta": {"data_version": "1.1.0", "created": "2024-05-02", "revision": 2},
        "info": {
            "balls_per_over": 6,
            "city": "Town",
            "dates": ["2024-05-01"],
            "event": {"name": "Fixture League", "match_number": 7, "stage": "Final", "group": "A"},
            "gender": "male",
            "match_type": "T20",
            "officials": {"umpires": ["U One", "U Two"], "match_referees": ["R"]},
            "outcome": {"winner": "B", "by": {"wickets": 9}, "method": "D/L"},
            "overs": 20,
            "player_of_match": ["b1"],
            "players": {"A": ["a1", "a2", "a3", "a4"], "B": ["b1", "b2", "b3", "b4"]},
            "registry": {"people": PEOPLE},
            "season": 2024,
            "team_type": "club",
            "teams": ["A", "B"],
            "toss": {"winner": "B", "decision": "field"},
            "venue": "Fixture Ground",
            "missing": ["reviews"],
        },
        "innings": [
            {
                "team": "A",
                "powerplays": [{"from": 0.1, "to": 5.6, "type": "mandatory"}],
                "penalty_runs": {"post": 5},
                "overs": [{"over": 0, "deliveries": first}],
            },
            {
                "team": "B",
                "target": {"runs": 15, "overs": 5},
                "miscounted_overs": {"1": {"balls": 7, "umpire": "U Two"}},
                "absent_hurt": ["b4"],
                "overs": [{"over": 0, "deliveries": second}],
            },
        ],
    }


@pytest.fixture()
def parsed():
    return cricsheet.parse_match_data(_match(), "M1")


def test_match_fields(parsed):
    m = parsed.match
    assert m["schema_version"] == cricsheet.SCHEMA_VERSION
    assert m["outcome_method"] == "D/L"
    assert m["season"] == "2024"
    assert (m["event_match_number"], m["event_stage"], m["event_group"]) == (7, "Final", "A")
    assert m["gender"] == "male" and m["team_type"] == "club" and m["balls_per_over"] == 6
    assert m["player_of_match"] == ["b1"]
    assert json.loads(m["officials"])["umpires"] == ["U One", "U Two"]
    assert json.loads(m["missing"]) == ["reviews"]
    assert (m["data_version"], m["revision"]) == ("1.1.0", 2)
    # the columns that existed before keep their meaning
    assert (m["outcome_winner"], m["outcome_by_wickets"], m["overs"]) == ("B", 9, 20)


def test_every_extras_key_is_kept(parsed):
    b = parsed.balls[1]
    assert b["extras_type"] == "noballs"  # the first key, as before
    assert (b["extras_noballs"], b["extras_byes"], b["extras_wides"]) == (1, 2, 0)
    assert b["runs_extras"] == 3


def test_non_boundary(parsed):
    assert parsed.balls[0]["runs_non_boundary"] is True
    assert parsed.balls[5]["runs_non_boundary"] is False


def test_two_wickets_on_one_ball(parsed):
    b = parsed.balls[2]
    assert b["n_wickets"] == 2
    assert (b["wicket_kind"], b["player_out"]) == ("caught", "a1")  # balls_ keeps the first
    ws = [w for w in parsed.wickets if w["ball_id"] == b["ball_id"]]
    assert [(w["wicket_idx"], w["player_out"]) for w in ws] == [(0, "a1"), (1, "a2")]
    assert ws[0]["fielders"] == ["sub1"] and ws[0]["fielder_substitute"] == [True]
    assert ws[1]["fielders"] == [] and ws[1]["fielder_substitute"] == []


def test_review(parsed):
    b = parsed.balls[3]
    assert (b["review_by"], b["review_umpire"], b["review_batter"]) == ("A", "U One", "a3")
    assert b["review_decision"] == "struck down"
    assert b["review_umpires_call"] is True
    assert b["review_type"] == "wicket"
    assert parsed.balls[0]["review_by"] is None and parsed.balls[0]["review_umpires_call"] is None


def test_replacements(parsed):
    impact, role = parsed.replacements
    assert impact["reason"] == "impact_player" and impact["kind"] == "match"
    assert (impact["team"], impact["player_in"], impact["player_out"]) == ("A", "a12", "a2")
    assert impact["ball_id"] == parsed.balls[4]["ball_id"]
    # a role replacement names no team: a bowler belongs to the fielding side
    assert role["kind"] == "role" and role["role"] == "bowler" and role["team"] == "A"
    assert role["innings_idx"] == 1


def test_innings_rows(parsed):
    first, chase = parsed.innings
    assert first["target_runs"] is None
    assert json.loads(first["powerplays"]) == [{"from": 0.1, "to": 5.6, "type": "mandatory"}]
    assert first["penalty_runs_post"] == 5 and first["penalty_runs_pre"] is None
    assert (chase["target_runs"], chase["target_overs"], chase["target_balls"]) == (15, 5.0, 30)
    assert chase["absent_hurt"] == ["b4"]
    assert json.loads(chase["miscounted_overs"])["1"]["balls"] == 7
    assert chase["super_over"] is False and chase["declared"] is False


def test_playing_xis(parsed):
    rows = parsed.match_players
    assert len(rows) == 8
    a = [r for r in rows if r["team"] == "A"]
    assert [r["name"] for r in a] == ["a1", "a2", "a3", "a4"]
    assert a[0]["identifier"] == "id-a1" and a[0]["player_order"] == 0


def test_overs_to_balls():
    assert cricsheet.overs_to_balls(35.1) == 211
    assert cricsheet.overs_to_balls(20, 5) == 100  # The Hundred
    assert cricsheet.overs_to_balls(None) is None


def test_missing_keys_do_not_crash():
    m = cricsheet.parse_match_data(
        {"info": {}, "innings": [{"overs": [{"deliveries": [{}]}]}]}, "X"
    )
    assert m.match["balls_per_over"] == 6 and m.match["match_date"] is None
    assert m.balls[0]["runs_total"] == 0 and m.balls[0]["extras_wides"] == 0
    assert m.innings[0]["target_runs"] is None


# ---- end to end: DuckDB + the chase metrics ---------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    src = tmp_path / "json"
    src.mkdir()
    (src / "M1.json").write_text(json.dumps(_match()), encoding="utf-8")
    parsed = cricsheet.parse_collection(src)
    m_path, b_path = cricsheet.write_collection(parsed, tmp_path / "parquet", "fixture")
    db_path = tmp_path / "c.duckdb"
    cricsheet.load_to_duckdb(m_path, b_path, "fixture", db_path)
    return db_path


def test_every_table_lands(db):
    with duckdb.connect(str(db), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for t in (
            "matches",
            "balls",
            "innings",
            "wickets",
            "replacements",
            "match_players",
            "players",
        ):
            assert f"{t}_fixture" in tables, t
        assert con.execute(
            "SELECT schema_version, n_matches FROM ingest_meta WHERE collection = 'fixture'"
        ).fetchone() == (cricsheet.SCHEMA_VERSION, 1)
        assert con.execute("SELECT COUNT(*) FROM wickets_fixture").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM replacements_fixture").fetchone()[0] == 2


def test_ngi_chase_uses_the_dls_target(db):
    with duckdb.connect(str(db), read_only=True) as con:
        s = ngi._build_state_table(con, "fixture")
    chase = s.filter(s["innings_idx"] == 1).sort("ball_in_over")
    assert chase["target"].to_list() == [15, 15, 15]
    # 5 overs = 30 balls, not the scheduled 120
    assert chase["balls_remaining"].to_list() == [30, 29, 28]
    assert chase["runs_needed"].to_list() == [15, 9, 5]


def test_ngi_falls_back_without_the_innings_table(db):
    with duckdb.connect(str(db)) as con:
        con.execute("DROP TABLE innings_fixture")
        con.execute("ALTER TABLE matches_fixture DROP COLUMN balls_per_over")
        s = ngi._build_state_table(con, "fixture")
    chase = s.filter(s["innings_idx"] == 1).sort("ball_in_over")
    first_total = int(s["first_total"][0])
    assert chase["target"].to_list() == [first_total + 1] * 3
    assert chase["balls_remaining"][0] == 120


def test_pressure_runs_runs_on_new_and_old_dbs(db):
    new = pressure_runs(collection="fixture", db_path=db, min_balls_faced=1, top_n=None)
    assert "b1" in new["batter"].to_list()
    with duckdb.connect(str(db)) as con:
        con.execute("DROP TABLE innings_fixture")
    old = pressure_runs(collection="fixture", db_path=db, min_balls_faced=1, top_n=None)
    assert old["chase_runs"].to_list() == new["chase_runs"].to_list()
