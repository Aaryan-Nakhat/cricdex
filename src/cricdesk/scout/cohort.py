"""Graph cohort — "who faced the same bowlers / bowled to the same batters".

A pure-DuckDB rewrite of the old Neo4j FACED-graph traversal (removed with the
rest of the graph stack). It answers the same question — which players operated
in the same competitive neighbourhood as the target — straight from the
ball-by-ball table, no graph DB:

- Target is a **batter** → other batters who faced the same bowlers, ranked by
  the count of distinct shared bowlers (`shared_bowlers`).
- Target is a **bowler** → other bowlers who bowled to the same batters, ranked
  by distinct shared batters (`shared_batters`).

Batter-vs-bowler is decided by ball volume (`balls_bowled > balls_faced`), not
the lenient role tag — so part-timers like Kohli/Rohit stay on the batter axis
and Bumrah on the bowler axis, matching the old graph behaviour.

`export_site.py` writes the result to `cohorts/<cricsheet_id>.json` (the
`co_faced` list the web + desktop Player Profile render).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from cricdesk.common.sql import (
    MAIN_INNINGS,
    cid_of,
    keyed_balls,
    label_map,
    name_of_key,
    resolve_key,
    table_suffix,
)
from cricdesk.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def ball_volumes(
    con: duckdb.DuckDBPyConnection, collection: str = "ipl"
) -> dict[str, tuple[int, int]]:
    """{player key: (balls_faced, balls_bowled)} for the collection — computed
    once and reused across every player's cohort to pick the batter/bowler axis. A key is the
    player's registry id (`unresolved:<name>` if the registry doesn't know him)."""
    table_suffix(collection)  # rejects an unsafe collection name
    kb = keyed_balls(con, collection)
    rows = con.execute(
        f"""
        SELECT player, SUM(faced) AS bf, SUM(bowled) AS bb FROM (
            SELECT batter AS player, 1 AS faced, 0 AS bowled FROM {kb}
            WHERE batter IS NOT NULL AND extras_type IS DISTINCT FROM 'wides' AND {MAIN_INNINGS}
            UNION ALL
            SELECT bowler AS player, 0, 1 FROM {kb} WHERE bowler IS NOT NULL AND {MAIN_INNINGS}
        ) GROUP BY player
        """
    ).fetchall()
    return {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}


def co_faced(
    name: str,
    collection: str = "ipl",
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    vol: dict[str, tuple[int, int]] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    top_k: int = 12,
) -> list[dict]:
    """Top-`top_k` cohort for a player (`name` = his registry id, or a scorecard name). Pass a
    shared `con` + precomputed `vol` when building many players in one export pass; otherwise it
    opens its own read-only connection. Rows carry `name` (scorecard) and `cricsheet_id`."""
    own = con is None
    if own:
        con = duckdb.connect(str(db_path), read_only=True)
    try:
        table_suffix(collection)  # rejects an unsafe collection name
        kb = keyed_balls(con, collection)
        key = name if name in (vol or {}) else resolve_key(con, collection, name)
        if vol is None:
            vol = ball_volumes(con, collection)
        bf, bb = vol.get(key, (0, 0))
        if bf == 0 and bb == 0:
            return []
        target_is_bowler = bb > bf

        if target_is_bowler:
            # other bowlers who bowled to the same batters this bowler saw
            rows = con.execute(
                f"""
                SELECT bowler AS q, COUNT(DISTINCT batter) AS shared
                FROM {kb}
                WHERE batter IN (
                        SELECT DISTINCT batter FROM {kb}
                        WHERE bowler = ? AND batter IS NOT NULL AND {MAIN_INNINGS}
                      )
                  AND bowler IS NOT NULL AND bowler <> ? AND {MAIN_INNINGS}
                GROUP BY bowler ORDER BY shared DESC, q LIMIT 300
                """,
                [key, key],
            ).fetchall()
            field = "shared_batters"
        else:
            # other batters who faced the same bowlers this batter faced
            rows = con.execute(
                f"""
                SELECT batter AS q, COUNT(DISTINCT bowler) AS shared
                FROM {kb}
                WHERE bowler IN (
                        SELECT DISTINCT bowler FROM {kb}
                        WHERE batter = ? AND bowler IS NOT NULL AND {MAIN_INNINGS}
                      )
                  AND batter IS NOT NULL AND batter <> ? AND {MAIN_INNINGS}
                GROUP BY batter ORDER BY shared DESC, q LIMIT 300
                """,
                [key, key],
            ).fetchall()
            field = "shared_bowlers"

        out: list[dict] = []
        labels: dict[str, str] | None = None
        for q, shared in rows:
            q_bf, q_bb = vol.get(q, (0, 0))
            # keep candidates on the same axis as the target (bowler vs batter)
            on_axis = (q_bb > q_bf) if target_is_bowler else (q_bf >= q_bb)
            if on_axis:
                labels = labels if labels is not None else label_map(con, collection)
                out.append(
                    {"name": name_of_key(q, labels), "cricsheet_id": cid_of(q), field: int(shared)}
                )
                if len(out) >= top_k:
                    break
        return out
    finally:
        if own:
            con.close()


__all__ = ["ball_volumes", "co_faced"]
