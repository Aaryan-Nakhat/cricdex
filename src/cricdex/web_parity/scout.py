"""3-tier Scout look-alikes. EXACT mirror of `site/src/pages/Scout.tsx`.

Pick an active IPL player -> similar players at three levels (IPL peers,
uncapped SMAT, overseas BBL), ranked by closeness of within-tier skill
standing (z). Same role/seam-spin/position matching, same gem rule, same
similarity formula as the browser.
"""

from __future__ import annotations

import math

# Uncapped "gem": punches above its sample — high standing on low exposure.
GEM_Z = 0.6


def _r1(x: float) -> float:
    """Half-up 1dp rounding, identical to JS `Math.round(x*10)/10` — so the TS
    `replacementByNeed` ranks rows the same way on exact-half savings."""
    return math.floor(x * 10 + 0.5) / 10


def gem_threshold(smat: list[dict]) -> float | None:
    """Median SMAT exposure (balls > 0) — the gem cutoff."""
    vals = sorted(p["balls"] for p in smat if p.get("balls", 0) > 0)
    if not vals:
        return None
    # Mirror the TS: balls[floor(len/2)] (lower-middle, not averaged).
    return float(vals[len(vals) // 2])


def is_gem(p: dict, median_balls: float | None) -> bool:
    if median_balls is None:
        return False
    return p["z"] >= GEM_Z and p.get("balls", 0) > 0 and p["balls"] <= median_balls


def similar_to(
    sel: dict,
    pool: list[dict],
    role: str | None = None,
    pos: str | None = None,
    top: int = 8,
) -> list[dict]:
    """Most-similar players of the chosen role (defaults to the pick's own),
    optionally a seam/spin (bowlers) and batting-slot filter. Returns rows
    [{..player.., "sim": float}] sorted by similarity desc, top-N.
    """
    role = role or sel["role"]
    out = []
    for p in pool:
        if p["cricsheet_id"] == sel["cricsheet_id"] or p["role"] != role:
            continue
        if (
            role == "bowler"
            and sel.get("bowling_category")
            and p.get("bowling_category") != sel["bowling_category"]
        ):
            continue
        if pos and p.get("batting_position") != pos:
            continue
        sim = max(0.0, 1 - abs(p["z"] - sel["z"]) / 2.5)
        out.append({**p, "sim": sim})
    out.sort(key=lambda r: r["sim"], reverse=True)
    return out[:top]


def replacement_by_need(
    sel: dict,
    pool: list[dict],
    tier: str = "ipl",
    role: str | None = None,
    max_price: float | None = None,
    pos: str | None = None,
    top: int = 8,
) -> list[dict]:
    """Cheaper same-mould replacements for `sel`: similar players (same role,
    optional batting slot) priced ≤ `max_price` (defaults to the pick's own
    price), ranked by saving then similarity. Each row carries `est_cr` +
    `saving`. EXACT mirror of the TS `replacementByNeed`.
    """
    from cricdex.web_parity.pricing import est_value

    sel_price = est_value(sel["value"], sel["role"], "ipl")
    cap = max_price if max_price is not None else sel_price
    out = []
    for r in similar_to(sel, pool, role=role, pos=pos, top=200):
        price = est_value(r["value"], r["role"], tier)
        if price > cap:
            continue
        out.append({**r, "est_cr": _r1(price), "saving": _r1(max(0.0, sel_price - price))})
    out.sort(key=lambda r: (-r["saving"], -r["sim"]))  # biggest saving, then closest
    return out[:top]


__all__ = ["GEM_Z", "gem_threshold", "is_gem", "replacement_by_need", "similar_to"]
