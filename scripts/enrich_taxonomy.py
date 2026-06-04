"""Enrich every player with cricket taxonomy via Gemini.

For each player we ask Gemini (reporting-service proxy) for the facts
ball-by-ball data can't give us: bowling type (seam vs spin + exact
style), primary role, usual batting position bucket, batting hand, and
country. Stored permanently in data/curated/player_taxonomy.json keyed
by cricsheet_id, so the scout graph stops calling Bhuvneshwar a twin of
Amit Mishra, and the UI can filter by role / type / country.

Resumable: only players missing from the cache are queried, so a rerun
fills gaps and a newly-ingested player is picked up next time.

Run:
    GEMINI_KONG_KEY=... uv run python scripts/enrich_taxonomy.py
    GEMINI_KONG_KEY=... uv run python scripts/enrich_taxonomy.py --batch 20 --limit 200
"""

from __future__ import annotations

import json
import os
import time

import httpx
import typer
from loguru import logger

from cricdex.config import ROOT  # importing config loads .env (GEMINI_TMP_*)

SITE_DATA = ROOT / "site" / "public" / "data"
CACHE = ROOT / "data" / "curated" / "player_taxonomy.json"

# Prefer the GEMINI_TMP_* vars (a full gemini base, e.g.
# https://api-kong.salesagents.ai/reporting-live/api/v1/gemini); fall back to
# the older GEMINI_KONG_BASE (which lacks the /api/v1/gemini suffix).
_TMP_BASE = os.environ.get("GEMINI_TMP_URL")
if _TMP_BASE:
    URL = f"{_TMP_BASE.rstrip('/')}/generate_json"
else:
    KONG_BASE = os.environ.get("GEMINI_KONG_BASE", "https://api-kong.salesagents.ai/reporting-prod")
    URL = f"{KONG_BASE}/api/v1/gemini/generate_json"
MODEL = "gemini-2.5-pro"

SYS = (
    "You are an authoritative cricket reference. For each player below return "
    "STRICT facts about their playing profile. Use the player's full name to "
    "disambiguate. If you are genuinely unsure of a field, use null / 'unknown' "
    "— do NOT guess. Buckets are fixed; pick the closest."
)

SCHEMA_HELP = (
    'Return JSON {"players":[...]} with one object per input in the same order. '
    "Fields per player:\n"
    "- id: echo the input id\n"
    "- primary_role: batter | bowler | allrounder | wk_batter\n"
    "- bowling_category: seam | spin | none   (none = doesn't bowl)\n"
    "- bowling_style: right-arm-fast | right-arm-fast-medium | right-arm-medium | "
    "off-spin | leg-spin | left-arm-orthodox | left-arm-wrist-spin | "
    "left-arm-fast | left-arm-medium | none\n"
    "- batting_position: opener | no3 | middle | finisher | lower | tailender | unknown "
    "(opener=1-2, no3=3, middle=4-5, finisher=6-7, lower=8, tailender=9-11)\n"
    "- batting_hand: right | left | unknown\n"
    "- country: ISO-3 code (IND, AUS, ENG, PAK, RSA, NZL, SRI, BAN, AFG, WIN, IRE, ...)\n"
    "- confidence: high | medium | low"
)


def _collect_players() -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for f in sorted(SITE_DATA.glob("*/players.json")):
        for p in json.loads(f.read_text()):
            cid = p["cricsheet_id"]
            if cid not in seen:
                seen[cid] = {"name": p["name"], "full_name": p.get("full_name", p["name"])}
    return seen


def _load_cache() -> dict[str, dict]:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")


def _ask(batch: list[dict], key: str) -> list[dict]:
    payload = {
        "system_prompt": SYS,
        "user_prompt": f"{SCHEMA_HELP}\n\nPlayers: {json.dumps(batch)}",
        "model": MODEL,
        "temperature": 0.0,
    }
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    r = httpx.post(URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    result = data.get("result") or {}
    return result.get("players", []) if isinstance(result, dict) else []


app = typer.Typer(add_completion=False)


@app.command()
def run(
    batch: int = typer.Option(20, "--batch", help="players per Gemini call"),
    limit: int = typer.Option(0, "--limit", help="max players this run (0 = all missing)"),
    sleep: float = typer.Option(0.4, "--sleep", help="pause between calls (s)"),
) -> None:
    key = os.environ.get("GEMINI_TMP_API_KEY") or os.environ.get("GEMINI_KONG_KEY")
    if not key:
        raise SystemExit("set GEMINI_TMP_API_KEY (or GEMINI_KONG_KEY) in the env")

    players = _collect_players()
    cache = _load_cache()
    todo = [
        {"id": cid, "name": v["name"], "full_name": v["full_name"]}
        for cid, v in players.items()
        if cid not in cache
    ]
    if limit:
        todo = todo[:limit]
    logger.info(f"{len(players)} players total, {len(cache)} cached, {len(todo)} to enrich")

    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        try:
            got = _ask(chunk, key)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"batch {i // batch} failed: {e}; retrying once")
            time.sleep(2)
            try:
                got = _ask(chunk, key)
            except Exception as e2:  # noqa: BLE001
                logger.error(f"batch {i // batch} failed again: {e2}; skipping")
                continue
        by_id = {g.get("id"): g for g in got if isinstance(g, dict)}
        for p in chunk:
            g = by_id.get(p["id"])
            if not g:
                continue
            cache[p["id"]] = {
                "name": p["name"],
                "full_name": p["full_name"],
                "primary_role": g.get("primary_role"),
                "bowling_category": g.get("bowling_category"),
                "bowling_style": g.get("bowling_style"),
                "batting_position": g.get("batting_position"),
                "batting_hand": g.get("batting_hand"),
                "country": g.get("country"),
                "confidence": g.get("confidence"),
                "source": MODEL,
            }
            done += 1
        _save_cache(cache)  # durable after every batch
        logger.info(f"  +{len(by_id)} ({done}/{len(todo)})")
        time.sleep(sleep)

    logger.info(f"done — cache now {len(cache)} players → {CACHE}")


if __name__ == "__main__":
    app()
