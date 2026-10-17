"""Cricsheet downloader + parser.

Pulls JSON match archives from https://cricsheet.org/downloads/ (which zip(s) a collection comes
from is set in the league registry, `config/leagues.toml`), extracts per-match files, flattens
every field of the JSON format (https://cricsheet.org/format/json/, v1.0–1.3) into normalised
tables, writes Parquet and loads DuckDB:

- `matches_<col>`        one row per match: info + meta (event, season, officials, outcome method …)
- `innings_<col>`        one row per innings: target (DLS-revised when rain hit), powerplays,
                         penalty runs, declared / forfeited / super over, absent hurt, miscounts
- `balls_<col>`          one row per delivery; keeps only its first wicket (all are in wickets_),
                         every extras type in its own column, DRS review, non-boundary flag
- `wickets_<col>`        every wicket on every delivery (a delivery can have two)
- `replacements_<col>`   every player replacement (Impact Player, concussion sub, injured bowler …)
- `match_players_<col>`  each team's listed players (the XI plus any substitutes) with Cricsheet ids
- `players_<col>`        each match's `info.registry.people`: scorecard name → Cricsheet identifier
- `ingest_meta`          one row per collection: schema version, source zips, match count, time

The parser never assumes an optional key exists: a missing field is NULL (or 0 / FALSE where
the format says "absent means none"), so older files and newer format versions both load.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, NamedTuple

import duckdb
import httpx
import polars as pl
from loguru import logger
from tqdm import tqdm

from cricdex import leagues
from cricdex.common.sql import table_suffix

CRICSHEET_BASE = leagues.CRICSHEET_BASE

# Bump when a table gains / changes columns. Stored in matches_<col>.schema_version and in
# `ingest_meta`, so a DB built by an older parser can be told apart (and re-ingested).
#   1 — matches / balls (first extras key, first wicket) + players / wickets
#   2 — every JSON field: innings_, replacements_, match_players_, per-type extras, reviews …
SCHEMA_VERSION = 2

# The extras types the format defines; each gets its own `extras_<type>` column on balls_.
EXTRAS_TYPES = ("wides", "noballs", "byes", "legbyes", "penalty")


def collections() -> dict[str, tuple[str, ...]]:
    """collection key → its Cricsheet zip file name(s), from the league registry."""
    return {lg.key: lg.zips for lg in leagues.all()}


def _known(collection: str) -> leagues.League:
    try:
        return leagues.get(collection)
    except KeyError:
        raise ValueError(
            f"unknown collection '{collection}'. options: {', '.join(leagues.keys())}"
        ) from None


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


def download_zip(zip_name: str, dest: Path, force: bool = False) -> Path:
    """One Cricsheet zip into `dest` (cached by file name unless `force`)."""
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / zip_name
    if zip_path.exists() and not force:
        logger.info(f"cached: {zip_path}")
        return zip_path
    url = f"{CRICSHEET_BASE}/{zip_name}"
    logger.info(f"downloading {url}")
    _fetch(url, zip_path)
    return zip_path


def download(collection: str, dest: Path, force: bool = False) -> list[Path]:
    """Every zip the registry lists for this collection."""
    return [download_zip(z, dest, force=force) for z in _known(collection).zips]


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


# ---- table schemas (explicit, so an all-NULL column in a small collection keeps its type) ------

MATCHES_SCHEMA: dict[str, Any] = {
    "match_id": pl.String,
    "match_date": pl.String,
    "match_type": pl.String,
    "event_name": pl.String,
    "league": pl.String,
    "venue": pl.String,
    "city": pl.String,
    "team_home": pl.String,
    "team_away": pl.String,
    "overs": pl.Int64,
    "toss_winner": pl.String,
    "toss_decision": pl.String,
    "outcome_winner": pl.String,
    "outcome_by_runs": pl.Int64,
    "outcome_by_wickets": pl.Int64,
    "result": pl.String,
    # schema 2
    "dates": pl.List(pl.String),
    "gender": pl.String,
    "team_type": pl.String,
    "season": pl.String,
    "match_type_number": pl.Int64,
    "event_match_number": pl.Int64,
    "event_stage": pl.String,
    "event_group": pl.String,
    "balls_per_over": pl.Int64,
    "toss_uncontested": pl.Boolean,
    "outcome_method": pl.String,  # "D/L", "VJD", "Awarded", "1st innings score", "Lost fewer wickets"
    "outcome_eliminator": pl.String,  # super-over winner of a tie
    "outcome_bowl_out": pl.String,  # bowl-out winner of a tie
    "outcome_by_innings": pl.Int64,
    "player_of_match": pl.List(pl.String),
    "officials": pl.String,  # JSON {role: [names]}
    "supersubs": pl.String,  # JSON {team: name}
    "bowl_out": pl.String,  # JSON [{bowler, outcome}]
    "missing": pl.String,  # JSON list of strings / {powerplays: …}
    "venue_id": pl.String,  # registry.venues
    "data_version": pl.String,
    "created": pl.String,
    "revision": pl.Int64,
    "schema_version": pl.Int64,
}

BALLS_SCHEMA: dict[str, Any] = {
    "ball_id": pl.String,
    "match_id": pl.String,
    "match_date": pl.String,
    "match_type": pl.String,
    "league": pl.String,
    "venue": pl.String,
    "innings_idx": pl.Int64,
    "batting_team": pl.String,
    "bowling_team": pl.String,
    "over": pl.Int64,
    "ball_in_over": pl.Int64,
    "phase": pl.String,
    "batter": pl.String,
    "non_striker": pl.String,
    "bowler": pl.String,
    "runs_batter": pl.Int64,
    "runs_extras": pl.Int64,
    "runs_total": pl.Int64,
    "extras_type": pl.String,  # the FIRST extras key, kept for back-compat; see extras_<type>
    "wicket_kind": pl.String,  # first wicket only; every wicket is in wickets_<col>
    "player_out": pl.String,
    "fielders": pl.List(pl.String),
    # schema 2
    "actual_delivery": pl.String,
    "extras_wides": pl.Int64,
    "extras_noballs": pl.Int64,
    "extras_byes": pl.Int64,
    "extras_legbyes": pl.Int64,
    "extras_penalty": pl.Int64,
    "runs_non_boundary": pl.Boolean,  # a 4 / 6 that was all run or overthrows, not a boundary
    "n_wickets": pl.Int64,
    "review_by": pl.String,
    "review_umpire": pl.String,
    "review_batter": pl.String,
    "review_decision": pl.String,  # "upheld" | "struck down"
    "review_type": pl.String,  # "wicket" when given (not in the published spec, but in the data)
    "review_umpires_call": pl.Boolean,
}

INNINGS_SCHEMA: dict[str, Any] = {
    "match_id": pl.String,
    "innings_idx": pl.Int64,
    "team": pl.String,
    "target_runs": pl.Int64,
    "target_overs": pl.Float64,  # "35.1" = 35 overs and 1 ball
    "target_balls": pl.Int64,  # target_overs in legal balls, using the match's balls_per_over
    "declared": pl.Boolean,
    "forfeited": pl.Boolean,
    "super_over": pl.Boolean,
    "penalty_runs_pre": pl.Int64,
    "penalty_runs_post": pl.Int64,
    "absent_hurt": pl.List(pl.String),
    "miscounted_overs": pl.String,  # JSON {over: {balls, umpire}}
    "powerplays": pl.String,  # JSON [{from, to, type}]
    "n_overs": pl.Int64,
}

PLAYERS_SCHEMA: dict[str, Any] = {"match_id": pl.String, "name": pl.String, "identifier": pl.String}

WICKETS_SCHEMA: dict[str, Any] = {
    "match_id": pl.String,
    "innings_idx": pl.Int64,
    "over": pl.Int64,
    "ball_in_over": pl.Int64,
    "ball_id": pl.String,
    "player_out": pl.String,
    "wicket_kind": pl.String,
    "fielders": pl.List(pl.String),
    # schema 2
    "wicket_idx": pl.Int64,  # position on the delivery (0 = the one balls_ keeps)
    "fielder_substitute": pl.List(pl.Boolean),  # aligned with `fielders`
}

REPLACEMENTS_SCHEMA: dict[str, Any] = {
    "match_id": pl.String,
    "innings_idx": pl.Int64,
    "ball_id": pl.String,  # the delivery it happened before (NULL if not tied to one)
    "over": pl.Int64,
    "ball_in_over": pl.Int64,
    "kind": pl.String,  # "match" (takes the player's place) | "role" (bowler / batter only)
    "team": pl.String,
    "player_in": pl.String,
    "player_out": pl.String,
    "reason": pl.String,  # impact_player, concussion_substitute, injury, too many overs …
    "role": pl.String,  # role replacements: "bowler" | "batter"
}

MATCH_PLAYERS_SCHEMA: dict[str, Any] = {
    "match_id": pl.String,
    "team": pl.String,
    "name": pl.String,
    "identifier": pl.String,
    "player_order": pl.Int64,  # position in the team list (the XI first, substitutes after)
}

# Table name → schema for everything beyond matches / balls.
EXTRA_TABLES: dict[str, dict[str, Any]] = {
    "players": PLAYERS_SCHEMA,
    "wickets": WICKETS_SCHEMA,
    "innings": INNINGS_SCHEMA,
    "replacements": REPLACEMENTS_SCHEMA,
    "match_players": MATCH_PLAYERS_SCHEMA,
}


class ParsedMatch(NamedTuple):
    match: dict
    balls: list[dict]
    players: list[dict]
    wickets: list[dict]
    innings: list[dict] = []
    replacements: list[dict] = []
    match_players: list[dict] = []


class ParsedCollection(NamedTuple):
    matches: pl.DataFrame
    balls: pl.DataFrame
    players: pl.DataFrame
    wickets: pl.DataFrame
    innings: pl.DataFrame | None = None
    replacements: pl.DataFrame | None = None
    match_players: pl.DataFrame | None = None


# ---- small, forgiving converters --------------------------------------------------------------


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None if v is None else int(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> str | None:
    return None if v is None else str(v)


def _json(v: Any) -> str | None:
    """Nested Cricsheet blocks (officials, powerplays …) are kept verbatim as JSON text."""
    if v is None or v == {} or v == []:
        return None
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v if x is not None]


def overs_to_balls(overs: float | int | None, balls_per_over: int | None = 6) -> int | None:
    """Cricket overs notation → legal balls: 35.1 (35 overs, 1 ball) → 211 with 6-ball overs."""
    if overs is None:
        return None
    bpo = balls_per_over or 6
    whole = int(overs)
    part = int(round((float(overs) - whole) * 10))
    return whole * bpo + part


def _ball_id(match_id: str, innings_idx: int, over: int, ball_idx: int) -> str:
    return f"{match_id}::{innings_idx}::{over}::{ball_idx}"


def _fielders(w: dict) -> tuple[list[str], list[bool]]:
    """Named fielders on a wicket and whether each was a substitute (two aligned lists)."""
    names: list[str] = []
    subs: list[bool] = []
    for f in w.get("fielders") or []:
        if isinstance(f, dict) and f.get("name"):
            names.append(f["name"])
            subs.append(bool(f.get("substitute", False)))
    return names, subs


# ---- per-table row builders -------------------------------------------------------------------


def _registry_rows(match_id: str, info: dict) -> list[dict]:
    people = (info.get("registry") or {}).get("people") or {}
    return [
        {"match_id": match_id, "name": name, "identifier": ident}
        for name, ident in people.items()
        if name and ident
    ]


def _match_player_rows(match_id: str, info: dict) -> list[dict]:
    people = (info.get("registry") or {}).get("people") or {}
    rows: list[dict] = []
    for team, names in (info.get("players") or {}).items():
        for i, name in enumerate(_str_list(names)):
            rows.append(
                {
                    "match_id": match_id,
                    "team": team,
                    "name": name,
                    "identifier": people.get(name),
                    "player_order": i,
                }
            )
    return rows


def _wicket_rows(match_id: str, data: dict) -> list[dict]:
    """Every wicket on every delivery, with the same ball_id as the balls table."""
    rows: list[dict] = []
    for innings_idx, innings in enumerate(data.get("innings") or []):
        for over_block in innings.get("overs") or []:
            over = over_block.get("over", 0)
            for ball_idx, d in enumerate(over_block.get("deliveries") or [], start=1):
                for wicket_idx, w in enumerate(d.get("wickets") or []):
                    names, subs = _fielders(w)
                    rows.append(
                        {
                            "match_id": match_id,
                            "innings_idx": innings_idx,
                            "over": over,
                            "ball_in_over": ball_idx,
                            "ball_id": _ball_id(match_id, innings_idx, over, ball_idx),
                            "player_out": w.get("player_out"),
                            "wicket_kind": w.get("kind"),
                            "fielders": names,
                            "wicket_idx": wicket_idx,
                            "fielder_substitute": subs,
                        }
                    )
    return rows


def _match_row(match_id: str, data: dict) -> dict:
    info = data.get("info") or {}
    meta = data.get("meta") or {}
    dates = _str_list(info.get("dates"))
    event = info.get("event") or {}
    teams = info.get("teams") or []
    outcome = info.get("outcome") or {}
    by = outcome.get("by") or {}
    toss = info.get("toss") or {}
    venue = info.get("venue")
    venues = (info.get("registry") or {}).get("venues") or {}
    return {
        "match_id": match_id,
        "match_date": dates[0] if dates else None,
        "match_type": info.get("match_type"),
        "event_name": event.get("name"),
        "league": event.get("name"),
        "venue": venue,
        "city": info.get("city"),
        "team_home": teams[0] if teams else None,
        "team_away": teams[1] if len(teams) > 1 else None,
        "overs": _int(info.get("overs")),
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "outcome_winner": outcome.get("winner"),
        "outcome_by_runs": _int(by.get("runs")),
        "outcome_by_wickets": _int(by.get("wickets")),
        "result": outcome.get("result"),
        "dates": dates,
        "gender": info.get("gender"),
        "team_type": info.get("team_type"),
        "season": _str(info.get("season")),
        "match_type_number": _int(info.get("match_type_number")),
        "event_match_number": _int(event.get("match_number")),
        "event_stage": _str(event.get("stage")),
        "event_group": _str(event.get("group")),
        "balls_per_over": _int(info.get("balls_per_over")) or 6,
        "toss_uncontested": bool(toss.get("uncontested", False)),
        "outcome_method": outcome.get("method"),
        "outcome_eliminator": outcome.get("eliminator"),
        "outcome_bowl_out": outcome.get("bowl_out"),
        "outcome_by_innings": _int(by.get("innings")),
        "player_of_match": _str_list(info.get("player_of_match")),
        "officials": _json(info.get("officials")),
        "supersubs": _json(info.get("supersubs")),
        "bowl_out": _json(info.get("bowl_out")),
        "missing": _json(info.get("missing")),
        "venue_id": venues.get(venue) if venue else None,
        "data_version": _str(meta.get("data_version")),
        "created": _str(meta.get("created")),
        "revision": _int(meta.get("revision")),
        "schema_version": SCHEMA_VERSION,
    }


def _innings_row(match_id: str, innings_idx: int, innings: dict, bpo: int) -> dict:
    target = innings.get("target") or {}
    penalty = innings.get("penalty_runs") or {}
    t_overs = _float(target.get("overs"))
    return {
        "match_id": match_id,
        "innings_idx": innings_idx,
        "team": innings.get("team"),
        "target_runs": _int(target.get("runs")),
        "target_overs": t_overs,
        "target_balls": overs_to_balls(t_overs, bpo),
        "declared": bool(innings.get("declared", False)),
        "forfeited": bool(innings.get("forfeited", False)),
        "super_over": bool(innings.get("super_over", False)),
        "penalty_runs_pre": _int(penalty.get("pre")),
        "penalty_runs_post": _int(penalty.get("post")),
        "absent_hurt": _str_list(innings.get("absent_hurt")),
        "miscounted_overs": _json(innings.get("miscounted_overs")),
        "powerplays": _json(innings.get("powerplays")),
        "n_overs": len(innings.get("overs") or []),
    }


def _replacement_rows(
    match_id: str,
    innings_idx: int,
    over: int,
    ball_idx: int,
    block: dict,
    batting_team: str | None,
    bowling_team: str | None,
) -> list[dict]:
    rows: list[dict] = []
    ball_id = _ball_id(match_id, innings_idx, over, ball_idx)
    for kind in ("match", "role"):
        for r in block.get(kind) or []:
            if not isinstance(r, dict):
                continue
            team = r.get("team")
            if team is None and kind == "role":
                # role replacements don't name a team: a bowler is the fielding side's, a batter the batting side's
                team = bowling_team if r.get("role") == "bowler" else batting_team
            rows.append(
                {
                    "match_id": match_id,
                    "innings_idx": innings_idx,
                    "ball_id": ball_id,
                    "over": over,
                    "ball_in_over": ball_idx,
                    "kind": kind,
                    "team": team,
                    "player_in": r.get("in"),
                    "player_out": r.get("out"),
                    "reason": r.get("reason"),
                    "role": r.get("role"),
                }
            )
    return rows


def parse_match(path: Path) -> tuple[dict, list[dict]]:
    """(match row, ball rows) — `parse_match_full` also returns every other table's rows."""
    full = parse_match_full(path)
    return full.match, full.balls


