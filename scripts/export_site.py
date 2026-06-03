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
        cohorts/<cricsheet_id>.json    co_faced / teammates / find_replacement
    site/data/collections.json         index: [{collection, data_as_of, ...}]

`data_as_of` is the max match_date actually in the collection — the
real "data up to" date the UI shows, not the build time.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import typer
from loguru import logger

from cricdex.config import DATA_DIR

app = typer.Typer(add_completion=False)

ROOT = Path(__file__).resolve().parent.parent
SITE_DATA = ROOT / "site" / "public" / "data"
METRIC_DIR = DATA_DIR / "metrics"
DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
# Gemini-built taxonomy (role / bowling type / batting position / country),
# keyed by cricsheet_id. See scripts/enrich_taxonomy.py.
TAXONOMY_PATH = DATA_DIR / "curated" / "player_taxonomy.json"

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
    if not TAXONOMY_PATH.exists():
        return {}
    raw = json.loads(TAXONOMY_PATH.read_text())
    return {cid: _clean_tax(rec) for cid, rec in raw.items() if isinstance(rec, dict)}


def _taxonomy_by_name() -> dict[str, dict]:
    """unique_name -> taxonomy, for tagging leaderboard rows (which key on
    the Cricsheet short name, not cricsheet_id)."""
    if not TAXONOMY_PATH.exists():
        return {}
    raw = json.loads(TAXONOMY_PATH.read_text())
    out: dict[str, dict] = {}
    for rec in raw.values():
        nm = rec.get("name") if isinstance(rec, dict) else None
        if nm:
            out[nm] = _clean_tax(rec)
    return out


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
]

DEFAULT_COLLECTIONS = [
    "ipl",
    "bbl",
    "t20s_male",
    "indian_domestic_male",
    "recently_played_30_male",
]


def _json_default(o):
    """DuckDB hands back Decimal + date/datetime that json can't encode."""
    import datetime as _dt
    from decimal import Decimal

    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, _dt.date | _dt.datetime):
        return o.isoformat()
    return str(o)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Trailing newline so the repo's end-of-file-fixer pre-commit hook
    # leaves the snapshot untouched (and CI-committed data matches).
    path.write_text(json.dumps(obj, separators=(",", ":"), default=_json_default) + "\n")


def _safe(collection: str) -> str:
    return collection.replace("-", "_")


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


def _export_retentions(players: list[dict], out_dir: Path) -> None:
    """Resolve the real 2025 mega retentions to cricsheet_ids and write
    ipl/retentions.json. Names matched on name / full_name (case-insensitive)."""
    by_name: dict[str, dict] = {}
    for p in players:
        by_name.setdefault(p["name"].lower(), p)
        if p.get("full_name"):
            by_name.setdefault(p["full_name"].lower(), p)
    mega: dict[str, list[dict]] = {}
    missing: list[str] = []
    for team, entries in MEGA_RETENTIONS_2025.items():
        rows = []
        for name, price in entries:
            p = by_name.get(name.lower())
            if p:
                rows.append({"cricsheet_id": p["cricsheet_id"], "name": p["name"], "price": price})
            else:
                missing.append(f"{team}:{name}")
        mega[team] = rows
    if missing:
        logger.info(f"retentions unmatched (below cutoff): {missing}")
    _write(out_dir / "retentions.json", {"mega": mega})


