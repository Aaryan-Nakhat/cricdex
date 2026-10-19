"""Export every computed CricDex artifact into a static JSON tree the
GitHub Pages frontend reads — no backend, no live compute in the
browser.

The browser only ever *displays* pre-cooked numbers. This script is
the "cook once" step: it flattens metrics / ratings / scout-graph
cohorts / per-player profiles / records / venues into
`site/data/<collection>/...` plus a top-level `collections.json`
carrying the "data up to <date>" freshness stamp per collection.

Run:
    uv run python scripts/export_site.py                 # all collections
    uv run python scripts/export_site.py -c ipl          # one collection
    uv run python scripts/export_site.py --min-balls 300 # profile/cohort cutoff

Output layout (per collection):
    site/data/<collection>/
        meta.json                      collection + data_as_of + counts
        ratings.json                   scout ratings (head-to-head runs in JS)
        players.json                   [{name, cricsheet_id, balls_*, role}]
        leaderboards/<slug>.json       the 10 metric tables (trimmed)
        records.json                   record leaderboards + on-this-day
        venues.json                    per-venue conditions
        profiles/<cricsheet_id>.json   full profile per qualifying player
        cohorts/<cricsheet_id>.json    co_faced (faced-the-same-bowlers cohort)
    site/data/collections.json         index: [{collection, data_as_of, ...}] in registry order
    site/data/leagues.json             the league registry (labels, tiers, discounts, pools)

`data_as_of` is the max match_date actually in the collection — the
real "data up to" date the UI shows, not the build time.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import typer
from loguru import logger

from cricdex import leagues
from cricdex.common.sql import (
    BOWLER_RUNS,
    MAIN_INNINGS,
    UNRESOLVED,
    WINDOWS,
    keyed_balls,
    label_map,
    materialize_keyed,
    name_of_key,
    player_ids,
    table_suffix,
)
from cricdex.config import CURATED_DIR, DATA_DIR
from cricdex.config import SITE_DATA as _DEFAULT_SITE_DATA
from cricdex.scout.identity import countries
from cricdex.scout.identity import master as player_master

app = typer.Typer(add_completion=False)

ROOT = Path(__file__).resolve().parent.parent
# The output root; `--out` points it somewhere else (a scratch export).
SITE_DATA = _DEFAULT_SITE_DATA
METRIC_DIR = DATA_DIR / "metrics"
DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
# LLM-built taxonomy (role / bowling type / batting position / country),
# keyed by cricsheet_id. See scripts/enrich_taxonomy.py.
TAXONOMY_PATH = CURATED_DIR / "player_taxonomy.json"

# Fields merged onto players / profiles / cohort members for filters + display.
_TAX_KEEP = (
    "primary_role",
    "bowling_category",
    "bowling_style",
    "batting_position",
    "batting_hand",
    "country",
)


def _clean_tax(rec: dict) -> dict:
    kept = {k: rec.get(k) for k in _TAX_KEEP if rec.get(k) not in (None, "unknown", "none")}
    # Pure batters / keepers shouldn't carry a bowling type — they only
    # bowl occasional part-time, so a "seam" tag pollutes bowling filters.
    if kept.get("primary_role") in {"batter", "wk_batter"}:
        kept.pop("bowling_category", None)
        kept.pop("bowling_style", None)
    return kept


def _load_taxonomy() -> dict[str, dict]:
    """cid -> the player's identity: the player master (data/curated/player_master.json, built by
    scripts/build_player_master.py) when it exists, else the bare LLM taxonomy with countries
    normalised. Every consumer reads it with `.get`, so either shape works."""
    ident = player_master.load()
    if ident:
        return ident
    logger.warning("player master not built — falling back to the raw LLM taxonomy")
    if not TAXONOMY_PATH.exists():
        return {}
    raw = json.loads(TAXONOMY_PATH.read_text())
    out = {}
    for cid, rec in raw.items():
        if isinstance(rec, dict):
            t = _clean_tax(rec)
            if t.get("country"):
                t["country"] = countries.normalise(t["country"])
            out[cid] = t
    return out


# Identity fields copied onto every leaderboard / phase row (looked up by the row's scorecard name).
_ROW_IDENTITY = (
    "cricsheet_id",
    "display_name",
    "primary_role",
    "bowling_category",
    "bowling_style",
    "batting_position",
    "batting_hand",
    "country",
    "capped",
    "retired",
    "team",
)


def _name_identity(
    con: duckdb.DuckDBPyConnection, collection: str, taxonomy: dict[str, dict]
) -> dict[str, dict]:
    """player key -> identity fields, for every player of this collection. A key is the registry id
    (`unresolved:<name>` for the rare name no registry knows), resolved per match, so two players
    sharing a scorecard name each get their own identity. Rows are tagged by their `cricsheet_id`."""
    out: dict[str, dict] = {}
    for key in label_map(con, collection):
        cid = None if key.startswith(UNRESOLVED) else key
        rec = taxonomy.get(cid or "") or {}
        row: dict = {"cricsheet_id": cid}
        for k in _ROW_IDENTITY[1:]:
            if rec.get(k) is not None:
                row[k] = rec[k]
        out[key] = row
    return out


def _row_key(r: dict) -> str | None:
    """The player key of an exported row: its `cricsheet_id`, else `unresolved:<scorecard name>`."""
    if r.get("cricsheet_id"):
        return r["cricsheet_id"]
    who = r.get("name") or r.get("batter") or r.get("bowler") or r.get("fielder")
    return f"{UNRESOLVED}{who}" if who else None


METRIC_SLUGS = [
    "ngi",
    "pressure_runs",
    "intent_curve",
    "dot_ball_recovery",
    "counter_attack",
    "boundary_dependency",
    "pressure_conversion",
    "wicket_quality",
    "crease_longevity",
    "slow_start_cost",
    "keeping",
    "fielding",
]

# Every league the registry marks `export = true` (config/leagues.toml), in display order.
DEFAULT_COLLECTIONS = leagues.exported_keys()


def _json_default(o):
    """DuckDB hands back Decimal + date/datetime that json can't encode."""
    import datetime as _dt
    from decimal import Decimal

    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, _dt.date | _dt.datetime):
        return o.isoformat()
    return str(o)


_NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?$")


def _is_text_key(key: str) -> bool:
    """Keys whose values are identifiers or labels even when they look numeric (match ids,
    register keys, seasons like "2020", dates)."""
    k = key.lower()
    return (
        k in {"id", "season", "name", "batter", "bowler", "fielder", "a", "b", "key"}
        or k.endswith("_id")
        or k.endswith("_key")
        or k.startswith("key_")
        or "date" in k
        or k.endswith("_qid")
        or k.endswith("name")
    )


