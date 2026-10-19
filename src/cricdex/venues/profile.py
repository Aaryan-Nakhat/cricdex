"""Per-venue pitch + conditions archive.

Aggregates Cricsheet ball-by-ball into a venue-level profile:

- match-count breakdown by match_type
- average first / second innings runs (limited-overs only)
- win share batting first vs chasing
- run rate per phase (powerplay / middle / death)
- boundary rate, dot rate
- dismissal-type mix
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.common.sql import DISMISSAL, MAIN_INNINGS, table_suffix
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def list_venues(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_matches: int = 5,
) -> pl.DataFrame:
    safe = table_suffix(collection)
    sql = f"""
    SELECT venue, COUNT(*) AS matches
    FROM matches_{safe}
    WHERE venue IS NOT NULL
    GROUP BY venue
    HAVING matches >= {min_matches}
    ORDER BY matches DESC
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql).pl()


def recent_seasons(
    collection: str = "ipl", db_path: Path | str = DEFAULT_DB_PATH, n: int = 3
) -> list[str]:
    """The league's last `n` seasons (Cricsheet `season`, e.g. "2024" or "2024/25"), newest last."""
    safe = table_suffix(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        rows = con.execute(
            f"SELECT season FROM matches_{safe} WHERE season IS NOT NULL "
            f"GROUP BY season ORDER BY MAX(match_date) DESC LIMIT {int(n)}"
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def innings_by_season(
    venue: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    """Average first- and second-innings totals at a ground, season by season (limited-overs main
    innings) — the par moves with the era, so an all-time average undersells a modern ground."""
    safe = table_suffix(collection)
    sql = f"""
    SELECT season, innings_idx, match_type,
           COUNT(*) AS innings_count, AVG(total_runs) AS avg_runs
    FROM (
        SELECT b.match_id, b.innings_idx, m.match_type, m.season, SUM(b.runs_total) AS total_runs
        FROM balls_{safe} b JOIN matches_{safe} m USING (match_id)
        WHERE b.venue = ? AND b.innings_idx <= 1 AND m.match_type NOT IN ('Test', 'MDM')
          AND m.season IS NOT NULL
        GROUP BY b.match_id, b.innings_idx, m.match_type, m.season
    )
    GROUP BY season, innings_idx, match_type
    ORDER BY season, innings_idx
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, [venue]).pl()


def innings_totals(
    venue: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    seasons: list[str] | None = None,
) -> pl.DataFrame:
    """Innings totals at a ground (all-time, or only the given seasons)."""
    safe = table_suffix(collection)
    in_seasons = ""
    params: list = [venue]
    if seasons:
        in_seasons = f"AND m.season IN ({', '.join('?' for _ in seasons)})"
        params += list(seasons)
    sql = f"""
    SELECT
        innings_idx,
        match_type,
        COUNT(DISTINCT match_id) AS innings_count,
        AVG(total_runs) AS avg_runs,
        MEDIAN(total_runs) AS median_runs,
        AVG(wickets) AS avg_wickets,
        AVG(overs_used) AS avg_overs
    FROM (
        SELECT
            b.match_id, b.innings_idx, m.match_type,
            SUM(b.runs_total) AS total_runs,
            COUNT(*) FILTER (WHERE {DISMISSAL}) AS wickets,
            MAX(b.over) + 1 AS overs_used
        FROM balls_{safe} b
        JOIN matches_{safe} m USING (match_id)
        WHERE b.venue = ? AND (b.innings_idx <= 1 OR m.match_type IN ('Test', 'MDM')) {in_seasons}
        GROUP BY b.match_id, b.innings_idx, m.match_type
    )
    GROUP BY innings_idx, match_type
    ORDER BY match_type, innings_idx
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, params).pl()


def chase_vs_set_winrate(
    venue: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    safe = table_suffix(collection)
    sql = f"""
    SELECT
        match_type,
        COUNT(*) AS matches,
        SUM(CASE WHEN outcome_winner = team_home AND team_home = (
            SELECT batting_team FROM balls_{safe} b2
            WHERE b2.match_id = matches.match_id AND b2.innings_idx = 0
            LIMIT 1
        ) THEN 1
        WHEN outcome_winner = team_away AND team_away = (
            SELECT batting_team FROM balls_{safe} b2
            WHERE b2.match_id = matches.match_id AND b2.innings_idx = 0
            LIMIT 1
        ) THEN 1
        ELSE 0 END) AS first_innings_team_wins,
        SUM(CASE WHEN outcome_winner IS NOT NULL THEN 1 ELSE 0 END) AS decided_matches
    FROM matches_{safe} matches
    WHERE venue = ?
    GROUP BY match_type
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, [venue]).pl()


def phase_run_rates(
    venue: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    """Phase-by-phase run rate / dot% / boundary% at a venue.

    `match_type` is qualified to `b.match_type` because `JOIN … USING
    (match_id)` keeps the duplicated column on both sides and duckdb
    refuses to disambiguate it on its own.
    """
    safe = table_suffix(collection)
    sql = f"""
    SELECT
        b.phase,
        b.match_type,
        COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs')) AS legal_balls,
        SUM(b.runs_total) AS total_runs,
        CAST(ROUND(SUM(b.runs_total) * 6.0 /
                NULLIF(COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs')), 0),
            2) AS DOUBLE) AS rpo,
        CAST(ROUND(100.0 * SUM(CASE WHEN b.runs_total = 0
                                     AND COALESCE(b.extras_type,'') NOT IN ('wides','noballs')
                                THEN 1 ELSE 0 END) /
                NULLIF(COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs')), 0),
            2) AS DOUBLE) AS dot_pct,
        CAST(ROUND(100.0 * SUM(CASE WHEN b.runs_batter IN (4, 6) THEN 1 ELSE 0 END) /
                NULLIF(COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs')), 0),
            2) AS DOUBLE) AS boundary_pct
    FROM balls_{safe} b
    JOIN matches_{safe} m USING (match_id)
    WHERE b.venue = ? AND (b.innings_idx <= 1 OR b.match_type IN ('Test', 'MDM'))
    GROUP BY b.phase, b.match_type
    ORDER BY b.match_type, b.phase
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, [venue]).pl()


def dismissal_mix(
    venue: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    safe = table_suffix(collection)
    sql = f"""
    SELECT
        wicket_kind,
        COUNT(*) AS dismissals,
        CAST(ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS DOUBLE) AS pct_share
    FROM balls_{safe}
    WHERE venue = ? AND {DISMISSAL} AND {MAIN_INNINGS}
    GROUP BY wicket_kind
    ORDER BY dismissals DESC
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, [venue]).pl()
