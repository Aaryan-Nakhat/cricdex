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
Keyed by `fielder` (short name), tagged with matches/taxonomy/activity at
export time like every other leaderboard.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
TAXONOMY_PATH = DATA_DIR / "curated" / "player_taxonomy.json"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def _keeper_names() -> set[str]:
    """Short-names the Gemini taxonomy classifies as wicket-keepers."""
    if not TAXONOMY_PATH.exists():
        return set()
    raw = json.loads(TAXONOMY_PATH.read_text())
    return {
        rec["name"]
        for rec in raw.values()
        if isinstance(rec, dict) and rec.get("name") and rec.get("primary_role") == "wk_batter"
    }


def _tally(collection: str, db_path: Path | str) -> pl.DataFrame:
    """Per-fielder {catches, stumpings, runouts, dismissals} + is_keeper."""
    safe = collection.replace("-", "_")
    sql = f"""
    WITH dis AS (
        SELECT unnest(fielders) AS fielder, wicket_kind
        FROM balls_{safe}
        WHERE wicket_kind IN ('caught', 'stumped', 'run out') AND len(fielders) > 0
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
        df = con.execute(sql).pl()
    keepers = _keeper_names()
    return df.with_columns(
        pl.col("catches").cast(pl.Int64),
        pl.col("stumpings").cast(pl.Int64),
        pl.col("runouts").cast(pl.Int64),
        ((pl.col("fielder").is_in(keepers)) | (pl.col("stumpings") > 0)).alias("is_keeper"),
    )


def keeping(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Wicketkeeping board — keepers, by total dismissals behind the stumps
    (catches + stumpings + run-out involvements)."""
    df = _tally(collection, db_path).filter(pl.col("is_keeper"))
    df = df.select("fielder", "dismissals", "catches", "stumpings", "runouts").sort(
        "dismissals", descending=True
    )
    return df.head(top_n) if top_n is not None else df


def fielding(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Fielding board — outfielders, by total dismissals (catches + run-outs)."""
    df = _tally(collection, db_path).filter(~pl.col("is_keeper"))
    df = df.select("fielder", "dismissals", "catches", "runouts").sort(
        "dismissals", descending=True
    )
    return df.head(top_n) if top_n is not None else df


__all__ = ["fielding", "keeping"]
