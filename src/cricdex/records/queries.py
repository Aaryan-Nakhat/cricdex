"""Canonical record queries over the Cricsheet ball-by-ball corpus.

Each function returns a polars DataFrame. The CLI / dashboard / API
all consume these via a small generic dispatcher so the queries live
in one place.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _ctx(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


# -- batting records --------------------------------------------------------


def highest_individual_innings(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        batter,
        match_id,
        match_date,
        venue,
        SUM(runs_batter) AS runs,
        COUNT(*) FILTER (WHERE COALESCE(extras_type, '') NOT IN ('wides')) AS balls,
        SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
        SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes
    FROM balls_{safe}
    WHERE batter IS NOT NULL
    GROUP BY batter, match_id, match_date, venue
    ORDER BY runs DESC, balls ASC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def fastest_fifty(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    """Fewest legal balls to reach 50 in a single innings."""
    safe = collection.replace("-", "_")
    sql = f"""
    WITH counted AS (
        SELECT
            batter, match_id, match_date, venue,
            SUM(runs_batter) OVER (
                PARTITION BY batter, match_id, innings_idx
                ORDER BY over, ball_in_over
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_runs,
            SUM(CASE WHEN COALESCE(extras_type, '') NOT IN ('wides') THEN 1 ELSE 0 END) OVER (
                PARTITION BY batter, match_id, innings_idx
                ORDER BY over, ball_in_over
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_balls
        FROM balls_{safe}
        WHERE batter IS NOT NULL
    ),
    fifty AS (
        SELECT batter, match_id, match_date, venue,
               MIN(running_balls) AS balls_to_fifty
        FROM counted
        WHERE running_runs >= 50
        GROUP BY 1, 2, 3, 4
    )
    SELECT *
    FROM fifty
    ORDER BY balls_to_fifty ASC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def fastest_hundred(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    WITH counted AS (
        SELECT
            batter, match_id, match_date, venue,
            SUM(runs_batter) OVER (
                PARTITION BY batter, match_id, innings_idx
                ORDER BY over, ball_in_over
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_runs,
            SUM(CASE WHEN COALESCE(extras_type, '') NOT IN ('wides') THEN 1 ELSE 0 END) OVER (
                PARTITION BY batter, match_id, innings_idx
                ORDER BY over, ball_in_over
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_balls
        FROM balls_{safe}
        WHERE batter IS NOT NULL
    )
    SELECT batter, match_id, match_date, venue,
           MIN(running_balls) AS balls_to_hundred
    FROM counted
    WHERE running_runs >= 100
    GROUP BY 1, 2, 3, 4
    ORDER BY balls_to_hundred ASC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def most_sixes_innings(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        batter, match_id, match_date, venue,
        SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
        SUM(runs_batter) AS runs
    FROM balls_{safe}
    WHERE batter IS NOT NULL
    GROUP BY batter, match_id, match_date, venue
    ORDER BY sixes DESC, runs DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def career_run_leaders(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        batter,
        SUM(runs_batter) AS career_runs,
        COUNT(DISTINCT match_id) AS innings_count,
        SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
        SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours
    FROM balls_{safe}
    WHERE batter IS NOT NULL
    GROUP BY batter
    ORDER BY career_runs DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


# -- bowling records ---------------------------------------------------------


def best_bowling_innings(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        bowler, match_id, match_date, venue,
        SUM(CASE WHEN wicket_kind IS NOT NULL
              AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
             THEN 1 ELSE 0 END) AS wickets,
        SUM(runs_batter + COALESCE(runs_extras, 0)) AS runs_conceded,
        COUNT(*) FILTER (WHERE COALESCE(extras_type, '') NOT IN ('wides','noballs')) AS legal_balls
    FROM balls_{safe}
    WHERE bowler IS NOT NULL
    GROUP BY bowler, match_id, match_date, venue
    HAVING legal_balls >= 12
    ORDER BY wickets DESC, runs_conceded ASC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def career_wicket_leaders(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        bowler,
        SUM(CASE WHEN wicket_kind IS NOT NULL
              AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
             THEN 1 ELSE 0 END) AS wickets,
        COUNT(DISTINCT match_id) AS matches,
        SUM(runs_batter + COALESCE(runs_extras, 0)) AS runs_conceded,
        COUNT(*) FILTER (WHERE COALESCE(extras_type, '') NOT IN ('wides','noballs')) AS legal_balls
    FROM balls_{safe}
    WHERE bowler IS NOT NULL
    GROUP BY bowler
    ORDER BY wickets DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


# -- team / venue records ----------------------------------------------------


def highest_team_totals(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        match_id, match_date, venue,
        batting_team,
        SUM(runs_total) AS total_runs,
        MAX(over) + 1 AS overs_used
    FROM balls_{safe}
    GROUP BY match_id, match_date, venue, batting_team
    ORDER BY total_runs DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


def highest_runs_in_over(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, top_n: int = 25
) -> pl.DataFrame:
    """Highest runs conceded by a bowler in a single over (legal balls only, no wides/no-balls extras)."""
    safe = collection.replace("-", "_")
    sql = f"""
    SELECT
        bowler, batter, match_id, match_date, venue, over,
        SUM(runs_batter + COALESCE(runs_extras, 0)) AS runs_in_over,
        SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes_in_over,
        SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours_in_over
    FROM balls_{safe}
    WHERE bowler IS NOT NULL
    GROUP BY bowler, batter, match_id, match_date, venue, over
    ORDER BY runs_in_over DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


# -- temporal ----------------------------------------------------------------


def on_this_day(
    month: int,
    day: int,
    collection: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int = 50,
) -> pl.DataFrame:
    """Return notable individual innings + bowling performances on the
    same calendar day (month + day, ignoring year) across the
    collection's history."""
    safe = collection.replace("-", "_")
    sql = f"""
    WITH same_day AS (
        SELECT
            batter, bowler, match_id, match_date, venue,
            runs_batter, wicket_kind, extras_type
        FROM balls_{safe}
        WHERE EXTRACT(month FROM match_date) = {month}
          AND EXTRACT(day FROM match_date) = {day}
    ),
    bat AS (
        SELECT match_date, batter AS player,
               'batter' AS role,
               SUM(runs_batter) AS value, match_id, venue
        FROM same_day WHERE batter IS NOT NULL
        GROUP BY 1, 2, 3, 5, 6
    ),
    bowl AS (
        SELECT match_date, bowler AS player,
               'bowler' AS role,
               SUM(CASE WHEN wicket_kind IS NOT NULL
                     AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
                    THEN 1 ELSE 0 END) AS value,
               match_id, venue
        FROM same_day WHERE bowler IS NOT NULL
        GROUP BY 1, 2, 3, 5, 6
    )
    SELECT * FROM bat WHERE value >= 50
    UNION ALL
    SELECT * FROM bowl WHERE value >= 4
    ORDER BY value DESC, match_date DESC
    LIMIT {top_n}
    """
    with _ctx(db_path) as con:
        return con.execute(sql).pl()


# -- registry ----------------------------------------------------------------


RECORDS: dict[str, callable] = {
    "highest_individual_innings": highest_individual_innings,
    "fastest_fifty": fastest_fifty,
    "fastest_hundred": fastest_hundred,
    "most_sixes_innings": most_sixes_innings,
    "career_run_leaders": career_run_leaders,
    "best_bowling_innings": best_bowling_innings,
    "career_wicket_leaders": career_wicket_leaders,
    "highest_team_totals": highest_team_totals,
    "highest_runs_in_over": highest_runs_in_over,
}
