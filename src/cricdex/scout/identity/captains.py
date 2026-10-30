"""Captaincy as of an auction, from `data/curated/ipl_captains.json` (scripts/ipl_captains.py).

`as_of(cid, season)` answers, for the auction that builds the squads of IPL `season` (held in the
December before it, or the January / February of it), only from seasons before it:

- `captain_ipl_last`: was he an IPL side's regular captain in season − 1 (not a stand-in);
- `captain_ipl_seasons`: how many IPL seasons he captained before `season`;
- `captain_intl_2y`: did he captain his country (men's Test, ODI or T20I) in calendar year season − 2
  or season − 1;
- `captain_teams`: the IPL sides he was regular captain of in season − 1 (display).

A stint counts every year from..to, except a stand-in (fewer than 4 matches a year: its first and last
years only). The market price reads the first three (web_parity/pricing.market_features); the site export
adds them, with a "Captain" badge, to the pool, squad and profile rows.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from cricdex.config import DATA_DIR

CAPTAINS = DATA_DIR / "curated" / "ipl_captains.json"
STAND_IN_PER_YEAR = 4


def stint_years(s: dict) -> list[int]:
    """The years a stint counts as captaincy (all, or a stand-in's first and last)."""
    span = s["to"] - s["from"] + 1
    if s.get("matches") is not None and s["matches"] < STAND_IN_PER_YEAR * span:
        return sorted({s["from"], s["to"]})
    return list(range(s["from"], s["to"] + 1))


@lru_cache(maxsize=2)
def _index(
    path: str,
) -> tuple[dict[str, dict[int, set[str]]], dict[str, dict[int, set[str]]], dict[str, set[int]]]:
    """(every captaincy year per player and team, the regular-captain years only, international)."""
    p = Path(path)
    if not p.exists():
        return {}, {}, {}
    d = json.loads(p.read_text(encoding="utf-8"))
    ipl: dict[str, dict[int, set[str]]] = {}
    regular: dict[str, dict[int, set[str]]] = {}
    # one regular captain per side and season: of the stints that aren't a stand-in's, the one with
    # the most matches a season (a stint's matches over its seasons; unknown = the full season). Two
    # could pass the stand-in bar in one season (SRH 2026: Cummins, 38 matches over 2024-26, and
    # Ishan Kishan, 7 while Cummins was injured): the reports named Cummins captain and Kishan stand-in.
    best: dict[tuple[str, int], tuple[float, str]] = {}
    for s in d.get("ipl") or []:
        cid = s.get("cricsheet_id")
        if not cid:
            continue
        ys = stint_years(s)
        for y in ys:
            ipl.setdefault(cid, {}).setdefault(y, set()).add(s["team"])
        if len(ys) == s["to"] - s["from"] + 1 and not _stand_in(s):
            per = math.inf if s.get("matches") is None else s["matches"] / len(ys)
            for y in ys:
                k = (s["team"], y)
                if k not in best or (per, cid) > best[k]:
                    best[k] = (per, cid)
    for (team, y), (_per, cid) in best.items():
        regular.setdefault(cid, {}).setdefault(y, set()).add(team)
    intl: dict[str, set[int]] = {}
    for s in d.get("international") or []:
        cid = s.get("cricsheet_id")
        if not cid:
            continue
        intl.setdefault(cid, set()).update(stint_years(s))
    return ipl, regular, intl


def _stand_in(s: dict) -> bool:
    span = s["to"] - s["from"] + 1
    return s.get("matches") is not None and s["matches"] < STAND_IN_PER_YEAR * span


def as_of(cid: str | None, season: int, path: Path | None = None) -> dict:
    """Captaincy known before the auction for IPL `season` (see the module docstring)."""
    ipl, regular, intl = _index(str(path or CAPTAINS))
    years = ipl.get(cid or "", {})
    # last season's captain = the regular captain (a stand-in's games don't make him one)
    last = sorted(regular.get(cid or "", {}).get(season - 1, set()))
    return {
        "captain_ipl_last": 1 if last else 0,
        "captain_ipl_seasons": sum(1 for y in years if y < season),
        "captain_intl_2y": 1 if intl.get(cid or "", set()) & {season - 2, season - 1} else 0,
        "captain_teams": last,
    }


def summary(cid: str | None, path: Path | None = None) -> dict | None:
    """His captaincy for display (the profile identity block): {ipl: [{team, from, to, matches}],
    international: [{country, format, from, to}]} merged per side, or None if he never captained."""
    p = Path(path or CAPTAINS)
    if not cid or not p.exists():
        return None
    d = _raw(str(p))
    ipl = [
        {k: s.get(k) for k in ("team", "from", "to", "matches")}
        for s in d.get("ipl") or []
        if s.get("cricsheet_id") == cid
    ]
    spans: dict[tuple[str, str], list[int]] = {}
    for s in d.get("international") or []:
        if s.get("cricsheet_id") != cid:
            continue
        k = (s["country"], s["format"])
        a = spans.setdefault(k, [s["from"], s["to"]])
        a[0], a[1] = min(a[0], s["from"]), max(a[1], s["to"])
    intl = [
        {"country": c, "format": f, "from": a[0], "to": a[1]}
        for (c, f), a in sorted(spans.items(), key=lambda kv: -kv[1][1])
    ]
    if not ipl and not intl:
        return None
    return {"ipl": sorted(ipl, key=lambda s: -s["to"]), "international": intl}


@lru_cache(maxsize=2)
def _raw(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
