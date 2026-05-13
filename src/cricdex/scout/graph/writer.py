"""Populate the scout Neo4j graph from DuckDB.

Reads `people` + `balls_<collection>` + `matches_<collection>` and writes:
    - Player nodes        (one per cricsheet_id)
    - Match nodes         (one per match_id)
    - Venue nodes
    - FACED edges         batter -[FACED]-> bowler, aggregated balls /
                          runs / dismissals across the collection.
    - TEAMMATE_OF edges   undirected (we write one direction; queries
                          should `[r:TEAMMATE_OF]-()` without arrow) —
                          aggregates `matches_together` per (player_a,
                          player_b) co-appearing in the same XI.
    - PLAYED_IN edges     (Player)-[:PLAYED_IN {team}]->(Match).

Resolves player names to Cricsheet IDs via the People Register
(`people.unique_name → people.identifier`). Names that don't resolve are
written as Player nodes with `unresolved=True` and `cricsheet_id=name`
so they still participate in the graph, just without cross-source bridges.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from loguru import logger
from neo4j import Driver

from cricdex.config import DATA_DIR
from cricdex.scout.graph.schema import bootstrap, driver

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _resolve_people(con: duckdb.DuckDBPyConnection) -> None:
    """Write a temp `_resolved_names` table that joins ball names to
    cricsheet identifiers via the people register."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _resolved_names AS
        SELECT
            p.unique_name AS name,
            p.identifier   AS cricsheet_id,
            p.key_cricinfo AS cricinfo_id,
            p.key_cricbuzz AS cricbuzz_id
        FROM people p
        """
    )


def _write_players(
    drv: Driver,
    con: duckdb.DuckDBPyConnection,
    collection: str,
) -> int:
    safe = collection.replace("-", "_")
    rows = con.execute(
        f"""
        WITH names AS (
            SELECT DISTINCT batter AS name FROM balls_{safe} WHERE batter IS NOT NULL
            UNION
            SELECT DISTINCT bowler FROM balls_{safe} WHERE bowler IS NOT NULL
        )
        SELECT
            n.name,
            COALESCE(r.cricsheet_id, 'unresolved:' || n.name) AS cricsheet_id,
            r.cricinfo_id,
            r.cricbuzz_id,
            (r.cricsheet_id IS NULL) AS unresolved
        FROM names n
        LEFT JOIN _resolved_names r ON r.name = n.name
        """
    ).fetchall()

    with drv.session() as s:
        s.run(
            """
            UNWIND $rows AS r
            MERGE (p:Player {cricsheet_id: r.cricsheet_id})
            SET p.unique_name = r.name,
                p.key_cricinfo = r.cricinfo_id,
                p.key_cricbuzz = r.cricbuzz_id,
                p.unresolved = r.unresolved
            """,
            rows=[
                {
                    "name": r[0],
                    "cricsheet_id": r[1],
                    "cricinfo_id": r[2],
                    "cricbuzz_id": r[3],
                    "unresolved": r[4],
                }
                for r in rows
            ],
        )
    return len(rows)


def _write_matches(
    drv: Driver,
    con: duckdb.DuckDBPyConnection,
    collection: str,
) -> int:
    safe = collection.replace("-", "_")
    rows = con.execute(
        f"""
        SELECT match_id, match_date, match_type, league, venue, city, overs
        FROM matches_{safe}
        """
    ).fetchall()

    with drv.session() as s:
        s.run(
            """
            UNWIND $rows AS r
            MERGE (m:Match {match_id: r.match_id})
            SET m.match_date = r.match_date,
                m.match_type = r.match_type,
                m.league     = r.league,
                m.overs      = r.overs
            MERGE (v:Venue {name: COALESCE(r.venue, 'Unknown')})
            SET v.city = r.city
            MERGE (m)-[:AT]->(v)
            """,
            rows=[
                {
                    "match_id": r[0],
                    "match_date": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
                    "match_type": r[2],
                    "league": r[3],
                    "venue": r[4],
                    "city": r[5],
                    "overs": r[6],
                }
                for r in rows
            ],
        )
    return len(rows)


def _write_faced_edges(
    drv: Driver,
    con: duckdb.DuckDBPyConnection,
    collection: str,
    batch_size: int = 5000,
) -> int:
    safe = collection.replace("-", "_")
    # Aggregate one row per (batter, bowler) across the whole collection.
    agg = con.execute(
        f"""
        WITH labelled AS (
            SELECT
                COALESCE(rb.cricsheet_id, 'unresolved:' || b.batter) AS batter_id,
                COALESCE(rk.cricsheet_id, 'unresolved:' || b.bowler) AS bowler_id,
                b.runs_batter,
                CASE WHEN b.extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball,
                CASE WHEN b.wicket_kind IS NOT NULL
                      AND (b.player_out IS NULL OR b.player_out = b.batter)
                     THEN 1 ELSE 0 END AS dismissed
            FROM balls_{safe} b
            LEFT JOIN _resolved_names rb ON rb.name = b.batter
            LEFT JOIN _resolved_names rk ON rk.name = b.bowler
            WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL
        )
        SELECT
            batter_id, bowler_id,
            SUM(legal_ball) AS balls,
            SUM(runs_batter) AS runs,
            SUM(dismissed)  AS dismissals
        FROM labelled
        GROUP BY batter_id, bowler_id
        """
    ).fetchall()

    total = 0
    with drv.session() as s:
        for start in range(0, len(agg), batch_size):
            chunk = agg[start : start + batch_size]
            s.run(
                """
                UNWIND $rows AS r
                MATCH (b:Player {cricsheet_id: r.batter_id})
                MATCH (k:Player {cricsheet_id: r.bowler_id})
                MERGE (b)-[f:FACED]->(k)
                SET f.balls = r.balls,
                    f.runs = r.runs,
                    f.dismissals = r.dismissals
                """,
                rows=[
                    {
                        "batter_id": row[0],
                        "bowler_id": row[1],
                        "balls": int(row[2] or 0),
                        "runs": int(row[3] or 0),
                        "dismissals": int(row[4] or 0),
                    }
                    for row in chunk
                ],
            )
            total += len(chunk)
    return total


def _write_played_in_edges(
    drv: Driver,
    con: duckdb.DuckDBPyConnection,
    collection: str,
    batch_size: int = 5000,
) -> int:
    """One (Player)-[:PLAYED_IN {team}]->(Match) edge per (player, match,
    team) triple. Aggregated from balls — anyone who batted, faced as
    non-striker, or bowled in a given innings is on that innings' team.
    """
    safe = collection.replace("-", "_")
    rows = con.execute(
        f"""
        WITH appearances AS (
            SELECT match_id, batting_team AS team, batter AS name
            FROM balls_{safe} WHERE batter IS NOT NULL
            UNION
            SELECT match_id, batting_team AS team, non_striker AS name
            FROM balls_{safe} WHERE non_striker IS NOT NULL
            UNION
            SELECT match_id, bowling_team AS team, bowler AS name
            FROM balls_{safe} WHERE bowler IS NOT NULL
        )
        SELECT DISTINCT
            a.match_id,
            a.team,
            COALESCE(r.cricsheet_id, 'unresolved:' || a.name) AS cricsheet_id
        FROM appearances a
        LEFT JOIN _resolved_names r ON r.name = a.name
        """
    ).fetchall()

    total = 0
    with drv.session() as s:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            s.run(
                """
                UNWIND $rows AS r
                MATCH (p:Player {cricsheet_id: r.cricsheet_id})
                MATCH (m:Match  {match_id: r.match_id})
                MERGE (p)-[e:PLAYED_IN]->(m)
                SET e.team = r.team
                """,
                rows=[
                    {"match_id": row[0], "team": row[1], "cricsheet_id": row[2]} for row in chunk
                ],
            )
            total += len(chunk)
    return total


def _write_teammate_edges(
    drv: Driver,
    con: duckdb.DuckDBPyConnection,
    collection: str,
    batch_size: int = 5000,
) -> int:
    """One (Player)-[:TEAMMATE_OF {matches_together}]->(Player) edge per
    unordered pair (a < b) that shared a team in any match across the
    collection. Aggregates the count of shared matches.
    """
    safe = collection.replace("-", "_")
    rows = con.execute(
        f"""
        WITH appearances AS (
            SELECT DISTINCT match_id, batting_team AS team, batter AS name
            FROM balls_{safe} WHERE batter IS NOT NULL
            UNION
            SELECT DISTINCT match_id, batting_team, non_striker
            FROM balls_{safe} WHERE non_striker IS NOT NULL
            UNION
            SELECT DISTINCT match_id, bowling_team, bowler
            FROM balls_{safe} WHERE bowler IS NOT NULL
        ),
        resolved AS (
            SELECT a.match_id, a.team,
                   COALESCE(r.cricsheet_id, 'unresolved:' || a.name) AS pid
            FROM appearances a
            LEFT JOIN _resolved_names r ON r.name = a.name
        ),
        pairs AS (
            SELECT DISTINCT
                r1.match_id,
                LEAST(r1.pid, r2.pid)    AS a,
                GREATEST(r1.pid, r2.pid) AS b
            FROM resolved r1
            JOIN resolved r2
              ON r1.match_id = r2.match_id
             AND r1.team = r2.team
             AND r1.pid < r2.pid
        )
        SELECT a, b, COUNT(*) AS matches_together
        FROM pairs
        GROUP BY a, b
        """
    ).fetchall()

    total = 0
    with drv.session() as s:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            s.run(
                """
                UNWIND $rows AS r
                MATCH (a:Player {cricsheet_id: r.a})
                MATCH (b:Player {cricsheet_id: r.b})
                MERGE (a)-[e:TEAMMATE_OF]->(b)
                SET e.matches_together = r.matches_together
                """,
                rows=[{"a": row[0], "b": row[1], "matches_together": int(row[2])} for row in chunk],
            )
            total += len(chunk)
    return total


def populate(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, int]:
    drv = driver()
    try:
        bootstrap(drv)
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            _resolve_people(con)
            n_players = _write_players(drv, con, collection)
            n_matches = _write_matches(drv, con, collection)
            n_faced = _write_faced_edges(drv, con, collection)
            n_played_in = _write_played_in_edges(drv, con, collection)
            n_teammates = _write_teammate_edges(drv, con, collection)
        finally:
            con.close()
    finally:
        drv.close()

    summary = {
        "players": n_players,
        "matches": n_matches,
        "faced_edges": n_faced,
        "played_in_edges": n_played_in,
        "teammate_edges": n_teammates,
    }
    logger.info(f"populated scout graph from {collection}: {summary}")
    return summary
