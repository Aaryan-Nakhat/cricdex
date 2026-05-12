"""Wicket Quality — opponent-strength-adjusted bowler metric.

Standard cricket scorecards treat every wicket as one wicket. That's
wrong: a Bumrah-dismisses-Kohli wicket is meaningfully harder than a
Bumrah-dismisses-No.11 wicket. Wicket Quality is the average of the
batters' Bayesian scout-rating skills weighted by who actually got
dismissed.

Definition
----------
For every legitimate dismissal credited to the bowler (excluding run
outs, retired hurts, etc.):

    wq_b  =  mean(batter_bayes_skill_at_dismissal)

So a bowler whose wickets list is full of high-Bayes batters scores
high. A bowler picking up tail-enders scores low.

Output columns
--------------
bowler            cricsheet display name
wickets           dismissals counted
wicket_quality    mean opponent Bayes skill (higher = harder wickets)
opponents_seen    distinct batters dismissed (sample-size signal)
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _load_batter_skills(collection: str) -> dict[str, float]:
    """Map cricsheet_id -> Bayes batter skill from the scout-ratings JSON."""
    path = DATA_DIR / "metrics" / f"scout_ratings_{collection}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        rows = json.load(f)
    return {r["cricsheet_id"]: float(r["skill"]) for r in rows if r.get("role") == "batter"}


def wicket_quality(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_wickets: int = 15,
    top_n: int | None = 200,
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    skills = _load_batter_skills(collection)
    if not skills:
        return pl.DataFrame()
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"balls_{safe}" not in tables or "people" not in tables:
            return pl.DataFrame()
        rows = con.execute(
            f"""
            SELECT
                b.bowler,
                COALESCE(b.player_out, b.batter) AS dismissed_name,
                p.identifier AS dismissed_cricsheet_id
            FROM balls_{safe} b
            LEFT JOIN people p
                ON p.unique_name = COALESCE(b.player_out, b.batter)
            WHERE b.wicket_kind IS NOT NULL
              AND b.wicket_kind NOT IN (
                  'run out', 'retired hurt', 'retired out',
                  'obstructing the field'
              )
              AND b.bowler IS NOT NULL
            """
        ).pl()
    if rows.is_empty():
        return pl.DataFrame()

    df = rows.with_columns(
        pl.col("dismissed_cricsheet_id")
        .map_elements(lambda x: skills.get(x), return_dtype=pl.Float64)
        .alias("dismissed_skill")
    ).drop_nulls("dismissed_skill")

    agg = (
        df.group_by("bowler")
        .agg(
            pl.len().alias("wickets"),
            pl.col("dismissed_skill").mean().alias("wicket_quality"),
            pl.col("dismissed_cricsheet_id").n_unique().alias("opponents_seen"),
        )
        .filter(pl.col("wickets") >= min_wickets)
        .sort("wicket_quality", descending=True)
    )
    if top_n is not None:
        agg = agg.head(top_n)
    return agg
