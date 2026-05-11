"""Novel batter metrics computed over Cricsheet ball-by-ball data.

Every metric is intentionally context-aware — standard avg/SR are
deliberately left out of this module because they're available
elsewhere. The point of CricDex metrics is to surface signals the
canonical scorecard hides.

Shipped:
    pressure_runs            — chase pressure (vs venue+phase median req RPB)
    intent_curve             — SR per ball-faced bucket (slow-start vs aggressor)
    recoverability_index     — runs in next 6 balls after a dot
    counter_attack_coefficient — SR in 12 balls after partner wicket
    boundary_dependency      — % of runs from 4s+6s (volatility proxy)
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_PRESSURE_MULTIPLIER = 1.5
DEFAULT_MIN_BALLS_FACED = 20
DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def pressure_runs(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    pressure_multiplier: float = DEFAULT_PRESSURE_MULTIPLIER,
    min_balls_faced: int = DEFAULT_MIN_BALLS_FACED,
    top_n: int | None = 200,
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    WITH match_meta AS (
        SELECT
            match_id, match_type, venue,
            COALESCE(overs, CASE match_type WHEN 'T20' THEN 20 WHEN 'ODI' THEN 50 END) AS innings_overs
        FROM matches_{safe}
        WHERE match_type IN ('T20', 'ODI')
    ),
    first_innings AS (
        SELECT match_id, SUM(runs_total) AS first_innings_total
        FROM balls_{safe}
        WHERE innings_idx = 0
        GROUP BY 1
    ),
    chase AS (
        SELECT
            b.match_id, b.venue, b.phase, b.batter,
            b.runs_batter, b.runs_total,
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
        FROM balls_{safe} b
        JOIN first_innings fi USING (match_id)
        JOIN match_meta mm USING (match_id)
        WHERE b.innings_idx = 1
    ),
    ball_pressure AS (
        SELECT *,
            (target_runs - runs_before) AS runs_needed,
            (innings_balls - balls_before) AS balls_remaining,
            CASE WHEN (innings_balls - balls_before) > 0
                 THEN CAST(target_runs - runs_before AS DOUBLE)
                      / (innings_balls - balls_before)
                 ELSE NULL END AS required_rpb
        FROM chase
        WHERE (target_runs - runs_before) > 0
    ),
    venue_phase_median AS (
        SELECT venue, phase, median(required_rpb) AS median_required_rpb
        FROM ball_pressure
        WHERE required_rpb IS NOT NULL
        GROUP BY 1, 2
    ),
    flagged AS (
        SELECT bp.batter, bp.runs_batter, bp.required_rpb, vp.median_required_rpb,
            CASE WHEN bp.required_rpb IS NOT NULL
                  AND vp.median_required_rpb IS NOT NULL
                  AND bp.required_rpb > {pressure_multiplier} * vp.median_required_rpb
                 THEN 1 ELSE 0 END AS is_pressure_ball
        FROM ball_pressure bp
        LEFT JOIN venue_phase_median vp USING (venue, phase)
    )
    SELECT
        batter,
        COUNT(*) AS chase_balls_faced,
        SUM(runs_batter) AS chase_runs,
        SUM(is_pressure_ball) AS pressure_balls,
        SUM(CASE WHEN is_pressure_ball = 1 THEN runs_batter ELSE 0 END) AS pressure_runs,
        CAST(ROUND(CASE WHEN SUM(is_pressure_ball) > 0
                        THEN 100.0 * SUM(CASE WHEN is_pressure_ball = 1 THEN runs_batter ELSE 0 END)
                             / SUM(is_pressure_ball)
                        ELSE 0 END, 2) AS DOUBLE) AS pressure_sr_per_100_balls,
        CAST(ROUND(CASE WHEN COUNT(*) > 0
                        THEN 100.0 * SUM(is_pressure_ball) / COUNT(*)
                        ELSE 0 END, 2) AS DOUBLE) AS pct_balls_under_pressure
    FROM flagged
    WHERE batter IS NOT NULL
    GROUP BY batter
    HAVING chase_balls_faced >= {min_balls_faced}
    ORDER BY pressure_runs DESC, pressure_sr_per_100_balls DESC
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n}"
    with _connect(db_path) as con:
        return con.execute(sql).pl()


def intent_curve(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls_in_bucket: int = 200,
    top_n: int | None = 200,
) -> pl.DataFrame:
    """Strike rate per (batter, ball-faced bucket).

    Buckets: 0-5, 6-10, 11-20, 21-30, 31-50, 51+ balls into the innings.
    Reveals whether a batter is a slow-starter who heats up, or an
    immediate-aggressor whose intent is high from ball one.
    """
    safe = collection.replace("-", "_")
    sql = f"""
    WITH ordered AS (
        SELECT
            match_id, innings_idx, batter, runs_batter,
            CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball,
            SUM(CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END)
                OVER (PARTITION BY match_id, innings_idx, batter
                      ORDER BY over, ball_in_over) AS balls_faced_to_date
        FROM balls_{safe}
        WHERE batter IS NOT NULL
    ),
    bucketed AS (
        SELECT
            batter,
            CASE
                WHEN balls_faced_to_date <= 5 THEN '01_0-5'
                WHEN balls_faced_to_date <= 10 THEN '02_6-10'
                WHEN balls_faced_to_date <= 20 THEN '03_11-20'
                WHEN balls_faced_to_date <= 30 THEN '04_21-30'
                WHEN balls_faced_to_date <= 50 THEN '05_31-50'
                ELSE '06_51+'
            END AS ball_bucket,
            runs_batter, legal_ball
        FROM ordered
        WHERE legal_ball = 1
    ),
    agg AS (
        SELECT
            batter, ball_bucket,
            SUM(legal_ball) AS balls,
            SUM(runs_batter) AS runs,
            CAST(ROUND(100.0 * SUM(runs_batter) / NULLIF(SUM(legal_ball), 0), 2) AS DOUBLE) AS sr
        FROM bucketed
        GROUP BY 1, 2
    )
    SELECT *
    FROM agg
    WHERE balls >= {min_balls_in_bucket}
    ORDER BY batter, ball_bucket
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n * 6}"
    with _connect(db_path) as con:
        return con.execute(sql).pl()


