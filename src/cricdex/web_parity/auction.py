"""Monte-Carlo IPL auction. EXACT mirror of `site/src/lib/auction.ts`.

Same pricing, same fitted demand model, same set order and accelerated round, same
ladder clearing — and a **bit-exact** LCG RNG seeded identically, so a run here
reproduces the browser's result trial-for-trial (to the last bit of exp / log). The parity
tests (`test_scripts/test_web_parity.py`, `test_bidplan_parity.py`) enforce this against
the TS under Node.

`opts` is a plain dict:
    {purse, squad_size, squad_min?, overseas_cap, trials, mode, retentions, real_prices, demand?}
mirroring the TS `SimOpts` (snake_cased).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from cricdex.web_parity.pricing import (
    est_value,
    has_market_inputs,
    market_price,
    price_tier,
)

# ---- pool pricing ----------------------------------------------------------


# the playing-time fields a pool row carries through (scripts/export_site.py PT_KEYS)
POOL_PT_KEYS = (
    "contrib", "contrib_bat", "contrib_bowl", "balls_faced", "balls_bowled", "p_play",
    "season_value",
)  # fmt: skip


def _retain_key(p: dict) -> float:
    """A mini auction's default retention order: expected season value (P(plays) × contribution),
    else (an export before it) value. Mirror of `retainKey` in auction.ts."""
    sv = p.get("season_value")
    return float(sv) if sv is not None else float(p["value"])


def build_pool(rows: list[dict], model: dict | None = None) -> list[dict]:
    """Price the auction pool (every active rated player). Adds crore pricing to each row: the
    market price when the model and its inputs are there (`projected_value`), with the on-field
    curve's price alongside (`onfield_value`); sorts by projected value desc."""
    out: list[dict] = []
    for r in rows:
        # pool value already tier-penalised; priced on the cautious estimate (value_sd)
        onfield = est_value(r["value"], r["role"], r.get("value_sd"), r.get("target_balls"))
        mk = market_price(r, model=model) if has_market_inputs(r, model) else None
        pv = mk["price"] if mk else onfield
        base = price_tier(pv)
        out.append(
            {
                "cricsheet_id": r["cricsheet_id"],
                "name": r["name"],
                "role": r["role"],
                "country": r.get("country") or "—",
                "is_overseas": bool(r["is_overseas"]),
                "team": r.get("team"),
                "value": r["value"],
                "projected_value": pv,
                "onfield_value": onfield,
                "p_bought": mk["p_bought"] if mk else None,
                # playing time (METHODOLOGY §6c): contribution per match, its parts and balls,
                # P(plays) and the expected season value; None in an export before 2026-10-22
                **{k: r.get(k) for k in POOL_PT_KEYS},
                # P(plays) as a free agent (the upgrade term of a lot he is in); None in older exports
                "p_play_free": r.get("p_play_free"),
                # the IPL sides he captained last season (the "Captain" badge), else None
                "captain": " / ".join(r.get("captain_teams") or []) or None,
                # the set he comes up in (capped before uncapped; None in an older export = capped)
                "capped": r.get("capped"),
                # his last IPL price as a share of that season's purse (the bidders' reference price)
                "prior_share": r.get("prior_share"),
                "base_price": base,
                "vpc": pv / base,
            }
        )
    out.sort(key=lambda p: p["projected_value"], reverse=True)
    return out


# ---- the franchises ---------------------------------------------------------

# The ten IPL franchises. They all bid by the same fitted demand model (`DEMAND`): what sets them apart
# at each lot is their squad by role, overseas places and purse (docs/METHODOLOGY.md §7).
IPL_TEAMS_DEFAULT: list[dict] = [
    {"team": t} for t in ("CSK", "MI", "RCB", "KKR", "DC", "PBKS", "SRH", "GT", "RR", "LSG")
]

# ---- retentions ------------------------------------------------------------

MINI_RETAIN = 18
SLABS = [18, 14, 11, 18, 14]


def slab_cost(i: int) -> float:
    return SLABS[i] if i < len(SLABS) else 4


def _lsum(xs) -> float:
    """Left-to-right float sum, as JS `reduce` does (Python 3.12's `sum` compensates, which can differ
    in the last bit and, in a close bid, flip a sale)."""
    t = 0.0
    for x in xs:
        t += x
    return t


