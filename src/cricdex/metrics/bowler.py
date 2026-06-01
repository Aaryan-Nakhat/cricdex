"""Novel bowler metrics over Cricsheet ball-by-ball data.

Shipped:
    pressure_conversion — wicket rate after a 4+ dot streak (squeeze conversion)
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def pressure_conversion(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    consecutive_dot_threshold: int = 4,
    min_pressure_balls: int | None = None,
    top_n: int | None = 200,
    auto_threshold: bool = True,
) -> pl.DataFrame:
    """Wicket rate on the next ball after `consecutive_dot_threshold` or more
    consecutive dot balls bowled by the same bowler in the same over.

    Captures the bowler's ability to convert sustained dot-ball pressure
    into a dismissal. Different from raw economy: a tight 4-dot bowler
    who never breaks the partnership scores lower here than one who finishes
    the pressure with a wicket.

    `min_pressure_balls` rules:
    - If explicitly passed, that value wins.
    - If `None` and `auto_threshold` is True (default), pick
      `max(5, round(0.5 * 75th-percentile pressure_balls))` for this
      collection so small corpora (e.g., 689-match SMAT) don't get
      filtered to 0 rows by a hard-coded 30-ball floor.
    - Else default to 30 (the v1 IPL-tuned floor).
    """
    safe = collection.replace("-", "_")
    # Aggregated table (before applying min_pressure_balls).
    agg_sql = f"""
    WITH numbered AS (
        SELECT
            match_id, innings_idx, bowler, over,
            (runs_total = 0 AND COALESCE(extras_type, '') NOT IN ('wides', 'noballs')) AS is_dot,
            (wicket_kind IS NOT NULL) AS is_wicket,
            ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx, bowler, over
                               ORDER BY ball_in_over) AS ball_in_over_seq
        FROM balls_{safe}
        WHERE bowler IS NOT NULL
    ),
    dot_streaks AS (
        SELECT
            *,
            CASE WHEN is_dot
                 THEN ball_in_over_seq -
                      MAX(CASE WHEN NOT is_dot THEN ball_in_over_seq ELSE 0 END)
                        OVER (PARTITION BY match_id, innings_idx, bowler, over
                              ORDER BY ball_in_over_seq
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                 ELSE 0 END AS streak_len
        FROM numbered
    ),
    after_streak AS (
        SELECT
            ds.bowler,
            LEAD(ds.is_wicket) OVER (PARTITION BY ds.match_id, ds.innings_idx, ds.bowler, ds.over
                                      ORDER BY ds.ball_in_over_seq) AS next_is_wicket,
            ds.streak_len
        FROM dot_streaks ds
    )
    SELECT
        bowler,
        COUNT(*) AS pressure_balls,
        SUM(CASE WHEN next_is_wicket THEN 1 ELSE 0 END) AS wickets_after_pressure,
        CAST(ROUND(100.0 * SUM(CASE WHEN next_is_wicket THEN 1 ELSE 0 END)
                   / NULLIF(COUNT(*), 0), 2) AS DOUBLE) AS wicket_rate_pct
    FROM after_streak
    WHERE streak_len >= {consecutive_dot_threshold} AND next_is_wicket IS NOT NULL
    GROUP BY 1
    """
    with _connect(db_path) as con:
        agg = con.execute(agg_sql).pl()

    if agg.is_empty():
        return agg

    if min_pressure_balls is None:
        if auto_threshold:
            p75 = float(agg["pressure_balls"].quantile(0.75) or 0)
            min_pressure_balls = max(5, int(round(0.5 * p75)))
        else:
            min_pressure_balls = 30

    out = agg.filter(pl.col("pressure_balls") >= min_pressure_balls).sort(
        ["wicket_rate_pct", "pressure_balls"], descending=[True, True]
    )
    if top_n is not None:
        out = out.head(top_n)
    return out