def recoverability_index(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_dot_balls: int = 100,
    top_n: int | None = 200,
) -> pl.DataFrame:
    """Mental-reset proxy: runs scored in the next 6 balls after a dot.

    Aggregated as runs_per_6_after_dot. High = quick re-engagement after
    pressure; low = batter who lets dots compound.
    """
    safe = collection.replace("-", "_")
    sql = f"""
    WITH numbered AS (
        SELECT
            match_id, innings_idx, batter, runs_batter,
            (runs_batter = 0 AND COALESCE(extras_type, '') NOT IN ('wides','noballs')) AS is_dot,
            ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx, batter
                               ORDER BY over, ball_in_over) AS ball_seq
        FROM balls_{safe}
        WHERE batter IS NOT NULL
    ),
    dots AS (
        SELECT match_id, innings_idx, batter, ball_seq AS dot_seq
        FROM numbered WHERE is_dot
    ),
    next_six AS (
        SELECT d.batter, n.runs_batter
        FROM dots d
        JOIN numbered n
          ON n.match_id = d.match_id
         AND n.innings_idx = d.innings_idx
         AND n.batter = d.batter
         AND n.ball_seq > d.dot_seq
         AND n.ball_seq <= d.dot_seq + 6
    ),
    agg AS (
        SELECT batter,
               COUNT(*) AS following_balls,
               SUM(runs_batter) AS runs_in_following,
               CAST(ROUND(6.0 * SUM(runs_batter) / NULLIF(COUNT(*), 0), 3) AS DOUBLE) AS runs_per_6_after_dot
        FROM next_six
        GROUP BY 1
    ),
    dot_counts AS (
        SELECT batter, COUNT(*) AS dots_faced FROM dots GROUP BY 1
    )
    SELECT a.batter, dc.dots_faced, a.following_balls, a.runs_in_following, a.runs_per_6_after_dot
    FROM agg a JOIN dot_counts dc USING (batter)
    WHERE dc.dots_faced >= {min_dot_balls}
    ORDER BY a.runs_per_6_after_dot DESC
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n}"
    with _connect(db_path) as con:
        return con.execute(sql).pl()


def counter_attack_coefficient(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_partner_wickets: int = 20,
    top_n: int | None = 200,
) -> pl.DataFrame:
    """Strike rate in the 12 balls immediately after a partner wicket.

    The batter who keeps a *non-self* wicket from snowballing into a
    collapse. Excludes the dismissed striker's own dismissals so the
    metric is about the surviving batter.
    """
    safe = collection.replace("-", "_")
    sql = f"""
    WITH numbered AS (
        SELECT
            match_id, innings_idx, batter, non_striker, runs_batter,
            CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball,
            (wicket_kind IS NOT NULL) AS is_wicket,
            player_out,
            ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx
                               ORDER BY over, ball_in_over) AS ball_seq
        FROM balls_{safe}
    ),
    partner_wickets AS (
        SELECT match_id, innings_idx, ball_seq AS wkt_seq,
               batter AS struck_at, player_out
        FROM numbered
        WHERE is_wicket = TRUE
    ),
    next_12 AS (
        SELECT
            pw.match_id, pw.innings_idx, pw.wkt_seq,
            n.batter, n.runs_batter, n.legal_ball
        FROM partner_wickets pw
        JOIN numbered n
          ON n.match_id = pw.match_id
         AND n.innings_idx = pw.innings_idx
         AND n.ball_seq > pw.wkt_seq
         AND n.ball_seq <= pw.wkt_seq + 12
        -- batter at the crease after the wicket; exclude the dismissed one
        WHERE n.batter <> COALESCE(pw.player_out, '')
    ),
    agg AS (
        SELECT batter,
               SUM(legal_ball) AS balls_after_partner_wkt,
               SUM(runs_batter) AS runs_after_partner_wkt,
               CAST(ROUND(100.0 * SUM(runs_batter) / NULLIF(SUM(legal_ball), 0), 2) AS DOUBLE) AS counter_attack_sr
        FROM next_12
        GROUP BY 1
    )
    SELECT *
    FROM agg
    WHERE balls_after_partner_wkt >= {min_partner_wickets}
    ORDER BY counter_attack_sr DESC, balls_after_partner_wkt DESC
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n}"
    with _connect(db_path) as con:
        return con.execute(sql).pl()


def boundary_dependency(
    collection: str = "recently_played_30_male",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_runs: int = 200,
    top_n: int | None = 200,
) -> pl.DataFrame:
    """Boundary Dependency Ratio (BDR) — % of a batter's runs from 4s/6s.

    High BDR = boundary-or-bust, more volatile, struggles when the boundary
    isn't there. Low BDR = strike-rotator who keeps the strike turning. Both
    profiles win matches; the metric exists to distinguish them.
    """
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        batter,
        SUM(runs_batter) AS total_runs,
        SUM(CASE WHEN runs_batter IN (4, 6) THEN runs_batter ELSE 0 END) AS boundary_runs,
        SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
        SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
        CAST(ROUND(100.0 *
            SUM(CASE WHEN runs_batter IN (4, 6) THEN runs_batter ELSE 0 END)
            / NULLIF(SUM(runs_batter), 0), 2) AS DOUBLE) AS bdr_pct
    FROM balls_{safe}
    WHERE batter IS NOT NULL
    GROUP BY batter
    HAVING total_runs >= {min_runs}
    ORDER BY bdr_pct DESC
    """
    if top_n is not None:
        sql += f"\nLIMIT {top_n}"
    with _connect(db_path) as con:
        return con.execute(sql).pl()