def _numify(obj, key: str = ""):
    """Numbers stored as strings (DuckDB Decimals that reached a metric file as "1028") back to
    numbers, recursively. Identifier-like keys are left alone."""
    if isinstance(obj, dict):
        return {k: _numify(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numify(v, key) for v in obj]
    if isinstance(obj, str) and key and not _is_text_key(key) and _NUMERIC.match(obj):
        return float(obj) if "." in obj else int(obj)
    return obj


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Trailing newline so the repo's end-of-file-fixer pre-commit hook
    # leaves the snapshot untouched (and CI-committed data matches).
    plain = json.loads(json.dumps(obj, default=_json_default))
    path.write_text(json.dumps(_numify(plain), separators=(",", ":")) + "\n", encoding="utf-8")


def _prune_player_files(out_dir: Path, keep: set[str]) -> int:
    """Delete profiles/, cohorts/ and matchups/ files for players not in this export of the
    league (a player who dropped out of the league, or an old id), so stale files never ship."""
    removed = 0
    for sub in ("profiles", "cohorts", "matchups"):
        d = out_dir / sub
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            if f.stem not in keep:
                f.unlink()
                removed += 1
    if removed:
        logger.info(f"{out_dir.name}: removed {removed} stale per-player files")
    return removed


class DataQualityError(ValueError):
    """An exported value that can't be true (a negative ball count, a strike rate of 900, an
    unknown country code). The export stops instead of publishing it."""


def _is_count_key(k: str) -> bool:
    return (
        k
        in {
            "balls",
            "runs",
            "wickets",
            "matches",
            "catches",
            "stumpings",
            "runouts",
            "fours",
            "sixes",
            "dismissals",
            "innings",
            "innings_count",
            "dots_faced",
            "balls_faced",
            "balls_bowled",
        }
        or k.endswith("_balls")
        or (k.endswith("_runs") and k != "pressure_runs_per_ball")
        or k.startswith("balls_")
    )


def _bad_value(k: str, v) -> str | None:
    """Why `v` can't be a real value of the column `k` (None when it's fine)."""
    import math

    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "not a finite number"
    if _is_count_key(k) and v < 0:
        return "negative count"
    if (k == "sr" or k.endswith("_sr") or k.startswith("sr_") or "_sr_" in k) and not 0 <= v <= 600:
        return "strike rate outside 0-600"
    if k in {"econ", "economy"} and not 0 <= v <= 36:
        return "economy outside 0-36"
    if k.endswith("_pct") and not 0 <= v <= 100:
        return "percentage outside 0-100"
    return None


def _assert_rows(rows: list[dict], where: str) -> None:
    """Fail loudly on an impossible value in a table about to be exported."""
    bad = []
    for r in rows:
        for k, v in r.items():
            why = _bad_value(k, v)
            if why:
                bad.append(
                    f"{r.get('name') or r.get('batter') or r.get('bowler')}: {k}={v} ({why})"
                )
    if bad:
        raise DataQualityError(f"{where}: {len(bad)} impossible values, e.g. {bad[:5]}")


_ROLES = {"batter", "bowler", "allrounder", "wk_batter", None}
_CATEGORIES = {"seam", "spin", None}


def _assert_players(players: list[dict], where: str, as_of: str | None) -> None:
    """players.json: one row per id, identity fields within their vocabularies, believable ages."""
    import datetime as _dt

    errs: list[str] = []
    ids = [p["cricsheet_id"] for p in players]
    if len(ids) != len(set(ids)):
        dup = sorted({c for c in ids if ids.count(c) > 1})
        errs.append(f"duplicate cricsheet_ids {dup[:5]}")
    codes = countries.all_codes()
    ref = _dt.date.fromisoformat(as_of[:10]) if as_of else _dt.date.today()
    for p in players:
        who = f"{p.get('name')} ({p['cricsheet_id']})"
        if not p.get("display_name"):
            errs.append(f"{who}: no display_name")
        if p.get("country") is not None and p["country"] not in codes:
            errs.append(f"{who}: country {p['country']!r} isn't a normalised code")
        if p.get("primary_role") not in _ROLES:
            errs.append(f"{who}: primary_role {p.get('primary_role')!r}")
        if p.get("bowling_category") not in _CATEGORIES:
            errs.append(f"{who}: bowling_category {p.get('bowling_category')!r}")
        for flag in ("capped", "active", "retired"):
            if flag in p and not isinstance(p[flag], bool):
                errs.append(f"{who}: {flag} is not a bool")
        if not isinstance(p.get("aliases", []), list):
            errs.append(f"{who}: aliases is not a list")
        if p.get("dob"):
            try:
                age = (ref - _dt.date.fromisoformat(str(p["dob"])[:10])).days / 365.25
            except ValueError:
                errs.append(f"{who}: dob {p['dob']!r} isn't a date")
            else:
                # the oldest players in an exported league can be long retired (T20Is since 2005)
                if not 12 <= age <= 80:
                    errs.append(f"{who}: age {age:.0f} from dob {p['dob']}")
        for k in ("balls_faced", "balls_bowled", "matches"):
            why = _bad_value(k, p.get(k))
            if why:
                errs.append(f"{who}: {k}={p.get(k)} ({why})")
    if errs:
        raise DataQualityError(f"{where}: {len(errs)} problems, e.g. {errs[:8]}")


def _safe(collection: str) -> str:
    return table_suffix(collection)


def _collection_meta(con: duckdb.DuckDBPyConnection, collection: str) -> dict | None:
    safe = _safe(collection)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if f"balls_{safe}" not in tables:
        return None
    row = con.execute(
        f"""
        SELECT MAX(match_date) AS as_of,
               COUNT(DISTINCT match_id) AS matches,
               COUNT(*) AS balls
        FROM balls_{safe}
        """
    ).fetchone()
    return {
        "collection": collection,
        "data_as_of": str(row[0]) if row[0] else None,
        "n_matches": int(row[1] or 0),
        "n_balls": int(row[2] or 0),
    }


# Cricsheet IPL team name (incl. renames) -> current franchise code.
# Defunct sides (Deccan, Pune, Kochi, Gujarat Lions) are intentionally
# absent — a player whose MOST-RECENT team is defunct stopped playing, so
# they fall out via the `active` flag and become a free agent here (None).
IPL_TEAM_CODE: dict[str, str] = {
    "Mumbai Indians": "MI",
    "Chennai Super Kings": "CSK",
    "Royal Challengers Bengaluru": "RCB",
    "Royal Challengers Bangalore": "RCB",
    "Kolkata Knight Riders": "KKR",
    "Delhi Capitals": "DC",
    "Delhi Daredevils": "DC",
    "Punjab Kings": "PBKS",
    "Kings XI Punjab": "PBKS",
    "Sunrisers Hyderabad": "SRH",
    "Gujarat Titans": "GT",
    "Rajasthan Royals": "RR",
    "Lucknow Super Giants": "LSG",
}


# Real IPL 2025 mega-auction retentions (team -> [(name, price_cr)]), from
# the official lists. Names are matched against player name / full_name at
# export; the few below the ball cutoff (Mayank Yadav, Prabhsimran, Ramandeep,
# Pathirana) simply drop out. Used as the editable default in the sim so it
# isn't foolish (GT keeps Sai Sudharsan, RCB keeps Kohli, etc.).
MEGA_RETENTIONS_2025: dict[str, list[tuple[str, float]]] = {
    "CSK": [
        ("Ruturaj Gaikwad", 18),
        ("Ravindra Jadeja", 18),
        ("Matheesha Pathirana", 13),
        ("Shivam Dube", 12),
        ("MS Dhoni", 4),
    ],
    "MI": [
        ("Jasprit Bumrah", 18),
        ("SA Yadav", 16.35),
        ("Hardik Pandya", 16.35),
        ("Rohit Sharma", 16.30),
        ("Tilak Varma", 8),
    ],
    "RCB": [("Virat Kohli", 21), ("Rajat Patidar", 11), ("Yash Dayal", 5)],
    "KKR": [
        ("Rinku Singh", 13),
        ("Varun Chakravarthy", 12),
        ("Sunil Narine", 12),
        ("Andre Russell", 12),
        ("Harshit Rana", 4),
        ("Ramandeep Singh", 4),
    ],
    "DC": [
        ("Axar Patel", 16.5),
        ("Kuldeep Yadav", 13.25),
        ("Tristan Stubbs", 10),
        ("Abishek Porel", 4),
    ],
    "GT": [
        ("Rashid Khan", 18),
        ("Shubman Gill", 16.5),
        ("Sai Sudharsan", 8.5),
        ("Rahul Tewatia", 4),
        ("M Shahrukh Khan", 4),
    ],
    "SRH": [
        ("Heinrich Klaasen", 23),
        ("Pat Cummins", 18),
        ("Abhishek Sharma", 14),
        ("Travis Head", 14),
        ("Nithish Kumar Reddy", 6),
    ],
    "RR": [
        ("Sanju Samson", 18),
        ("Yashasvi Jaiswal", 18),
        ("Riyan Parag", 14),
        ("Dhruv Jurel", 14),
        ("Shimron Hetmyer", 11),
        ("Sandeep Sharma", 4),
    ],
    "LSG": [
        ("N Pooran", 21),
        ("Ravi Bishnoi", 11),
        ("Mayank Yadav", 11),
        ("Mohsin Khan", 4),
        ("A Badoni", 4),
    ],
    "PBKS": [("Shashank Singh", 5.5), ("Prabhsimran Singh", 4)],
}


def _dob_by_cid(taxonomy: dict[str, dict]) -> dict[str, str]:
    """cid -> date of birth: the player master's (Wikidata / Wikipedia), else the older
    one-time Wikidata enrichment."""
    out: dict[str, str] = {}
    try:
        for cid, rec in json.loads((CURATED_DIR / "wikidata_enrichment.json").read_text()).items():
            if isinstance(rec, dict) and rec.get("dob"):
                out[cid] = rec["dob"]
    except (FileNotFoundError, ValueError):
        pass
    for cid, rec in taxonomy.items():
        if rec.get("dob"):
            out[cid] = rec["dob"]
    return out


# The leagues the auction pool draws from (`auction_pool = true` in config/leagues.toml). Men's
# T20Is are left out there — associate-nation matches inflate value against minnows.
AUCTION_POOL_COLLECTIONS = [lg.key for lg in leagues.auction_pool()]
# The competition the pool is priced for (the IPL), and who may enter it as a free agent: its
# `auction_nationalities` allow-list and `auction_excluded_nationalities` deny-list (Pakistan and
# associate sides are left out — data in config/leagues.toml, not code).
AUCTION_TARGET = leagues.auction_target().key
auction_eligible = leagues.auction_target().auction_eligible
AUCTION_RECENCY_DAYS = 1100  # ~3 years of activity in ANY of those comps
AUCTION_POOL_CAP = 600  # top-N by value (keeps the sim snappy + relevant)
AUCTION_MIN_BALLS = 150  # drop tiny-sample players whose Bayes value is inflated
AUCTION_TARGET = "ipl"  # the league the auction is for (competition-rules config, later sprint)
AUCTION_TRUST_BALLS = 300  # a role record this big in the target league stands on its own
# Value removed from a player with zero IPL relevance (league-only veteran). In
# value units (runs per 100 balls, see scout/ratings/runs_value.py): 36 ≈ the
# earlier 2.7 population-sd units × 13.3, the measured sd ratio of the runs value
# to the old one (IPL players with 150+ balls; docs/AUCTION_MATH.md).
PEN_SCALE_VALUE = 36.0


def _export_auction_pool(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    taxonomy: dict[str, dict],
    teams: dict[str, str],
) -> int:
    """Cross-collection auction pool — the whole active T20 world an IPL
    auction draws from, not just IPL. Overseas players surface via BBL /
    men's T20Is, uncapped Indians via SMAT. Deduped by player; IPL players
    keep their franchise (retainable), everyone else is a free agent."""
    import datetime as _dt

    # Value isn't comparable across tiers (a number vs weak SMAT attacks ≠ vs
    # IPL), so each league's rating is first discounted by its tier (config/leagues.toml;
    # web_parity/pricing ⇄ lib/auction.ts read the same table). A player's leagues are then
    # BLENDED, per role, weighted by 1 / (rating sd² + the tier's translation_sd²): IPL evidence
    # dominates whenever it exists, and one hot spell in a weaker or provisional league can't
    # outrank a real IPL record (taking the best league did exactly that). Best role wins.
    acc: dict[tuple[str, str], list[float]] = {}  # (cid, role) -> [Σw, Σw·value]
    target_rows: dict[tuple[str, str], tuple[float, int, float]] = {}  # target (value, balls, sd)
    names: dict[str, str | None] = {}
    max_balls: dict[str, int] = {}
    for col in AUCTION_POOL_COLLECTIONS:
        f = METRIC_DIR / f"scout_ratings_{col}.json"
        if not f.exists():
            continue
        pen = leagues.discount(col)
        tsd = leagues.translation_sd(col)
        for r in json.loads(f.read_text()):
            cid, v = r.get("cricsheet_id"), r.get("value")
            if cid is None or v is None:
                continue
            max_balls[cid] = max(max_balls.get(cid, 0), int(r.get("balls") or 0))
            names.setdefault(cid, r.get("unique_name"))  # registry order: the IPL name first
            sd = float(r.get("value_sd") or 1.0)
            w = 1.0 / (sd * sd + tsd * tsd)
            a = acc.setdefault((cid, r.get("role") or ""), [0.0, 0.0])
            a[0] += w
            a[1] += w * (v - pen)
            if col == AUCTION_TARGET:
                target_rows[(cid, r.get("role") or "")] = (v, int(r.get("balls") or 0), sd)
    best: dict[str, dict] = {}
    for (cid, role), (sw, swx) in acc.items():
        # A big enough record in the target league stands on its own: a flat tier discount is too
        # harsh on stars, so other leagues only fill in when that sample is thin.
        # The value's sd goes along: the price is set on value − PRICE_CAUTION_SD × sd (pricing.py).
        # A blend's sd is 1 / √Σw (translation uncertainty included); a trusted IPL record its own.
        own = target_rows.get((cid, role))
        if own and own[1] >= AUCTION_TRUST_BALLS:
            val, vsd = own[0], own[2]
        else:
            val, vsd = swx / sw, (1.0 / sw) ** 0.5
        # his IPL balls in this role set the price ceiling (pricing.price_ceiling)
        tb = own[1] if own else 0
        if cid not in best or val > best[cid]["value"]:
            best[cid] = {"value": val, "value_sd": vsd, "target_balls": tb, "name": names.get(cid)}
    # drop tiny-sample players (inflated value)
    best = {cid: b for cid, b in best.items() if max_balls.get(cid, 0) >= AUCTION_MIN_BALLS}

    # Per-league last-played (keyed by cid). Keeping the breakdown — not just a
    # single cross-league max — lets us tell "active in SA20 but hasn't played
    # IPL in years" apart from "current IPL regular".
    last_by_col: dict[str, dict[str, str]] = {col: {} for col in AUCTION_POOL_COLLECTIONS}
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    for col in AUCTION_POOL_COLLECTIONS:
        safe = _safe(col)
        if f"balls_{safe}" not in have:
            logger.warning(f"auction_pool: {col} isn't ingested yet — left out of the pool")
            continue
        # by Cricsheet id through each match's registry: a player's scorecard name can differ
        # between leagues ("Navdeep Saini" here, "NA Saini" there), and two players can share one
        materialize_keyed(
            con, col
        )  # temp table: a keyed relation used twice in one query trips DuckDB
        kb = keyed_balls(con, col)
        for cid, d in con.execute(
            f"""
            SELECT k, MAX(match_date) FROM (
                SELECT batter AS k, match_date FROM {kb}
                UNION ALL SELECT bowler, match_date FROM {kb}
            ) WHERE k IS NOT NULL GROUP BY 1
            """
        ).fetchall():
            if cid in best and d:
                last_by_col[col][cid] = str(d)[:10]

    def _last_ipl(cid: str) -> str | None:
        return last_by_col[AUCTION_TARGET].get(cid)

    def _last_any(cid: str) -> str | None:
        ds = [last_by_col[c].get(cid) for c in AUCTION_POOL_COLLECTIONS]
        ds = [d for d in ds if d]
        return max(ds) if ds else None

    def _leagues(cid: str) -> list[dict]:
        rows = [
            {"league": c, "last": last_by_col[c][cid]}
            for c in AUCTION_POOL_COLLECTIONS
            if cid in last_by_col[c]
        ]
        return sorted(rows, key=lambda r: r["last"], reverse=True)

    asof = max((d for c in last_by_col.values() for d in c.values()), default=None)
    stale_league = {
        c: _is_stale(max(last_by_col[c].values(), default=None), asof) for c in last_by_col
    }
    asof_d = _dt.date.fromisoformat(asof) if asof else None
    cutoff = (asof_d - _dt.timedelta(days=AUCTION_RECENCY_DAYS)).isoformat() if asof_d else None

    # Age from the player master's date of birth (Wikidata / Wikipedia), where known.
    dob_by_cid = _dob_by_cid(taxonomy)

    def _age(cid: str) -> float | None:
        dob = dob_by_cid.get(cid)
        if not dob or not asof_d:
            return None
        try:
            return (asof_d - _dt.date.fromisoformat(str(dob)[:10])).days / 365.25
        except ValueError:
            return None

    def _age_factor(age: float | None) -> float | None:
        if age is None:
            return None
        if age <= 32:
            return 1.0
        if age >= 42:
            return 0.35
        return 1.0 - (age - 32) * 0.065  # 32→1.0 … 42→0.35

    def _relevance(cid: str, team: str | None, country: str | None, age: float | None) -> float:
        """IPL-relevance weight in [0,1]: how much this player's value should
        count toward an *IPL* auction. Current IPL players ≈ 1; league-only
        veterans (Imran Tahir) get hit by IPL-staleness + age."""
        li = _last_ipl(cid)
        af = _age_factor(age)
        if li:
            yrs = (asof_d - _dt.date.fromisoformat(li)).days / 365.25 if asof_d else 0
            if yrs <= 1.5:
                # current IPL regular — proven *now*, so age barely matters
                # (don't bury a 37-yo Kohli who's playing this season).
                return 1.0 if (age is None or age < 40) else 0.8
            ipl_f = max(0.4, 1.0 - (yrs - 1.5) * 0.18)
            return max(0.3, ipl_f * (af if af is not None else 1.0))
        # never played IPL
        if country == "IND" and not team:
            return 0.7  # uncapped Indian — a genuine draft target
        if af is not None:
            return max(0.2, 0.7 * af)  # overseas leaguer: young ~0.7, old ~0.25
        return 0.5  # unknown age → moderate (mid-pool, not top)

    PEN_SCALE = PEN_SCALE_VALUE  # value units removed at relevance 0
    role_map = {
        "wk_batter": "keeper",
        "allrounder": "all_rounder",
        "bowler": "bowler",
        "batter": "batter",
    }
    activity: dict[str, dict] = {}
    out = []
    for cid, b in best.items():
        name = b["name"]
        ld = _last_any(cid)
        if not name or not ld or (cutoff and ld < cutoff):
            continue  # active somewhere in the last ~3 years
        tax = taxonomy.get(cid, {})
        if tax.get("retired"):
            continue  # retired from the IPL (or from cricket): not in any auction
        country = tax.get("country")
        # IPL franchise (the 2026 squads in the player master), else None (free agent)
        team = tax.get("team") if tax.get("display_name") else teams.get(cid)
        if not team and not auction_eligible(country):
            continue
        age = _age(cid)
        rel = _relevance(cid, team, country, age)
        li = _last_ipl(cid)
        played = _leagues(cid)
        home = played[0]["league"] if played else None
        activity[cid] = {
            "leagues": played,
            "last_ipl": li,
            "last_any": ld,
            "home_league": home,
            "age": round(age, 1) if age is not None else None,
            "ipl_relevance": round(rel, 3),
        }
        out.append(
            {
                "cricsheet_id": cid,
                "name": name,
                "display_name": tax.get("display_name") or name,
                # value decayed by IPL-relevance so a league-only veteran stops
                # topping the IPL pool (the breakdown columns explain why).
                "value": round(b["value"] - (1 - rel) * PEN_SCALE, 4),
                # its uncertainty: the price uses value − PRICE_CAUTION_SD × value_sd
                "value_sd": round(b["value_sd"], 4),
                # IPL balls in the role priced: the price ceiling rises with them
                "target_balls": int(b["target_balls"]),
                "role": role_map.get(tax.get("primary_role"), "batter"),
                "primary_role": tax.get("primary_role"),
                "bowling_category": tax.get("bowling_category"),
                "bowling_style": tax.get("bowling_style"),
                "country": country,
                "is_overseas": bool(country) and country != "IND",
                "capped": bool(tax.get("capped")),
                "team": team,
                # where this player's profile lives: the target league if he has played it,
                # else his most recent league
                "profile_collection": AUCTION_TARGET if li else home,
                # every league his value rests on is stale (e.g. SMAT only)
                "stale": bool(played) and all(stale_league.get(r["league"]) for r in played),
                "last_match_date": ld,
                "last_ipl": li,
                "home_league": home,
                "age": round(age, 1) if age is not None else None,
                "ipl_relevance": round(rel, 3),
            }
        )
    out.sort(key=lambda p: p["value"], reverse=True)
    out = out[:AUCTION_POOL_CAP]
    _write(out_dir / "auction_pool.json", out)
    _write(out_dir / "activity_index.json", activity)
    return len(out)


# A league whose newest match is more than this many days older than the newest match anywhere is
# stale (SMAT on Cricsheet ended at the 2024-25 season): its numbers carry `stale: true`.
STALE_DAYS = 300


def _newest_match(con: duckdb.DuckDBPyConnection) -> str | None:
    """The newest match date in any exported league (the reference for staleness)."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    best = None
    for col in DEFAULT_COLLECTIONS:
        if f"balls_{_safe(col)}" not in have:
            continue
        d = con.execute(f"SELECT MAX(match_date) FROM balls_{_safe(col)}").fetchone()[0]
        if d and (best is None or str(d)[:10] > best):
            best = str(d)[:10]
    return best


def _is_stale(as_of: str | None, newest: str | None) -> bool:
    import datetime as _dt

    if not as_of or not newest:
        return False
    gap = _dt.date.fromisoformat(newest[:10]) - _dt.date.fromisoformat(as_of[:10])
    return gap.days > STALE_DAYS


def _scout_role_score(role: str, bat: float | None, bowl: float | None) -> float:
    """A player's standing on the role he is matched in: batters and keepers on
    batting value, bowlers on bowling value, all-rounders on both added (each
    value is centred on the average player, so a missing side counts as 0)."""
    if role == "all_rounder":
        return (bat or 0.0) + (bowl or 0.0)
    if role == "bowler":
        return bowl if bowl is not None else (bat or 0.0)
    return bat if bat is not None else (bowl or 0.0)


def _export_scout_index(
    con: duckdb.DuckDBPyConnection, out_dir: Path, taxonomy: dict[str, dict]
) -> int:
    """Cross-tier scouting index: for every Scout pool in the league registry (IPL peers, SMAT
    uncapped Indians, each overseas league), per recently-active player emit role/type + skill
    standing (z on the player's own role, among the shown players of that role in that tier, so
    levels compare across competitions). Keyed by tier, in registry order; a pool whose league
    hasn't been ingested and rated yet is an empty list. Powers 'players similar to <IPL player>
    in each tier'."""
    import datetime as _dt
    import statistics as _st

    # scout_index.json is keyed by each Scout pool's tier (`smat` for indian_domestic_male …)
    pools = leagues.scout_pools()
    tiers = {lg.tier: lg.key for lg in pools}
    draftable = {lg.tier for lg in pools if lg.draftable}
    uncapped = {lg.tier for lg in pools if lg.scout_group == "uncapped"}
    newest = _newest_match(con)
    role_map = {
        "wk_batter": "keeper",
        "allrounder": "all_rounder",
        "bowler": "bowler",
        "batter": "batter",
    }
    index: dict[str, list[dict]] = {}
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    # IPL balls per (player, side): the price ceiling rises with them (pricing.price_ceiling)
    target_balls: dict[tuple[str, str], int] = {}
    tf = METRIC_DIR / f"scout_ratings_{AUCTION_TARGET}.json"
    if tf.exists():
        for r in json.loads(tf.read_text()):
            side = "bowl" if r.get("role") == "bowler" else "bat"
            target_balls[(r.get("cricsheet_id"), side)] = int(r.get("balls") or 0)
    for tier, col in tiers.items():
        f = METRIC_DIR / f"scout_ratings_{col}.json"
        if not f.exists() or f"balls_{_safe(col)}" not in have:
            logger.warning(f"scout_index: no ratings / balls for {col} — the {tier} pool is empty")
            index[tier] = []
            continue
        # Each player's batting and bowling value, kept apart so a player is
        # scored on the role he is matched in (not his better side).
        bat: dict[str, float] = {}
        bowl: dict[str, float] = {}
        sds: dict[tuple[str, str], float] = {}  # (cid, side) -> value sd
        tsd = leagues.translation_sd(col)
        names: dict[str, str | None] = {}
        balls: dict[str, int] = {}
        for r in json.loads(f.read_text()):
            cid, v = r.get("cricsheet_id"), r.get("value")
            if cid is None or v is None:
                continue
            balls[cid] = max(balls.get(cid, 0), int(r.get("balls") or 0))
            side = "bowl" if r.get("role") == "bowler" else "bat"
            (bowl if side == "bowl" else bat)[cid] = v
            sds[(cid, side)] = float(r.get("value_sd") or 0.0)
            names[cid] = names.get(cid) or r.get("unique_name")
        # recency in this tier, by player key (registry id, resolved per match)
        materialize_keyed(
            con, col
        )  # temp table: a keyed relation used twice in one query trips DuckDB
        kb = keyed_balls(con, col)
        last = {
            k: str(d)[:10]
            for k, d in con.execute(
                f"SELECT k, MAX(match_date) FROM (SELECT batter k, match_date FROM {kb} "
                f"UNION ALL SELECT bowler, match_date FROM {kb}) WHERE k IS NOT NULL GROUP BY 1"
            ).fetchall()
            if d
        }
        asof = max(last.values()) if last else None
        cutoff = (
            (_dt.date.fromisoformat(asof) - _dt.timedelta(days=900)).isoformat() if asof else None
        )
        # a league whose newest match is over STALE_DAYS older than the newest anywhere (SMAT on
        # Cricsheet stops at 2024-12): every number from it carries the flag
        stale = _is_stale(asof, newest)
        rows = []
        scores: list[float] = []
        for cid in sorted(set(bat) | set(bowl)):
            nm = names.get(cid)
            ld = last.get(cid) or (last.get(f"{UNRESOLVED}{nm}") if nm else None)
            if not nm or balls.get(cid, 0) < 150 or not ld or (cutoff and ld < cutoff):
                continue
            tax = taxonomy.get(cid, {})
            # a draftable pool only offers players who could enter the auction (a known country
            # outside the auction target's nationality list is left out; untagged players stay),
            # and nobody who has retired from it
            if tier in draftable and tax.get("country") and not auction_eligible(tax["country"]):
                continue
            if tier in draftable and tax.get("retired"):
                continue
            # the uncapped pool ("the next big things") is uncapped players only: anyone who has
            # played a men's T20I, ODI or Test is out, however few his league balls
            if tier in uncapped and tax.get("capped"):
                continue
            role = role_map.get(tax.get("primary_role"), "batter")
            b, w = bat.get(cid), bowl.get(cid)
            sides = [x for x in (b, w) if x is not None]
            # the price basis is the better side; its sd, with the tier's translation sd added as in
            # the auction pool, feeds the cautious price (value − PRICE_CAUTION_SD × value_sd)
            better = "bat" if w is None or (b is not None and b >= w) else "bowl"
            vsd = (sds.get((cid, better), 0.0) ** 2 + tsd**2) ** 0.5
            rows.append(
                {
                    "cricsheet_id": cid,
                    "name": nm,
                    "display_name": tax.get("display_name") or nm,
                    "role": role,
                    "primary_role": tax.get("primary_role"),
                    "bowling_category": tax.get("bowling_category"),
                    "bowling_style": tax.get("bowling_style"),
                    "batting_position": tax.get("batting_position"),
                    "batting_hand": tax.get("batting_hand"),
                    "country": tax.get("country"),
                    "capped": bool(tax.get("capped")),
                    "team": tax.get("team"),
                    # price basis: the better side, as in the auction pool
                    "value": round(max(sides), 4),
                    "value_sd": round(vsd, 4),
                    "target_balls": target_balls.get((cid, better), 0),
                    "balls": balls.get(cid, 0),  # exposure — for the uncapped-gem flag
                    "last_match_date": ld,
                    # the league this row's numbers come from (its profile lives there)
                    "profile_collection": col,
                    "data_as_of": asof,
                    "stale": stale,
                }
            )
            scores.append(_scout_role_score(role, b, w))
        # z = standing on the matched role among the players SHOWN with that
        # role in this tier (look-alikes only ever compare within a role).
        for role in {r["role"] for r in rows}:
            idx = [i for i, r in enumerate(rows) if r["role"] == role]
            vals = [scores[i] for i in idx]
            mean = _st.mean(vals)
            sd = _st.pstdev(vals) if len(vals) > 1 else 0.0
            for i in idx:
                rows[i]["z"] = round((scores[i] - mean) / (sd or 1), 3)
        rows.sort(key=lambda r: r["z"], reverse=True)
        index[tier] = rows
    _write(out_dir / "scout_index.json", index)
    return sum(len(v) for v in index.values())


def _export_retentions(players: list[dict], out_dir: Path) -> None:
    """Resolve the real 2025 mega retentions to cricsheet_ids and write
    ipl/retentions.json. Names matched on name / full_name (case-insensitive)."""
    by_name: dict[str, dict] = {}
    for p in players:
        for n in (p["name"], p.get("display_name"), p.get("full_name"), *(p.get("aliases") or [])):
            if n:
                by_name.setdefault(n.lower(), p)
    mega: dict[str, list[dict]] = {}
    missing: list[str] = []
    for team, entries in MEGA_RETENTIONS_2025.items():
        rows = []
        for name, price in entries:
            p = by_name.get(name.lower())
            if p:
                rows.append(
                    {
                        "cricsheet_id": p["cricsheet_id"],
                        "name": p["name"],
                        "display_name": p.get("display_name") or p["name"],
                        "price": price,
                    }
                )
            else:
                missing.append(f"{team}:{name}")
        mega[team] = rows
    if missing:
        logger.info(f"retentions unmatched (below cutoff): {missing}")
    _write(out_dir / "retentions.json", {"mega": mega})


def _current_teams(con: duckdb.DuckDBPyConnection, collection: str) -> dict[str, str]:
    """player key -> current franchise code, from the team in each
    player's most-recent match — only for players who appeared in the
    latest season (a retired player's last franchise isn't their team).
    Only meaningful for IPL (the 10 franchises); other collections return
    {} since the codes don't map."""
    if collection != "ipl":
        return {}
    safe = _safe(collection)
    materialize_keyed(con, collection)
    kb = keyed_balls(con, collection)
    rows = con.execute(
        f"""
        -- scan the keyed balls ONCE (inlining the keyed relation three times in a UNION trips a
        -- DuckDB internal error), then fan out batter / non-striker / bowler from that
        WITH k AS MATERIALIZED (
            SELECT batter, non_striker, bowler, batting_team, bowling_team, match_date FROM {kb}
        ),
        app AS (
            SELECT batter AS name, batting_team AS team, match_date FROM k
                WHERE batting_team IS NOT NULL
            UNION ALL
            SELECT non_striker, batting_team, match_date FROM k
                WHERE batting_team IS NOT NULL AND non_striker IS NOT NULL
            UNION ALL
            SELECT bowler, bowling_team, match_date FROM k
                WHERE bowling_team IS NOT NULL
        ),
        ranked AS (
            SELECT name, team, match_date,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY match_date DESC) AS rk
            FROM app
        )
        SELECT name, team FROM ranked
        WHERE rk = 1
          AND EXTRACT(YEAR FROM match_date::DATE)
              = (SELECT MAX(EXTRACT(YEAR FROM match_date::DATE)) FROM balls_{safe})
        """
    ).fetchall()
    return {name: IPL_TEAM_CODE[team] for name, team in rows if team in IPL_TEAM_CODE}


def _players(
    con: duckdb.DuckDBPyConnection,
    collection: str,
    min_balls: int,
    taxonomy: dict[str, dict],
    activity: dict[str, dict],
) -> list[dict]:
    """Every player of the league (cleared `min_balls` faced + bowled; 0 = everyone, the default),
    with the cross-source ids needed for profile / cohort file lookups and the identity block."""
    teams = _current_teams(con, collection)
    if player_ids(con, collection) is None and not _has_registry(con, collection):
        return []
    # every player key (registry id, resolved per match), with the scorecard name he bats or bowls
    # under most often: two players who share a name are two rows
    materialize_keyed(con, collection)
    kb = keyed_balls(con, collection)
    names = label_map(con, collection)
    rows = con.execute(
        f"""
        WITH bats AS (
            SELECT batter AS cid,
                   COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS bf
            FROM {kb} WHERE batter IS NOT NULL AND {MAIN_INNINGS}
            GROUP BY 1
        ),
        bowls AS (
            SELECT bowler AS cid,
                   COUNT(*) FILTER (WHERE COALESCE(extras_type,'') NOT IN ('wides')) AS bb
            FROM {kb} WHERE bowler IS NOT NULL AND {MAIN_INNINGS}
            GROUP BY 1
        )
        SELECT COALESCE(bats.cid, bowls.cid) AS cid,
               COALESCE(bats.bf, 0) AS balls_faced,
               COALESCE(bowls.bb, 0) AS balls_bowled
        FROM bats FULL OUTER JOIN bowls ON bats.cid = bowls.cid
        """
    ).fetchall()
    counts = _match_counts(con, collection)
    # Full display names (Wikidata label) so search matches "Manish"
    # not just the Cricsheet short form "MK Pandey" (used only without a player master).
    from cricdex.profiles import builder

    wiki = builder._wikidata_cache()
    stats = {
        cid: (name_of_key(cid, names), bf, bb, counts.get(cid, 0))
        for cid, bf, bb in rows
        if cid and not cid.startswith(UNRESOLVED)
    }
    # everyone in an XI of this league, even if he never batted or bowled (a fielding sub-in, a
    # washed-out debut): every player gets a profile, so every link resolves
    for cid, rec in taxonomy.items():
        lg = (rec.get("leagues") or {}).get(collection)
        if lg and cid not in stats:
            nm = (rec.get("scorecard_names") or {}).get(collection) or rec.get("scorecard_name")
            if nm:
                stats[cid] = (nm, 0, 0, 0)
    out = []
    for cid, (name, bf, bb, matches) in stats.items():
        if (bf or 0) + (bb or 0) < min_balls:
            continue
        tax = taxonomy.get(cid, {})
        act = activity.get(cid, {})
        ident = player_master.identity_block(tax, fallback_name=name)
        if not tax.get("display_name"):
            # no master yet: the Wikidata label is the best full name we have
            ident["full_name"] = (wiki.get(cid) or {}).get("label") or name
            ident["team"] = teams.get(cid)
            ident["active"] = act.get("active", False)
        if name not in ident["aliases"]:
            ident["aliases"] = [*ident["aliases"], name]  # the scorecard name stays searchable
        out.append(
            {
                "cricsheet_id": cid,
                "name": name,  # the scorecard name: leaderboard rows key on it
                "balls_faced": int(bf or 0),
                "balls_bowled": int(bb or 0),
                # appearances in the XI (Cricsheet info.players; batting/bowling if absent)
                "matches": int(matches or 0),
                "role": "bowler" if (bb or 0) > (bf or 0) else "batter",
                "batting_position": tax.get("batting_position"),
                # data-driven activity in THIS league (the identity's `active` is across leagues)
                "first_match_date": act.get("first_match_date"),
                "last_match_date": act.get("last_match_date"),
                "active_here": act.get("active", False),
                "dob": tax.get("dob"),
                # identity (player master): display_name, full_name, aliases, capped, active,
                # retired, country, team, batting_hand, bowling_arm/category/style, primary_role
                **ident,
            }
        )
    out.sort(key=lambda r: (-(r["balls_faced"] + r["balls_bowled"]), r["cricsheet_id"]))
    return out


def _has_registry(con: duckdb.DuckDBPyConnection, collection: str) -> bool:
    from cricdex.common.sql import match_name_map

    return match_name_map(con, collection) is not None


def _match_counts(con: duckdb.DuckDBPyConnection, collection: str) -> dict[str, int]:
    """player key -> matches played, ALL players (no ball cutoff) so leaderboard rows can be filtered
    by a min-matches gate. An appearance is a place in the XI (Cricsheet `info.players`, the
    `match_players_<col>` table, counted in this collection's — or time window's — matches), so a
    batter who never got in or a bowler who didn't bowl still played; matches batted or bowled in
    are added for anyone the XI tables miss (a DB ingested before them)."""
    from cricdex.metrics.ngi import appearances

    return appearances(con, collection)


def _activity_map(
    con: duckdb.DuckDBPyConnection, collection: str, as_of: str | None
) -> dict[str, dict]:
    """player key -> {first_match_date, last_match_date, active}. 'active'
    = appeared within 18 months of the collection's latest match (so it's
    per-collection = per-format; a player retired from internationals can
    still be active in IPL). Data-driven, no model needed."""
    import datetime as _dt

    materialize_keyed(con, collection)
    kb = keyed_balls(con, collection)
    rows = con.execute(
        f"""
        SELECT name, MIN(match_date) AS first_d, MAX(match_date) AS last_d FROM (
            SELECT batter AS name, match_date FROM {kb}
            UNION ALL SELECT bowler AS name, match_date FROM {kb}
        ) WHERE name IS NOT NULL GROUP BY 1
        """
    ).fetchall()
    cutoff_iso: str | None = None
    if as_of:
        try:
            cutoff_iso = (_dt.date.fromisoformat(as_of[:10]) - _dt.timedelta(days=548)).isoformat()
        except ValueError:
            cutoff_iso = None
    out: dict[str, dict] = {}
    for name, first_d, last_d in rows:
        # duckdb may hand match_date back as a str here; ISO dates compare
        # lexicographically, so normalise to str and string-compare.
        last_iso = str(last_d)[:10] if last_d else None
        active = bool(cutoff_iso and last_iso and last_iso >= cutoff_iso)
        out[name] = {
            "first_match_date": str(first_d)[:10] if first_d else None,
            "last_match_date": last_iso,
            "active": active,
        }
    return out


# Fixed time windows for the leaderboards period selector. label -> days
# back from the collection's latest match. "all" (no window) is the base.
# WINDOWS (window → days) comes from common/sql.py, the one definition of the time windows.


# Ball-faced buckets in innings order; the index is the x-axis of the curve.
_INTENT_BUCKETS = ["01_0-5", "02_6-10", "03_11-20", "04_21-30", "05_31-50", "06_51+"]


def _pivot_intent_curve(rows: list[dict]) -> list[dict]:
    """Reshape intent_curve from long (one row per batter*bucket) to one row
    per batter: the 6-point SR curve as an array (for an inline sparkline), an
    `early_sr` scalar to rank by, and totals.

    The raw long form fed the generic 'sort by primary column' leaderboard,
    which (a) duplicated each batter across up to 6 rows, (b) let late-innings
    buckets dominate the top — i.e. ranked plain strike rate once set, not
    intent — and (c) scattered a batter's buckets so the curve was unreadable.
    Ranking by early-phase SR surfaces the part that was buried (who attacks
    from ball one) while the sparkline keeps the full shape visible.
    """
    by_batter: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_batter.setdefault(_row_key(r) or r["batter"], {})[r["ball_bucket"]] = r
    out: list[dict] = []
    for _key, buckets in by_batter.items():
        first = next(iter(buckets.values()))
        curve = [round(buckets[b]["sr"], 1) if b in buckets else None for b in _INTENT_BUCKETS]
        # Early intent = SR over the first 10 balls (buckets 0-5 + 6-10),
        # weighted by balls so it's not a naive mean of two bucket SRs.
        e_runs = sum(int(buckets[b]["runs"]) for b in _INTENT_BUCKETS[:2] if b in buckets)
        e_balls = sum(int(buckets[b]["balls"]) for b in _INTENT_BUCKETS[:2] if b in buckets)
        if e_balls == 0:
            continue  # no early-phase evidence → can't rank fairly
        present = [c for c in curve if c is not None]
        out.append(
            {
                "batter": first["batter"],
                "cricsheet_id": first.get("cricsheet_id"),
                "display_name": first.get("display_name"),
                "early_sr": round(100.0 * e_runs / e_balls, 1),
                "peak_sr": max(present) if present else None,
                "balls": sum(int(v["balls"]) for v in buckets.values()),
                "curve": curve,
            }
        )
    out.sort(key=lambda r: r["early_sr"], reverse=True)
    return out


def _export_leaderboards(
    collection: str,
    out_dir: Path,
    matches: dict[str, int],
    name_tax: dict[str, dict],
    activity: dict[str, dict],
    window: str | None = None,
) -> int:
    """All-time (window=None) or a recomputed time window. Window metrics
    live in data/metrics/<slug>_<collection>_<window>.json (cooked by the
    subprocess pass); the site file gets a `.<window>` suffix."""
    src_col = f"{collection}_{window}" if window else collection
    suffix = f".{window}" if window else ""
    n = 0
    for slug in METRIC_SLUGS:
        src = METRIC_DIR / f"{slug}_{src_col}.json"
        if not src.exists():
            continue
        rows = json.loads(src.read_text())
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        # intent_curve is a per-(batter,bucket) shape, not a per-player
        # ranking — pivot to one row/batter (curve array + early_sr) so it
        # ranks honestly and the table stays one-row-per-player.
        if slug == "intent_curve":
            rows = _pivot_intent_curve(rows)
        # Tag each row with match count (for the min-matches gate; counted inside the window on a
        # windowed board) and the player's identity (cricsheet_id, display name, role, bowling
        # type, country, capped...) so the UI filter bar works per-row without a ball cutoff.
        for r in rows:
            key = _row_key(r)
            r["matches"] = matches.get(key, 0)
            for k, v in (name_tax.get(key) or {}).items():
                if r.get(k) is None:
                    r[k] = v
            for k, v in (activity.get(key) or {}).items():
                r.setdefault(k, v)
        _assert_rows(rows, f"{collection} {slug}{suffix}")
        # Trim each leaderboard to a sane top-N for the browser.
        _write(out_dir / "leaderboards" / f"{slug}{suffix}.json", rows[:300])
        n += 1
    return n


def _build_window_tables(
    con: duckdb.DuckDBPyConnection, collection: str, as_of: str | None
) -> list[str]:
    """Create date-filtered balls_<col>_<win> tables (the last-1y / last-3y windows and every era
    of the league in config/leagues.toml) so the existing metric functions recompute over each.
    `con` must be a read-write connection (call before the read-only export)."""
    import datetime as _dt

    if not as_of:
        return []
    safe = _safe(collection)
    built: list[str] = []
    cutoffs: dict[str, str] = {}
    for win, days in WINDOWS.items():
        try:
            cutoffs[win] = (
                _dt.date.fromisoformat(as_of[:10]) - _dt.timedelta(days=days)
            ).isoformat()
        except ValueError:
            continue
    # the league's eras (config/leagues.toml [[league.era]]): every match since the era began
    for era in leagues.eras(collection):
        cutoffs[era.window] = era.since
    for win, cutoff in cutoffs.items():
        wsafe = f"{safe}_{win}"
        con.execute(
            f"CREATE OR REPLACE TABLE balls_{wsafe} AS "
            f"SELECT * FROM balls_{safe} WHERE match_date >= '{cutoff}'"
        )
        # metric fns also read matches_<safe> — window it too.
        con.execute(
            f"CREATE OR REPLACE TABLE matches_{wsafe} AS "
            f"SELECT * FROM matches_{safe} WHERE match_date >= '{cutoff}'"
        )
        cnt = con.execute(f"SELECT COUNT(*) FROM balls_{wsafe}").fetchone()[0]
        if cnt and cnt > 0:
            built.append(win)
    return built


def _compute_window_metrics(collection: str, win: str) -> None:
    """Run the tested `compute_metrics all` over a window collection (its own
    read-only connection — safe alongside the export's). wicket_quality needs
    a ratings file, so copy the base collection's in first."""
    import subprocess
    import sys

    wcol = f"{collection}_{win}"
    base_r = METRIC_DIR / f"scout_ratings_{collection}.json"
    win_r = METRIC_DIR / f"scout_ratings_{wcol}.json"
    if base_r.exists():
        shutil.copy(base_r, win_r)  # weight window wickets by all-time batter skill
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "compute_metrics.py"), "all", "-c", wcol],
        check=False,
        capture_output=True,
    )


