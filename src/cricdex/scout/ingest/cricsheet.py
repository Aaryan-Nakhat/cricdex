"""Cricsheet downloader + parser.

Pulls JSON match archives from https://cricsheet.org/downloads/, extracts
per-match files, flattens into two tables (matches + balls), writes Parquet.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import httpx
import polars as pl
from loguru import logger
from tqdm import tqdm

CRICSHEET_BASE = "https://cricsheet.org/downloads"

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
    "sa20": "sa20_male_json.zip",
    "ilt20": "ilt20_male_json.zip",
    "mlc": "mlc_male_json.zip",
    "t20s_male": "t20s_male_json.zip",
    "t20s_female": "t20s_female_json.zip",
    "tests_male": "tests_male_json.zip",
    "tests_female": "tests_female_json.zip",
    "odis_male": "odis_male_json.zip",
    "odis_female": "odis_female_json.zip",
}


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
    with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(zip_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
            for chunk in r.iter_bytes(chunk_size=1 << 16):
                f.write(chunk)
                bar.update(len(chunk))
    return zip_path


def extract(zip_path: Path, dest: Path) -> Path:
    out_dir = dest / zip_path.stem
    if out_dir.exists() and any(out_dir.iterdir()):
        logger.info(f"already extracted: {out_dir}")
        return out_dir
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


def parse_match(path: Path) -> tuple[dict, list[dict]]:
    with open(path) as f:
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
    return match_row, ball_rows


def parse_collection(extracted_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    files = [fp for fp in sorted(extracted_dir.glob("*.json")) if fp.name.lower() != "readme.txt"]
    match_rows: list[dict] = []
    ball_rows: list[dict] = []
    for fp in tqdm(files, desc="parsing matches"):
        try:
            m, b = parse_match(fp)
        except Exception as e:
            logger.warning(f"skip {fp.name}: {e}")
            continue
        match_rows.append(m)
        ball_rows.extend(b)
    return pl.DataFrame(match_rows), pl.DataFrame(ball_rows)


def write_parquet(
    matches: pl.DataFrame,
    balls: pl.DataFrame,
    out_dir: Path,
    collection: str,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    m_path = out_dir / f"matches_{collection}.parquet"
    b_path = out_dir / f"balls_{collection}.parquet"
    matches.write_parquet(m_path)
    balls.write_parquet(b_path)
    logger.info(f"wrote {m_path} ({len(matches)} rows)")
    logger.info(f"wrote {b_path} ({len(balls)} rows)")
    return m_path, b_path
