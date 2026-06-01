"""Cross-metric player comparison.

Pulls every relevant per-player number (novel metrics + Bayesian
ratings + raw career totals) and returns one row per player so the
dashboard / CLI / future API can render a side-by-side view.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

METRIC_DIR = DATA_DIR / "metrics"
DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


BATTER_NUMERIC = {
    "pressure_runs": ("pressure_runs", "pressure_runs"),
    "pressure_runs_sr": ("pressure_runs", "pressure_sr_per_100_balls"),
    "pct_pressure_balls": ("pressure_runs", "pct_balls_under_pressure"),
    "dot_ball_recovery": ("dot_ball_recovery", "runs_per_6_after_dot"),
    "counter_attack_sr": ("counter_attack", "counter_attack_sr"),
    "bdr_pct": ("boundary_dependency", "bdr_pct"),
}

BOWLER_NUMERIC = {
    "pressure_conversion_pct": ("pressure_conversion", "wicket_rate_pct"),
}


def _load_json(name: str) -> pl.DataFrame:
    path = METRIC_DIR / name
    if not path.exists():
        return pl.DataFrame()
    with open(path) as f:
        rows = json.load(f)
    # infer_schema_length=None: scout_ratings has batter-only
    # (survival_skill) and bowler-only (strike_skill) columns, so a
    # truncated scan over the leading batter rows trips on the first
    # bowler row.
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


def _safe_get(df: pl.DataFrame, key_col: str, key: str, value_col: str) -> float | None:
    if df.is_empty() or key_col not in df.columns or value_col not in df.columns:
        return None
    hit = df.filter(pl.col(key_col) == key)
    if hit.is_empty():
        return None
    v = hit[value_col][0]
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _career_totals(con: duckdb.DuckDBPyConnection, collection: str, player: str) -> dict:
    safe = collection.replace("-", "_")
    bat = con.execute(
        f"""
        SELECT
            SUM(runs_batter) AS runs,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS balls,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            COUNT(DISTINCT match_id) AS matches
        FROM balls_{safe}
        WHERE batter = ?
        """,
        [player],
    ).fetchone()
    bowl = con.execute(
        f"""
        SELECT
            SUM(CASE WHEN wicket_kind IS NOT NULL
                  AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
                 THEN 1 ELSE 0 END) AS wickets,
            SUM(runs_batter + COALESCE(runs_extras,0)) AS runs_conceded,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides','noballs')) AS legal_balls
        FROM balls_{safe}
        WHERE bowler = ?
        """,
        [player],
    ).fetchone()
    return {
        "career_runs": int(bat[0] or 0),
        "career_balls": int(bat[1] or 0),
        "career_sixes": int(bat[2] or 0),
        "career_fours": int(bat[3] or 0),
        "career_matches": int(bat[4] or 0),
        "career_wickets": int(bowl[0] or 0),
        "career_runs_conceded": int(bowl[1] or 0),
        "career_legal_balls_bowled": int(bowl[2] or 0),
    }


def _bayes_skill(
    con: duckdb.DuckDBPyConnection,
    ratings_df: pl.DataFrame,
    player: str,
    role: str,
    col: str = "skill",
) -> float | None:
    """Look up a ratings column (`skill` / `survival_skill` /
    `strike_skill`) for a player+role. None if absent."""
    if ratings_df.is_empty() or col not in ratings_df.columns:
        return None
    # Bridge name -> cricsheet_id via the people register, then look up.
    if "unique_name" not in ratings_df.columns:
        bridge = con.execute(
            "SELECT identifier, unique_name FROM people WHERE unique_name = ?",
            [player],
        ).fetchone()
        if not bridge:
            return None
        cricsheet_id = bridge[0]
    else:
        match = ratings_df.filter(pl.col("unique_name") == player)
        if match.is_empty():
            return None
        cricsheet_id = match["cricsheet_id"][0]
    row = ratings_df.filter((pl.col("cricsheet_id") == cricsheet_id) & (pl.col("role") == role))
    if row.is_empty() or row[col][0] is None:
        return None
    return float(row[col][0])


def compare(
    players: list[str],
    collection: str = "ipl",
    db_path: Path | str = DUCKDB_PATH,
) -> pl.DataFrame:
    if not players:
        return pl.DataFrame()

    pr = _load_json(f"pressure_runs_{collection}.json")
    rec = _load_json(f"dot_ball_recovery_{collection}.json")
    ca = _load_json(f"counter_attack_{collection}.json")
    bdr = _load_json(f"boundary_dependency_{collection}.json")
    sticky = _load_json(f"pressure_conversion_{collection}.json")
    ratings = _load_json(f"scout_ratings_{collection}.json")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        out_rows: list[dict] = []
        for p in players:
            row: dict = {"player": p}
            row.update(_career_totals(con, collection, p))

            row["pressure_runs"] = _safe_get(pr, "batter", p, "pressure_runs")
            row["pressure_runs_sr"] = _safe_get(pr, "batter", p, "pressure_sr_per_100_balls")
            row["pct_pressure_balls"] = _safe_get(pr, "batter", p, "pct_balls_under_pressure")
            row["dot_ball_recovery"] = _safe_get(rec, "batter", p, "runs_per_6_after_dot")
            row["counter_attack_sr"] = _safe_get(ca, "batter", p, "counter_attack_sr")
            row["bdr_pct"] = _safe_get(bdr, "batter", p, "bdr_pct")
            row["pressure_conversion_pct"] = _safe_get(sticky, "bowler", p, "wicket_rate_pct")
            row["bayes_skill_batter"] = _bayes_skill(con, ratings, p, "batter")
            row["bayes_survival_batter"] = _bayes_skill(
                con, ratings, p, "batter", col="survival_skill"
            )
            row["bayes_skill_bowler"] = _bayes_skill(con, ratings, p, "bowler")
            row["bayes_strike_bowler"] = _bayes_skill(con, ratings, p, "bowler", col="strike_skill")
            out_rows.append(row)
    finally:
        con.close()

    return pl.DataFrame(out_rows)