def retention_inputs(data: dict | None) -> dict:
    """The real 2025 retentions (retentions.json) as simulator inputs: {"mega_ids": team → ids,
    "real_prices": id → price, "retention_slabs", "slab_holders": id → capped / uncapped,
    "fixed_retained": team → [{salary, slab_holder}] (retentions outside the pool)}. Mirror of
    `retentionInputs` in auction.ts."""
    data = data or {}
    mega_ids: dict[str, list[str]] = {}
    prices: dict[str, float] = {}
    holders: dict[str, str] = {}
    for team, rows in (data.get("mega") or {}).items():
        mega_ids[team] = [r["cricsheet_id"] for r in rows]
        for r in rows:
            prices[r["cricsheet_id"]] = r["price"]
            if r.get("slab_holder"):
                holders[r["cricsheet_id"]] = r["slab_holder"]
    fixed = {
        team: [
            {"salary": r["salary"], "slab_holder": r.get("slab_holder") or "capped"} for r in rows
        ]
        for team, rows in (data.get("unpooled") or {}).items()
    }
    return {
        "mega_ids": mega_ids,
        "real_prices": prices,
        "retention_slabs": data.get("slabs"),
        "slab_holders": holders,
        "fixed_retained": fixed,
    }


def retention_spend(team: str, retained: list[dict], opts: dict) -> tuple[float, list[float]]:
    """(what a team's retentions cost the purse, each retained player's share). Mini: 0 (the squad is
    already paid for). Mega: each at his real retention price (else the slab for his position); with
    `opts["retention_slabs"]` ({"capped": [...], "uncapped": x}) the team's retentions together cost
    the slab rule (keep.slab_charge: max(the slabs, their salaries)), capped / uncapped from
    `opts["slab_holders"]` (absent = capped), plus `opts["fixed_retained"][team]` (real retentions
    outside the pool, still charged); each player's share is the charge less the charge without him
    (keep.retention_costs). Mirror of `retentionSpend` in auction.ts."""
    from cricdex.web_parity.keep import slab_charge

    if opts["mode"] == "mini":
        return 0.0, [0.0] * len(retained)
    sal = [
        float(opts["real_prices"].get(p["cricsheet_id"], slab_cost(i)))
        for i, p in enumerate(retained)
    ]
    slabs = opts.get("retention_slabs")
    if not slabs:
        t = 0.0
        for x in sal:
            t += x
        return t, sal
    hk = opts.get("slab_holders") or {}
    holders = [
        {"salary": s, "slab_holder": hk.get(p["cricsheet_id"], "capped")}
        for p, s in zip(retained, sal, strict=True)
    ]
    for h in (opts.get("fixed_retained") or {}).get(team, []):
        holders.append({"salary": float(h["salary"]), "slab_holder": h.get("slab_holder")})
    rules = {"retention_slabs": slabs["capped"], "uncapped_retention_slab": slabs["uncapped"]}
    total = slab_charge(holders, rules) if holders else 0.0
    each = [
        total - slab_charge([h for j, h in enumerate(holders) if j != k], rules)
        for k in range(len(retained))
    ]
    return total, each


