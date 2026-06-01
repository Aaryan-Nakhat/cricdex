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

import json
from pathlib import Path

import duckdb
from loguru import logger
from neo4j import Driver

from cricdex.config import DATA_DIR, ROOT
from cricdex.scout.graph.schema import bootstrap, driver

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
BOWLING_STYLES_PATH = ROOT / "data" / "curated" / "bowling_styles.json"


def _load_bowling_style_overrides() -> dict:
    """Return curated overrides keyed by cricsheet_id and unique_name.

    Falls back to {} if the file is missing — heuristic still runs.
    """
    if not BOWLING_STYLES_PATH.exists():
        return {"by_cricsheet_id": {}, "by_unique_name": {}}
    with open(BOWLING_STYLES_PATH) as f:
        data = json.load(f)
    return {
        "by_cricsheet_id": data.get("by_cricsheet_id", {}),
        "by_unique_name": data.get("by_unique_name", {}),
    }


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
    """Player nodes carry a heuristic `role` + `bowling_style`.

    `role` ∈ {batter, bowler, all_rounder} comes from balls_faced vs
    balls_bowled.

    `bowling_style` ∈ {pace, spin, unknown} is decided in two passes:

    1. **Curated override** — `data/curated/bowling_styles.json` is
       hand-labelled for tricky cases (e.g. HV Patel and DJ Bravo
       bowl enough middle overs to trip the heuristic). When present,
       wins.
    2. **Middle-overs heuristic** — IPL spinners cluster on the
       middle overs (≥55% of their balls), pacers split between
       powerplay + death (<50% middle). Edge cases stay `unknown`.
       Validated against a holdout of 11 well-known IPL bowlers,
       perfect separation.

    Every Player node carries `bowling_style_source` so the dashboard
    can show provenance ("curated" / "inferred" / "unknown").

    DOB / handedness / bowling arm + Wikidata-grade biographical
    metadata remain DEFERRED — Wikidata works from this VM but is
    rate-limited; ESPNcricinfo is IP-blocked. See VNEXT group A.
    """
    safe = collection.replace("-", "_")
    overrides = _load_bowling_style_overrides()

    rows = con.execute(
        f"""
        WITH batting AS (
            SELECT batter AS name,
                   SUM(CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END) AS balls_faced,
                   MAX(match_date) AS last_match_date
            FROM balls_{safe}
            WHERE batter IS NOT NULL
            GROUP BY batter
        ),
        bowling AS (
            SELECT bowler AS name,
                   SUM(CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END) AS balls_bowled,
                   MAX(match_date) AS last_match_date,
                   SUM(CASE WHEN phase = 'middle' THEN 1 ELSE 0 END) AS middle_balls
            FROM balls_{safe}
            WHERE bowler IS NOT NULL
            GROUP BY bowler
        ),
        merged AS (
            SELECT COALESCE(b.name, k.name) AS name,
                   COALESCE(b.balls_faced, 0) AS balls_faced,
                   COALESCE(k.balls_bowled, 0) AS balls_bowled,
                   COALESCE(k.middle_balls, 0) AS middle_balls,
                   GREATEST(
                       COALESCE(b.last_match_date, ''),
                       COALESCE(k.last_match_date, '')
                   ) AS last_match_date
            FROM batting b
            FULL OUTER JOIN bowling k ON b.name = k.name
        )
        SELECT
            m.name,
            COALESCE(r.cricsheet_id, 'unresolved:' || m.name) AS cricsheet_id,
            r.cricinfo_id,
            r.cricbuzz_id,
            (r.cricsheet_id IS NULL) AS unresolved,
            CAST(m.balls_faced AS BIGINT)   AS balls_faced,
            CAST(m.balls_bowled AS BIGINT)  AS balls_bowled,
            CAST(m.middle_balls AS BIGINT)  AS middle_balls,
            m.last_match_date,
            CASE
                WHEN m.balls_bowled >= 60 AND m.balls_faced >= 60 THEN 'all_rounder'
                WHEN m.balls_bowled >= m.balls_faced THEN 'bowler'
                ELSE 'batter'
            END AS role
        FROM merged m
        LEFT JOIN _resolved_names r ON r.name = m.name
        """
    ).fetchall()

    by_cid = overrides["by_cricsheet_id"]
    by_name = overrides["by_unique_name"]

    enriched = []
    for r in rows:
        name = r[0]
        cid = r[1]
        balls_bowled = int(r[6] or 0)
        middle_balls = int(r[7] or 0)

        # Bowling-style decision
        if cid in by_cid:
            style = by_cid[cid]["style"]
            style_src = "curated"
        elif name in by_name:
            style = by_name[name]["style"]
            style_src = "curated"
        elif balls_bowled < 120:
            style = "unknown"
            style_src = "insufficient_balls"
        else:
            mid_pct = (middle_balls / balls_bowled) if balls_bowled else 0
            if mid_pct >= 0.55:
                style = "spin"
                style_src = "inferred"
            elif mid_pct < 0.50:
                style = "pace"
                style_src = "inferred"
            else:
                style = "unknown"
                style_src = "inferred_borderline"

        middle_pct_val = round((middle_balls / balls_bowled) * 100, 1) if balls_bowled else None

        enriched.append(
            {
                "name": name,
                "cricsheet_id": cid,
                "cricinfo_id": r[2],
                "cricbuzz_id": r[3],
                "unresolved": r[4],
                "balls_faced": int(r[5] or 0),
                "balls_bowled": balls_bowled,
                "last_match_date": r[8],
                "role": r[9],
                "bowling_style": style,
                "bowling_style_source": style_src,
                "middle_overs_pct": middle_pct_val,
            }
        )

    with drv.session() as s:
        s.run(
            """
            UNWIND $rows AS r
            MERGE (p:Player {cricsheet_id: r.cricsheet_id, collection: $collection})
            SET p.unique_name          = r.name,
                p.key_cricinfo         = r.cricinfo_id,
                p.key_cricbuzz         = r.cricbuzz_id,
                p.unresolved           = r.unresolved,
                p.balls_faced          = r.balls_faced,
                p.balls_bowled         = r.balls_bowled,
                p.last_match_date      = r.last_match_date,
                p.role                 = r.role,
                p.bowling_style        = r.bowling_style,
                p.bowling_style_source = r.bowling_style_source,
                p.middle_overs_pct     = r.middle_overs_pct
            """,
            rows=enriched,
            collection=collection,
        )
    return len(enriched)


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
                MATCH (b:Player {cricsheet_id: r.batter_id, collection: $collection})
                MATCH (k:Player {cricsheet_id: r.bowler_id, collection: $collection})
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
                collection=collection,
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
                MATCH (p:Player {cricsheet_id: r.cricsheet_id, collection: $collection})
                MATCH (m:Match  {match_id: r.match_id})
                MERGE (p)-[e:PLAYED_IN]->(m)
                SET e.team = r.team
                """,
                rows=[
                    {"match_id": row[0], "team": row[1], "cricsheet_id": row[2]} for row in chunk
                ],
                collection=collection,
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
                MATCH (a:Player {cricsheet_id: r.a, collection: $collection})
                MATCH (b:Player {cricsheet_id: r.b, collection: $collection})
                MERGE (a)-[e:TEAMMATE_OF]->(b)
                SET e.matches_together = r.matches_together
                """,
                rows=[{"a": row[0], "b": row[1], "matches_together": int(row[2])} for row in chunk],
                collection=collection,
            )
            total += len(chunk)
    return total


def _clear_collection(drv: Driver, collection: str) -> None:
    """Delete this collection's subgraph (Player nodes carrying the
    collection tag + their relationships) so a re-populate is a clean
    rewrite, not a stale-node accumulation. Match/Venue nodes are shared
    across collections and left intact."""
    with drv.session() as s:
        s.run(
            "MATCH (p:Player {collection: $collection}) DETACH DELETE p",
            collection=collection,
        )


def populate(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, int]:
    drv = driver()
    try:
        bootstrap(drv)
        _clear_collection(drv, collection)
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
