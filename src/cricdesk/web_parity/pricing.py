"""Skill -> crore pricing. EXACT mirror of `site/src/lib/auction.ts`.

Keep the constants and `est_value` byte-identical to the TS so Scout's
prices and the Auction pool agree across web + desktop.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

Role = str  # "batter" | "bowler" | "all_rounder" | "keeper"

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
# The base price a player picks (the 2026 auction's eight brackets, 30 lakh to 2 cr). Until the official
# list is out a player's base is INFERRED from his market price (`price_tier`) over the six brackets
# players actually pick: in 2024-26 one lot opened at 0.4 cr and four at 1.25 cr, so a price can't
# say when those two apply (ipl_auction_history.json).
BASE_BRACKETS = [0.3, 0.4, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
PRICE_TIERS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0]

# A rating from another league is put on the IPL rating scale by the fitted league translation
# (cricdesk.scout.translation, per league and role) before it is priced: the export does it (the pool's
# `value`, Scout's `ipl_value`), so every price here takes a value already on the IPL scale. (Until
# 2026-10-23: one hand-set discount per league, TIER_PENALTY, taken off here and in auction.ts.)


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
    value_sd: float | None = None,
    target_balls: float | None = None,
) -> float:
    """Estimated crore value from a value on the IPL rating scale (runs per 100 balls) — the
    on-field curve, on the cautious estimate (`priced_value`), capped by the IPL-evidence ceiling
    (`price_ceiling`). A rating from another league must be translated first
    (cricdesk.scout.translation). `role` is kept for the callers: the hand-set all-rounder ×1.15 /
    keeper ×1.05 premium was removed on 2026-10-22 (audit item 6; the market model's fitted role
    terms are the price premium, and a player's second discipline counts through his contribution
    per match, scout/playing_time.py). Mirror of `iplPrice` in auction.ts."""
    adj = priced_value(value, value_sd)
    cap = price_ceiling(target_balls)
    return max(0.3, min(cap, PV_BASE * math.exp(PV_SCALE * adj)))


# ---- market price: fitted to real IPL auction prices --------------------------------------------
#
# `est_value` above prices what a player does on the field (the hand-set curve, now called his
# "on-field worth"). `market_price` is what the auction market pays for a player like him: a
# hurdle model fitted to every IPL auction 2009-2026 (scripts/ipl_price_model.py, data from
# data/curated/ipl_auction_history.json): ln(price / purse) from his cautious value, nationality,
# international caps, age, IPL experience and the auction type, and, for a player with an IPL
# record, the chance a franchise buys him at all. The coefficients live in config/price_model.json
# (the site export copies it to data/<league>/price_model.json for the web); the feature
# definitions below are mirrored exactly in site/src/lib/auction.ts (`marketFeatures`), and
# test_scripts/test_web_parity.py checks both on fixed inputs. docs/METHODOLOGY.md §6.

MARKET_AGE_CENTRE = 28.0
MARKET_PV_MIN = -40.0
MARKET_PV_MAX = 60.0
MARKET_GAP_MAX = 6.0  # years since his last IPL match, capped
# `high` = the upper quartile of what players like him fetch: the median × e^(0.674 × residual sd)
MARKET_HIGH_Z = 0.674
# recent internationals saturate: 1 - e^(-caps in two years / this) (METHODOLOGY §6b)
RECENT_SAT_SCALE = 10.0
# The prior market price (`prior` = ln(prior_share / PRIOR_REF_SHARE), clamped): 2% of the purse is
# about 2.5 cr in 2026. Seasons since it are capped at PRIOR_YEARS_MAX.
PRIOR_REF_SHARE = 0.02
PRIOR_MIN = -4.0
PRIOR_MAX = 3.0
PRIOR_YEARS_MAX = 6.0
# The brand (since 2026-10-27, recipe AA/AB, METHODOLOGY §6b): `wiki_views` = the mean monthly human
# views of his English Wikipedia article over the 12 complete months before the auction
# (scout/identity/pageviews.py; Wikimedia Pageviews API, CC0). brand = ln(1 + views / BRAND_SCALE).
BRAND_SCALE = 1000.0

_MODEL_PATHS = (
    Path(__file__).resolve().parents[3] / "config" / "price_model.json",
    Path(__file__).resolve().parents[1] / "price_model.json",  # the copy shipped in the package
)


@lru_cache(maxsize=4)
def load_price_model(path: str | None = None) -> dict | None:
    """The fitted market-price model ($CRICDESK_PRICE_MODEL, else config/price_model.json, else the
    package copy); None when there is none (prices then fall back to the on-field curve)."""
    cands = [Path(path)] if path else []
    env = os.environ.get("CRICDESK_PRICE_MODEL")
    if env:
        cands.append(Path(env))
    cands += list(_MODEL_PATHS)
    for p in cands:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, int | float) and math.isfinite(x) else None


def market_features(row: dict, cycle: str, pv_max: float | None = None) -> dict[str, float]:
    """A player's market-model features from a pool / squad row. `row` keys: `price_value` (his
    value as the price recipe takes it, runs per 100 balls; missing = unrated: `value_input`),
    `price_value_sd` (its sd; missing → `value_sd`), `role`, `is_overseas` (or `overseas`), `intl_caps` (men's T20I + ODI + Test
    matches), `intl_caps_2y` (those in the two years before the auction), `age`, `ipl_balls`,
    `ipl_seasons`, `ipl_gap` (years since his last IPL match; missing = never played it), and the
    captaincy known before the auction (scout/identity/captains.py): `captain_ipl_last` (captained
    an IPL side the season before), `captain_ipl_seasons`, `captain_intl_2y` (captained his country
    in the two calendar years before).
    `wiki_views` (his article's mean monthly views in the 12 months before the auction; missing = no
    article or no reading: the brand features, METHODOLOGY §6b). `ipl_matches_2y` (his IPL matches in
    the two seasons before the auction) and `bowling_category` ("seam" / "spin"): the refit's terms
    (METHODOLOGY §6b, 2026-10-30).
    `cycle` = "mega" | "mini". `pv_max` (the model's `price.pv_max`: the largest priced value in its
    training rows) holds the priced value to the range the market has priced, so a value beyond the
    best player ever sold is priced as that player (no extrapolation); missing → MARKET_PV_MAX.
    Same definitions as `marketFeatures` in auction.ts."""
    v = _num(row.get("price_value"))
    rated = v is not None
    pv = 0.0
    top = MARKET_PV_MAX if pv_max is None else min(MARKET_PV_MAX, float(pv_max))
    if rated:
        sd = row.get("price_value_sd")
        sd = row.get("value_sd") if sd is None else sd
        pv = min(top, max(MARKET_PV_MIN, priced_value(v, sd)))
    ov = row.get("is_overseas", row.get("overseas"))
    ov = 1.0 if ov else 0.0
    caps_n = _num(row.get("intl_caps")) or 0.0
    caps = math.log1p(max(caps_n, 0.0))
    recent = math.log1p(max(_num(row.get("intl_caps_2y")) or 0.0, 0.0))
    capped_ind = (1.0 if caps_n > 0 else 0.0) * (1.0 - ov)
    age = _num(row.get("age"))
    a = (age - MARKET_AGE_CENTRE) if age is not None else 0.0
    gap = _num(row.get("ipl_gap"))
    never = 1.0 if gap is None else 0.0
    role = row.get("role")
    # the market's last verdict on him (scripts/ipl_price_model.market_verdicts): the price a
    # franchise last paid, as a share of that season's purse, the seasons since and whether it was
    # a mega-auction retention rather than a sale
    ps = _num(row.get("prior_share"))
    has_prior = ps is not None and ps > 0
    prior = 0.0
    p_years = 0.0
    if has_prior:
        prior = min(PRIOR_MAX, max(PRIOR_MIN, math.log(ps / PRIOR_REF_SHARE)))
        p_years = min(max(_num(row.get("prior_years")) or 0.0, 0.0), PRIOR_YEARS_MAX)
    views = _num(row.get("wiki_views"))
    brand = math.log1p(max(views, 0.0) / BRAND_SCALE) if views is not None else 0.0
    # a seam bowler (a bowler or all-rounder who bowls seam): the market pays for pace the rating
    # scale doesn't see (METHODOLOGY §6b)
    pace = (
        1.0 if role in ("bowler", "all_rounder") and row.get("bowling_category") == "seam" else 0.0
    )
    # recent internationals, saturating: the first caps say most (a log count doubled a price for one
    # India cap; METHODOLOGY §6b)
    recent_sat = 1.0 - math.exp(-max(_num(row.get("intl_caps_2y")) or 0.0, 0.0) / RECENT_SAT_SCALE)
    return {
        "pv": pv,
        "pv_pos_sq": (max(pv, 0.0) ** 2) / 100.0,
        "unrated": 0.0 if rated else 1.0,
        "overseas": ov,
        "pv_x_overseas": pv * ov,
        "caps": caps,
        "caps_x_indian": caps * (1.0 - ov),
        "pv_x_capped_indian": pv * capped_ind,
        "recent_caps": recent,
        "recent_caps_x_indian": recent * (1.0 - ov),
        "age": a,
        "age_sq": a * a / 10.0,
        "age_missing": 0.0 if age is not None else 1.0,
        "ipl_balls": math.log1p(max(_num(row.get("ipl_balls")) or 0.0, 0.0)),
        "ipl_seasons": min(_num(row.get("ipl_seasons")) or 0.0, 15.0),
        "never_ipl": never,
        "ipl_gap": 0.0 if gap is None else min(max(gap, 0.0), MARKET_GAP_MAX),
        "all_rounder": 1.0 if role == "all_rounder" else 0.0,
        "keeper": 1.0 if role == "keeper" else 0.0,
        "bowler": 1.0 if role == "bowler" else 0.0,
        "mega": 1.0 if cycle == "mega" else 0.0,
        "captain_ipl": 1.0 if (_num(row.get("captain_ipl_last")) or 0.0) > 0 else 0.0,
        "captain_seasons": math.log1p(max(_num(row.get("captain_ipl_seasons")) or 0.0, 0.0)),
        "captain_intl": 1.0 if (_num(row.get("captain_intl_2y")) or 0.0) > 0 else 0.0,
        "prior": prior,
        "no_prior": 0.0 if has_prior else 1.0,
        "prior_years": p_years,
        "prior_x_years": prior * p_years,
        "prior_retained": 1.0 if has_prior and row.get("prior_retained") else 0.0,
        "brand": brand,
        "no_brand": 0.0 if views is not None else 1.0,
        "brand_x_indian": brand * (1.0 - ov),
        # his value as far as the IPL has seen it (value x ln IPL balls / 8), and his value when he
        # is a capped Indian out of the India side (no international in the two years before)
        "pv_x_ipl_evidence": pv * math.log1p(max(_num(row.get("ipl_balls")) or 0.0, 0.0)) / 8.0,
        "pv_x_indian_no_recent": pv * capped_ind * (1.0 if recent == 0.0 else 0.0),
        # the 2026-10-30 refit's terms (METHODOLOGY §6b)
        "ipl_recent": math.log1p(max(_num(row.get("ipl_matches_2y")) or 0.0, 0.0)),
        "pace": pace,
        "pv_x_pace": pv * pace,
        "recent_sat_x_indian": recent_sat * (1.0 - ov),
        "recent_sat_x_overseas": recent_sat * ov,
        # one pooled captaincy term (METHODOLOGY §6b): led an IPL side last season or his country in
        # the two years before
        "captain_any": 1.0
        if (_num(row.get("captain_ipl_last")) or 0.0) > 0
        or (_num(row.get("captain_intl_2y")) or 0.0) > 0
        else 0.0,
    }


def _linear(part: dict, f: dict[str, float]) -> float:
    """intercept + Σ coef × feature, summed left to right in the model's feature order."""
    t = float(part["intercept"])
    for k, c in part["coef"].items():
        t += float(c) * f[k]
    return t


