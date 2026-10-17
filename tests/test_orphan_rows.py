"""Side tables must never point at matches the ball data doesn't have."""

import duckdb

from cricdex.scout.ingest.cricsheet import drop_orphan_rows


def test_drop_orphan_rows_keeps_only_ingested_matches():
    con = duckdb.connect()
    con.execute("CREATE TABLE matches_x AS SELECT * FROM (VALUES ('m1'), ('m2')) t(match_id)")
    con.execute(
        "CREATE TABLE players_x AS SELECT * FROM (VALUES ('m1','A'), ('m3','B'), ('m3','C')) "
        "t(match_id, name)"
    )
    con.execute("CREATE TABLE wickets_x AS SELECT * FROM (VALUES ('m2'), ('m9')) t(match_id)")
    removed = drop_orphan_rows(con, "x")
    assert removed == {"players_x": 2, "wickets_x": 1}
    assert con.execute("SELECT match_id FROM players_x").fetchall() == [("m1",)]
    assert con.execute("SELECT match_id FROM wickets_x").fetchall() == [("m2",)]
    # nothing to do the second time, and a missing table is fine
    assert drop_orphan_rows(con, "x") == {}
    assert drop_orphan_rows(con, "nope") == {}
