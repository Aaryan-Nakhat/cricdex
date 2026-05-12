"""Cricbuzz live-score fetcher.

Cricbuzz exposes a few mobile-app JSON endpoints under
`www.cricbuzz.com/match-api/`. They're not officially documented but
have been stable for years; we use:

- `livematches.json` — index of currently-playing + recently-finished
  matches.
- `<matchId>/leanback.json` — current scorecard.
- `<matchId>/commentary.json` — running commentary feed.

This module is the read-side glue: an `httpx.Client` with realistic
browser headers + retries, plus thin parsers that flatten the JSON
into simple dicts the rest of CricDex (live dashboard, predict
scoring, news digest) consumes.

Known caveat — datacenter-IP blocking
-------------------------------------
Cricbuzz returns 403 to GCP / AWS datacenter IPs on the
`match-api/livematches.json` route (same family of issue as the WDQS
+ Reddit blocks documented elsewhere in this repo). The pipeline is
correct end-to-end; populate from a residential / mobile / VPN'd
network for now. The official Cricbuzz partner API is the long-term
fix.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

CRICBUZZ_BASE = "https://www.cricbuzz.com/match-api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.cricbuzz.com/",
}


def _get_json(client: httpx.Client, url: str, retries: int = 2) -> dict | None:
    for attempt in range(retries + 1):
        try:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning(f"GET {url} failed after {retries + 1} attempts: {e}")
            return None
        except ValueError:
            logger.warning(f"GET {url} returned non-JSON")
            return None
    return None


def live_index(timeout: float = 20.0) -> list[dict]:
    """Return a flat list of {match_id, status, team_a, team_b, score, venue}
    for every currently-listed match."""
    with httpx.Client(timeout=timeout, headers=HEADERS) as cx:
        raw = _get_json(cx, f"{CRICBUZZ_BASE}/livematches.json")
    if not raw:
        return []
    rows: list[dict] = []
    for series in raw.get("matches") or []:
        for m in series.get("matches", []):
            rows.append(
                {
                    "match_id": m.get("matchId") or m.get("id"),
                    "series_id": series.get("seriesId"),
                    "series_name": series.get("seriesName"),
                    "team_a": (m.get("team1") or {}).get("name"),
                    "team_b": (m.get("team2") or {}).get("name"),
                    "status": m.get("status"),
                    "state": m.get("state"),
                    "venue": (m.get("venueInfo") or {}).get("ground"),
                    "city": (m.get("venueInfo") or {}).get("city"),
                    "format": m.get("matchFormat"),
                    "start_date": m.get("startDate"),
                    "score": m.get("score"),
                }
            )
    return rows


def leanback(match_id: str | int, timeout: float = 20.0) -> dict | None:
    """Compact scorecard for a single match — current batters, bowler,
    score line, last few overs."""
    with httpx.Client(timeout=timeout, headers=HEADERS) as cx:
        return _get_json(cx, f"{CRICBUZZ_BASE}/{match_id}/leanback.json")


def commentary(match_id: str | int, timeout: float = 20.0) -> dict | None:
    """Running commentary feed for a match."""
    with httpx.Client(timeout=timeout, headers=HEADERS) as cx:
        return _get_json(cx, f"{CRICBUZZ_BASE}/{match_id}/commentary.json")


def snapshot_to_disk(out_dir: Path) -> Path | None:
    """One-shot helper for cron: pull the live index, dump it to a
    timestamped JSON under `out_dir`. Returns the path, or None if
    Cricbuzz blocked the request."""
    import datetime as dt
    import json

    rows = live_index()
    if not rows:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"live_{stamp}.json"
    out_path.write_text(json.dumps(rows, indent=2))
    return out_path


__all__ = ["live_index", "leanback", "commentary", "snapshot_to_disk"]


# Helper so type-checkers see a clean API.
_ = Any
