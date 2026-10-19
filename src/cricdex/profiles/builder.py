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
from cricdex.common.sql import (
    BOWLER_RUNS,
    MAIN_INNINGS,
    cid_of,
    keyed_balls,
    label_map,
    name_of_key,
    resolve_key,
    table_suffix,
)
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


def _people_row(con: duckdb.DuckDBPyConnection, key: str, name: str) -> dict | None:
    """The player's ids: his Cricsheet id (the key, resolved per match through the collection's
    registry) and the People Register's cross-site keys for it."""
    cid = cid_of(key)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "people" not in tables:
        return {"cricsheet_id": cid, "unique_name": name} if cid else None
    row = con.execute(
        """
        SELECT identifier AS cricsheet_id, unique_name,
               key_cricinfo, key_cricbuzz, key_cricheroes, key_bigbash
        FROM people
        WHERE identifier = ? OR (? IS NULL AND unique_name = ?)
        """,
        [cid, cid, name],
    ).fetchone()
    if not row:
        # an id the register doesn't have yet still identifies the player
        return {"cricsheet_id": cid, "unique_name": name} if cid else None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row, strict=True))


def _wikidata_row(cricsheet_id: str | None) -> dict | None:
    """Identity (dob / photo / socials) for a player, by cricsheet_id."""
    if not cricsheet_id:
        return None
    return _wikidata_cache().get(cricsheet_id)


def career_totals(con: duckdb.DuckDBPyConnection, collection: str, name: str) -> dict:
    """Raw career totals for one player from the ball table (main innings only). `name` is his
    registry id or scorecard name (see `common.sql.resolve_key`). Shared with `comparator.compare`,
    which renames a few keys."""
    table_suffix(collection)  # rejects an unsafe collection name
    key = resolve_key(con, collection, name)
    kb = keyed_balls(con, collection)
    bat = con.execute(
        f"""
        SELECT
            SUM(runs_batter) AS runs,
            COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS balls,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            COUNT(DISTINCT (match_id, innings_idx)) AS innings,
            COUNT(DISTINCT match_id) AS matches
        FROM {kb}
        WHERE batter = ? AND {MAIN_INNINGS}
        """,
        [key],
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
        FROM {kb}
        WHERE bowler = ? AND {MAIN_INNINGS}
        """,
        [key],
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
        **career_standard(con, collection, key),
    }


_BOWLER_WICKET_SQL = (
    "wicket_kind IS NOT NULL AND wicket_kind NOT IN "
    "('run out','retired hurt','retired out','obstructing the field')"
)


def career_standard(con: duckdb.DuckDBPyConnection, collection: str, name: str) -> dict:
    """The standard stat line on top of the totals (main innings only, legal balls): 50s / 100s,
    highest score (and whether not out), dismissals, dots faced / bowled, best bowling, 3-wicket
    (exactly three) and 4+-wicket hauls. `name` is a registry id or scorecard name."""
    table_suffix(collection)  # rejects an unsafe collection name
    name = resolve_key(con, collection, name)
    kb = keyed_balls(con, collection)
    inns = con.execute(
        f"""
        WITH b AS (SELECT * FROM {kb} WHERE {MAIN_INNINGS}),
        bat AS (
            SELECT match_id, innings_idx, SUM(runs_batter) AS runs FROM b
            WHERE batter = ? GROUP BY 1, 2
        ),
        outs AS (
            SELECT DISTINCT match_id, innings_idx FROM b
            WHERE player_out = ? AND COALESCE(wicket_kind, '') <> 'retired hurt'
        )
        SELECT bat.runs, outs.match_id IS NOT NULL AS out
        FROM bat LEFT JOIN outs USING (match_id, innings_idx)
        """,
        [name, name],
    ).fetchall()
    dismissals, dots_faced, dots_bowled = con.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE player_out = ? AND COALESCE(wicket_kind, '') <> 'retired hurt'),
            COUNT(*) FILTER (WHERE batter = ? AND COALESCE(extras_type, '') <> 'wides'
                             AND runs_batter = 0),
            COUNT(*) FILTER (WHERE bowler = ? AND COALESCE(extras_type, '') NOT IN ('wides', 'noballs')
                             AND runs_batter = 0)
        FROM {kb} WHERE {MAIN_INNINGS} AND (player_out = ? OR batter = ? OR bowler = ?)
        """,
        [name] * 6,
    ).fetchone()
    spells = con.execute(
        f"""
        SELECT SUM(CASE WHEN {_BOWLER_WICKET_SQL} THEN 1 ELSE 0 END) AS w, SUM({BOWLER_RUNS}) AS r
        FROM {kb} WHERE bowler = ? AND {MAIN_INNINGS}
        GROUP BY match_id, innings_idx
        """,
        [name],
    ).fetchall()
    scores = [(int(r or 0), bool(o)) for r, o in inns]
    top = max(scores, key=lambda s: (s[0], not s[1]), default=None)
    best = min(((-int(w or 0), int(r or 0)) for w, r in spells), default=None)
    return {
        "career_fifties": sum(1 for r, _ in scores if 50 <= r < 100),
        "career_hundreds": sum(1 for r, _ in scores if r >= 100),
        "career_highest_score": top[0] if top else None,
        "career_highest_score_not_out": (not top[1]) if top else None,
        "career_dismissals": int(dismissals or 0),
        "career_dots_faced": int(dots_faced or 0),
        "career_dots_bowled": int(dots_bowled or 0),
        "career_best_bowling_wickets": -best[0] if best else None,
        "career_best_bowling_runs": best[1] if best else None,
        "career_three_wkt_hauls": sum(1 for w, _ in spells if int(w or 0) == 3),
        "career_four_wkt_hauls": sum(1 for w, _ in spells if int(w or 0) >= 4),
    }