def _export_ratings(collection: str, out_dir: Path, taxonomy: dict[str, dict] | None = None) -> int:
    src = METRIC_DIR / f"scout_ratings_{collection}.json"
    if not src.exists():
        _write(out_dir / "ratings.json", [])
        return 0
    rows = json.loads(src.read_text())
    for r in rows:  # the fan name for head-to-head, which runs in the browser off this file
        rec = (taxonomy or {}).get(r.get("cricsheet_id") or "") or {}
        r["display_name"] = rec.get("display_name") or r.get("unique_name")
    _write(out_dir / "ratings.json", rows)
    return len(rows)


def _with_display(row: dict, name_ident: dict[str, dict]) -> dict:
    """`<key>_display` (and `display_name` for the row's main player) next to every player-name
    column of a records row."""
    main = row.get("cricsheet_id")
    for key in ("batter", "bowler", "name", "fielder", "player"):
        nm = row.get(key)
        if isinstance(nm, str):
            ident = name_ident.get(main or f"{UNRESOLVED}{nm}") or {}
            disp = row.get("display_name") or ident.get("display_name") or nm
            row[f"{key}_display"] = disp
            row["display_name"] = disp
    return row


def _export_records_venues(
    collection: str, out_dir: Path, name_ident: dict[str, dict] | None = None
) -> None:
    """Record leaderboards + venue conditions, pre-computed to JSON."""
    try:
        from cricdex.records import queries as rq

        recs: dict = {}
        keys = getattr(rq, "RECORDS", {})
        for key in keys:
            try:
                df = rq.RECORDS[key](collection, top_n=25)
                rows = df.to_dicts() if hasattr(df, "to_dicts") else df
                recs[key] = [
                    _with_display(r, name_ident or {}) if isinstance(r, dict) else r for r in rows
                ]
            except Exception:  # noqa: BLE001
                recs[key] = []
        _write(out_dir / "records.json", recs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"records export skipped for {collection}: {e}")

    try:
        from cricdex.common.venue_names import aliases_for
        from cricdex.venues import profile as vp

        venue_names = vp.list_venues(collection, min_matches=10)
        names = venue_names["venue"].to_list() if not venue_names.is_empty() else []
        with duckdb.connect(str(vp.DEFAULT_DB_PATH), read_only=True) as con:
            aliases = aliases_for(con)
        venues_out = {}
        # pars move with the era: the last three seasons are the default view, by-season the trend
        recent = vp.recent_seasons(collection, n=3)
        for v in names[:60]:
            try:
                venues_out[v] = {
                    "innings_totals": vp.innings_totals(v, collection).to_dicts(),
                    "innings_totals_recent": vp.innings_totals(
                        v, collection, seasons=recent
                    ).to_dicts(),
                    "recent_seasons": recent,
                    "innings_by_season": vp.innings_by_season(v, collection).to_dicts(),
                    "phase_run_rates": vp.phase_run_rates(v, collection).to_dicts(),
                    "chase_vs_set": vp.chase_vs_set_winrate(v, collection).to_dicts(),
                    # other names the ground has had (spellings, former names) — the venue search matches these
                    "aliases": aliases.get(v, []),
                }
            except Exception:  # noqa: BLE001
                continue
        _write(out_dir / "venues.json", venues_out)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"venues export skipped for {collection}: {e}")


