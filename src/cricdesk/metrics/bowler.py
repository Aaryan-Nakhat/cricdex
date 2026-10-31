"""Novel bowler metrics over Cricsheet ball-by-ball data.

Shipped:
    pressure_conversion — wicket rate on balls bowled after the batting side's 4+ ball drought,
                          shrunk toward the league's (squeeze conversion)
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from cricdesk.common.sql import BOWLER_WICKET, MAIN_INNINGS, keyed_query, table_suffix
from cricdesk.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


# A pressure ball needs this many balls in a row before it without a run or a wicket (the batting side's
# drought, across overs and bowlers), and a bowler this many pressure balls to be listed
PRESSURE_DOTS = 4
MIN_PRESSURE_BALLS = 50


def _beta_strength(w: np.ndarray, n: np.ndarray, p0: float) -> float:
    """The beta-binomial prior strength k (pseudo-balls) for rates w / n around the league rate p0, by
    the method of moments: the spread of the observed rates beyond what binomial noise alone gives is
    the spread of true rates, tau² = var(w/n) − mean(p0(1 − p0)/n); k = p0(1 − p0)/tau² − 1. No spread
    beyond the noise (tau² ≤ 0) means nothing tells the bowlers apart: k is infinite."""
    if len(n) < 3 or not 0 < p0 < 1:
        return math.inf
    r = w / n
    tau2 = float(np.var(r, ddof=1) - np.mean(p0 * (1 - p0) / n))
    return math.inf if tau2 <= 0 else max(p0 * (1 - p0) / tau2 - 1, 0.0)


def pressure_conversion(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    consecutive_dot_threshold: int = PRESSURE_DOTS,
    min_pressure_balls: int | None = None,
    top_n: int | None = 200,
    auto_threshold: bool = True,
) -> pl.DataFrame:
    """How often a bowler takes a wicket on a pressure ball, shrunk toward the league's rate.

    A pressure ball is any legal or illegal delivery that comes after `consecutive_dot_threshold` or
    more balls in a row with no run and no wicket for the batting side, whoever bowled them and across
    overs (the squeeze is the batters', not one bowler's over). The outcome is a wicket credited to the
    bowler of that ball (run-outs don't count). Rates are tiny and samples small, so each bowler's rate
    is shrunk toward the league's pressure-ball rate by a beta-binomial prior fitted on the bowlers
    themselves (`_beta_strength`): `conversion_pct` = (wickets + k × league rate) ÷ (pressure balls + k).
    `wicket_rate_pct` is the raw rate. A bowler needs `min_pressure_balls` (default 50; on a small
    collection with `auto_threshold`, half its 75th-percentile count when that is lower, at least 10).

    Until 2026-10-29 a pressure ball was the 5th or 6th ball of one bowler's over after 4 dots in it, so
    a season gave a bowler a handful and the board sorted raw rates of 0 out of 9.
    """
    table_suffix(collection)  # rejects an unsafe collection name
    agg_sql = f"""
    WITH seq AS (
        SELECT
            match_id, innings_idx, bowler,
            (runs_total = 0 AND wicket_kind IS NULL) AS quiet,
            {BOWLER_WICKET} AS is_wicket,  -- a run out isn't the bowler's squeeze paying off
            ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx ORDER BY over, ball_in_over, ball_id)
                AS i
        FROM __BALLS__
        WHERE {MAIN_INNINGS}
    ),
    drought AS (
        SELECT *,
            -- balls since the side last scored or lost a wicket, before this one
            i - 1 - COALESCE(MAX(CASE WHEN NOT quiet THEN i END) OVER (
                PARTITION BY match_id, innings_idx ORDER BY i
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS quiet_before
        FROM seq
    )
    SELECT
        bowler,
        COUNT(*) AS pressure_balls,
        SUM(CASE WHEN is_wicket THEN 1 ELSE 0 END) AS wickets_after_pressure
    FROM drought
    WHERE quiet_before >= {int(consecutive_dot_threshold)} AND bowler IS NOT NULL
    GROUP BY 1
    """
    with _connect(db_path) as con:
        agg = keyed_query(con, collection, agg_sql, ("bowler",))

    if agg.is_empty():
        return agg
    agg = agg.with_columns(
        pl.col("pressure_balls").cast(pl.Int64), pl.col("wickets_after_pressure").cast(pl.Int64)
    )

    if min_pressure_balls is None:
        min_pressure_balls = MIN_PRESSURE_BALLS
        if auto_threshold:
            p75 = float(agg["pressure_balls"].quantile(0.75) or 0)
            min_pressure_balls = min(MIN_PRESSURE_BALLS, max(10, int(round(0.5 * p75))))

    n_all = agg["pressure_balls"].to_numpy().astype(float)
    w_all = agg["wickets_after_pressure"].to_numpy().astype(float)
    p0 = float(w_all.sum() / n_all.sum()) if n_all.sum() else 0.0
    big = n_all >= min_pressure_balls
    k = _beta_strength(w_all[big], n_all[big], p0)
    kk = 1e12 if math.isinf(k) else k
    out = (
        agg.filter(pl.col("pressure_balls") >= min_pressure_balls)
        .with_columns(
            (100.0 * (pl.col("wickets_after_pressure") + kk * p0) / (pl.col("pressure_balls") + kk))
            .round(2)
            .alias("conversion_pct"),
            (100.0 * pl.col("wickets_after_pressure") / pl.col("pressure_balls"))
            .round(2)
            .alias("wicket_rate_pct"),
            pl.lit(round(100.0 * p0, 2)).alias("league_pct"),
            pl.lit(None if math.isinf(k) else round(k, 1), dtype=pl.Float64).alias("prior_balls"),
        )
        .sort(["conversion_pct", "pressure_balls", "cricsheet_id"], descending=[True, True, False])
    )
    if top_n is not None:
        out = out.head(top_n)
    return out