_INTENT_BUCKETS = ["01_0-5", "02_6-10", "03_11-20", "04_21-30", "05_31-50", "06_51+"]


def _intent_rows(rows: list[dict]) -> dict[str, dict]:
    """intent_curve is long (one row per batter and ball bucket); fold it into
    one record per batter: the 6-point SR curve plus `early_sr` (balls 1-10),
    the same shape as the exported leaderboard row."""
    by_batter: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r.get("batter") is not None:
            by_batter.setdefault(_row_key(r, "batter"), {})[r.get("ball_bucket")] = r
    out: dict[str, dict] = {}
    for key, buckets in by_batter.items():
        batter = next(iter(buckets.values()))["batter"]
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
        out[key] = {
            "batter": batter,
            "cricsheet_id": cid_of(key),
            "early_sr": round(100.0 * e_runs / e_balls, 1) if e_balls else None,
            "peak_sr": max(present) if present else None,
            "balls": sum(int(r.get("balls") or 0) for r in buckets.values()),
            "curve": curve,
        }
    return out


def _row_key(row: dict, name_col: str) -> str:
    """A metric row's player key: its `cricsheet_id`, else (an unresolved player, or a file written
    before rows carried ids) `unresolved:<scorecard name>`."""
    return row.get("cricsheet_id") or f"unresolved:{row.get(name_col)}"


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    return rows.get("rows", []) if isinstance(rows, dict) else rows


def load_metric_tables(collection: str) -> dict[str, dict[str, dict]]:
    """Every catalog metric (all 12 leaderboards) for a collection, indexed
    slug -> player key (registry id) -> row. Read once and reused for every profile."""
    tables: dict[str, dict[str, dict]] = {}
    for m in METRICS:
        rows = _read_rows(METRIC_DIR / f"{m.slug}_{collection}.json")
        if m.slug == "intent_curve":
            tables[m.slug] = _intent_rows(rows)
        else:
            tables[m.slug] = {
                _row_key(r, m.name_col): r for r in rows if r.get(m.name_col) is not None
            }
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
        self.labels: dict[str, str] | None = None  # player key -> scorecard name, on first use
        self.twins: dict[str, twin.TwinIndex | None] = {}
        for role in ("batter", "bowler"):
            try:
                self.twins[role] = twin.TwinIndex(role, collection, DUCKDB_PATH)
            except Exception:  # noqa: BLE001 — twins are optional on a profile
                self.twins[role] = None


TWINS_K = 25  # enough look-alikes left after a country filter


def _twins(sources: Sources, role: str, key: str) -> list[dict]:
    index = sources.twins.get(role)
    if index is None:
        return []
    try:
        found = index.query(key, k=TWINS_K)
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
    """One player's profile. `name` is his registry id (exact) or a scorecard name (a name two
    players share resolves to the one with more matches here). Pass an open read-only `con` and the
    collection's `Sources` to reuse them across players; otherwise both are made here."""
    profile: dict = {"name": name, "collection": collection}
    if con is None and not DUCKDB_PATH.exists():
        return profile
    sources = sources or Sources(collection)
    own = con is None
    if own:
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        key = resolve_key(con, collection, name)
        if sources.labels is None:
            sources.labels = label_map(con, collection)
        scorecard = name_of_key(key, sources.labels) or name
        profile["name"] = scorecard
        people = _people_row(con, key, scorecard)
        profile["ids"] = people or {}
        cid = cid_of(key)
        profile["cricsheet_id"] = cid
        profile["wikidata"] = _wikidata_row(cid) or {}
        profile["taxonomy"] = (_taxonomy_cache().get(cid) if cid else None) or {}
        profile["bayes"] = (sources.bayes.get(cid) if cid else None) or {}
        profile["career"] = career_totals(con, collection, key)

        # Every catalog metric, keyed by slug; None where the player isn't on that board.
        profile["metrics"] = {m.slug: sources.metrics.get(m.slug, {}).get(key) for m in METRICS}
        profile["style_twins_batter"] = _twins(sources, "batter", key)
        profile["style_twins_bowler"] = _twins(sources, "bowler", key)

        # Dismissal fingerprint — *how* this player gets out / takes wickets
        # (scouting metadata, separate from the Bayesian skill numbers).
        try:
            profile["dismissal_fingerprint"] = {
                "batter": df.batter_modes(key, collection, con=con),
                "bowler": df.bowler_modes(key, collection, con=con),
            }
        except Exception:  # noqa: BLE001
            profile["dismissal_fingerprint"] = {}
    finally:
        if own:
            con.close()
    return profile