def parse_match_data(data: dict, match_id: str) -> ParsedMatch:
    """Flatten one Cricsheet match (already-loaded JSON) into rows for every table."""
    info = data.get("info") or {}
    match_row = _match_row(match_id, data)
    match_date = match_row["match_date"]
    match_type = match_row["match_type"]
    event_name = match_row["event_name"]
    venue = match_row["venue"]
    teams = info.get("teams") or []
    overs_per_innings = match_row["overs"]
    bpo = match_row["balls_per_over"]

    ball_rows: list[dict] = []
    innings_rows: list[dict] = []
    replacement_rows: list[dict] = []
    for innings_idx, innings in enumerate(data.get("innings") or []):
        batting_team = innings.get("team")
        bowling_team = next((t for t in teams if t != batting_team), None)
        innings_rows.append(_innings_row(match_id, innings_idx, innings, bpo))
        for over_block in innings.get("overs") or []:
            over = over_block.get("over", 0)
            phase = _phase(over, overs_per_innings, match_type)
            for ball_idx, d in enumerate(over_block.get("deliveries") or [], start=1):
                runs = d.get("runs") or {}
                extras = d.get("extras") or {}
                extras_type = next(iter(extras.keys())) if extras else None
                wickets = d.get("wickets") or []
                wicket = wickets[0] if wickets else {}
                fielders, _subs = _fielders(wicket)
                review = d.get("review") or {}
                row = {
                    "ball_id": _ball_id(match_id, innings_idx, over, ball_idx),
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
                    "runs_batter": _int(runs.get("batter", runs.get("batsman", 0))) or 0,
                    "runs_extras": _int(runs.get("extras", 0)) or 0,
                    "runs_total": _int(runs.get("total", 0)) or 0,
                    "extras_type": extras_type,
                    "wicket_kind": wicket.get("kind"),
                    "player_out": wicket.get("player_out"),
                    "fielders": fielders,
                    "actual_delivery": _str(d.get("actual_delivery")),
                    "runs_non_boundary": bool(runs.get("non_boundary", False)),
                    "n_wickets": len(wickets),
                    "review_by": review.get("by"),
                    "review_umpire": review.get("umpire"),
                    "review_batter": review.get("batter"),
                    "review_decision": review.get("decision"),
                    "review_type": _str(review.get("type")),
                    "review_umpires_call": bool(review["umpires_call"])
                    if "umpires_call" in review
                    else None,
                }
                for t in EXTRAS_TYPES:
                    row[f"extras_{t}"] = _int(extras.get(t, 0)) or 0
                ball_rows.append(row)
                if d.get("replacements"):
                    replacement_rows += _replacement_rows(
                        match_id,
                        innings_idx,
                        over,
                        ball_idx,
                        d["replacements"],
                        batting_team,
                        bowling_team,
                    )
    return ParsedMatch(
        match_row,
        ball_rows,
        _registry_rows(match_id, info),
        _wicket_rows(match_id, data),
        innings_rows,
        replacement_rows,
        _match_player_rows(match_id, info),
    )


