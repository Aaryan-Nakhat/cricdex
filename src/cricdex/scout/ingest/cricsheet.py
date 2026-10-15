"""Cricsheet downloader + parser.

Pulls JSON match archives from https://cricsheet.org/downloads/, extracts
per-match files, flattens into tables, writes Parquet:

- `matches_<col>` / `balls_<col>` — one row per match / delivery (a delivery keeps only its first wicket)
- `players_<col>` — each match's `info.registry.people`: scorecard name → Cricsheet identifier
- `wickets_<col>` — every wicket on every delivery (a delivery can have two)
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import NamedTuple

import duckdb
import httpx
import polars as pl
from loguru import logger
from tqdm import tqdm

from cricdex.common.sql import table_suffix

CRICSHEET_BASE = "https://cricsheet.org/downloads"

# 38 Indian state teams whose Cricsheet zip files together cover every
# Ranji Trophy, Vijay Hazare, and Syed Mushtaq Ali match that Cricsheet
# tracks. Each match is in multiple state-team zips (one per side), so the
# aggregator must de-dup by file name (= cricsheet match_id).
INDIAN_STATE_TEAMS: list[str] = [
    "andhra_male_json.zip",
    "arunachal_pradesh_male_json.zip",
    "assam_male_json.zip",
    "baroda_male_json.zip",
    "bengal_male_json.zip",
    "bihar_male_json.zip",
    "chandigarh_male_json.zip",
    "chhattisgarh_male_json.zip",
    "delhi_male_json.zip",
    "goa_male_json.zip",
    "gujarat_male_json.zip",
    "haryana_male_json.zip",
    "himachal_pradesh_male_json.zip",
    "hyderabad_(india)_male_json.zip",
    "jammu_and_kashmir_male_json.zip",
    "jharkhand_male_json.zip",
    "karnataka_male_json.zip",
    "kerala_male_json.zip",
    "madhya_pradesh_male_json.zip",
    "maharashtra_male_json.zip",
    "manipur_male_json.zip",
    "meghalaya_male_json.zip",
    "mizoram_male_json.zip",
    "mumbai_male_json.zip",
    "nagaland_male_json.zip",
    "odisha_male_json.zip",
    "puducherry_male_json.zip",
    "punjab_(india)_male_json.zip",
    "railways_male_json.zip",
    "rajasthan_male_json.zip",
    "saurashtra_male_json.zip",
    "services_male_json.zip",
    "sikkim_male_json.zip",
    "tamil_nadu_male_json.zip",
    "tripura_male_json.zip",
    "uttarakhand_male_json.zip",
    "uttar_pradesh_male_json.zip",
    "vidarbha_male_json.zip",
]

COLLECTIONS: dict[str, str] = {
    "recently_played_30_male": "recently_played_30_male_json.zip",
    "recently_played_30_female": "recently_played_30_female_json.zip",
    "all": "all_json.zip",
    "ipl": "ipl_json.zip",
    "wpl": "wpl_json.zip",
    "bbl": "bbl_male_json.zip",
    "wbbl": "wbbl_female_json.zip",
    "hundred_male": "hundred_male_json.zip",
    "hundred_female": "hundred_female_json.zip",
    "lpl": "lpl_male_json.zip",
    "cpl": "cpl_male_json.zip",
    "sa20": "sat_json.zip",  # Cricsheet codes SA20 as "sat"
    "blast": "ntb_male_json.zip",  # T20 Blast (Cricsheet codes it "ntb")
    "ilt20": "ilt20_male_json.zip",
    "mlc": "mlc_male_json.zip",
    "t20s_male": "t20s_male_json.zip",
    "t20s_female": "t20s_female_json.zip",
    "tests_male": "tests_male_json.zip",
    "tests_female": "tests_female_json.zip",
    "odis_male": "odis_male_json.zip",
    "odis_female": "odis_female_json.zip",
}


def _fetch(url: str, dest: Path, timeout: float = 300.0, headers: dict | None = None) -> None:
    """Download to `<dest>.part`, then rename — an interrupted download never looks like a finished file."""
    tmp = dest.with_name(dest.name + ".part")
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True, headers=headers) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
                    bar.update(len(chunk))
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def download(collection: str, dest: Path, force: bool = False) -> Path:
    if collection not in COLLECTIONS:
        raise ValueError(f"unknown collection '{collection}'. options: {sorted(COLLECTIONS)}")
    dest.mkdir(parents=True, exist_ok=True)
    zip_name = COLLECTIONS[collection]
    zip_path = dest / zip_name
    url = f"{CRICSHEET_BASE}/{zip_name}"

    if zip_path.exists() and not force:
        logger.info(f"cached: {zip_path}")
        return zip_path

    logger.info(f"downloading {url}")
    _fetch(url, zip_path)
    return zip_path


def extract(zip_path: Path, dest: Path, force: bool = False) -> Path:
    out_dir = dest / zip_path.stem
    fresh = out_dir.exists() and any(out_dir.iterdir())
    # Re-extract when forced OR when the downloaded zip is newer than what we
    # last extracted — otherwise a refreshed Cricsheet zip is silently ignored
    # and we keep parsing the stale match set (this is what stalled the scheduled
    # refresh). A stem-name match alone is not enough; compare mtimes.
    if fresh and not force and zip_path.stat().st_mtime <= out_dir.stat().st_mtime:
        logger.info(f"already extracted (up to date): {out_dir}")
        return out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    logger.info(f"extracted to {out_dir}")
    return out_dir


MULTI_DAY_MATCH_TYPES = frozenset({"Test", "MDM"})


def _phase(over: int, total_overs: int | None, match_type: str | None = None) -> str:
    if match_type in MULTI_DAY_MATCH_TYPES:
        return "test"
    n = total_overs or 50
    if n <= 20:
        if over < 6:
            return "powerplay"
        if over >= n - 4:
            return "death"
        return "middle"
    if over < 10:
        return "powerplay"
    if over >= n - 10:
        return "death"
    return "middle"


PLAYERS_SCHEMA = {"match_id": pl.String, "name": pl.String, "identifier": pl.String}
WICKETS_SCHEMA = {
    "match_id": pl.String,
    "innings_idx": pl.Int64,
    "over": pl.Int64,
    "ball_in_over": pl.Int64,
    "ball_id": pl.String,
    "player_out": pl.String,
    "wicket_kind": pl.String,
    "fielders": pl.List(pl.String),
}


class ParsedMatch(NamedTuple):
    match: dict
    balls: list[dict]
    players: list[dict]
    wickets: list[dict]


class ParsedCollection(NamedTuple):
    matches: pl.DataFrame
    balls: pl.DataFrame
    players: pl.DataFrame
    wickets: pl.DataFrame


def _registry_rows(match_id: str, info: dict) -> list[dict]:
    people = (info.get("registry") or {}).get("people") or {}
    return [
        {"match_id": match_id, "name": name, "identifier": ident}
        for name, ident in people.items()
        if name and ident
    ]


def _wicket_rows(match_id: str, data: dict) -> list[dict]:
    """Every wicket on every delivery, with the same ball_id as the balls table."""
    rows: list[dict] = []
    for innings_idx, innings in enumerate(data.get("innings") or []):
        for over_block in innings.get("overs") or []:
            over = over_block.get("over", 0)
            for ball_idx, d in enumerate(over_block.get("deliveries") or [], start=1):
                for w in d.get("wickets") or []:
                    rows.append(
                        {
                            "match_id": match_id,
                            "innings_idx": innings_idx,
                            "over": over,
                            "ball_in_over": ball_idx,
                            "ball_id": f"{match_id}::{innings_idx}::{over}::{ball_idx}",
                            "player_out": w.get("player_out"),
                            "wicket_kind": w.get("kind"),
                            "fielders": [
                                f.get("name") for f in (w.get("fielders") or []) if f.get("name")
                            ],
                        }
                    )
    return rows


def parse_match(path: Path) -> tuple[dict, list[dict]]:
    """(match row, ball rows) — `parse_match_full` also returns the registry and wicket rows."""
    full = parse_match_full(path)
    return full.match, full.balls


def parse_match_full(path: Path) -> ParsedMatch:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    info = data.get("info", {}) or {}
    match_id = path.stem
    dates = info.get("dates") or []
    match_date = dates[0] if dates else None
    match_type = info.get("match_type")
    event = info.get("event") or {}
    event_name = event.get("name")
    venue = info.get("venue")
    city = info.get("city")
    teams = info.get("teams") or []
    overs_per_innings = info.get("overs")
    outcome = info.get("outcome") or {}
    by = outcome.get("by") or {}
    toss = info.get("toss") or {}

    match_row = {
        "match_id": match_id,
        "match_date": match_date,
        "match_type": match_type,
        "event_name": event_name,
        "league": event_name,
        "venue": venue,
        "city": city,
        "team_home": teams[0] if teams else None,
        "team_away": teams[1] if len(teams) > 1 else None,
        "overs": overs_per_innings,
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "outcome_winner": outcome.get("winner"),
        "outcome_by_runs": by.get("runs"),
        "outcome_by_wickets": by.get("wickets"),
        "result": outcome.get("result"),
    }

    ball_rows: list[dict] = []
    for innings_idx, innings in enumerate(data.get("innings") or []):
        batting_team = innings.get("team")
        bowling_team = next((t for t in teams if t != batting_team), None)
        for over_block in innings.get("overs") or []:
            over = over_block.get("over", 0)
            phase = _phase(over, overs_per_innings, match_type)
            for ball_idx, d in enumerate(over_block.get("deliveries") or [], start=1):
                runs = d.get("runs") or {}
                extras = d.get("extras") or {}
                extras_type = next(iter(extras.keys())) if extras else None
                wickets = d.get("wickets") or []
                wicket = wickets[0] if wickets else {}
                fielders = [f.get("name") for f in (wicket.get("fielders") or []) if f.get("name")]
                ball_rows.append(
                    {
                        "ball_id": f"{match_id}::{innings_idx}::{over}::{ball_idx}",
                        "match_id": match_id,
                        "match_date": match_date,
                        "match_type": match_type,
                        "league": event_name,
                        "venue": venue,
                        "innings_idx": innings_idx,
                        "batting_team": batting_team,
                        "bowling_team": bowling_team,
                        "over": over,
                        "ball_in_over": ball_idx,
                        "phase": phase,
                        "batter": d.get("batter"),
                        "non_striker": d.get("non_striker"),
                        "bowler": d.get("bowler"),
                        "runs_batter": runs.get("batter", 0),
                        "runs_extras": runs.get("extras", 0),
                        "runs_total": runs.get("total", 0),
                        "extras_type": extras_type,
                        "wicket_kind": wicket.get("kind"),
                        "player_out": wicket.get("player_out"),
                        "fielders": fielders,
                    }
                )
    return ParsedMatch(
        match_row, ball_rows, _registry_rows(match_id, info), _wicket_rows(match_id, data)
    )


def parse_collection(extracted_dir: Path) -> ParsedCollection:
    files = sorted(extracted_dir.glob("*.json"))
    match_rows: list[dict] = []
    ball_rows: list[dict] = []
    player_rows: list[dict] = []
    wicket_rows: list[dict] = []
    skipped: list[str] = []
    for fp in tqdm(files, desc="parsing matches"):
        try:
            parsed = parse_match_full(fp)
        except Exception as e:
            logger.warning(f"skip {fp.name}: {e}")
            skipped.append(fp.name)
            continue
        match_rows.append(parsed.match)
        ball_rows.extend(parsed.balls)
        player_rows.extend(parsed.players)
        wicket_rows.extend(parsed.wickets)
    if skipped:
        # Say how many matches were lost, so a bad parse can't silently shrink a collection.
        logger.warning(
            f"{len(skipped)} of {len(files)} match files could not be parsed: {', '.join(skipped[:20])}"
        )
        if len(skipped) > max(5, len(files) // 20):
            raise RuntimeError(
                f"{len(skipped)} of {len(files)} match files failed to parse — stopping"
            )
    # infer_schema_length=None forces polars to scan every row when
    # guessing column dtypes. Necessary for heterogeneous collections like
    # the indian-domestic merge where early rows can have NULL city and
    # later rows pull in proper city names (e.g. "Jaipur"), which the
    # default 100-row inference misclassifies.
    return ParsedCollection(
        pl.DataFrame(match_rows, infer_schema_length=None),
        pl.DataFrame(ball_rows, infer_schema_length=None),
        pl.DataFrame(player_rows, schema=PLAYERS_SCHEMA),
        pl.DataFrame(wicket_rows, schema=WICKETS_SCHEMA),
    )


def parse_identity(extracted_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(players, wickets) only — reads the match JSON but skips building the far bigger ball rows."""
    player_rows: list[dict] = []
    wicket_rows: list[dict] = []
    for fp in tqdm(sorted(extracted_dir.glob("*.json")), desc="reading registries"):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"skip {fp.name}: {e}")
            continue
        player_rows.extend(_registry_rows(fp.stem, data.get("info") or {}))
        wicket_rows.extend(_wicket_rows(fp.stem, data))
    return (
        pl.DataFrame(player_rows, schema=PLAYERS_SCHEMA),
        pl.DataFrame(wicket_rows, schema=WICKETS_SCHEMA),
    )


