"""Player identity from Cricsheet's per-match registry, and every wicket on a delivery."""

from __future__ import annotations

import json

import duckdb
import pytest

from cricdesk.common.sql import base_suffix, player_ids, scorecard_names, wickets_rel
from cricdesk.scout.ingest import cricsheet


def _delivery(batter, bowler, non_striker="C Partner", runs=0, wickets=None, extras=None):
    d = {
        "batter": batter,
        "bowler": bowler,
        "non_striker": non_striker,
        "runs": {
            "batter": runs,
            "extras": 1 if extras else 0,
            "total": runs + (1 if extras else 0),
        },
    }
    if wickets:
        d["wickets"] = wickets
    if extras:
        d["extras"] = extras
    return d


MATCH_1 = {
    "info": {
        "dates": ["2024-04-01"],
        "match_type": "T20",
        "event": {"name": "Test League"},
        "venue": "Somewhere Ground",
        "teams": ["Reds", "Blues"],
        "overs": 20,
        "outcome": {"winner": "Reds", "by": {"runs": 5}},
        "toss": {"winner": "Reds", "decision": "bat"},
        "registry": {
            "people": {
                "A Batter": "aaaa0001",
                "C Partner": "cccc0001",
                "Navdeep Saini": "nnnn0001",
                "F Fielder": "ffff0001",
            }
        },
    },
    "innings": [
        {
            "team": "Reds",
            "overs": [
                {
                    "over": 0,
                    "deliveries": [
                        _delivery("A Batter", "Navdeep Saini", runs=4),
                        # a no-ball: the striker is stumped... and the non-striker is run out too
                        _delivery(
                            "A Batter",
                            "Navdeep Saini",
                            extras={"noballs": 1},
                            wickets=[
                                {"player_out": "A Batter", "kind": "obstructing the field"},
                                {
                                    "player_out": "C Partner",
                                    "kind": "run out",
                                    "fielders": [{"name": "F Fielder"}],
                                },
                            ],
                        ),
                    ],
                }
            ],
        }
    ],
}


@pytest.fixture
def extracted(tmp_path):
    d = tmp_path / "cricsheet" / "extracted" / "ipl_json"
    d.mkdir(parents=True)
    (d / "1001.json").write_text(json.dumps(MATCH_1), encoding="utf-8")
    return d


def test_parse_match_keeps_registry_and_every_wicket(extracted):
    full = cricsheet.parse_match_full(extracted / "1001.json")
    assert {(r["name"], r["identifier"]) for r in full.players} >= {
        ("A Batter", "aaaa0001"),
        ("Navdeep Saini", "nnnn0001"),
    }
    assert all(r["match_id"] == "1001" for r in full.players)
    # balls keep their shape (first wicket only) …
    assert len(full.balls) == 2
    assert full.balls[1]["player_out"] == "A Batter"
    # … while the wickets rows have both, on the same ball_id
    assert [(w["player_out"], w["wicket_kind"]) for w in full.wickets] == [
        ("A Batter", "obstructing the field"),
        ("C Partner", "run out"),
    ]
    assert {w["ball_id"] for w in full.wickets} == {full.balls[1]["ball_id"]}
    assert full.wickets[1]["fielders"] == ["F Fielder"]
    # the old two-tuple API still works
    m, b = cricsheet.parse_match(extracted / "1001.json")
    assert m["match_id"] == "1001" and len(b) == 2


def test_build_tables_land_in_duckdb(extracted, tmp_path):
    parsed = cricsheet.parse_collection(extracted)
    m_path, b_path = cricsheet.write_parquet(
        parsed.matches,
        parsed.balls,
        tmp_path / "parquet",
        "ipl",
        players=parsed.players,
        wickets=parsed.wickets,
    )
    db = tmp_path / "x.duckdb"
    cricsheet.load_to_duckdb(m_path, b_path, "ipl", db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM players_ipl").fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) FROM wickets_ipl").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM balls_ipl").fetchone()[0] == 2


