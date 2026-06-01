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


def _players(con: duckdb.DuckDBPyConnection, collection: str, min_balls: int) -> list[dict]:
    """Players who cleared the ball cutoff (faced or bowled), with the
    cross-source ids needed for profile/cohort file lookups."""
    safe = _safe(collection)
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
        out.append(
            {
                "cricsheet_id": cid,
                "name": name,
                "full_name": full or name,
                "balls_faced": int(bf or 0),
                "balls_bowled": int(bb or 0),
                "matches": int(matches or 0),
                "role": "bowler" if (bb or 0) > (bf or 0) else "batter",
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


def _export_leaderboards(collection: str, out_dir: Path, matches: dict[str, int]) -> int:
    n = 0
    for slug in METRIC_SLUGS:
        src = METRIC_DIR / f"{slug}_{collection}.json"
        if not src.exists():
            continue
        rows = json.loads(src.read_text())
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        # Tag each row with the player's match count so the UI can apply a
        # configurable min-matches filter (keeps 1-match flukes off the top).
        for r in rows:
            who = r.get("name") or r.get("batter") or r.get("bowler")
            r["matches"] = matches.get(who, 0)
        # Trim each leaderboard to a sane top-N for the browser.
        _write(out_dir / "leaderboards" / f"{slug}.json", rows[:300])
        n += 1
    return n


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


def _export_profiles_and_cohorts(
    collection: str, out_dir: Path, players: list[dict]
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
            _write(out_dir / "profiles" / f"{cid}.json", prof)
            n_prof += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"profile failed {name}: {e}")

        if graph_ok:
            try:
                cohort = {
                    "co_faced": similar.co_faced_bowlers(name, top_k=12, collection=collection),
                    "teammates": similar.teammate_overlap(name, top_k=12, collection=collection),
                    "find_replacement": similar.find_replacement(
                        name, top_k=12, collection=collection
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

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    index: list[dict] = []
    try:
        for col in cols:
            meta = _collection_meta(con, col)
            if meta is None:
                logger.warning(f"no balls table for {col} — skipping")
                continue
            out_dir = SITE_DATA / col
            players = _players(con, col, min_balls)
            meta["n_players"] = len(players)
            _write(out_dir / "meta.json", meta)
            _write(out_dir / "players.json", players)
            match_counts = _match_counts(con, col)
            n_lb = _export_leaderboards(col, out_dir, match_counts)
            n_rat = _export_ratings(col, out_dir)
            _export_records_venues(col, out_dir)
            n_prof, n_cohort = _export_profiles_and_cohorts(col, out_dir, players)
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