def _tag(rows: list[dict], taxonomy: dict[str, dict]) -> list[dict]:
    """Attach role / bowling type to graph cohort members so the UI can
    filter (e.g. seam-only replacements) and stop pairing a seamer with a
    leg-spinner."""
    for r in rows:
        t = taxonomy.get(r.get("cricsheet_id", ""))
        if t:
            r["display_name"] = t.get("display_name") or r.get("name")
            r["primary_role"] = t.get("primary_role")
            r["bowling_category"] = t.get("bowling_category")
            r["batting_position"] = t.get("batting_position")
            r["country"] = t.get("country")
    return rows


def _export_profiles_and_cohorts(
    collection: str,
    out_dir: Path,
    players: list[dict],
    taxonomy: dict[str, dict],
    activity: dict[str, dict],
    name_ident: dict[str, dict] | None = None,
) -> tuple[int, int]:
    import duckdb

    from cricdex.profiles import builder
    from cricdex.scout import cohort

    # One read-only connection + one ball-volume pass, reused across players
    # so the graph cohort (co_faced) costs ~one query per player. The profile
    # builder shares that connection and reads the metric / ratings JSON and
    # fits the style-twin indexes once per collection (`builder.Sources`).
    sources = builder.Sources(collection)
    try:
        con = duckdb.connect(str(cohort.DEFAULT_DB_PATH), read_only=True)
        # the id-keyed balls once per league, so every per-player query reads a temp table
        materialize_keyed(con, collection)
        vol = cohort.ball_volumes(con, collection)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"cohort connection failed for {collection}: {e}")
        con = None
        vol = {}

    n_prof = n_cohort = 0
    for p in players:
        name = p["name"]
        cid = p["cricsheet_id"]
        try:
            # builder.build already merges Wikidata identity (dob / photo
            # / socials) from the JSON cache by cricsheet_id.
            prof = builder.build(cid, collection, con=con, sources=sources)
            tax = taxonomy.get(cid)
            if tax:
                prof["taxonomy"] = {k: tax.get(k) for k in _TAX_KEEP if tax.get(k) is not None}
            # the identity contract (display name, aliases, capped, role, style, country, team...)
            # style twins: who each one is, and his country (the profile's country filter)
            for key in ("style_twins_batter", "style_twins_bowler"):
                for t in prof.get(key) or []:
                    tk = t.get("cricsheet_id") or f"{UNRESOLVED}{t.get('name')}"
                    ident = (name_ident or {}).get(tk) or {}
                    t["cricsheet_id"] = t.get("cricsheet_id") or ident.get("cricsheet_id")
                    t["display_name"] = ident.get("display_name") or t.get("name")
                    t["country"] = ident.get("country")
            prof["identity"] = player_master.identity_block(tax, fallback_name=name)
            prof["identity"]["scorecard_name"] = name
            for k in (
                "dob",
                "first_international",
                "last_international",
                "squad_status",
                "retired_scope",
                "name_source",
                "role_source",
                "bowling_style_source",
                "country_source",
                "wikipedia_title",
                "wikidata_qid",
            ):
                if tax and tax.get(k) is not None:
                    prof["identity"][k] = tax[k]
            if tax and tax.get("dob"):
                # the profile page reads age from here
                prof.setdefault("wikidata", {})
                prof["wikidata"] = {**(prof["wikidata"] or {}), "dob": tax["dob"]}
            act = activity.get(cid)
            if act:
                prof["activity"] = act
            _write(out_dir / "profiles" / f"{cid}.json", prof)
            n_prof += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"profile failed {name}: {e}")

        # Graph cohort — "faced the same bowlers / bowled to the same batters",
        # computed straight from the ball-by-ball (no Neo4j). co_faced is the
        # only signal any surface renders (the web Player Profile card).
        if con is not None:
            try:
                rows = cohort.co_faced(cid, collection, con=con, vol=vol, top_k=12)
                # Drop any member we can't resolve to a cricsheet_id — the UI
                # links cohort rows by id, so a null-id row is dead weight.
                rows = _tag([r for r in rows if r.get("cricsheet_id")], taxonomy)
                _write(out_dir / "cohorts" / f"{cid}.json", {"co_faced": rows})
                n_cohort += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"cohort failed {name}: {e}")
    if con is not None:
        con.close()
    return n_prof, n_cohort


