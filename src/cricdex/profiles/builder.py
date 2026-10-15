"""Player-profile assembler.

Builds a single dict for one player from every source CricDex has:
- Cricsheet People Register cross-IDs
- Wikidata enrichment (DOB / country / gender) if loaded
- Career totals from the ball table
- Every catalog metric the player appears in (all 12 leaderboards)
- Bayesian scout rating skills
- Top-5 style twins

Profiling many players (the site export): build one `Sources` per collection
and pass it, with one open read-only connection, to every `build` call.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import duckdb

from cricdex.common.metrics import METRICS
from cricdex.common.sql import BOWLER_RUNS, MAIN_INNINGS, table_suffix
from cricdex.config import CURATED_DIR, DATA_DIR
from cricdex.metrics import dismissal_fingerprint as df
from cricdex.scout.search import style_twin as twin

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
METRIC_DIR = DATA_DIR / "metrics"
# Wikidata identity enrichment lives in this JSON cache keyed by
# cricsheet_id — NOT a DuckDB table (no ingest step builds one).
WIKIDATA_ENRICHMENT = CURATED_DIR / "wikidata_enrichment.json"
# Fields surfaced on profiles (drop the qid/status plumbing).
_WIKI_KEEP = (
    "dob",
    "label",
    "image_url",
    "instagram",
    "twitter",
    "espn_id",
    "cricbuzz_id",
    "statsguru_id",
    "wikidata_qid",
    "country_qid",
    "birthplace_qid",
)


@lru_cache(maxsize=1)
def _wikidata_cache() -> dict[str, dict]:
    """cricsheet_id -> cleaned identity record (dob/photo/socials), only
    where the Wikidata lookup succeeded. Loaded once per process."""
    if not WIKIDATA_ENRICHMENT.exists():
        return {}
    raw = json.loads(WIKIDATA_ENRICHMENT.read_text())
    out: dict[str, dict] = {}
    for cid, rec in raw.items():
        if not isinstance(rec, dict) or rec.get("_status") != "ok":
            continue
        kept = {k: rec.get(k) for k in _WIKI_KEEP if rec.get(k) is not None}
        if kept:
            out[cid] = kept
    return out


# LLM-built taxonomy (role / bowling type / batting slot / country),
# keyed by cricsheet_id. See scripts/enrich_taxonomy.py.
TAXONOMY_CACHE_PATH = CURATED_DIR / "player_taxonomy.json"
_TAX_KEEP = (
    "primary_role",
    "bowling_category",
    "bowling_style",
    "batting_position",
    "batting_hand",
    "country",
)


@lru_cache(maxsize=1)
def _taxonomy_cache() -> dict[str, dict]:
    """cricsheet_id -> taxonomy. Pure batters/keepers get their bowling
    type dropped (part-time bowling shouldn't read as a bowling identity)."""
    if not TAXONOMY_CACHE_PATH.exists():
        return {}
    raw = json.loads(TAXONOMY_CACHE_PATH.read_text())
    out: dict[str, dict] = {}
    for cid, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        kept = {k: rec.get(k) for k in _TAX_KEEP if rec.get(k) not in (None, "unknown", "none")}
        if kept.get("primary_role") in {"batter", "wk_batter"}:
            kept.pop("bowling_category", None)
            kept.pop("bowling_style", None)
        if kept:
            out[cid] = kept
    return out


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


def _wikidata_row(cricsheet_id: str | None) -> dict | None:
    """Identity (dob / photo / socials) for a player, by cricsheet_id."""
    if not cricsheet_id:
        return None
    return _wikidata_cache().get(cricsheet_id)


def career_totals(con: duckdb.DuckDBPyConnection, collection: str, name: str) -> dict:
    """Raw career totals for one player from the ball table (main innings only).
    Shared with `comparator.compare`, which renames a few keys."""
    safe = table_suffix(collection)
    bat = con.execute(
        f"""
        SELECT
            SUM(runs_batter) AS runs,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS balls,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            COUNT(DISTINCT (match_id, innings_idx)) AS innings,
            COUNT(DISTINCT match_id) AS matches
        FROM balls_{safe}
        WHERE batter = ? AND {MAIN_INNINGS}
        """,
        [name],
    ).fetchone()
    bowl = con.execute(
        f"""
        SELECT
            SUM(CASE WHEN wicket_kind IS NOT NULL
                  AND wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field')
                 THEN 1 ELSE 0 END) AS wickets,
            SUM({BOWLER_RUNS}) AS runs_conceded,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides','noballs')) AS legal_balls,
            COUNT(DISTINCT match_id) AS matches_bowled
        FROM balls_{safe}
        WHERE bowler = ? AND {MAIN_INNINGS}
        """,
        [name],
    ).fetchone()
    return {
        "career_runs": int(bat[0] or 0),
        "career_balls_faced": int(bat[1] or 0),
        "career_sixes": int(bat[2] or 0),
        "career_fours": int(bat[3] or 0),
        "career_innings": int(bat[4] or 0),
        "career_matches": int(bat[5] or 0),
        "career_wickets": int(bowl[0] or 0),
        "career_runs_conceded": int(bowl[1] or 0),
        "career_legal_balls_bowled": int(bowl[2] or 0),
        "career_matches_bowled": int(bowl[3] or 0),
    }


_INTENT_BUCKETS = ["01_0-5", "02_6-10", "03_11-20", "04_21-30", "05_31-50", "06_51+"]


def _intent_rows(rows: list[dict]) -> dict[str, dict]:
    """intent_curve is long (one row per batter and ball bucket); fold it into
    one record per batter: the 6-point SR curve plus `early_sr` (balls 1-10),
    the same shape as the exported leaderboard row."""
    by_batter: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r.get("batter") is not None:
            by_batter.setdefault(r["batter"], {})[r.get("ball_bucket")] = r
    out: dict[str, dict] = {}
    for batter, buckets in by_batter.items():
        curve = [
            round(float(buckets[b]["sr"]), 1)
            if b in buckets and buckets[b].get("sr") is not None
            else None
            for b in _INTENT_BUCKETS
        ]
        early = [buckets[b] for b in _INTENT_BUCKETS[:2] if b in buckets]
        e_balls = sum(int(r.get("balls") or 0) for r in early)
        e_runs = sum(int(r.get("runs") or 0) for r in early)
        present = [c for c in curve if c is not None]
        out[batter] = {
            "batter": batter,
            "early_sr": round(100.0 * e_runs / e_balls, 1) if e_balls else None,
            "peak_sr": max(present) if present else None,
            "balls": sum(int(r.get("balls") or 0) for r in buckets.values()),
            "curve": curve,
        }
    return out


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    return rows.get("rows", []) if isinstance(rows, dict) else rows


def load_metric_tables(collection: str) -> dict[str, dict[str, dict]]:
    """Every catalog metric (all 12 leaderboards) for a collection, indexed
    slug -> player name -> row. Read once and reused for every profile."""
    tables: dict[str, dict[str, dict]] = {}
    for m in METRICS:
        rows = _read_rows(METRIC_DIR / f"{m.slug}_{collection}.json")
        if m.slug == "intent_curve":
            tables[m.slug] = _intent_rows(rows)
        else:
            tables[m.slug] = {r[m.name_col]: r for r in rows if r.get(m.name_col) is not None}
    return tables


def load_bayes_table(collection: str) -> dict[str, dict]:
    """cricsheet_id -> {bayes_<role>: {skill, skill_sd, balls, ...}} from the
    scout ratings, read once per collection."""
    out: dict[str, dict] = {}
    for r in _read_rows(METRIC_DIR / f"scout_ratings_{collection}.json"):
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
        out.setdefault(r.get("cricsheet_id"), {})[f"bayes_{r['role']}"] = entry
    return out


class Sources:
    """Everything `build` reads that is the same for every player of a
    collection: metric tables, ratings and the style-twin indexes. Make one
    per collection when profiling many players (the site export does)."""

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.metrics = load_metric_tables(collection)
        self.bayes = load_bayes_table(collection)
        self.twins: dict[str, twin.TwinIndex | None] = {}
        for role in ("batter", "bowler"):
            try:
                self.twins[role] = twin.TwinIndex(role, collection, DUCKDB_PATH)
            except Exception:  # noqa: BLE001 — twins are optional on a profile
                self.twins[role] = None


def _twins(sources: Sources, role: str, name: str) -> list[dict]:
    index = sources.twins.get(role)
    if index is None:
        return []
    try:
        found = index.query(name, k=5)
    except Exception:  # noqa: BLE001 — not in this role's feature table
        return []
    return found.to_dicts() if not found.is_empty() else []


def build(
    name: str,
    collection: str = "ipl",
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    sources: Sources | None = None,
) -> dict:
    """One player's profile. Pass an open read-only `con` and the collection's
    `Sources` to reuse them across players; otherwise both are made here."""
    profile: dict = {"name": name, "collection": collection}
    if con is None and not DUCKDB_PATH.exists():
        return profile
    sources = sources or Sources(collection)
    own = con is None
    if own:
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        people = _people_row(con, name)
        profile["ids"] = people or {}
        cid = people.get("cricsheet_id") if people else None
        profile["cricsheet_id"] = cid
        profile["wikidata"] = _wikidata_row(cid) or {}
        profile["taxonomy"] = (_taxonomy_cache().get(cid) if cid else None) or {}
        profile["bayes"] = (sources.bayes.get(cid) if cid else None) or {}
        profile["career"] = career_totals(con, collection, name)

        # Every catalog metric, keyed by slug; None where the player isn't on that board.
        profile["metrics"] = {m.slug: sources.metrics.get(m.slug, {}).get(name) for m in METRICS}
        profile["style_twins_batter"] = _twins(sources, "batter", name)
        profile["style_twins_bowler"] = _twins(sources, "bowler", name)

        # Dismissal fingerprint — *how* this player gets out / takes wickets
        # (scouting metadata, separate from the Bayesian skill numbers).
        try:
            profile["dismissal_fingerprint"] = {
                "batter": df.batter_modes(name, collection, con=con),
                "bowler": df.bowler_modes(name, collection, con=con),
            }
        except Exception:  # noqa: BLE001
            profile["dismissal_fingerprint"] = {}
    finally:
        if own:
            con.close()
    return profile
