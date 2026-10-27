"""Fielding + wicketkeeping boards from the `fielders` dismissal field.

Cricsheet records the fielder(s) involved in a dismissal in `balls.fielders`
(a VARCHAR[]). We count, per fielder:
  • catches      — wicket_kind = 'caught'   (NB: 'caught and bowled' is a
                   separate kind with an empty fielders array — a bowling
                   wicket — so it's excluded here, correctly)
  • stumpings    — wicket_kind = 'stumped'
  • run-outs     — wicket_kind = 'run out'  (every fielder in the array is
                   credited an involvement; rows with a null/empty array are
                   skipped — incomplete data)

Players are split into two boards because keepers also assist run-outs:
  • Wicketkeeping — keepers (taxonomy primary_role 'wk_batter' OR any stumping)
  • Fielding      — everyone else (outfield)

This is a dismissal *count* (no diving/range/positioning — that needs video).
Keyed by the fielder's registry id (`cricsheet_id`; `fielder` is his scorecard name), tagged with
matches/taxonomy/activity at export time like every other leaderboard.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.common.sql import MAIN_INNINGS, keyed_query, table_suffix
from cricdex.config import CURATED_DIR, DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
TAXONOMY_PATH = CURATED_DIR / "player_taxonomy.json"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def _keeper_ids() -> set[str]:
    """Cricsheet ids of the players classified as wicket-keepers: the player master when it is built,
    else the LLM taxonomy (both keyed by id, so a namesake of a keeper isn't one)."""
    from cricdex.scout.identity import master

    ident = master.load()
    if not ident and TAXONOMY_PATH.exists():
        from cricdex.scout.identity.taxonomy import load_taxonomy

        ident = load_taxonomy(TAXONOMY_PATH)  # LLM output: allow-lists checked
    return {
        cid
        for cid, rec in ident.items()
        if isinstance(rec, dict) and rec.get("primary_role") == "wk_batter"
    }


def _tally(collection: str, db_path: Path | str) -> pl.DataFrame:
    """Per-fielder {catches, stumpings, runouts, dismissals} + is_keeper."""
    table_suffix(collection)  # rejects an unsafe collection name
    # every wicket on a delivery (a second one off the same ball is lost from balls_), fielders as ids
    sql = f"""
    WITH dis AS (
        SELECT unnest(fielders) AS fielder, wicket_kind
        FROM __WICKETS__
        WHERE wicket_kind IN ('caught', 'stumped', 'run out') AND len(fielders) > 0 AND {MAIN_INNINGS}
    )
    SELECT
        fielder,
        SUM(CASE WHEN wicket_kind = 'caught' THEN 1 ELSE 0 END) AS catches,
        SUM(CASE WHEN wicket_kind = 'stumped' THEN 1 ELSE 0 END) AS stumpings,
        SUM(CASE WHEN wicket_kind = 'run out' THEN 1 ELSE 0 END) AS runouts,
        COUNT(*) AS dismissals
    FROM dis
    WHERE fielder IS NOT NULL
    GROUP BY fielder
    """
    with _connect(db_path) as con:
        df = keyed_query(con, collection, sql, ("fielder",))
    if df.is_empty():
        return df.with_columns(pl.lit(False).alias("is_keeper"))
    keepers = _keeper_ids()
    return df.with_columns(
        pl.col("catches").cast(pl.Int64),
        pl.col("stumpings").cast(pl.Int64),
        pl.col("runouts").cast(pl.Int64),
        ((pl.col("cricsheet_id").is_in(list(keepers))) | (pl.col("stumpings") > 0)).alias(
            "is_keeper"
        ),
    )


def keeping(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Wicketkeeping board — keepers, by total dismissals behind the stumps
    (catches + stumpings + run-out involvements)."""
    df = _tally(collection, db_path).filter(pl.col("is_keeper"))
    df = df.select(
        "fielder", "cricsheet_id", "display_name", "dismissals", "catches", "stumpings", "runouts"
    ).sort("dismissals", descending=True)
    return df.head(top_n) if top_n is not None else df


def fielding(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Fielding board — outfielders, by total dismissals (catches + run-outs)."""
    df = _tally(collection, db_path).filter(~pl.col("is_keeper"))
    df = df.select(
        "fielder", "cricsheet_id", "display_name", "dismissals", "catches", "runouts"
    ).sort("dismissals", descending=True)
    return df.head(top_n) if top_n is not None else df


__all__ = ["fielding", "keeping"]
