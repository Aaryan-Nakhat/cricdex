"""Phase specialists — powerplay / middle / death leaderboards.

Uses the `phase` column already on `balls_<collection>` (set at ingest:
powerplay / middle / death for limited-overs). Batters ranked by strike rate
in a phase; bowlers by economy. Min-balls gated to drop tiny samples.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from cricdesk.common.sql import (
    BOWLER_RUNS,
    MAIN_INNINGS,
    cid_of,
    keyed_balls,
    label_map,
    name_of_key,
    table_suffix,
)
from cricdesk.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
PHASES = ("powerplay", "middle", "death")


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def phase_leaders(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_bat_balls: int = 90,
    min_bowl_balls: int = 90,
    top: int = 25,
) -> dict[str, dict]:
    """{phase: {"batters": [{name,balls,runs,sr}], "bowlers": [{name,balls,
    runs,wickets,econ}]}} for powerplay / middle / death. Grouped by registry id (two players who
    share a scorecard name stay two rows); each row carries `name` (scorecard), `cricsheet_id` and
    `key` (the id, or `unresolved:<name>`)."""
    table_suffix(collection)  # rejects an unsafe collection name
    out: dict[str, dict] = {}
    with _connect(db_path) as con:
        kb = keyed_balls(con, collection)
        labels = label_map(con, collection)
        for ph in PHASES:
            bat = con.execute(
                f"""
                SELECT batter AS name,
                       SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
                       SUM(runs_batter) AS runs
                FROM {kb}
                WHERE phase = ? AND batter IS NOT NULL AND {MAIN_INNINGS}
                GROUP BY batter
                HAVING balls >= {min_bat_balls}
                ORDER BY 100.0 * runs / NULLIF(balls, 0) DESC, name
                LIMIT {top}
                """,
                [ph],
            ).fetchall()
            bowl = con.execute(
                f"""
                SELECT bowler AS name,
                       SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides'
                                 AND extras_type IS DISTINCT FROM 'noballs'
                                THEN 1 ELSE 0 END) AS balls,
                       SUM({BOWLER_RUNS}) AS runs,
                       SUM(CASE WHEN player_out IS NOT NULL
                                 AND wicket_kind NOT IN ('run out', 'retired hurt',
                                     'retired out', 'obstructing the field')
                                THEN 1 ELSE 0 END) AS wickets
                FROM {kb}
                WHERE phase = ? AND bowler IS NOT NULL AND {MAIN_INNINGS}
                GROUP BY bowler
                HAVING balls >= {min_bowl_balls}
                ORDER BY 6.0 * runs / NULLIF(balls, 0) ASC, name
                LIMIT {top}
                """,
                [ph],
            ).fetchall()
            out[ph] = {
                "batters": [
                    {
                        "name": name_of_key(n, labels),
                        "cricsheet_id": cid_of(n),
                        "key": n,
                        "balls": int(b),
                        "runs": int(r or 0),
                        "sr": round(100.0 * (r or 0) / b, 1) if b else 0.0,
                    }
                    for n, b, r in bat
                ],
                "bowlers": [
                    {
                        "name": name_of_key(n, labels),
                        "cricsheet_id": cid_of(n),
                        "key": n,
                        "balls": int(b),
                        "runs": int(r or 0),
                        "wickets": int(w or 0),
                        "econ": round(6.0 * (r or 0) / b, 2) if b else 0.0,
                    }
                    for n, b, r, w in bowl
                ],
            }
    return out


__all__ = ["PHASES", "phase_leaders"]
