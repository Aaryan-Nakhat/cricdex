"""3-tier Scout look-alikes. EXACT mirror of `site/src/pages/Scout.tsx`.

Pick an active IPL player -> similar players at three levels (IPL peers,
uncapped SMAT, overseas BBL), ranked by closeness of within-tier skill
standing (z). Same role/seam-spin/position matching, same gem rule, same
similarity formula as the browser.
"""

from __future__ import annotations

# Uncapped "gem": punches above its sample — high standing on low exposure.
GEM_Z = 0.6


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


__all__ = ["GEM_Z", "gem_threshold", "is_gem", "similar_to"]
