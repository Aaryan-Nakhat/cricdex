"""Head-to-head matchups + pace/spin splits, straight from the ball-by-ball.

- `pairwise(collection)` → one row per (batter, bowler) with balls / runs / SR /
  dot% / bowler-credited dismissals. The export slices it per player into
  `matchups/<cid>.json` (`as_batter` = rows where batter==P, `as_bowler` = rows
  where bowler==P).
- `pace_spin_splits(collection, bowler_category)` → per batter, SR + dismissal
  rate vs seam vs spin (bowler type from the player master / taxonomy, by id).

Players are keyed by their registry id, resolved per match (`common.sql.keyed_balls`), so
two players sharing a scorecard name are never merged; rows carry the scorecard names for
display and `batter_key` / `bowler_key` (the id, or `unresolved:<name>`) for lookups.

No new columns — `balls_<collection>` already carries batter/bowler/runs/
extras_type/wicket_kind/player_out.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from cricdesk.common.sql import MAIN_INNINGS, UNRESOLVED, keyed_query, keyed_sql, table_suffix
from cricdesk.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# Dismissals credited to the bowler (run-outs etc. are not the matchup's).
_BOWLER_OUTS = ("bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket")


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def pairwise(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 6,
) -> list[dict]:
    """One row per (batter, bowler) meeting `min_balls` legal deliveries."""
    table_suffix(collection)  # rejects an unsafe collection name
    outs = " OR ".join(f"wicket_kind = '{k}'" for k in _BOWLER_OUTS)
    sql = f"""
    WITH agg AS (
        SELECT
            batter, bowler,
            SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
            SUM(runs_batter) AS runs,
            SUM(CASE WHEN runs_total = 0 AND extras_type IS DISTINCT FROM 'wides'
                     THEN 1 ELSE 0 END) AS dots,
            SUM(CASE WHEN player_out = batter AND ({outs}) THEN 1 ELSE 0 END) AS outs
        FROM __BALLS__
        WHERE batter IS NOT NULL AND bowler IS NOT NULL AND {MAIN_INNINGS}
        GROUP BY batter, bowler
    )
    SELECT batter, bowler, batter AS batter_key, bowler AS bowler_key, balls, runs, outs,
           CAST(ROUND(100.0 * runs / NULLIF(balls, 0), 1) AS DOUBLE) AS sr,
           CAST(ROUND(100.0 * dots / NULLIF(balls, 0), 1) AS DOUBLE) AS dot_pct
    FROM agg
    WHERE balls >= {min_balls}
    ORDER BY balls DESC, batter_key, bowler_key
    """
    with _connect(db_path) as con:
        df = keyed_query(con, collection, sql, ("batter", "bowler"))
    if df.is_empty():
        return []
    df = df.rename({"cricsheet_id": "batter_id"}).drop("display_name")
    cols = ["batter", "bowler", "batter_id", "bowler_id", "batter_key", "bowler_key", "balls"]
    cols += ["runs", "outs", "sr", "dot_pct"]
    return df.select(cols).to_dicts()


def pace_spin_splits(
    collection: str = "ipl",
    bowler_category: dict[str, str] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 60,
) -> dict[str, dict]:
    """{batter key -> {vs_seam:{balls,runs,sr,outs,out_rate}, vs_spin:{…}}}.

    `bowler_category` maps a bowler's registry id (or, for an unresolved player, his scorecard
    name) → 'seam' | 'spin'; deliveries by uncategorised bowlers are ignored. The result is keyed
    by the batter's key (his registry id, or `unresolved:<name>`).
    """
    if not bowler_category:
        return {}
    table_suffix(collection)  # rejects an unsafe collection name
    outs = " OR ".join(f"wicket_kind = '{k}'" for k in _BOWLER_OUTS)
    pairs = [{"bowler": n, "cat": c} for n, c in bowler_category.items() if c in ("seam", "spin")]
    if not pairs:
        return {}
    with _connect(db_path) as con:
        import polars as pl

        con.register("bcat", pl.DataFrame(pairs))
        rows = con.execute(
            keyed_sql(
                con,
                collection,
                f"""
            SELECT b.batter AS batter, bc.cat AS cat,
                   SUM(CASE WHEN b.extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
                   SUM(b.runs_batter) AS runs,
                   SUM(CASE WHEN b.player_out = b.batter AND ({outs}) THEN 1 ELSE 0 END) AS outs
            FROM __BALLS__ b
            JOIN bcat bc ON bc.bowler = b.bowler
                OR (b.bowler LIKE '{UNRESOLVED}%' AND bc.bowler = b.bowler_name)
            WHERE b.batter IS NOT NULL AND {MAIN_INNINGS}
            GROUP BY b.batter, bc.cat
            ORDER BY b.batter, bc.cat
            """,
            )
        ).fetchall()
    out: dict[str, dict] = {}
    for batter, cat, balls, runs, dis in rows:
        if not balls:
            continue
        rec = {
            "balls": int(balls),
            "runs": int(runs or 0),
            "sr": round(100.0 * (runs or 0) / balls, 1),
            "outs": int(dis or 0),
            "out_rate": round((dis or 0) / balls * 100, 2),  # dismissals per 100 balls
        }
        out.setdefault(batter, {})[f"vs_{cat}"] = rec
    # keep only batters with a decent sample on at least one side
    return {
        b: v
        for b, v in out.items()
        if max((s.get("balls", 0) for s in v.values()), default=0) >= min_balls
    }


__all__ = ["pace_spin_splits", "pairwise"]