def test_backfill_identity_leaves_balls_alone(extracted, tmp_path):
    base = tmp_path / "cricsheet"
    db = base / "cricsheet.duckdb"
    parsed = cricsheet.parse_collection(extracted)
    m_path, b_path = cricsheet.write_parquet(parsed.matches, parsed.balls, tmp_path / "pq", "ipl")
    cricsheet.load_to_duckdb(m_path, b_path, "ipl", db)  # an "old" DB: no players/wickets
    with duckdb.connect(str(db), read_only=True) as con:
        assert "players_ipl" not in {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        before = con.execute("SELECT * FROM balls_ipl ORDER BY ball_id").fetchall()

    assert cricsheet.backfill_identity("ipl", base=base) == (4, 2)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT * FROM balls_ipl ORDER BY ball_id").fetchall() == before
        assert con.execute(
            "SELECT identifier FROM players_ipl WHERE name = 'Navdeep Saini'"
        ).fetchone() == ("nnnn0001",)


def test_backfill_identity_needs_extracted_json(tmp_path):
    with pytest.raises(FileNotFoundError):
        cricsheet.backfill_identity("ipl", base=tmp_path)


@pytest.fixture
def id_db(tmp_path):
    path = tmp_path / "ids.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE people (identifier TEXT, name TEXT, unique_name TEXT)")
    con.executemany(
        "INSERT INTO people VALUES (?,?,?)",
        [
            (
                "nnnn0001",
                "NA Saini",
                "NA Saini",
            ),  # register spells him differently from the scorecard
            ("aaaa0001", "A Batter", "A Batter"),
            ("aaaa0002", "A Batter", "A Batter (2)"),
            ("zzzz0001", "Z Old", "Z Old"),  # only reachable by unique_name
        ],
    )
    con.execute("CREATE TABLE players_ipl (match_id TEXT, name TEXT, identifier TEXT)")
    con.executemany(
        "INSERT INTO players_ipl VALUES (?,?,?)",
        [
            ("1", "Navdeep Saini", "nnnn0001"),
            ("1", "A Batter", "aaaa0001"),
            ("2", "A Batter", "aaaa0001"),
            ("3", "A Batter", "aaaa0002"),  # a namesake in one match: the majority id wins
        ],
    )
    con.execute(
        "CREATE TABLE balls_ipl (ball_id TEXT, match_id TEXT, batter TEXT, bowler TEXT, "
        "player_out TEXT, wicket_kind TEXT, fielders TEXT[], innings_idx INT, match_type TEXT, "
        "extras_type TEXT)"
    )
    con.executemany(
        "INSERT INTO balls_ipl VALUES (?,?,?,?,?,?,?,0,'T20',NULL)",
        [
            ("1::0::0::1", "1", "A Batter", "Navdeep Saini", None, None, []),
            (
                "1::0::0::2",
                "1",
                "A Batter",
                "Navdeep Saini",
                "A Batter",
                "obstructing the field",
                [],
            ),
            ("1::0::0::3", "1", "Z Old", "Navdeep Saini", None, None, []),
        ],
    )
    con.execute(
        "CREATE TABLE wickets_ipl (match_id TEXT, innings_idx BIGINT, over BIGINT, ball_in_over BIGINT, "
        "ball_id TEXT, player_out TEXT, wicket_kind TEXT, fielders TEXT[])"
    )
    con.executemany(
        "INSERT INTO wickets_ipl VALUES ('1', 0, 0, 2, '1::0::0::2', ?, ?, ?)",
        [("A Batter", "obstructing the field", []), ("C Partner", "run out", ["F Fielder"])],
    )
    con.execute("CREATE TABLE balls_ipl_last1y AS SELECT * FROM balls_ipl")
    con.close()
    return path