def _export_matchups(
    collection: str, out_dir: Path, players: list[dict], taxonomy: dict[str, dict]
) -> int:
    """matchups/<cid>.json — per player: as_batter (vs each bowler), as_bowler
    (vs each batter), and the batter's pace/spin splits."""
    from cricdex.metrics import matchups as mm

    pairs = mm.pairwise(collection, min_balls=6)
    # bowler type by registry id (the player master / taxonomy are keyed by id)
    bowler_cat = {
        c: t.get("bowling_category")
        for c, t in taxonomy.items()
        if (t or {}).get("bowling_category") in ("seam", "spin")
    }
    splits = mm.pace_spin_splits(collection, bowler_cat)

    by_batter: dict[str, list[dict]] = {}
    by_bowler: dict[str, list[dict]] = {}
    for r in pairs:
        stats = {k: r[k] for k in ("balls", "runs", "sr", "dot_pct", "outs")}
        by_batter.setdefault(r["batter_key"], []).append(
            {"bowler": r["bowler"], "bowler_id": r["bowler_id"], **stats}
        )
        by_bowler.setdefault(r["bowler_key"], []).append(
            {"batter": r["batter"], "batter_id": r["batter_id"], **stats}
        )
    n = 0
    for p in players:
        cid = p.get("cricsheet_id")
        ab = sorted(by_batter.get(cid, []), key=lambda x: x["balls"], reverse=True)[:40]
        aw = sorted(by_bowler.get(cid, []), key=lambda x: x["balls"], reverse=True)[:40]
        sp = splits.get(cid)
        if not (ab or aw or sp):
            continue
        _write(
            out_dir / "matchups" / f"{cid}.json", {"as_batter": ab, "as_bowler": aw, "splits": sp}
        )
        n += 1
    return n


