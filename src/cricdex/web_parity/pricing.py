"""Skill -> crore pricing. EXACT mirror of `site/src/lib/auction.ts`.

Keep the constants and `est_value` byte-identical to the TS so Scout's
prices and the Auction pool agree across web + desktop.
"""

from __future__ import annotations

import math

from cricdex import leagues

Role = str  # "batter" | "bowler" | "all_rounder" | "keeper"
PriceTier = str  # a tier key from config/leagues.toml: "ipl" | "smat" | "bbl" | …

# All-rounders / keepers carry a small scarcity premium.
ROLE_MULT: dict[str, float] = {
    "batter": 1.0,
    "bowler": 1.0,
    "all_rounder": 1.15,
    "keeper": 1.05,
}

# value is in runs per 100 balls above the league's average ball (see
# scout/ratings/runs_value.py), priced on the cautious estimate (PRICE_CAUTION_SD
# below); re-fitted to the earlier curve so the pool keeps the same median price
# (~1.18cr) and the same count of 10cr+ players (25).
# See the comment in auction.ts and docs/AUCTION_MATH.md.
PV_BASE = 4.03
PV_SCALE = 0.0743
PV_MAX = 27.0

# Price on a cautious estimate, not the central one: value − PRICE_CAUTION_SD × value_sd. A star
# with thousands of balls (sd ≈ 3 runs) loses ~1.5 runs; a 400-ball prodigy (sd ≈ 12) loses ~6,
# so "promising but unproven" stops reaching the cap on its posterior mean. `value` itself stays
# the central estimate for display and rankings. Mirrored in auction.ts (PRICE_CAUTION_SD).
PRICE_CAUTION_SD = 0.5

# A player's price ceiling rises with his evidence in the auction's target league (the IPL), in the
# role being priced: PV_MAX × (CEILING_FLOOR_SHARE + (1 − CEILING_FLOOR_SHARE) × min(1, balls /
# CEILING_FULL_BALLS)). 0 IPL balls → 13.5 cr at most, 163 → ~17, 449 → ~23.6, 600+ (about two full
# seasons in the role) → the full 27 cr. Applied after the cautious estimate. Mirrored in auction.ts.
CEILING_FULL_BALLS = 600
CEILING_FLOOR_SHARE = 0.5

# IPL base-price set bands (cr).
PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0]

# Cross-tier value discount — runs in a weaker comp aren't worth IPL crore.
# Mirrors the export-time penalty so Scout's est. prices agree with the pool.
# In value units (runs per 100 balls). The values live in the league registry
# (`[tiers.*]` in config/leagues.toml); the web reads the same numbers from the
# exported `leagues.json`, so Python and TS can't disagree.
TIER_PENALTY: dict[str, float] = leagues.tier_discounts()


def price_tier(pv: float) -> float:
    if pv < 2:
        return PRICE_TIERS[0]
    if pv < 4:
        return PRICE_TIERS[1]
    if pv < 7:
        return PRICE_TIERS[2]
    if pv < 11:
        return PRICE_TIERS[3]
    if pv < 16:
        return PRICE_TIERS[4]
    return PRICE_TIERS[5]


def priced_value(value: float, value_sd: float | None = None) -> float:
    """The value a price is set from: the cautious estimate value − PRICE_CAUTION_SD × sd (a
    missing or non-finite sd counts as 0)."""
    sd = value_sd if isinstance(value_sd, int | float) and math.isfinite(value_sd) else 0.0
    return value - PRICE_CAUTION_SD * max(sd, 0.0)


def price_ceiling(target_balls: float | None = None) -> float:
    """The most a player can be priced at (cr), from his balls in the target league in the role
    being priced (missing → 0)."""
    b = target_balls if isinstance(target_balls, int | float) and math.isfinite(target_balls) else 0
    share = min(1.0, max(b, 0) / CEILING_FULL_BALLS)
    return PV_MAX * (CEILING_FLOOR_SHARE + (1 - CEILING_FLOOR_SHARE) * share)


def est_value(
    value: float,
    role: Role,
    tier: PriceTier = "ipl",
    value_sd: float | None = None,
    target_balls: float | None = None,
) -> float:
    """Estimated crore value from a raw Bayes value (runs per 100 balls) — same curve the auction
    uses, on the cautious estimate (`priced_value`), capped by the IPL-evidence ceiling
    (`price_ceiling`). `tier` discounts non-IPL comps so a SMAT/BBL price is comparable."""
    adj = priced_value(value, value_sd) - TIER_PENALTY[tier]
    cap = price_ceiling(target_balls)
    return max(0.3, min(cap, PV_BASE * math.exp(PV_SCALE * adj) * ROLE_MULT[role]))