def test_player_ids_prefers_match_registry(id_db):
    with duckdb.connect(str(id_db), read_only=True) as con:
        rel = player_ids(con, "ipl")
        got = dict(con.execute(f"SELECT name, identifier FROM {rel}").fetchall())
        # a window table resolves through its base collection's registry
        assert player_ids(con, "ipl_last1y") == rel
    assert got["Navdeep Saini"] == "nnnn0001"  # unique_name join would miss him
    assert got["A Batter"] == "aaaa0001"
    assert got["Z Old"] == "zzzz0001"  # not in the registry: unique_name fallback
    assert "NA Saini" in got  # register names still map (harmless: no balls carry them)


def test_player_ids_without_registry_falls_back(tmp_path):
    path = tmp_path / "old.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE people AS SELECT 'x1' AS identifier, 'X' AS name, 'X' AS unique_name"
        )
        rel = player_ids(con, "ipl")
        assert con.execute(f"SELECT * FROM {rel}").fetchall() == [("X", "x1")]
    with duckdb.connect(str(tmp_path / "empty.duckdb")) as con:
        assert player_ids(con, "ipl") is None


def test_scorecard_names(id_db):
    with duckdb.connect(str(id_db), read_only=True) as con:
        got = dict(con.execute(f"SELECT * FROM {scorecard_names(con, 'ipl')}").fetchall())
    assert got == {"aaaa0001": "A Batter", "nnnn0001": "Navdeep Saini", "zzzz0001": "Z Old"}


def test_wickets_rel_counts_every_wicket(id_db):
    with duckdb.connect(str(id_db), read_only=True) as con:
        rows = con.execute(
            f"SELECT player_out, wicket_kind, batter FROM {wickets_rel(con, 'ipl_last1y')} ORDER BY 1"
        ).fetchall()
    assert rows == [
        ("A Batter", "obstructing the field", "A Batter"),
        ("C Partner", "run out", "A Batter"),
    ]


def test_wickets_rel_falls_back_to_balls(tmp_path):
    path = tmp_path / "old.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE balls_ipl AS SELECT 'p' AS player_out, 'bowled' AS wicket_kind "
            "UNION ALL SELECT NULL, NULL"
        )
        assert con.execute(f"SELECT COUNT(*) FROM {wickets_rel(con, 'ipl')}").fetchone()[0] == 1


def test_base_suffix():
    assert base_suffix("ipl_last3y") == "ipl"
    assert base_suffix("indian-domestic_male") == "indian_domestic_male"


def test_dismissal_metrics_see_the_second_wicket(id_db):
    from cricdesk.metrics import batter, dismissal_fingerprint

    modes = dismissal_fingerprint.batter_modes("C Partner", collection="ipl", db_path=id_db)
    assert modes["total"] == 1 and modes["rows"][0]["kind"] == "run out"

    # C Partner never faced a ball here, so longevity is about A Batter: 1 dismissal in 2 balls
    out = batter.crease_longevity(collection="ipl", db_path=id_db, min_dismissals=1, top_n=None)
    row = out.filter(out["batter"] == "A Batter").to_dicts()[0]
    assert row["dismissals"] == 1 and row["total_balls"] == 2


def test_alias_map_goes_through_identifier(id_db):
    from cricdesk.profiles import identity

    with duckdb.connect(str(id_db)) as con:
        con.execute("CREATE TABLE people_names (identifier TEXT, name TEXT)")
        con.execute("INSERT INTO people_names VALUES ('nnnn0001', 'Navdeep Amarjeet Saini')")
    aliases = identity._alias_map("ipl", db_path=id_db)
    # the register's own name and its variations both land on the scorecard spelling
    assert aliases["na saini"] == "Navdeep Saini"
    assert aliases["navdeep amarjeet saini"] == "Navdeep Saini"
    # "A Batter (2)" is a different person who never plays in this collection's balls
    assert aliases.get("a batter (2)") is None