def _export_phase(
    collection: str,
    out_dir: Path,
    matches: dict[str, int],
    name_tax: dict[str, dict],
    activity: dict[str, dict],
) -> None:
    """phase.json — powerplay/middle/death batter-SR + bowler-economy boards.

    Each row is tagged with match count + the LLM taxonomy (role / bowling
    type / position / country) + activity, exactly like the leaderboards, so the
    UI filter bar works per-row."""
    from cricdex.metrics import phase as ph

    try:
        # Fuller pool (top 150) so the UI filter bar has material to narrow.
        boards = ph.phase_leaders(collection, top=150)
        for board in boards.values():
            for r in (*board.get("batters", []), *board.get("bowlers", [])):
                key = r.pop("key", None) or _row_key(r)
                r["matches"] = matches.get(key, 0)
                for k, v in (name_tax.get(key) or {}).items():
                    if r.get(k) is None:
                        r[k] = v
                for k, v in (activity.get(key) or {}).items():
                    r.setdefault(k, v)
            _assert_rows(
                [*board.get("batters", []), *board.get("bowlers", [])], f"{collection} phase"
            )
        _write(out_dir / "phase.json", boards)
    except DataQualityError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"phase export skipped for {collection}: {e}")


def _export_partnerships(
    con: duckdb.DuckDBPyConnection, collection: str, out_dir: Path, players: list[dict]
) -> int:
    """partnerships.json — batter-pair stands. Aggregates per unordered pair
    across innings: innings, runs (incl. extras while both at the crease), legal
    balls, SR, best single-innings stand, average, fifty/hundred stands. The
    per-player view is derived client-side by filtering pairs containing them."""
    # pairs of player keys (registry ids, resolved per match): namesakes never merge
    materialize_keyed(con, collection)
    kb = keyed_balls(con, collection)
    labels = label_map(con, collection)
    rows = con.execute(
        f"""
        WITH p AS (
            SELECT match_id, innings_idx,
                   LEAST(batter, non_striker) AS a, GREATEST(batter, non_striker) AS b,
                   SUM(runs_total) AS runs,
                   SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls
            FROM {kb}
            WHERE non_striker IS NOT NULL AND batter IS NOT NULL AND {MAIN_INNINGS}
            GROUP BY 1, 2, 3, 4
        )
        SELECT a, b,
               COUNT(*) AS innings,
               SUM(runs) AS runs,
               SUM(balls) AS balls,
               MAX(runs) AS best,
               SUM(CASE WHEN runs >= 50 THEN 1 ELSE 0 END) AS fifties,
               SUM(CASE WHEN runs >= 100 THEN 1 ELSE 0 END) AS hundreds
        FROM p
        GROUP BY a, b
        HAVING SUM(runs) >= 50
        ORDER BY runs DESC, a, b
        """
    ).fetchall()
    disp = {p["cricsheet_id"]: p.get("display_name") for p in players if p.get("cricsheet_id")}

    def _cid(k: str) -> str | None:
        return None if k.startswith(UNRESOLVED) else k

    pairs = [
        {
            "a": name_of_key(a, labels),
            "b": name_of_key(b, labels),
            "a_cid": _cid(a),
            "b_cid": _cid(b),
            "a_display": disp.get(a) or name_of_key(a, labels),
            "b_display": disp.get(b) or name_of_key(b, labels),
            "innings": int(inns),
            "runs": int(runs),
            "balls": int(balls),
            "sr": round(100.0 * runs / balls, 1) if balls else 0.0,
            "best": int(best),
            "avg": round(runs / inns, 1) if inns else 0.0,
            "fifties": int(fifties),
            "hundreds": int(hundreds),
        }
        for a, b, inns, runs, balls, best, fifties, hundreds in rows
    ]
    _write(out_dir / "partnerships.json", {"pairs": pairs})
    return len(pairs)