def parse_match_full(path: Path) -> ParsedMatch:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse_match_data(data, path.stem)


def _frame(rows: list[dict], schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def _match_files(dirs: Path | list[Path]) -> list[Path]:
    """Every match JSON across the given directories, one per match id (= file stem): a composite
    collection's zips can overlap, and the first copy wins."""
    seen: dict[str, Path] = {}
    for d in [dirs] if isinstance(dirs, Path) else dirs:
        for fp in sorted(d.glob("*.json")):
            seen.setdefault(fp.stem, fp)
    return [seen[k] for k in sorted(seen)]


def parse_collection(extracted: Path | list[Path]) -> ParsedCollection:
    files = _match_files(extracted)
    parsed_rows: dict[str, list[dict]] = {
        "matches": [],
        "balls": [],
        "players": [],
        "wickets": [],
        "innings": [],
        "replacements": [],
        "match_players": [],
    }
    skipped: list[str] = []
    for fp in tqdm(files, desc="parsing matches"):
        try:
            parsed = parse_match_full(fp)
        except Exception as e:
            logger.warning(f"skip {fp.name}: {e}")
            skipped.append(fp.name)
            continue
        parsed_rows["matches"].append(parsed.match)
        parsed_rows["balls"].extend(parsed.balls)
        parsed_rows["players"].extend(parsed.players)
        parsed_rows["wickets"].extend(parsed.wickets)
        parsed_rows["innings"].extend(parsed.innings)
        parsed_rows["replacements"].extend(parsed.replacements)
        parsed_rows["match_players"].extend(parsed.match_players)
    if skipped:
        # Say how many matches were lost, so a bad parse can't silently shrink a collection.
        logger.warning(
            f"{len(skipped)} of {len(files)} match files could not be parsed: {', '.join(skipped[:20])}"
        )
        if len(skipped) > max(5, len(files) // 20):
            raise RuntimeError(
                f"{len(skipped)} of {len(files)} match files failed to parse — stopping"
            )
    return ParsedCollection(
        _frame(parsed_rows["matches"], MATCHES_SCHEMA),
        _frame(parsed_rows["balls"], BALLS_SCHEMA),
        _frame(parsed_rows["players"], PLAYERS_SCHEMA),
        _frame(parsed_rows["wickets"], WICKETS_SCHEMA),
        _frame(parsed_rows["innings"], INNINGS_SCHEMA),
        _frame(parsed_rows["replacements"], REPLACEMENTS_SCHEMA),
        _frame(parsed_rows["match_players"], MATCH_PLAYERS_SCHEMA),
    )


def parse_identity(extracted: Path | list[Path]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(players, wickets) only — reads the match JSON but skips building the far bigger ball rows."""
    player_rows: list[dict] = []
    wicket_rows: list[dict] = []
    for fp in tqdm(_match_files(extracted), desc="reading registries"):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"skip {fp.name}: {e}")
            continue
        player_rows.extend(_registry_rows(fp.stem, data.get("info") or {}))
        wicket_rows.extend(_wicket_rows(fp.stem, data))
    return _frame(player_rows, PLAYERS_SCHEMA), _frame(wicket_rows, WICKETS_SCHEMA)


def write_parquet(
    matches: pl.DataFrame,
    balls: pl.DataFrame,
    out_dir: Path,
    collection: str,
    players: pl.DataFrame | None = None,
    wickets: pl.DataFrame | None = None,
    **extra: pl.DataFrame | None,
) -> tuple[Path, Path]:
    """Writes `<table>_<collection>.parquet` for each frame given and returns the matches + balls
    paths. `players` / `wickets` and any of `innings` / `replacements` / `match_players` (keyword
    arguments) land next to them, where `load_to_duckdb` picks them up."""
    unknown = set(extra) - set(EXTRA_TABLES)
    if unknown:
        raise TypeError(f"unknown table(s) {sorted(unknown)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    m_path = out_dir / f"matches_{collection}.parquet"
    b_path = out_dir / f"balls_{collection}.parquet"
    frames = {m_path: matches, b_path: balls}
    for table, df in {"players": players, "wickets": wickets, **extra}.items():
        if df is not None:
            frames[out_dir / f"{table}_{collection}.parquet"] = df
    for path, df in frames.items():
        df.write_parquet(path)
        logger.info(f"wrote {path} ({len(df)} rows)")
    return m_path, b_path


def write_collection(parsed: ParsedCollection, out_dir: Path, collection: str) -> tuple[Path, Path]:
    """Every table of a parsed collection to Parquet (stale tables from an older run are removed)."""
    for table in EXTRA_TABLES:
        (out_dir / f"{table}_{collection}.parquet").unlink(missing_ok=True)
    return write_parquet(
        parsed.matches,
        parsed.balls,
        out_dir,
        collection,
        players=parsed.players,
        wickets=parsed.wickets,
        innings=parsed.innings,
        replacements=parsed.replacements,
        match_players=parsed.match_players,
    )


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _record_ingest(
    con: duckdb.DuckDBPyConnection, collection: str, n_matches: int, zips: str
) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS ingest_meta (collection VARCHAR, schema_version BIGINT, "
        "zips VARCHAR, n_matches BIGINT, ingested_at VARCHAR)"
    )
    con.execute("DELETE FROM ingest_meta WHERE collection = ?", [collection])
    con.execute(
        "INSERT INTO ingest_meta VALUES (?, ?, ?, ?, ?)",
        [
            collection,
            SCHEMA_VERSION,
            zips,
            n_matches,
            dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        ],
    )


def load_to_duckdb(matches_path: Path, balls_path: Path, collection: str, db_path: Path) -> None:
    """(Re)create matches_<col> / balls_<col> from the parquet, plus every other table
    (players_ / wickets_ / innings_ / replacements_ / match_players_) whose parquet sits next to the
    balls file, and record the ingest in `ingest_meta`."""
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
        for table in EXTRA_TABLES:
            path = balls_path.with_name(f"{table}_{collection}.parquet")
            if path.exists():
                con.execute(
                    f"CREATE OR REPLACE TABLE {table}_{safe} AS "
                    f"SELECT * FROM read_parquet('{_sql_path(path)}')"
                )
        drop_orphan_rows(con, safe)
        n = con.execute(f"SELECT COUNT(*) FROM matches_{safe}").fetchone()[0]
        try:
            zips = " ".join(leagues.get(collection).zips)
        except KeyError:
            zips = ""
        _record_ingest(con, safe, int(n), zips)
        # one name per ground, across every collection (keeps the raw spelling + aliases)
        from cricdex.common.venue_names import normalize_venues

        normalize_venues(con)
    finally:
        con.close()


def drop_orphan_rows(con: duckdb.DuckDBPyConnection, safe: str) -> dict[str, int]:
    """Delete rows of the per-match side tables (players_ / wickets_ / innings_ / …) whose match
    isn't in matches_<col>: a side table rebuilt from newer extracted JSON would otherwise point at
    matches the ball data doesn't have. Returns rows removed per table."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    removed: dict[str, int] = {}
    if f"matches_{safe}" not in have:
        return removed
    for table in EXTRA_TABLES:
        name = f"{table}_{safe}"
        if name not in have:
            continue
        before = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        con.execute(
            f"DELETE FROM {name} WHERE match_id NOT IN (SELECT match_id FROM matches_{safe})"
        )
        after = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        if before != after:
            removed[name] = int(before - after)
            logger.info(f"{name}: dropped {before - after} rows for matches not in matches_{safe}")
    return removed


def extracted_dirs_for(collection: str, base: Path) -> list[Path]:
    """Where `build` extracted this collection's match JSON (one folder per source zip)."""
    return [base / "extracted" / Path(z).stem for z in _known(collection).zips]


def extracted_dir_for(collection: str, base: Path) -> Path:
    """The first (usually only) extracted folder of a collection."""
    return extracted_dirs_for(collection, base)[0]


def backfill_identity(
    collection: str, base: Path | None = None, db_path: Path | None = None
) -> tuple[int, int]:
    """Build players_<col> + wickets_<col> for a DB ingested before those tables existed, from the
    match JSON already extracted on disk. No download; balls / matches are left untouched.
    Returns (player rows, wicket rows)."""
    from cricdex.config import DATA_DIR

    base = base or (DATA_DIR / "cricsheet")
    db_path = db_path or (base / "cricsheet.duckdb")
    srcs = [d for d in extracted_dirs_for(collection, base) if d.exists() and any(d.glob("*.json"))]
    if not srcs:
        raise FileNotFoundError(
            f"no extracted match JSON for '{collection}' at {extracted_dir_for(collection, base)}"
        )
    players, wickets = parse_identity(srcs)
    safe = table_suffix(collection)
    con = duckdb.connect(str(db_path))
    try:
        con.register("players_df", players.to_arrow())
        con.register("wickets_df", wickets.to_arrow())
        con.execute(f"CREATE OR REPLACE TABLE players_{safe} AS SELECT * FROM players_df")
        con.execute(f"CREATE OR REPLACE TABLE wickets_{safe} AS SELECT * FROM wickets_df")
        # the extracted JSON can be newer than the ingested matches: keep only matches we have
        drop_orphan_rows(con, safe)
    finally:
        con.close()
    logger.info(f"{collection}: players_{safe} {len(players)} rows, wickets_{safe} {len(wickets)}")
    return len(players), len(wickets)


def build(collection: str, out: Path | None = None, force: bool = False) -> Path:
    """Full pipeline: download → extract → parse → parquet → DuckDB. Returns the
    DuckDB path. The single entry point used by both the CLI
    (`cricdex data ingest cricsheet`) and `scripts/ingest_cricsheet.py`, so they
    can't drift. `extract` re-runs automatically when a zip is newer. A collection
    built from several zips is merged by match id."""
    from cricdex.config import DATA_DIR

    _known(collection)
    base = out or (DATA_DIR / "cricsheet")
    zip_paths = download(collection, base / "raw", force=force)
    extracted = [extract(z, base / "extracted", force=force) for z in zip_paths]
    parsed = parse_collection(extracted)
    m_path, b_path = write_collection(parsed, base / "parquet", collection)
    db_path = base / "cricsheet.duckdb"
    load_to_duckdb(m_path, b_path, collection, db_path)
    logger.info(f"duckdb loaded: {db_path} ({collection}: {len(parsed.matches)} matches)")
    return db_path
