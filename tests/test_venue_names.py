"""One name per ground: city added, spellings and renames merged, aliases kept."""

from __future__ import annotations

import duckdb

from cricdesk.common.venue_names import aliases_for, canonical_names, normalize_venues


def test_spellings_and_renames_become_one_ground():
    rows = [
        ("Wankhede Stadium", "Mumbai"),
        ("Wankhede Stadium, Mumbai", "Mumbai"),
        ("M.Chinnaswamy Stadium", "Bangalore"),
        ("M Chinnaswamy Stadium, Bengaluru", "Bengaluru"),
        ("Feroz Shah Kotla", "Delhi"),
        ("Arun Jaitley Stadium, Delhi", "Delhi"),
        ("MA Chidambaram Stadium, Chepauk", "Chennai"),
    ]
    m = canonical_names(rows)
    assert {m[r] for r in rows[:2]} == {"Wankhede Stadium, Mumbai"}
    assert {m[r] for r in rows[2:4]} == {"M Chinnaswamy Stadium, Bengaluru"}
    assert {m[r] for r in rows[4:6]} == {"Arun Jaitley Stadium, Delhi"}
    assert m[rows[6]] == "MA Chidambaram Stadium, Chennai"


def test_same_name_in_different_cities_stays_apart():
    m = canonical_names(
        [
            ("County Ground", "Bristol"),
            ("County Ground", "Derby"),
            ("County Ground, Hove", "Brighton"),
        ]
    )
    assert set(m.values()) == {
        "County Ground, Bristol",
        "County Ground, Derby",
        "County Ground, Hove",
    }


def test_missing_city_is_filled_from_the_same_grounds_other_matches():
    m = canonical_names([("Eden Gardens", None), ("Eden Gardens", "Kolkata")])
    assert set(m.values()) == {"Eden Gardens, Kolkata"}
    # a city already in the ground's name isn't repeated
    assert canonical_names([("Melbourne Cricket Ground", "Melbourne")])[
        ("Melbourne Cricket Ground", "Melbourne")
    ] == ("Melbourne Cricket Ground")


def test_normalize_rewrites_tables_and_keeps_aliases():
    con = duckdb.connect()
    con.execute("CREATE TABLE matches_x (match_id VARCHAR, venue VARCHAR, city VARCHAR)")
    con.execute("CREATE TABLE balls_x (match_id VARCHAR, venue VARCHAR)")
    con.execute(
        "INSERT INTO matches_x VALUES ('1', 'Feroz Shah Kotla', 'Delhi'), ('2', 'Arun Jaitley Stadium', 'Delhi')"
    )
    con.execute(
        "INSERT INTO balls_x VALUES ('1', 'Feroz Shah Kotla'), ('2', 'Arun Jaitley Stadium')"
    )
    assert normalize_venues(con) == 1
    assert normalize_venues(con) == 1  # idempotent
    assert {r[0] for r in con.execute("SELECT DISTINCT venue FROM balls_x").fetchall()} == {
        "Arun Jaitley Stadium, Delhi"
    }
    assert "Feroz Shah Kotla" in aliases_for(con)["Arun Jaitley Stadium, Delhi"]
    assert (
        con.execute("SELECT venue_raw FROM matches_x WHERE match_id = '1'").fetchone()[0]
        == "Feroz Shah Kotla"
    )