_BOWLER_WKT = (
    "bowled",
    "caught",
    "lbw",
    "stumped",
    "caught and bowled",
    "hit wicket",
)


def _export_aging(
    con: duckdb.DuckDBPyConnection,
    collection: str,
    out_dir: Path,
    taxonomy: dict[str, dict] | None = None,
) -> int:
    """aging.json — performance vs age. Per (player, season-year) batting + bowling
    stats from the ball-by-ball, joined to age that year via the Wikidata dob, then
    averaged by integer age into a curve (one line per discipline). Dob covers only
    ~a third of players, so the curve is indicative + elite-skewed (flagged in UI).
    Also emits a per-player trajectory (dob-known players) for an optional overlay."""
    dob_by_cid = _dob_by_cid(taxonomy or {})
    # player columns are registry ids, resolved per match (namesakes are two players)
    materialize_keyed(con, collection)
    kb = keyed_balls(con, collection)

    def _age(nm: str, yr: int) -> int | None:
        dob = dob_by_cid.get(nm)
        if not dob:
            return None
        try:
            return yr - int(str(dob)[:4])
        except ValueError:
            return None

    bat = con.execute(
        f"""
        SELECT batter AS nm, EXTRACT(YEAR FROM match_date::DATE)::INT AS yr,
               SUM(runs_batter) AS runs,
               SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
               SUM(CASE WHEN player_out = batter THEN 1 ELSE 0 END) AS outs
        FROM {kb}
        WHERE batter IS NOT NULL AND {MAIN_INNINGS}
        GROUP BY 1, 2
        HAVING balls >= 60
        """
    ).fetchall()
    kinds = "', '".join(_BOWLER_WKT)
    bowl = con.execute(
        f"""
        SELECT bowler AS nm, EXTRACT(YEAR FROM match_date::DATE)::INT AS yr,
               SUM({BOWLER_RUNS}) AS runs,
               SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides'
                         AND extras_type IS DISTINCT FROM 'noballs' THEN 1 ELSE 0 END) AS balls,
               SUM(CASE WHEN player_out IS NOT NULL AND wicket_kind IN ('{kinds}')
                        THEN 1 ELSE 0 END) AS wkts
        FROM {kb}
        WHERE bowler IS NOT NULL AND {MAIN_INNINGS}
        GROUP BY 1, 2
        HAVING balls >= 60
        """
    ).fetchall()

    # bucket by age + per-player trajectory
    bat_age: dict[int, list[tuple[float, float | None]]] = {}
    bowl_age: dict[int, list[tuple[float, float | None]]] = {}
    players: dict[str, dict] = {}
    for nm, yr, runs, balls, outs in bat:
        age = _age(nm, yr)
        if age is None or not (15 <= age <= 45) or not balls:
            continue
        sr = 100.0 * float(runs) / float(balls)
        avg = float(runs) / outs if outs else None
        bat_age.setdefault(age, []).append((sr, avg))
        cid = nm
        if cid:
            players.setdefault(cid, {"batting": [], "bowling": []})["batting"].append(
                {"age": age, "sr": round(sr, 1)}
            )
    for nm, yr, runs, balls, wkts in bowl:
        age = _age(nm, yr)
        if age is None or not (15 <= age <= 45) or not balls:
            continue
        econ = 6.0 * float(runs) / float(balls)
        srate = float(balls) / wkts if wkts else None
        bowl_age.setdefault(age, []).append((econ, srate))
        cid = nm
        if cid:
            players.setdefault(cid, {"batting": [], "bowling": []})["bowling"].append(
                {"age": age, "economy": round(econ, 2)}
            )

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs)

    MIN_N = 3
    batting = [
        {
            "age": age,
            "sr": round(_mean([s for s, _ in rows]), 1),
            "average": round(_mean([a for _, a in rows if a is not None]), 1)
            if any(a is not None for _, a in rows)
            else None,
            "n": len(rows),
        }
        for age, rows in sorted(bat_age.items())
        if len(rows) >= MIN_N
    ]
    bowling = [
        {
            "age": age,
            "economy": round(_mean([e for e, _ in rows]), 2),
            "strike_rate": round(_mean([s for _, s in rows if s is not None]), 1)
            if any(s is not None for _, s in rows)
            else None,
            "n": len(rows),
        }
        for age, rows in sorted(bowl_age.items())
        if len(rows) >= MIN_N
    ]
    # keep only multi-season trajectories (signal): each discipline needs 3+ seasons on its own
    for p in players.values():
        for k in ("batting", "bowling"):
            p[k] = sorted(p[k], key=lambda r: r["age"]) if len(p[k]) >= 3 else []
    players = {cid: p for cid, p in players.items() if p["batting"] or p["bowling"]}
    _write(out_dir / "aging.json", {"batting": batting, "bowling": bowling, "players": players})
    return len(batting) + len(bowling)