def link_share(part: dict, eta: float) -> float:
    """The median ln share of the purse from the linear index η (`_linear`), by `part["link"]`:
    "log" (or none): η itself; "sat": ln S + ln σ(η), σ the logistic function and S =
    `cap_share`, the fitted most one franchise pays for one player as a share of its purse (the
    price saturates there instead of growing without limit; METHODOLOGY §6b). Mirror of
    `linkShare` in auction.ts."""
    link = part.get("link") or {}
    if link.get("kind") != "sat":
        return eta
    # ln σ(η) = −ln(1 + e^(−η)), written to stay finite for large |η|
    ls = -math.log1p(math.exp(-eta)) if eta >= 0 else eta - math.log1p(math.exp(eta))
    return math.log(float(link["cap_share"])) + ls


def calibrate(part: dict, lin: float) -> float:
    """The calibration of the linear predictor (ln price / purse): a monotone piecewise-
    linear map through `part["calibration"]` knots {x, y} (x increasing), continued below the first
    knot at slope 1 and above the last at the map's `hi_slope` (the slope of real prices on the
    prediction over the top fifth of the lots, fitted; 1 when absent), plus `part["shift"]` (the
    group's level). No calibration → lin. Mirror of `calibrate` in auction.ts."""
    cal = part.get("calibration")
    out = lin
    if cal and cal.get("x"):
        xs, ys = cal["x"], cal["y"]
        n = len(xs)
        hi = cal.get("hi_slope")
        hi = 1.0 if hi is None else float(hi)
        if lin <= xs[0]:
            out = lin + (ys[0] - xs[0])
        elif lin >= xs[n - 1]:
            out = ys[n - 1] + hi * (lin - xs[n - 1])
        else:
            i = 0
            while i < n - 2 and lin > xs[i + 1]:
                i += 1
            out = ys[i] + (lin - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    return out + float(part.get("shift") or 0.0)


def calibration_part(part: dict, f: dict[str, float]) -> dict:
    """The calibration that applies to a player: the first of `part["groups"]` whose `when` holds
    (every {feature: [lo, hi]} with lo <= feature <= hi), else `part` itself. Groups let each kind
    of player (overseas, capped Indian, uncapped Indian) have its own map and shift. Mirror of
    `calibrationPart` in auction.ts."""
    for g in part.get("groups") or []:
        if all(lo <= f[k] <= hi for k, (lo, hi) in g["when"].items()):
            return g
    return part


def market_price(
    row: dict, competition: dict | None = None, model: dict | None = None
) -> dict[str, float | None]:
    """{"price": cr, "high": cr, "p_bought": 0-1 or None} — what the auction market pays for this
    player (the model's median), the upper quartile of that (`high`), both at least the floor
    (the lowest base price), and, for a player with an IPL record, the chance he's bought at all.
    No ceiling: the fitted link saturates the median at the budget limit (`link_share`).
    `competition` = {"cycle", "purse"} (the model's own default when missing). Mirror of
    `marketPrice` in auction.ts."""
    model = model or load_price_model()
    if model is None:
        raise RuntimeError("no price model: run scripts/ipl_price_model.py fit")
    comp = competition or model["competition"]
    f = market_features(row, comp["cycle"], model["price"].get("pv_max"))
    cal = calibration_part(model["price"], f)
    raw = link_share(model["price"], _linear(model["price"], f))
    lin = calibrate(cal, raw)
    floor = float(model["floor_cr"])
    price = max(floor, float(comp["purse"]) * math.exp(lin))
    hi = _upper(model["price"], cal, raw, lin)
    # resale: a player the market priced at the last auction (`resale.max_years` seasons ago or
    # less) is priced from both, ln share = a + b × ln(the model's share) + c × ln(his last share)
    # + d × the seasons since + e × (it was a retention) + f × ln(his last share) × the seasons since,
    # fitted on the resold lots
    # (scripts/ipl_price_model.py resale); the upper quartile moves with it
    rs = model["price"].get("resale")
    ps = _num(row.get("prior_share"))
    py = _num(row.get("prior_years"))
    if rs and ps is not None and ps > 0 and py is not None and py <= float(rs["max_years"]):
        base = math.log(price / float(comp["purse"]))
        adj = (
            float(rs["intercept"]) + float(rs["b_model"]) * base + float(rs["c_last"]) * math.log(ps)
            + float(rs.get("d_years", 0.0)) * py
            + float(rs.get("e_retained", 0.0)) * (1.0 if row.get("prior_retained") else 0.0)
            + float(rs.get("f_last_years", 0.0)) * math.log(ps) * py
        )  # fmt: skip
        price = max(floor, float(comp["purse"]) * math.exp(adj))
        # the upper quartile keeps its gap above the model's own (unfloored) median: measured from the
        # floored price instead it fell below the price for a player the model puts under the floor
        hi = adj + (hi - lin)
    high = max(floor, float(comp["purse"]) * math.exp(hi))
    p = None
    if f["never_ipl"] == 0.0:
        # fitted on players at most `gap_max` years out of the IPL (its risk window): a longer
        # absence is read as the window's edge, not extrapolated
        gm = model["bought"].get("gap_max")
        fb = f if gm is None else {**f, "ipl_gap": min(f["ipl_gap"], float(gm))}
        p = 1.0 / (1.0 + math.exp(-_linear(model["bought"], fb)))
    return {"price": price, "high": high, "p_bought": p}


def _upper(price: dict, cal: dict, raw: float, lin: float) -> float:
    """The upper quartile's ln share. With a fitted `spread` {a, b} (the 75th percentile of the
    out-of-fold residuals as a + b × the calibrated prediction, METHODOLOGY §6b): lin + that, at least
    0 (the spread widens toward the top, where one sd was too narrow). Without it: a player 0.674
    residual sd above him on the model's index, through the same calibration."""
    sp = price.get("spread")
    if sp:
        return lin + max(0.0, float(sp["a"]) + float(sp["b"]) * lin)
    return calibrate(cal, raw + MARKET_HIGH_Z * float(price["resid_sd"]))


def has_market_inputs(row: dict, model: dict | None = None) -> bool:
    """True when this row can take the market price: a model is loaded and the row carries its
    inputs (an export from before the market model doesn't). Mirror of `hasMarketInputs`."""
    return (model or load_price_model()) is not None and "price_value" in row


def value_input(model: dict | None = None) -> str:
    """Which value the market price was fitted on, so the export hands it the same one: "legacy"
    (the blend every recipe up to T used: one discount per league and the 300-ball switch,
    cricdesk.scout.translation.legacy_blend), "translated" (the fitted league translation) or
    "time_aware" (the legacy blend moved to the coming season by the time-aware rating,
    scout/ratings/drift.py; recipe Z, since 2026-10-27). Read from the model's `value_input`; a model
    without it is "legacy"."""
    m = model or load_price_model() or {}
    return str(m.get("value_input") or "legacy")


def scout_ipl_value(r: dict) -> tuple[float, float | None]:
    """A Scout row's value on the IPL rating scale and its sd: `ipl_value` / `ipl_value_sd` (the
    export translates every league's row, scripts/export_site.py), else — a row exported before
    2026-10-23 — its own `value` / `value_sd`. Mirror of `scoutIplValue` in auction.ts."""
    if r.get("ipl_value") is not None:
        return float(r["ipl_value"]), r.get("ipl_value_sd")
    return float(r["value"]), r.get("value_sd")


def scout_price(r: dict, model: dict | None = None) -> float:
    """A Scout row's estimated IPL price: the market price when the model and the row's market inputs
    are there (on the row's `price_value` / `price_value_sd`, the value the price recipe takes, which
    the export sets; else on his value on the IPL scale), else the on-field curve (`est_value`) on
    his value on the IPL scale. Mirror of `scoutPrice` in auction.ts."""
    v, sd = scout_ipl_value(r)
    if (model or load_price_model()) is not None and "intl_caps" in r:
        if r.get("price_value") is None:
            r = {**r, "price_value": v, "price_value_sd": sd}
        return market_price(r, model=model)["price"]
    return est_value(v, r["role"], sd, r.get("target_balls"))


# ---- the prior market price: the market's last verdict on a player ------------------------------
#
# Python only: the training rows (scripts/ipl_price_model.py) and the site export
# (scripts/export_site.py) both build `prior_share` / `prior_years` / `prior_retained` with these from
# data/curated/ipl_auction_history.json; the TS reads the exported fields (marketFeatures).


def verdict_key(r: dict) -> str | None:
    """A history row's player: his Cricsheet id, else "wiki:<Wikipedia title>" (a player with no
    ball-by-ball record, so a squad row with the same title finds his price)."""
    if r.get("cricsheet_id"):
        return str(r["cricsheet_id"])
    return f"wiki:{r['wiki_title']}" if r.get("wiki_title") else None


# Retention kinds that are a franchise's verdict on a player's price: a mega-auction retention (the
# franchise chose to pay him this rather than re-buy him) and the 2016 draft of the two new sides.
# A mini year's retained list is not one: those salaries are older contracts (an auction price or a
# mega retention already counted in its own season).
VERDICT_RETENTION_KINDS = ("retained", "draft")


def market_verdicts(hist: dict) -> dict[str, list[tuple[int, float, bool]]]:
    """`verdict_key` → [(season, share of that season's purse, was a retention)], every market
    verdict on the player: each auction he was sold at (the price, a bid: for an overseas buy over the
    2025-27 fee cap the franchise still paid the bid) and each mega-auction retention or draft (his
    agreed salary). The share of the purse makes 2008's US$ and 2026's 125 cr comparable."""
    out: dict[str, list[tuple[int, float, bool]]] = {}
    for r in hist["lots"]:
        key = verdict_key(r)
        if r.get("sold") and key and r.get("price_cr"):
            purse = hist["auctions"][str(r["season"])]["purse_cr"]
            out.setdefault(key, []).append((r["season"], r["price_cr"] / purse, False))
    for r in hist["retentions"]:
        a = hist["auctions"].get(str(r["season"]))
        key = verdict_key(r)
        if not (key and r.get("salary_cr") and a):
            continue
        if r["kind"] not in VERDICT_RETENTION_KINDS:
            continue
        if r["kind"] == "retained" and a["kind"] != "mega":
            continue
        out.setdefault(key, []).append((r["season"], r["salary_cr"] / a["purse_cr"], True))
    return out


def prior_verdict(v: list[tuple[int, float, bool]], season: int) -> dict:
    """The latest market verdict before `season`'s auction: {prior_share, prior_years (seasons
    since), prior_retained}; Nones when there is none. A retention and a sale in the same season
    (can't happen) would keep the sale."""
    prev = [x for x in v if x[0] < season]
    if not prev:
        return {"prior_share": None, "prior_years": None, "prior_retained": None}
    s, share, ret = max(prev, key=lambda x: (x[0], not x[2]))
    return {"prior_share": share, "prior_years": season - s, "prior_retained": ret}