def _download_url(url: str, dest_dir: Path, force: bool = False) -> Path:
    """Download an arbitrary cricsheet zip by full URL — used by the
    Indian-domestic aggregator which does not go through `COLLECTIONS`."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / Path(url).name
    if zip_path.exists() and not force:
        logger.info(f"cached: {zip_path}")
        return zip_path
    logger.info(f"downloading {url}")
    _fetch(url, zip_path)
    return zip_path


def aggregate_indian_domestic(raw_dir: Path, extracted_dir: Path, force: bool = False) -> Path:
    """Download all 38 Indian state-team zips and merge match JSONs into
    a single deduped directory keyed by match_id (= filename).

    With `force`, re-downloads every state zip and rebuilds the merge from
    scratch — otherwise a refreshed Cricsheet season is never pulled (the
    merge only ever *adds*, and cached zips/extracts are reused)."""
    merged_dir = extracted_dir / "indian_domestic_male"
    if force and merged_dir.exists():
        shutil.rmtree(merged_dir)
    merged_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = {p.name for p in merged_dir.glob("*.json")}
    for zip_name in INDIAN_STATE_TEAMS:
        zip_url = f"{CRICSHEET_BASE}/{zip_name}"
        try:
            zip_path = _download_url(zip_url, raw_dir, force=force)
        except httpx.HTTPError as e:
            logger.warning(f"skip {zip_name}: {e}")
            continue
        team_dir = extracted_dir / zip_path.stem
        if force and team_dir.exists():
            shutil.rmtree(team_dir)
        if not team_dir.exists() or not any(team_dir.iterdir()):
            team_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(team_dir)
        new = 0
        for fp in team_dir.glob("*.json"):
            if fp.name in seen:
                continue
            target = merged_dir / fp.name
            if not target.exists():
                target.write_bytes(fp.read_bytes())
            seen.add(fp.name)
            new += 1
        logger.info(f"{zip_path.name}: +{new} new matches (total unique {len(seen)})")
    return merged_dir


def write_parquet(
    matches: pl.DataFrame,
    balls: pl.DataFrame,
    out_dir: Path,
    collection: str,
    players: pl.DataFrame | None = None,
    wickets: pl.DataFrame | None = None,
) -> tuple[Path, Path]:
    """Writes `<table>_<collection>.parquet` for each frame given and returns the matches + balls
    paths. `players` / `wickets` land next to them, where `load_to_duckdb` picks them up."""
    out_dir.mkdir(parents=True, exist_ok=True)
    m_path = out_dir / f"matches_{collection}.parquet"
    b_path = out_dir / f"balls_{collection}.parquet"
    frames = {m_path: matches, b_path: balls}
    if players is not None:
        frames[out_dir / f"players_{collection}.parquet"] = players
    if wickets is not None:
        frames[out_dir / f"wickets_{collection}.parquet"] = wickets
    for path, df in frames.items():
        df.write_parquet(path)
        logger.info(f"wrote {path} ({len(df)} rows)")
    return m_path, b_path


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def load_to_duckdb(matches_path: Path, balls_path: Path, collection: str, db_path: Path) -> None:
    """(Re)create matches_<col> / balls_<col> from the parquet, plus players_<col> / wickets_<col>
    when their parquet sits next to the balls file."""
    safe = table_suffix(collection)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            f"CREATE OR REPLACE TABLE matches_{safe} AS "
            f"SELECT * FROM read_parquet('{_sql_path(matches_path)}')"
        )
        con.execute(
            f"CREATE OR REPLACE TABLE balls_{safe} AS "
            f"SELECT * FROM read_parquet('{_sql_path(balls_path)}')"
        )
        for table in ("players", "wickets"):
            path = balls_path.with_name(f"{table}_{collection}.parquet")
            if path.exists():
                con.execute(
                    f"CREATE OR REPLACE TABLE {table}_{safe} AS "
                    f"SELECT * FROM read_parquet('{_sql_path(path)}')"
                )
        # one name per ground, across every collection (keeps the raw spelling + aliases)
        from cricdex.common.venue_names import normalize_venues

        normalize_venues(con)
    finally:
        con.close()


def extracted_dir_for(collection: str, base: Path) -> Path:
    """Where `build` (or the Indian-domestic merge) extracted this collection's match JSON."""
    if collection == "indian_domestic_male":
        return base / "extracted" / "indian_domestic_male"
    if collection not in COLLECTIONS:
        raise ValueError(f"unknown collection '{collection}'. options: {sorted(COLLECTIONS)}")
    return base / "extracted" / Path(COLLECTIONS[collection]).stem