def _existing_windows(con: duckdb.DuckDBPyConnection, collection: str) -> list[str]:
    """Windows already built for this league (`--skip-prep`: nothing is rebuilt)."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    safe = _safe(collection)
    return [
        w
        for w in [*WINDOWS, *(e.window for e in leagues.eras(collection))]
        if f"balls_{safe}_{w}" in have and any(METRIC_DIR.glob(f"*_{collection}_{w}.json"))
    ]


def _linked_players(
    out_dir: Path, collection: str, players: list[dict], name_ident: dict[str, dict]
) -> list[dict]:
    """Rows on this league's boards whose player has no players.json row yet (a fielding
    substitute, a name spelled two ways): add them, so every board link resolves to a profile."""
    have = {p["cricsheet_id"] for p in players}
    extra: dict[str, str] = {}

    def see(name: str | None, cid: str | None = None) -> None:
        if name and cid and cid not in have:
            extra.setdefault(cid, name)

    for f in sorted((out_dir / "leaderboards").glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            who = r.get("name") or r.get("batter") or r.get("bowler") or r.get("fielder")
            see(who, r.get("cricsheet_id"))
    phase = out_dir / "phase.json"
    if phase.exists():
        for board in json.loads(phase.read_text(encoding="utf-8")).values():
            for r in (*board.get("batters", []), *board.get("bowlers", [])):
                see(r.get("name"), r.get("cricsheet_id"))
    rows = []
    for cid, name in sorted(extra.items()):
        ident = name_ident.get(cid) or {}
        rows.append(
            {
                "cricsheet_id": cid,
                "name": name,
                "balls_faced": 0,
                "balls_bowled": 0,
                "matches": 0,
                "role": "batter",
                "first_match_date": None,
                "last_match_date": None,
                "active_here": False,
                **player_master.identity_block(ident, fallback_name=name),
            }
        )
    if rows:
        logger.info(
            f"  {collection}: +{len(rows)} players seen only on boards (fielding subs etc.)"
        )
    return rows


@app.command()
def export(
    collection: str | None = typer.Option(
        None, "--collection", "-c", help="One collection; omit for all."
    ),
    min_balls: int = typer.Option(
        0,
        "--min-balls",
        help="Per-player profile/cohort cutoff (faced + bowled); 0 = every player of the league.",
    ),
    clean: bool = typer.Option(False, "--clean", help="Wipe the output folder first."),
    out: Path | None = typer.Option(
        None, "--out", help="Write here instead of site/public/data (e.g. a scratch export)."
    ),
    skip_prep: bool = typer.Option(
        False,
        "--skip-prep",
        help="Don't rebuild the time-window tables or their metrics (no DB writes): use the "
        "ones already built.",
    ),
) -> None:
    """Cook every artifact into site/data/ for the static frontend."""
    global SITE_DATA
    if out is not None:
        SITE_DATA = out
    if clean and SITE_DATA.exists():
        shutil.rmtree(SITE_DATA)
    if collection:
        try:
            leagues.validate_collection(collection)
        except ValueError as e:
            raise typer.BadParameter(str(e), param_hint="--collection") from None
    cols = [collection] if collection else DEFAULT_COLLECTIONS

    # PREP: build window tables (exclusive write) then cook window metrics via
    # subprocess — both before the read-only export connection opens.
    windows_by_col: dict[str, list[str]] = {}
    if skip_prep:
        with duckdb.connect(str(DUCKDB_PATH), read_only=True) as ro:
            for col in cols:
                windows_by_col[col] = _existing_windows(ro, col)
    else:
        prep = duckdb.connect(str(DUCKDB_PATH))  # read-write
        try:
            for col in cols:
                m = _collection_meta(prep, col)
                if m is None:
                    continue
                windows_by_col[col] = _build_window_tables(prep, col, m.get("data_as_of"))
        finally:
            prep.close()
        for col, wins in windows_by_col.items():
            for win in wins:
                logger.info(f"cooking window metrics: {col} / {win}")
                _compute_window_metrics(col, win)

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    taxonomy = _load_taxonomy()
    logger.info(f"identity: {len(taxonomy)} players (player master or LLM taxonomy)")
    index: list[dict] = []
    try:
        newest = _newest_match(con)
        for col in cols:
            meta = _collection_meta(con, col)
            if meta is None:
                logger.warning(f"no balls table for {col} — skipping")
                continue
            out_dir = SITE_DATA / col
            # keyed (registry-id) balls/wickets as temp tables once per league: every query below
            # reads them, and inlining the keyed relation several times in one statement trips a
            # DuckDB internal error
            materialize_keyed(con, col)
            name_tax = _name_identity(con, col, taxonomy)
            activity = _activity_map(con, col, meta.get("data_as_of"))
            players = _players(con, col, min_balls, taxonomy, activity)
            meta["windows"] = windows_by_col.get(col, [])
            # labels for the period selector: the time windows plus the league's eras
            meta["window_labels"] = {
                w: lbl for w, lbl in leagues.window_labels(col).items() if w in meta["windows"]
            }
            # the league's data stops long before the newest data anywhere (SMAT): flag it
            meta["stale"] = _is_stale(meta.get("data_as_of"), newest)
            meta["newest_data_anywhere"] = newest
            if col == AUCTION_TARGET:
                _export_retentions(players, out_dir)
                n_pool = _export_auction_pool(con, out_dir, taxonomy, _current_teams(con, col))
                n_scout = _export_scout_index(con, out_dir, taxonomy)
                logger.info(f"  auction_pool: {n_pool}, scout_index: {n_scout}")
            match_counts = _match_counts(con, col)
            n_lb = _export_leaderboards(col, out_dir, match_counts, name_tax, activity)
            for win in windows_by_col.get(col, []):
                # matches counted inside the window, so a min-matches gate means what it says
                win_counts = _match_counts(con, f"{col}_{win}")
                _export_leaderboards(col, out_dir, win_counts, name_tax, activity, window=win)
            n_rat = _export_ratings(col, out_dir, taxonomy)
            _export_records_venues(col, out_dir, name_tax)
            _export_phase(col, out_dir, match_counts, name_tax, activity)
            players += _linked_players(out_dir, col, players, name_tax)
            _assert_players(players, f"{col} players.json", meta.get("data_as_of"))
            meta["n_players"] = len(players)
            meta["n_active"] = sum(1 for p in players if p.get("active"))
            _write(out_dir / "meta.json", meta)
            _write(out_dir / "players.json", players)
            n_match = _export_matchups(col, out_dir, players, taxonomy)
            _export_partnerships(con, col, out_dir, players)
            _export_aging(con, col, out_dir, taxonomy)
            n_prof, n_cohort = _export_profiles_and_cohorts(
                col, out_dir, players, taxonomy, activity, name_tax
            )
            if n_prof < len(players):
                raise DataQualityError(
                    f"{col}: {len(players) - n_prof} of {len(players)} profiles failed to build"
                )
            # per-player files of players no longer in this league would linger forever otherwise
            _prune_player_files(
                out_dir, {p["cricsheet_id"] for p in players if p.get("cricsheet_id")}
            )
            logger.info(
                f"{col}: as_of={meta['data_as_of']} players={len(players)} "
                f"leaderboards={n_lb} ratings={n_rat} profiles={n_prof} "
                f"cohorts={n_cohort} matchups={n_match}"
            )
            index.append(meta)
    finally:
        con.close()

    # Merge into any existing index so a single-collection run (-c ipl)
    # doesn't drop the other collections from the dropdown. Preserve the
    # canonical order; refreshed entries win.
    existing: dict[str, dict] = {}
    idx_path = SITE_DATA / "collections.json"
    if idx_path.exists():
        try:
            for e in json.loads(idx_path.read_text()):
                existing[e["collection"]] = e
        except Exception:  # noqa: BLE001
            pass
    for e in index:
        existing[e["collection"]] = e
    # registry order; a league no longer in the registry drops out of the dropdown
    known = leagues.keys()
    ordered = [existing[c] for c in known if c in existing]
    dropped = sorted(c for c in existing if c not in known)
    if dropped:
        logger.warning(f"collections.json: dropping {dropped} (not in config/leagues.toml)")
    _write(idx_path, ordered)
    # the registry itself: labels, tiers, discounts and pools for the web app
    _write(SITE_DATA / "leagues.json", leagues.site_payload())
    logger.info(
        f"wrote site/data/ for {len(index)} collections; index has {len(ordered)} → {SITE_DATA}"
    )


if __name__ == "__main__":
    app()