def default_retentions(
    pool: list[dict], team_cfg: list[dict], mode: str, mega_ids: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Mega = the real 2025 lists (mega_ids); Mini = each team's top-N active players by expected
    season value (`_retain_key`)."""
    out: dict[str, list[str]] = {}
    pool_ids = {p["cricsheet_id"] for p in pool}
    for cfg in team_cfg:
        team = cfg["team"]
        if mode == "mega":
            out[team] = [i for i in mega_ids.get(team, []) if i in pool_ids]
        else:
            roster = sorted((p for p in pool if p["team"] == team), key=_retain_key, reverse=True)
            out[team] = [p["cricsheet_id"] for p in roster[:MINI_RETAIN]]
    return out


# ---- the bidding ladder ------------------------------------------------------


def ladder_step(x: float) -> float:
    """The IPL bid increment at a price of x cr: 5 lakh below 1 cr, 10 lakh to 2 cr, 20 lakh to
    5 cr, 25 lakh above (Business Today, 2024-11-23, for the 2025 auction: 5 / 10 / 20 lakh, above
    3 cr at the auctioneer's call with 20 lakh the least; checked on the real prices: above 5 cr
    most 2020-2025 prices sit on 25 lakh steps). Mirror of `ladderStep` in auction.ts."""
    if x < 1.0:
        return 0.05
    if x < 2.0:
        return 0.1
    if x < 5.0:
        return 0.2
    return 0.25


def ladder_next(x: float) -> float:
    """The next ladder price above a bid of x cr (the price that beats it)."""
    s = ladder_step(x)
    return round((math.floor(x / s + 1e-9) + 1) * s, 2)


# ---- seeded RNG (bit-exact mirror of the TS LCG) ---------------------------


def rng(seed: int) -> Callable[[], float]:
    s = seed & 0xFFFFFFFF

    def _next() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return s / 4294967296

    return _next


# ---- the simulation --------------------------------------------------------

# Bidding (audit item 7; docs/METHODOLOGY.md §7, docs/AUCTION_MATH.md Part 3): each franchise's bid for
# a lot is a draw from a demand model fitted on the real sales of the 2019-2026 auctions
# (scripts/auction_demand_fit.py → config/auction_demand.json: who bought each lot and at what price, with
# each team's squad and purse rebuilt lot by lot). For each team with a place (and an overseas place) and
# the purse for his base price:
#
#   it bids at all with P = logistic(P0 + P1 × ln market price + P2 × ln base price + I_* × its needs)
#   ln bid = mu + u + SIGMA × e,  e ~ Gumbel (the team's own view), u ~ Normal(0, TAU²) (the lot's heat
#            on the day, shared by every team)
#   mu = A + C × ln market price + HINGE × max(0, ln(market price ÷ 2 cr)) + BASE × ln base price
#        + ANCHOR × ln(last price ÷ market price)
#        + MONEY × the bidding teams' mean ln(purse per open place) + STAGE × the share of the league's
#        open places already filled + MEGA (a mega auction)
#        + NEED × ln(1 + places short in his role) + OS × (overseas lot) × open overseas places ÷ open places
#        + PPS × (ln its purse per open place − that mean) + UP × (his expected contribution − its best
#        in his role so far, held to ±UP_CLIP runs a match) [+ the team's effect, if fitted]
#
# held to the team's spendable purse (less the minimum base price for each place still needed to reach
# the squad minimum); the highest bid wins at the next ladder step above the second (the base price when
# nobody else reaches it). Replaces the hand-set personalities, need × 1.5 / 0.7, the clamped budget
# pressure, the 2% clearing step and the five knobs calibrated on top of them. `opts["demand"]`
# overrides these (the fit's replays).
# Shipped: candidate R4 (round 2: D7 + the market price above the top base price), refitted on 2019-2026
# (`params` in config/auction_demand.json, rounded to 6 decimals; tests/test_auction_demand.py checks they
# match). "mega", "val" and the bidding-war heat (heat_q, tau2) are 0: candidates that lost out of time.
DEMAND = {
    "a": 0.508317, "c": 0.112129, "sigma": 0.464998, "tau": 0.551503, "p0": -1.796694,
    "p1": 0.264341, "p2": 0.193581, "base": 0.090694, "anchor": 0.015805, "money": 0.655568,
    "stage": -0.766261, "mega": 0.0, "need": 0.179662, "os": 1.11955, "pps": 1.106038,
    "up": 0.007074, "i_need": 0.38828, "i_os": -0.174691, "i_pps": -0.319634, "i_up": 0.043653,
    "val": 0.0, "i_val": 0.0, "heat_q": 0.0, "tau2": 0.0, "hinge": 0.221426,
}  # fmt: skip
LN_TOP_BASE = math.log(
    2.0
)  # the highest base price (cr): the "hinge" term is the market price above it
# Fitted team effects (ln bid; empty unless the fit chose them)
TEAM_EFFECTS: dict[str, float] = {}
# The squad's usual make-up (median end-of-auction count per role, real squads 2019-2024): "places short
# in his role" is measured against it.
ROLE_TARGETS = {"batter": 6.0, "bowler": 11.0, "all_rounder": 4.0, "keeper": 3.0}
UP_CLIP = 15.0
VAL_CLIP = 15.0
MIN_BASE = 0.3


def demand(opts: dict) -> dict:
    """The demand model in force: the shipped constants, overridden by `opts["demand"]`."""
    d = dict(DEMAND)
    d.update({k: float(v) for k, v in (opts.get("demand") or {}).items() if k in DEMAND})
    return d


# money within this of a base price counts as enough: a purse is a running sum of bids whose last bit
# (exp / log) can differ between Python and JS, and a team can be left with exactly a base price
PURSE_EPS = 1e-9


def member_value(p: dict) -> float:
    """A squad member's (or lot's) expected contribution a match: `v` when the row carries it (a Bid
    plan piece), else P(plays) × contribution (0 unrated). Mirror of `memberValue` in auction.ts."""
    v = p.get("v")
    if v is not None:
        return float(v)
    c = p.get("contrib")
    if c is None:
        return 0.0
    pp = p.get("p_play")
    return float(c) * (1.0 if pp is None else float(pp))


def _lot_value(p: dict) -> float | None:
    """A lot's expected contribution for the upgrade term: P(plays as a free agent) × contribution
    (`p_play_free` when the row has it, else `p_play`; a Bid plan piece's `v`); None unrated."""
    if p.get("v") is not None:
        return float(p["v"])
    c = p.get("contrib")
    if c is None:
        return None
    pp = p.get("p_play_free")
    if pp is None:
        pp = p.get("p_play")
    return float(c) * (1.0 if pp is None else float(pp))


def _build_franchises(pool: list[dict], team_cfg: list[dict], opts: dict):
    by_id = {p["cricsheet_id"]: p for p in pool}
    retained_ids: set[str] = set()
    bases: list[dict] = []
    for cfg in team_cfg:
        ids = opts["retentions"].get(cfg["team"], [])
        retained = [by_id[i] for i in ids if i in by_id]
        retain_overseas = 0
        for p in retained:
            retained_ids.add(p["cricsheet_id"])
            if p["is_overseas"]:
                retain_overseas += 1
        # Mega: retentions draw from the purse by the slab rule; mini: free (already paid for)
        retain_spend = retention_spend(cfg["team"], retained, opts)[0]
        bases.append(
            {
                "team": cfg["team"],
                "retained": retained,
                "retain_spend": retain_spend,
                "retain_overseas": retain_overseas,
            }
        )
    auction_pool = [p for p in pool if p["cricsheet_id"] not in retained_ids]
    return bases, auction_pool


def _fresh_state(b: dict) -> dict:
    counts = {"batter": 0, "bowler": 0, "all_rounder": 0, "keeper": 0}
    best = {"batter": 0.0, "bowler": 0.0, "all_rounder": 0.0, "keeper": 0.0}
    for p in b["retained"]:
        counts[p["role"]] += 1
        best[p["role"]] = max(best[p["role"]], member_value(p))
    return {
        "team": b["team"],
        "retained": b["retained"],
        "bought": [],
        "bought_prices": [],  # aligned with bought
        "spent": 0.0,
        "overseas": b["retain_overseas"],
        "counts": counts,
        "best": best,
    }


# Set structure (the 2025 and 2026 pages): the capped sets come up before the uncapped (a mega auction
# opens with its marquee sets, the best-known capped players, so the same order holds); inside each
# group the dearest market price first (the role sets inside a group aren't modelled). Unsold lots come
# back once in an accelerated round (fresh views, the same heat).


def lot_sequence(lots: list[dict]) -> list[dict]:
    """The order the lots come up in: capped (a row without `capped` counts as capped), then
    uncapped, each by market price. Mirror of `lotSequence` in auction.ts."""

    def key(p: dict) -> tuple:
        return (-p["projected_value"], p["cricsheet_id"])

    capped = sorted((p for p in lots if p.get("capped") is not False), key=key)
    uncapped = sorted((p for p in lots if p.get("capped") is False), key=key)
    return capped + uncapped


def _normal(rand: Callable[[], float]) -> float:
    """A standard normal draw (Marsaglia's polar method on the seeded uniforms)."""
    while True:
        u = 2.0 * rand() - 1.0
        v = 2.0 * rand() - 1.0
        s = u * u + v * v
        if 0.0 < s < 1.0:
            return u * math.sqrt(-2.0 * math.log(s) / s)


def one_trial(
    bases: list[dict],
    auction_pool: list[dict],
    opts: dict,
    seed: int,
    on_sale: Callable[[dict, int, float, float], None] | None = None,
) -> list[dict]:
    """One mock auction. `on_sale(player, team index, winning bid, price)` is called for each sale when
    given (Bid plan reads the winning bid: the price a rival would have paid); a sale in the final
    squad-minimum pass reports his base price as the bid. Mirror of `oneTrial` in auction.ts."""
    rand = rng(seed)
    states = [_fresh_state(b) for b in bases]
    dm = demand(opts)
    mode = opts.get("mode", "mini")
    sq_max = int(opts["squad_size"])
    sq_min = int(opts.get("squad_min", 18))
    os_cap = int(opts["overseas_cap"])
    min_base = float(opts.get("min_base", MIN_BASE))
    mega = 1.0 if mode == "mega" else 0.0
    team_fx = [float(TEAM_EFFECTS.get(st["team"], 0.0)) for st in states]

    def filled_of(st: dict) -> int:
        return len(st["retained"]) + len(st["bought"])

    def rem_purse_of(i: int) -> float:
        return opts["purse"] - bases[i]["retain_spend"] - states[i]["spent"]

    def buy(i: int, player: dict, price: float) -> None:
        st = states[i]
        st["bought"].append(player)
        st["bought_prices"].append(price)
        st["spent"] += price
        st["counts"][player["role"]] += 1
        r = player["role"]
        lv = _lot_value(player)
        if lv is not None:
            st["best"][r] = max(st["best"][r], lv)
        if player["is_overseas"]:
            st["overseas"] += 1

    order = lot_sequence(auction_pool)
    open0 = 0
    for st in states:
        open0 += max(0, sq_max - filled_of(st))
    open0 = max(open0, 1)
    sold: set[str] = set()
    heat: dict[str, float] = {}
    filled = [0]

    def offer(player: dict) -> None:
        pid = player["cricsheet_id"]
        if pid not in heat:
            # the lot's heat: a bidding war (sd TAU2) with probability HEAT_Q, else quiet (sd TAU)
            war = rand() < dm["heat_q"]
            heat[pid] = (dm["tau2"] if war else dm["tau"]) * _normal(rand)
        u = heat[pid]
        base = float(player["base_price"])
        mk = max(float(player["projected_value"]), 1e-6)
        anchor = player.get("anchor_price")
        if not anchor and player.get("prior_share"):
            anchor = float(player["prior_share"]) * float(opts["purse"])
        lv = _lot_value(player)
        role = player["role"]
        os_lot = bool(player["is_overseas"])
        elig: list[int] = []
        spend: list[float] = []
        lpps: list[float] = []
        for i, st in enumerate(states):
            open_ = sq_max - filled_of(st)
            if open_ <= 0:
                continue
            if os_lot and st["overseas"] >= os_cap:
                continue
            left = rem_purse_of(i)
            sp = left - max(0, sq_min - filled_of(st) - 1) * min_base
            if sp < base - PURSE_EPS:
                continue
            elig.append(i)
            spend.append(sp)
            lpps.append(math.log(max(left, min_base) / open_))
        if not elig:
            return
        money = _lsum(lpps) / len(lpps)
        lmk = math.log(mk)
        lb = math.log(max(base, 1e-6))
        lot_mu = dm["a"] + dm["c"] * lmk + dm["base"] * lb
        if anchor:
            lot_mu += dm["anchor"] * math.log(float(anchor) / mk)
        lot_mu += dm["money"] * money + dm["stage"] * (filled[0] / open0) + dm["mega"] * mega
        val = 0.0 if lv is None else max(-VAL_CLIP, min(VAL_CLIP, lv))
        lot_mu += dm["val"] * val + dm["hinge"] * max(0.0, lmk - LN_TOP_BASE)
        lot_i = dm["p0"] + dm["p1"] * lmk + dm["p2"] * lb + dm["i_val"] * val
        best_i = -1
        best_bid = 0.0
        second = 0.0
        for k, i in enumerate(elig):
            st = states[i]
            open_ = sq_max - filled_of(st)
            x_need = math.log1p(max(0.0, ROLE_TARGETS[role] - st["counts"][role]))
            x_os = (min(os_cap - st["overseas"], open_) / open_) if os_lot else 0.0
            x_pps = lpps[k] - money
            x_up = 0.0 if lv is None else max(-UP_CLIP, min(UP_CLIP, lv - st["best"][role]))
            r_in = rand()  # does it bid at all
            r_e = rand()  # its own view
            z = (
                lot_i
                + dm["i_need"] * x_need
                + dm["i_os"] * x_os
                + dm["i_pps"] * x_pps
                + dm["i_up"] * x_up
            )
            if r_in >= 1.0 / (1.0 + math.exp(-z)):
                continue
            mu = (
                lot_mu
                + dm["need"] * x_need
                + dm["os"] * x_os
                + dm["pps"] * x_pps
                + dm["up"] * x_up
                + team_fx[i]
            )
            e = -math.log(-math.log(r_e if r_e > 0.0 else 1e-12))
            bid = min(math.exp(mu + u + dm["sigma"] * e), spend[k])
            if bid > best_bid:
                second = best_bid
                best_bid = bid
                best_i = i
            elif bid > second:
                second = bid
        if best_i < 0 or best_bid < base - PURSE_EPS:
            return
        price = base if second < base else min(ladder_next(second), best_bid)
        price = max(base, price)
        buy(best_i, player, price)
        sold.add(pid)
        filled[0] += 1
        if on_sale is not None:
            on_sale(player, best_i, best_bid, price)

    for player in order:  # the sets
        offer(player)
    for player in order:  # the accelerated round: each unsold lot once more
        if player["cricsheet_id"] not in sold:
            offer(player)

    # The squad minimum is a rule: a team still short buys the cheapest leftovers at base price.
    leftovers = sorted(
        (p for p in order if p["cricsheet_id"] not in sold), key=lambda p: p["base_price"]
    )
    for player in leftovers:
        pick = -1
        fewest = float("inf")
        for i in range(len(states)):
            if filled_of(states[i]) >= sq_min:
                continue
            if player["is_overseas"] and states[i]["overseas"] >= os_cap:
                continue
            if rem_purse_of(i) < player["base_price"] - PURSE_EPS:
                continue
            if filled_of(states[i]) < fewest:
                fewest = filled_of(states[i])
                pick = i
        if pick >= 0:
            buy(pick, player, player["base_price"])
            sold.add(player["cricsheet_id"])
            if on_sale is not None:
                on_sale(player, pick, player["base_price"], player["base_price"])
    return states


# Lots per auction (task: from the real lists). The shortlists of 2018-2024 (Wikipedia's personnel pages,
# `data/curated/ipl_auction_pages`) held LOTS_PER_PLACE times the auction's open squad places (25 less
# the retained, summed over the teams): mini 4.56 (2019), 4.63 (2021), 4.66 (2023), 4.32 (2024) → median
# 4.6; mega 3.18 (2018), 2.76 (2022) → mean 3.0; and OVERSEAS_SHARE of each shortlist was overseas
# (0.377, 0.350, 0.428, 0.326, 0.357 → median 0.357). The lots are the most valuable unretained
# players (pool order) up to that many, at most that share overseas.
LOTS_PER_PLACE = {"mega": 3.0, "mini": 4.6}
OVERSEAS_SHARE = 0.357


def auction_lots(auction_pool: list[dict], open_places: int, mode: str = "mini") -> list[dict]:
    """The lots: the most valuable unretained players (pool order), LOTS_PER_PLACE[mode] × the open
    squad places of them, at most OVERSEAS_SHARE of those overseas. Mirror of `auctionLots`."""
    n = max(1, round(LOTS_PER_PLACE.get(mode, LOTS_PER_PLACE["mini"]) * max(open_places, 0)))
    max_os = round(n * OVERSEAS_SHARE)
    out: list[dict] = []
    n_os = 0
    for p in auction_pool:
        if len(out) >= n:
            break
        if p["is_overseas"]:
            if n_os >= max_os:
                continue
            n_os += 1
        out.append(p)
    return out


def open_squad_places(bases: list[dict], squad_size: int) -> int:
    """The auction's open squad places: squad maximum less the retained, summed over the teams."""
    t = 0
    for b in bases:
        t += max(0, squad_size - len(b["retained"]))
    return t


def simulate_auction(pool: list[dict], team_cfg: list[dict], opts: dict) -> dict:
    bases, auction_pool = _build_franchises(pool, team_cfg, opts)
    use_pool = auction_lots(
        auction_pool, open_squad_places(bases, int(opts["squad_size"])), opts.get("mode", "mini")
    )
    agg = [
        {
            "team": b["team"],
            "retained": len(b["retained"]),
            "ret_val": _lsum(p["projected_value"] for p in b["retained"]),
            "bought": 0,
            "spend": 0.0,
            "value": 0.0,
            "overseas": 0,
        }
        for b in bases
    ]
    top = use_pool[:20]
    marquee_wins: dict[str, dict[str, int]] = {p["cricsheet_id"]: {} for p in top}
    # per-player landing accumulators (every auctioned player)
    buys: dict[str, dict] = {
        p["cricsheet_id"]: {"count": 0, "price_sum": 0.0, "teams": {}} for p in use_pool
    }
    sample_draft: list[dict] = []
    n = opts["trials"]
    for t in range(n):
        states = one_trial(bases, use_pool, opts, 1000 + t * 7919)
        if t == n // 2:
            sample_draft = states
        for i, st in enumerate(states):
            agg[i]["bought"] += len(st["bought"])
            agg[i]["spend"] += st["spent"]
            agg[i]["value"] += agg[i]["ret_val"] + _lsum(p["projected_value"] for p in st["bought"])
            agg[i]["overseas"] += st["overseas"]
            for k, p in enumerate(st["bought"]):
                m = marquee_wins.get(p["cricsheet_id"])
                if m is not None:
                    m[st["team"]] = m.get(st["team"], 0) + 1
                b = buys.get(p["cricsheet_id"])
                if b is not None:
                    b["count"] += 1
                    b["price_sum"] += st["bought_prices"][k]
                    b["teams"][st["team"]] = b["teams"].get(st["team"], 0) + 1
    teams = [
        {
            "team": a["team"],
            "retained": a["retained"],
            "avg_bought": a["bought"] / n,
            "avg_spend": a["spend"] / n,
            "avg_value": a["value"] / n,
            "avg_overseas": a["overseas"] / n,
        }
        for a in agg
    ]
    marquee = []
    for p in top:
        m = marquee_wins[p["cricsheet_id"]]
        winners = sorted(
            ({"team": k, "pct": c / n * 100} for k, c in m.items()),
            key=lambda w: w["pct"],
            reverse=True,
        )[:3]
        marquee.append({"player": p, "winners": winners})

    def _top_winners(tm: dict[str, int]) -> list[dict]:
        return sorted(
            ({"team": k, "pct": c / n * 100} for k, c in tm.items()),
            key=lambda w: w["pct"],
            reverse=True,
        )[:3]

    # outcomes = retained (in team order) then every auctioned player (pool order)
    outcomes: list[dict] = []
    for b in bases:
        costs = retention_spend(b["team"], b["retained"], opts)[1]
        for i, p in enumerate(b["retained"]):
            cost = costs[i]
            outcomes.append(
                {
                    "cricsheet_id": p["cricsheet_id"],
                    "name": p["name"],
                    "role": p["role"],
                    "is_overseas": p["is_overseas"],
                    "status": "retained",
                    "team": b["team"],
                    "soldPct": 0,
                    "avgPrice": cost,
                    "winners": [],
                }
            )
    for p in use_pool:
        b = buys[p["cricsheet_id"]]
        winners = _top_winners(b["teams"])
        outcomes.append(
            {
                "cricsheet_id": p["cricsheet_id"],
                "name": p["name"],
                "role": p["role"],
                "is_overseas": p["is_overseas"],
                "status": "sold" if b["count"] > 0 else "unsold",
                "team": winners[0]["team"] if winners else None,
                "soldPct": b["count"] / n * 100,
                "avgPrice": b["price_sum"] / b["count"] if b["count"] > 0 else 0,
                "winners": winners,
            }
        )
    return {
        "mode": opts["mode"],
        "bases": bases,
        "pool_size": len(auction_pool),
        "auctioned": len(use_pool),
        "teams": teams,
        "marquee": marquee,
        "outcomes": outcomes,
        "sample_draft": sample_draft,
    }