def _current_teams(con: duckdb.DuckDBPyConnection, collection: str) -> dict[str, str]:
    """unique_name -> current franchise code, from the team in each
    player's most-recent match. Only meaningful for IPL (the 10 franchises);
    other collections return {} since the codes don't map."""
    if collection != "ipl":
        return {}
    safe = _safe(collection)
    rows = con.execute(
        f"""
        WITH app AS (
            SELECT batter AS name, batting_team AS team, match_date FROM balls_{safe}
                WHERE batting_team IS NOT NULL
            UNION ALL
            SELECT bowler, bowling_team, match_date FROM balls_{safe}
                WHERE bowling_team IS NOT NULL
        ),
        ranked AS (
            SELECT name, team,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY match_date DESC) AS rk
            FROM app
        )
        SELECT name, team FROM ranked WHERE rk = 1
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
    """Players who cleared the ball cutoff (faced or bowled), with the
    cross-source ids needed for profile/cohort file lookups."""
    safe = _safe(collection)
    teams = _current_teams(con, collection)
    rows = con.execute(
        f"""
        WITH bats AS (
            SELECT p.identifier AS cid, p.unique_name AS name,
                   COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides')) AS bf
            FROM balls_{safe} b JOIN people p ON p.unique_name = b.batter
            GROUP BY 1, 2
        ),
        bowls AS (
            SELECT p.identifier AS cid,
                   COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides')) AS bb
            FROM balls_{safe} b JOIN people p ON p.unique_name = b.bowler
            GROUP BY 1
        ),
        -- matches a player appeared in, whether batting or bowling
        appeared AS (
            SELECT p.identifier AS cid, b.match_id FROM balls_{safe} b
                JOIN people p ON p.unique_name = b.batter
            UNION
            SELECT p.identifier AS cid, b.match_id FROM balls_{safe} b
                JOIN people p ON p.unique_name = b.bowler
        ),
        mt AS (
            SELECT cid, COUNT(DISTINCT match_id) AS matches FROM appeared GROUP BY 1
        )
        SELECT COALESCE(bats.cid, bowls.cid) AS cid,
               bats.name AS name,
               COALESCE(bats.bf, 0) AS balls_faced,
               COALESCE(bowls.bb, 0) AS balls_bowled,
               COALESCE(mt.matches, 0) AS matches
        FROM bats FULL OUTER JOIN bowls ON bats.cid = bowls.cid
             LEFT JOIN mt ON mt.cid = COALESCE(bats.cid, bowls.cid)
        """
    ).fetchall()
    # Full display names (Wikidata label) so search matches "Manish"
    # not just the Cricsheet short form "MK Pandey".
    from cricdex.profiles import builder

    wiki = builder._wikidata_cache()
    out = []
    for cid, name, bf, bb, matches in rows:
        if cid is None or name is None:
            continue
        if (bf or 0) + (bb or 0) < min_balls:
            continue
        full = (wiki.get(cid) or {}).get("label")
        tax = taxonomy.get(cid, {})
        act = activity.get(name, {})
        out.append(
            {
                "cricsheet_id": cid,
                "name": name,
                "full_name": full or name,
                "balls_faced": int(bf or 0),
                "balls_bowled": int(bb or 0),
                "matches": int(matches or 0),
                "role": "bowler" if (bb or 0) > (bf or 0) else "batter",
                # Gemini taxonomy (None if not yet enriched) — powers filters.
                "primary_role": tax.get("primary_role"),
                "bowling_category": tax.get("bowling_category"),
                "batting_position": tax.get("batting_position"),
                "country": tax.get("country"),
                # data-driven activity (per collection = per format)
                "first_match_date": act.get("first_match_date"),
                "last_match_date": act.get("last_match_date"),
                "active": act.get("active", False),
                # current IPL franchise (None = free agent / non-IPL collection)
                "team": teams.get(name),
            }
        )
    out.sort(key=lambda r: r["balls_faced"] + r["balls_bowled"], reverse=True)
    return out


def _match_counts(con: duckdb.DuckDBPyConnection, collection: str) -> dict[str, int]:
    """unique_name -> matches played (batting or bowling), ALL players (no
    ball cutoff) so leaderboard rows can be filtered by a min-matches gate."""
    safe = _safe(collection)
    rows = con.execute(
        f"""
        WITH appeared AS (
            SELECT batter AS name, match_id FROM balls_{safe}
            UNION
            SELECT bowler AS name, match_id FROM balls_{safe}
        )
        SELECT name, COUNT(DISTINCT match_id) AS m FROM appeared
        WHERE name IS NOT NULL GROUP BY 1
        """
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _activity_map(
    con: duckdb.DuckDBPyConnection, collection: str, as_of: str | None
) -> dict[str, dict]:
    """unique_name -> {first_match_date, last_match_date, active}. 'active'
    = appeared within 18 months of the collection's latest match (so it's
    per-collection = per-format; a player retired from internationals can
    still be active in IPL). Data-driven, no model needed."""
    import datetime as _dt

    safe = _safe(collection)
    rows = con.execute(
        f"""
        SELECT name, MIN(match_date) AS first_d, MAX(match_date) AS last_d FROM (
            SELECT batter AS name, match_date FROM balls_{safe}
            UNION ALL SELECT bowler AS name, match_date FROM balls_{safe}
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
WINDOWS: dict[str, int] = {"last3y": 1095, "last1y": 365}


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
        # Tag each row with match count (for the min-matches gate) and the
        # Gemini taxonomy (role / bowling type / country / position) so the
        # UI filter bar works per-row without a ball cutoff.
        for r in rows:
            who = r.get("name") or r.get("batter") or r.get("bowler")
            r["matches"] = matches.get(who, 0)
            for k, v in (name_tax.get(who) or {}).items():
                r.setdefault(k, v)
            for k, v in (activity.get(who) or {}).items():
                r.setdefault(k, v)
        # Trim each leaderboard to a sane top-N for the browser.
        _write(out_dir / "leaderboards" / f"{slug}{suffix}.json", rows[:300])
        n += 1
    return n


def _build_window_tables(
    con: duckdb.DuckDBPyConnection, collection: str, as_of: str | None
) -> list[str]:
    """Create date-filtered balls_<col>_<win> tables so the existing metric
    functions (which query balls_<safe> by name) recompute over each window.
    `con` must be a read-write connection (call before the read-only export)."""
    import datetime as _dt

    if not as_of:
        return []
    safe = _safe(collection)
    built: list[str] = []
    for win, days in WINDOWS.items():
        try:
            cutoff = (_dt.date.fromisoformat(as_of[:10]) - _dt.timedelta(days=days)).isoformat()
        except ValueError:
            continue
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


def _export_ratings(collection: str, out_dir: Path) -> int:
    src = METRIC_DIR / f"scout_ratings_{collection}.json"
    if not src.exists():
        _write(out_dir / "ratings.json", [])
        return 0
    rows = json.loads(src.read_text())
    _write(out_dir / "ratings.json", rows)
    return len(rows)


def _export_records_venues(collection: str, out_dir: Path) -> None:
    """Record leaderboards + venue conditions, pre-computed to JSON."""
    try:
        from cricdex.records import queries as rq

        recs: dict = {}
        keys = getattr(rq, "RECORDS", {})
        for key in keys:
            try:
                df = rq.RECORDS[key](collection, top_n=25)
                recs[key] = df.to_dicts() if hasattr(df, "to_dicts") else df
            except Exception:  # noqa: BLE001
                recs[key] = []
        _write(out_dir / "records.json", recs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"records export skipped for {collection}: {e}")

    try:
        from cricdex.venues import profile as vp

        venue_names = vp.list_venues(collection, min_matches=10)
        names = venue_names["venue"].to_list() if not venue_names.is_empty() else []
        venues_out = {}
        for v in names[:60]:
            try:
                venues_out[v] = {
                    "innings_totals": vp.innings_totals(v, collection).to_dicts(),
                    "phase_run_rates": vp.phase_run_rates(v, collection).to_dicts(),
                    "chase_vs_set": vp.chase_vs_set_winrate(v, collection).to_dicts(),
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
            r["primary_role"] = t.get("primary_role")
            r["bowling_category"] = t.get("bowling_category")
            r["batting_position"] = t.get("batting_position")
    return rows


def _export_profiles_and_cohorts(
    collection: str,
    out_dir: Path,
    players: list[dict],
    taxonomy: dict[str, dict],
    activity: dict[str, dict],
) -> tuple[int, int]:
    from cricdex.profiles import builder

    try:
        from cricdex.scout.graph import similar

        graph_ok = True
    except ImportError:
        graph_ok = False

    n_prof = n_cohort = 0
    for p in players:
        name = p["name"]
        cid = p["cricsheet_id"]
        try:
            # builder.build already merges Wikidata identity (dob / photo
            # / socials) from the JSON cache by cricsheet_id.
            prof = builder.build(name, collection)
            tax = taxonomy.get(cid)
            if tax:
                prof["taxonomy"] = tax
            act = activity.get(name)
            if act:
                prof["activity"] = act
            _write(out_dir / "profiles" / f"{cid}.json", prof)
            n_prof += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"profile failed {name}: {e}")

        if graph_ok:
            try:
                cohort = {
                    "co_faced": _tag(
                        similar.co_faced_bowlers(name, top_k=12, collection=collection), taxonomy
                    ),
                    "teammates": _tag(
                        similar.teammate_overlap(name, top_k=12, collection=collection), taxonomy
                    ),
                    "find_replacement": _tag(
                        similar.find_replacement(name, top_k=12, collection=collection), taxonomy
                    ),
                }
                _write(out_dir / "cohorts" / f"{cid}.json", cohort)
                n_cohort += 1
            except Exception:  # noqa: BLE001
                pass
    return n_prof, n_cohort


@app.command()
def export(
    collection: str | None = typer.Option(
        None, "--collection", "-c", help="One collection; omit for all."
    ),
    min_balls: int = typer.Option(
        300, "--min-balls", help="Per-player profile/cohort cutoff (faced + bowled)."
    ),
    clean: bool = typer.Option(False, "--clean", help="Wipe site/data first."),
) -> None:
    """Cook every artifact into site/data/ for the static frontend."""
    if clean and SITE_DATA.exists():
        shutil.rmtree(SITE_DATA)
    cols = [collection] if collection else DEFAULT_COLLECTIONS

    # PREP: build window tables (exclusive write) then cook window metrics via
    # subprocess — both before the read-only export connection opens.
    windows_by_col: dict[str, list[str]] = {}
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
    name_tax = _taxonomy_by_name()
    logger.info(f"taxonomy: {len(taxonomy)} players enriched (role / bowling type / country)")
    index: list[dict] = []
    try:
        for col in cols:
            meta = _collection_meta(con, col)
            if meta is None:
                logger.warning(f"no balls table for {col} — skipping")
                continue
            out_dir = SITE_DATA / col
            activity = _activity_map(con, col, meta.get("data_as_of"))
            players = _players(con, col, min_balls, taxonomy, activity)
            meta["n_players"] = len(players)
            meta["n_active"] = sum(1 for p in players if p.get("active"))
            meta["windows"] = windows_by_col.get(col, [])
            _write(out_dir / "meta.json", meta)
            _write(out_dir / "players.json", players)
            if col == "ipl":
                _export_retentions(players, out_dir)
            match_counts = _match_counts(con, col)
            n_lb = _export_leaderboards(col, out_dir, match_counts, name_tax, activity)
            for win in windows_by_col.get(col, []):
                _export_leaderboards(col, out_dir, match_counts, name_tax, activity, window=win)
            n_rat = _export_ratings(col, out_dir)
            _export_records_venues(col, out_dir)
            n_prof, n_cohort = _export_profiles_and_cohorts(
                col, out_dir, players, taxonomy, activity
            )
            logger.info(
                f"{col}: as_of={meta['data_as_of']} players={len(players)} "
                f"leaderboards={n_lb} ratings={n_rat} profiles={n_prof} cohorts={n_cohort}"
            )
            index.append(meta)
    finally:
        con.close()

    _write(SITE_DATA / "collections.json", index)
    logger.info(f"wrote site/data/ for {len(index)} collections → {SITE_DATA}")


if __name__ == "__main__":
    app()
