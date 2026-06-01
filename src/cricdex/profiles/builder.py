"""Player-profile assembler.

Builds a single dict for one player from every source CricDex has:
- Cricsheet People Register cross-IDs
- Wikidata enrichment (DOB / country / gender) if loaded
- Career totals from the ball table
- Every novel metric we've computed
- Bayesian scout rating skills
- Top-5 style twins
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR
from cricdex.scout.search import style_twin as twin

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
METRIC_DIR = DATA_DIR / "metrics"


def _people_row(con: duckdb.DuckDBPyConnection, name: str) -> dict | None:
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "people" not in tables:
        return None
    row = con.execute(
        """
        SELECT identifier AS cricsheet_id, unique_name,
               key_cricinfo, key_cricbuzz, key_cricheroes, key_bigbash
        FROM people
        WHERE unique_name = ?
        """,
        [name],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row, strict=True))


def _wikidata_row(con: duckdb.DuckDBPyConnection, key_cricinfo) -> dict | None:
    if key_cricinfo is None:
        return None
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "wikidata_players" not in tables:
        return None
    row = con.execute(
        """
        SELECT dob, country, gender, wikidata_id
        FROM wikidata_players
        WHERE cricinfo_id = ?
        """,
        [int(key_cricinfo)],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row, strict=True))


def _career_totals(con: duckdb.DuckDBPyConnection, collection: str, name: str) -> dict:
    safe = collection.replace("-", "_")
    bat = con.execute(
        f"""
        SELECT
            SUM(runs_batter) AS runs,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS balls,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            COUNT(DISTINCT match_id) AS innings
        FROM balls_{safe}
        WHERE batter = ?
        """,
        [name],
    ).fetchone()
    bowl = con.execute(
        f"""
        SELECT
            SUM(CASE WHEN wicket_kind IS NOT NULL
                  AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
                 THEN 1 ELSE 0 END) AS wickets,
            SUM(runs_batter + COALESCE(runs_extras,0)) AS runs_conceded,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides','noballs')) AS legal_balls,
            COUNT(DISTINCT match_id) AS matches_bowled
        FROM balls_{safe}
        WHERE bowler = ?
        """,
        [name],
    ).fetchone()
    return {
        "career_runs": int(bat[0] or 0),
        "career_balls_faced": int(bat[1] or 0),
        "career_sixes": int(bat[2] or 0),
        "career_fours": int(bat[3] or 0),
        "career_innings": int(bat[4] or 0),
        "career_wickets": int(bowl[0] or 0),
        "career_runs_conceded": int(bowl[1] or 0),
        "career_legal_balls_bowled": int(bowl[2] or 0),
        "career_matches_bowled": int(bowl[3] or 0),
    }


def _load_metric_row(slug: str, collection: str, name: str, key_col: str = "batter") -> dict | None:
    path = METRIC_DIR / f"{slug}_{collection}.json"
    if not path.exists():
        return None
    with open(path) as f:
        rows = json.load(f)
    for r in rows:
        if r.get(key_col) == name:
            return r
    return None


def _bayes_skills(con: duckdb.DuckDBPyConnection, collection: str, cricsheet_id: str) -> dict:
    path = METRIC_DIR / f"scout_ratings_{collection}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        rows = json.load(f)
    out: dict = {}
    for r in rows:
        if r.get("cricsheet_id") == cricsheet_id:
            entry = {
                "skill": r.get("skill"),
                "skill_sd": r.get("skill_sd"),
                "balls": r.get("balls"),
            }
            # Dismissal-aware extras (present once the joint model is fit):
            # batters get survival, bowlers get strike, both get `value`.
            if r.get("survival_skill") is not None:
                entry["survival_skill"] = r.get("survival_skill")
                entry["survival_skill_sd"] = r.get("survival_skill_sd")
            if r.get("strike_skill") is not None:
                entry["strike_skill"] = r.get("strike_skill")
                entry["strike_skill_sd"] = r.get("strike_skill_sd")
            if r.get("value") is not None:
                entry["value"] = r.get("value")
            out[f"bayes_{r['role']}"] = entry
    return out


def build(name: str, collection: str = "ipl") -> dict:
    profile: dict = {"name": name, "collection": collection}
    if not DUCKDB_PATH.exists():
        return profile

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        people = _people_row(con, name)
        profile["ids"] = people or {}
        if people:
            profile["cricsheet_id"] = people.get("cricsheet_id")
            wikidata = _wikidata_row(con, people.get("key_cricinfo"))
            profile["wikidata"] = wikidata or {}
            profile["bayes"] = _bayes_skills(con, collection, people.get("cricsheet_id"))
        else:
            profile["cricsheet_id"] = None
            profile["wikidata"] = {}
            profile["bayes"] = {}
        profile["career"] = _career_totals(con, collection, name)
    finally:
        con.close()

    profile["metrics"] = {
        "pressure_runs": _load_metric_row("pressure_runs", collection, name),
        "recoverability": _load_metric_row("recoverability", collection, name),
        "counter_attack": _load_metric_row("counter_attack", collection, name),
        "boundary_dependency": _load_metric_row("boundary_dependency", collection, name),
        "sticky_dot_pressure": _load_metric_row(
            "sticky_dot_pressure", collection, name, key_col="bowler"
        ),
    }

    try:
        twins = twin.style_twin(name, role="batter", k=5, collection=collection)
        profile["style_twins_batter"] = twins.to_dicts() if not twins.is_empty() else []
    except Exception:
        profile["style_twins_batter"] = []
    try:
        twins_b = twin.style_twin(name, role="bowler", k=5, collection=collection)
        profile["style_twins_bowler"] = twins_b.to_dicts() if not twins_b.is_empty() else []
    except Exception:
        profile["style_twins_bowler"] = []

    # Dismissal fingerprint — *how* this player gets out / takes wickets
    # (scouting metadata, separate from the Bayesian skill numbers).
    try:
        from cricdex.metrics import dismissal_fingerprint as df

        profile["dismissal_fingerprint"] = {
            "batter": df.batter_modes(name, collection),
            "bowler": df.bowler_modes(name, collection),
        }
    except Exception:
        profile["dismissal_fingerprint"] = {}
    return profile


def write(name: str, collection: str = "ipl", out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (DATA_DIR / "profiles" / collection)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "_")
    out_path = out_dir / f"{safe_name}.json"
    profile = build(name, collection)
    out_path.write_text(json.dumps(profile, indent=2, default=str))
    return out_path


def _from_polars(df: pl.DataFrame) -> list[dict]:
    return df.to_dicts() if not df.is_empty() else []
