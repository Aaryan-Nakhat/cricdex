"""Scout look-alikes + gems. EXACT mirror of `site/src/lib/scout.ts`.

Pick an active IPL player -> similar players in every Scout pool (IPL peers,
uncapped SMAT, overseas leagues), ranked by closeness of within-tier skill
standing (z). Same type only (role, plus seam/spin for anyone who bowls),
optional batting-slot and country filters, same gem rule, same similarity
formula as the browser.
"""

from __future__ import annotations

# Uncapped "gem": punches above its sample — high standing on low exposure.
GEM_Z = 0.6

# `pos` value meaning "the pick's own batting band" (top / middle / lower order).
SAME_SLOT = "same"

# Batting slot -> band: a No. 3 matches openers, a finisher matches the middle order.
SLOT_BAND = {
    "opener": "top",
    "no3": "top",
    "middle": "middle",
    "finisher": "middle",
    "lower": "lower",
    "tailender": "lower",
}
BAND_LABEL = {
    "top": "Top order (1–3)",
    "middle": "Middle order (4–7)",
    "lower": "Lower order (8–11)",
}


def slot_band(pos: str | None) -> str:
    """The band a slot belongs to ("" when the slot is unknown)."""
    return SLOT_BAND.get(pos, "") if pos else ""


# Country filter modes: the pick's own country, every other country, or anyone.
COUNTRY_MODES = ("same", "overseas", "all")

# Older exports mix IOC-style and ISO-3 codes for the same nation; compare on one spelling.
_COUNTRY_ALIAS = {"RSA": "ZAF", "SA": "ZAF", "SRI": "LKA", "SL": "LKA"}

# Roles that bowl: these must match the pick's seam / spin type.
_BOWLING_ROLES = {"bowler", "all_rounder"}


def norm_country(c: str | None) -> str | None:
    """One spelling per nation ("RSA" and "ZAF" are the same team); None when unknown."""
    if not c:
        return None
    up = c.strip().upper()
    return _COUNTRY_ALIAS.get(up, up) if up else None


def gem_threshold(smat: list[dict]) -> float | None:
    """Median SMAT exposure (balls > 0) — the gem cutoff."""
    vals = sorted(p["balls"] for p in smat if p.get("balls", 0) > 0)
    if not vals:
        return None
    # Mirror the TS: balls[floor(len/2)] — the upper-middle value for an even
    # count (not averaged), the middle one for an odd count.
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
    country: str = "all",
    fallback_country: str | None = None,
) -> list[dict]:
    """Most-similar players of the chosen role (defaults to the pick's own), of
    the same type: a bowler or all-rounder only matches players who bowl the
    same way (seam with seam, spin with spin). `pos` narrows the batting slot
    ("" = any, "same" = the pick's own band: top / middle / lower order, else
    one exact slot). `country` keeps the pick's country ("same"), every other
    country ("overseas") or all; a pool player with no country on file takes
    `fallback_country` (a domestic pool).
    Returns rows [{..player.., "sim": float}] sorted by similarity desc, top-N.
    """
    role = role or sel["role"]
    want_band = slot_band(sel.get("batting_position")) if pos == SAME_SLOT else ""
    want_pos = "" if pos == SAME_SLOT else (pos or "")
    sel_country = norm_country(sel.get("country"))
    fallback = norm_country(fallback_country)
    out = []
    for p in pool:
        if p["cricsheet_id"] == sel["cricsheet_id"] or p["role"] != role:
            continue
        if (
            role in _BOWLING_ROLES
            and sel["role"] in _BOWLING_ROLES
            and sel.get("bowling_category")
            and p.get("bowling_category") != sel["bowling_category"]
        ):
            continue
        if want_pos and p.get("batting_position") != want_pos:
            continue
        if want_band and slot_band(p.get("batting_position")) != want_band:
            continue
        if country != "all" and sel_country:
            pc = norm_country(p.get("country")) or fallback
            if pc is None:  # unknown country: can't say it's the same or overseas
                continue
            if (pc != sel_country) if country == "same" else (pc == sel_country):
                continue
        sim = max(0.0, 1 - abs(p["z"] - sel["z"]) / 2.5)
        out.append({**p, "sim": sim})
    out.sort(key=lambda r: r["sim"], reverse=True)
    return out[:top]


__all__ = [
    "BAND_LABEL",
    "COUNTRY_MODES",
    "GEM_Z",
    "SAME_SLOT",
    "SLOT_BAND",
    "gem_threshold",
    "is_gem",
    "norm_country",
    "similar_to",
    "slot_band",
]
