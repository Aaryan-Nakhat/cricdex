"""Skill -> crore pricing. EXACT mirror of `site/src/lib/auction.ts`.

Keep the constants and `est_value` byte-identical to the TS so Scout's
prices and the Auction pool agree across web + desktop.
"""

from __future__ import annotations

import math

Role = str  # "batter" | "bowler" | "all_rounder" | "keeper"
PriceTier = str  # "ipl" | "smat" | "bbl"

# All-rounders / keepers carry a small scarcity premium.
ROLE_MULT: dict[str, float] = {
    "batter": 1.0,
    "bowler": 1.0,
    "all_rounder": 1.15,
    "keeper": 1.05,
}

PV_BASE = 1.6
PV_SCALE = 5.8
PV_MAX = 27.0

# IPL base-price set bands (cr).
PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0]

# Cross-tier value discount — runs in a weaker comp aren't worth IPL crore.
# Mirrors the export-time penalty so Scout's est. prices agree with the pool.
TIER_PENALTY: dict[str, float] = {
    "ipl": 0.0,
    "smat": 0.2,
    "bbl": 0.07,
    "sa20": 0.07,
    "cpl": 0.1,
}


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


def est_value(value: float, role: Role, tier: PriceTier = "ipl") -> float:
    """Estimated crore value from a raw Bayes value — same curve the auction
    uses. `tier` discounts non-IPL comps so a SMAT/BBL price is comparable."""
    adj = value - TIER_PENALTY[tier]
    return max(0.3, min(PV_MAX, PV_BASE * math.exp(PV_SCALE * adj) * ROLE_MULT[role]))
