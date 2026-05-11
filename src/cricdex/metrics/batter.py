"""Novel batter metrics computed over Cricsheet ball-by-ball data.

First metric: Pressure Runs (PR). Runs scored by a batter on balls where
the required run rate (per ball) is meaningfully above the venue+phase
median — i.e. on the high-leverage chase deliveries the venue's history
says are hard. Quantifies clutch hitting under chase pressure.

The metric is intentionally chase-only (innings_idx=1, T20/ODI) because
required RPB has no clean definition outside a chase. Pressure for the
batting-first team is captured separately by a different metric (Phase
Dilation / Setting Tax).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_PRESSURE_MULTIPLIER = 1.5
DEFAULT_MIN_BALLS_FACED = 20
DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def pressure_runs(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    pressure_multiplier: float = DEFAULT_PRESSURE_MULTIPLIER,
    min_balls_faced: int = DEFAULT_MIN_BALLS_FACED,
    top_n: int | None = 200,
) -> pl.DataFrame:
    """Return a batter leaderboard ranked by Pressure Runs.

    Args:
        collection: Cricsheet collection name as ingested (suffix on the
            DuckDB table names: balls_<collection>, matches_<collection>).
        db_path: Path to the DuckDB file written by `ingest_cricsheet.py`.
        pressure_multiplier: Required RPB must exceed
            `pressure_multiplier * venue_phase_median_rpb` to count as a
            pressure ball. 1.5 is a sensible default.
        min_balls_faced: Minimum total chase balls faced to qualify
            (sample-size guard).
        top_n: Slice the leaderboard to top N batters (None = all).

    Returns:
        polars DataFrame with one row per qualifying batter, sorted by
        pressure_runs desc.
    """
    safe_collection = collection.replace("-", "_")
    sql = f"""
    WITH match_meta AS (
        SELECT
            match_id,
            match_type,
            venue,
            COALESCE(overs, CASE match_type WHEN 'T20' THEN 20 WHEN 'ODI' THEN 50 END) AS innings_overs
        FROM matches_{safe_collection}
        WHERE match_type IN ('T20', 'ODI')
    ),
    first_innings AS (
        SELECT match_id, SUM(runs_total) AS first_innings_total
        FROM balls_{safe_collection}
        WHERE innings_idx = 0
        GROUP BY 1
    ),
    chase AS (
        SELECT
            b.match_id,
            b.venue,
            b.phase,
            b.batter,
            b.runs_batter,
            b.runs_total,
            (fi.first_innings_total + 1) AS target_runs,
            mm.innings_overs * 6 AS innings_balls,
            (ROW_NUMBER() OVER (PARTITION BY b.match_id ORDER BY b.over, b.ball_in_over)) - 1 AS balls_before,
            COALESCE(
                SUM(b.runs_total) OVER (
                    PARTITION BY b.match_id
                    ORDER BY b.over, b.ball_in_over
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ),
                0
            ) AS runs_before
        FROM balls_{safe_collection} b
        JOIN first_innings fi USING (match_id)
        JOIN match_meta mm USING (match_id)
        WHERE b.innings_idx = 1
    ),
    ball_pressure AS (
        SELECT
            *,
            (target_runs - runs_before) AS runs_needed,
            (innings_balls - balls_before) AS balls_remaining,
            CASE
                WHEN (innings_balls - balls_before) > 0
                THEN CAST(target_runs - runs_before AS DOUBLE)
                     / (innings_balls - balls_before)
                ELSE NULL
            END AS required_rpb
        FROM chase
        WHERE (target_runs - runs_before) > 0
    ),
    venue_phase_median AS (
        SELECT
            venue,
            phase,
            median(required_rpb) AS median_required_rpb
        FROM ball_pressure
        WHERE required_rpb IS NOT NULL
        GROUP BY 1, 2
    ),
    flagged AS (
        SELECT
            bp.batter,
            bp.runs_batter,
            bp.required_rpb,
            vp.median_required_rpb,
            CASE
                WHEN bp.required_rpb IS NOT NULL
                 AND vp.median_required_rpb IS NOT NULL
                 AND bp.required_rpb > {pressure_multiplier} * vp.median_required_rpb
                THEN 1 ELSE 0
            END AS is_pressure_ball
        FROM ball_pressure bp
        LEFT JOIN venue_phase_median vp USING (venue, phase)
    )
    SELECT
        batter,
        COUNT(*) AS chase_balls_faced,
        SUM(runs_batter) AS chase_runs,
        SUM(is_pressure_ball) AS pressure_balls,
        SUM(CASE WHEN is_pressure_ball = 1 THEN runs_batter ELSE 0 END) AS pressure_runs,
        CAST(
            ROUND(
                CASE
                    WHEN SUM(is_pressure_ball) > 0
                    THEN 100.0 * SUM(CASE WHEN is_pressure_ball = 1 THEN runs_batter ELSE 0 END)
                         / SUM(is_pressure_ball)
                    ELSE 0
                END,
                2
            ) AS DOUBLE
        ) AS pressure_sr_per_100_balls,
        CAST(
            ROUND(
                CASE
                    WHEN COUNT(*) > 0
                    THEN 100.0 * SUM(is_pressure_ball) / COUNT(*)
                    ELSE 0
                END,
                2
            ) AS DOUBLE
        ) AS pct_balls_under_pressure
    FROM flagged
    WHERE batter IS NOT NULL
    GROUP BY batter
    HAVING chase_balls_faced >= {min_balls_faced}
    ORDER BY pressure_runs DESC, pressure_sr_per_100_balls DESC
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n}"

    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql).pl()