def backfill_identity(
    collection: str, base: Path | None = None, db_path: Path | None = None
) -> tuple[int, int]:
    """Build players_<col> + wickets_<col> for a DB ingested before those tables existed, from the
    match JSON already extracted on disk. No download; balls / matches are left untouched.
    Returns (player rows, wicket rows)."""
    from cricdex.config import DATA_DIR

    base = base or (DATA_DIR / "cricsheet")
    db_path = db_path or (base / "cricsheet.duckdb")
    src = extracted_dir_for(collection, base)
    if not src.exists() or not any(src.glob("*.json")):
        raise FileNotFoundError(f"no extracted match JSON for '{collection}' at {src}")
    players, wickets = parse_identity(src)
    safe = table_suffix(collection)
    con = duckdb.connect(str(db_path))
    try:
        con.register("players_df", players.to_arrow())
        con.register("wickets_df", wickets.to_arrow())
        con.execute(f"CREATE OR REPLACE TABLE players_{safe} AS SELECT * FROM players_df")
        con.execute(f"CREATE OR REPLACE TABLE wickets_{safe} AS SELECT * FROM wickets_df")
    finally:
        con.close()
    logger.info(f"{collection}: players_{safe} {len(players)} rows, wickets_{safe} {len(wickets)}")
    return len(players), len(wickets)


def build(collection: str, out: Path | None = None, force: bool = False) -> Path:
    """Full pipeline: download → extract → parse → parquet → DuckDB. Returns the
    DuckDB path. The single entry point used by both the CLI
    (`cricdex data ingest cricsheet`) and `scripts/ingest_cricsheet.py`, so they
    can't drift. `extract` re-runs automatically when the zip is newer."""
    from cricdex.config import DATA_DIR

    base = out or (DATA_DIR / "cricsheet")
    zip_path = download(collection, base / "raw", force=force)
    extracted = extract(zip_path, base / "extracted", force=force)
    parsed = parse_collection(extracted)
    m_path, b_path = write_parquet(
        parsed.matches,
        parsed.balls,
        base / "parquet",
        collection,
        players=parsed.players,
        wickets=parsed.wickets,
    )
    db_path = base / "cricsheet.duckdb"
    load_to_duckdb(m_path, b_path, collection, db_path)
    logger.info(f"duckdb loaded: {db_path}")
    return db_path
