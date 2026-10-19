"""Monte-Carlo IPL auction. EXACT mirror of `site/src/lib/auction.ts`.

Same pricing, same franchise personalities, same two-phase fill, same
second-price clearing — and a **bit-exact** LCG RNG seeded identically, so a
run here reproduces the browser's result trial-for-trial. The parity test
(`test_scripts/test_web_parity.py`) enforces this against the TS under Node.

`opts` is a plain dict:
    {purse, squad_size, overseas_cap, trials, mode, retentions, real_prices}
mirroring the TS `SimOpts` (snake_cased).
"""

from __future__ import annotations

from collections.abc import Callable

from cricdex.web_parity.pricing import est_value, price_ceiling, price_tier

# ---- pool pricing ----------------------------------------------------------


def build_pool(rows: list[dict]) -> list[dict]:
    """Price the auction pool (every active rated player). Adds crore pricing
    to each row; sorts by projected value desc."""
    out: list[dict] = []
    for r in rows:
        # pool value already tier-penalised; priced on the cautious estimate (value_sd)
        pv = est_value(r["value"], r["role"], "ipl", r.get("value_sd"), r.get("target_balls"))
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
                "base_price": base,
                "vpc": pv / base,
                # his price ceiling (rises with IPL balls): bidding can't clear him above it
                "price_cap": price_ceiling(r.get("target_balls")),
            }
        )
    out.sort(key=lambda p: p["projected_value"], reverse=True)
    return out


# ---- franchise personalities -----------------------------------------------

ARCHETYPES: list[dict] = [
    {
        "id": "MarqueeChaser",
        "blurb": "Overpays for stars; empties the purse early.",
        "aggression": 1.35,
        "risk": 0.2,
        "overseas_appetite": 0.6,
        "role_mins": {"batter": 6, "bowler": 4, "all_rounder": 4, "keeper": 2},
    },
    {
        "id": "ValueHunter",
        "blurb": "Disciplined; hunts bargains, walks away from bidding wars.",
        "aggression": 0.85,
        "risk": 0.3,
        "overseas_appetite": 0.45,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
    {
        "id": "OverseasHeavy",
        "blurb": "Loads up on overseas talent up to the cap.",
        "aggression": 1.15,
        "risk": 0.18,
        "overseas_appetite": 0.9,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
    {
        "id": "IndianFocus",
        "blurb": "Builds a local core; sparing on overseas slots.",
        "aggression": 1.05,
        "risk": 0.15,
        "overseas_appetite": 0.2,
        "role_mins": {"batter": 7, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
    {
        "id": "AllRounderStack",
        "blurb": "Hoards all-rounders for balance.",
        "aggression": 1.1,
        "risk": 0.22,
        "overseas_appetite": 0.55,
        "role_mins": {"batter": 4, "bowler": 4, "all_rounder": 6, "keeper": 2},
    },
    {
        "id": "Balanced",
        "blurb": "Even spread, steady cap management.",
        "aggression": 1.0,
        "risk": 0.15,
        "overseas_appetite": 0.5,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
]
ARCH_BY_ID: dict[str, dict] = {a["id"]: a for a in ARCHETYPES}

IPL_TEAMS_DEFAULT: list[dict] = [
    {"team": "CSK", "personality": "Balanced"},
    {"team": "MI", "personality": "MarqueeChaser"},
    {"team": "RCB", "personality": "MarqueeChaser"},
    {"team": "KKR", "personality": "AllRounderStack"},
    {"team": "DC", "personality": "IndianFocus"},
    {"team": "PBKS", "personality": "ValueHunter"},
    {"team": "SRH", "personality": "OverseasHeavy"},
    {"team": "GT", "personality": "Balanced"},
    {"team": "RR", "personality": "ValueHunter"},
    {"team": "LSG", "personality": "OverseasHeavy"},
]

# ---- retentions ------------------------------------------------------------

MINI_RETAIN = 18
SLABS = [18, 14, 11, 18, 14]


def slab_cost(i: int) -> float:
    return SLABS[i] if i < len(SLABS) else 4


def default_retentions(
    pool: list[dict], team_cfg: list[dict], mode: str, mega_ids: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Mega = the real 2025 lists (mega_ids); Mini = each team's top-N active
    players by value."""
    out: dict[str, list[str]] = {}
    pool_ids = {p["cricsheet_id"] for p in pool}
    for cfg in team_cfg:
        team = cfg["team"]
        if mode == "mega":
            out[team] = [i for i in mega_ids.get(team, []) if i in pool_ids]
        else:
            roster = sorted(
                (p for p in pool if p["team"] == team), key=lambda p: p["value"], reverse=True
            )
            out[team] = [p["cricsheet_id"] for p in roster[:MINI_RETAIN]]
    return out


# ---- seeded RNG (bit-exact mirror of the TS LCG) ---------------------------


def rng(seed: int) -> Callable[[], float]:
    s = seed & 0xFFFFFFFF

    def _next() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return s / 4294967296

    return _next


# ---- the simulation --------------------------------------------------------

MIN_BASE = 0.3
MIN_SQUAD = 20
# No player clears above the real IPL record (Pant, 27 cr, 2025 mega auction).
PRICE_CAP = 27.0
# Budget pressure: a team with more purse per open slot than the league bids
# harder (and a stretched one softer) — (ratio ** EXP), clamped.
PRESSURE_EXP = 0.5
PRESSURE_MIN = 0.75
PRESSURE_MAX = 1.6


def _build_franchises(pool: list[dict], team_cfg: list[dict], opts: dict):
    by_id = {p["cricsheet_id"]: p for p in pool}
    retained_ids: set[str] = set()
    bases: list[dict] = []
    for cfg in team_cfg:
        ids = opts["retentions"].get(cfg["team"], [])
        retained = [by_id[i] for i in ids if i in by_id]
        retain_spend = 0.0
        retain_overseas = 0
        for i, p in enumerate(retained):
            retained_ids.add(p["cricsheet_id"])
            if opts["mode"] != "mini":
                retain_spend += opts["real_prices"].get(p["cricsheet_id"], slab_cost(i))
            if p["is_overseas"]:
                retain_overseas += 1
        bases.append(
            {
                "team": cfg["team"],
                "personality": cfg["personality"],
                "retained": retained,
                "retain_spend": retain_spend,
                "retain_overseas": retain_overseas,
            }
        )
    auction_pool = [p for p in pool if p["cricsheet_id"] not in retained_ids]
    return bases, auction_pool


def _fresh_state(b: dict) -> dict:
    counts = {"batter": 0, "bowler": 0, "all_rounder": 0, "keeper": 0}
    for p in b["retained"]:
        counts[p["role"]] += 1
    return {
        "team": b["team"],
        "personality": b["personality"],
        "retained": b["retained"],
        "bought": [],
        "bought_prices": [],  # aligned with bought
        "spent": 0.0,
        "overseas": b["retain_overseas"],
        "counts": counts,
    }


def one_trial(bases: list[dict], auction_pool: list[dict], opts: dict, seed: int) -> list[dict]:
    rand = rng(seed)
    states = [_fresh_state(b) for b in bases]

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
        if player["is_overseas"]:
            st["overseas"] += 1

    # Reshuffle order by a small random nudge — rand() called once per pool
    # player, in pool order (same as the TS .map).
    keyed = [(p, p["projected_value"] * (1 + (rand() - 0.5) * 0.1)) for p in auction_pool]
    keyed.sort(key=lambda x: x[1], reverse=True)
    order = [x[0] for x in keyed]
    sold: set[str] = set()

    def per_slot_of(i: int) -> float:
        slots_left = opts["squad_size"] - filled_of(states[i])
        return rem_purse_of(i) / slots_left if slots_left > 0 else 0.0

    def bid_round(target: int) -> None:
        for player in order:
            if player["cricsheet_id"] in sold:
                continue
            # league purse-per-open-slot, for budget pressure
            open_slots = [
                per_slot_of(i)
                for i in range(len(states))
                if filled_of(states[i]) < opts["squad_size"]
            ]
            league_per_slot = sum(open_slots) / len(open_slots) if open_slots else 0.0
            best_team = -1
            best_bid = 0.0
            second_bid = player["base_price"]
            for i in range(len(states)):
                st = states[i]
                arc = ARCH_BY_ID.get(st["personality"], ARCH_BY_ID["Balanced"])
                if filled_of(st) >= target:
                    continue
                if player["is_overseas"] and st["overseas"] >= opts["overseas_cap"]:
                    continue
                slots_left = opts["squad_size"] - filled_of(st)
                spendable = rem_purse_of(i) - (slots_left - 1) * MIN_BASE
                if spendable < player["base_price"]:
                    continue
                need = (
                    1.5 if st["counts"][player["role"]] < arc["role_mins"][player["role"]] else 0.7
                )
                overseas_bias = arc["overseas_appetite"] * 1.4 if player["is_overseas"] else 1
                jitter = 1 + (rand() - 0.5) * 2 * arc["risk"]
                pressure = 1.0
                if league_per_slot > 0:
                    pressure = min(
                        PRESSURE_MAX,
                        max(
                            PRESSURE_MIN,
                            (per_slot_of(i) / league_per_slot) ** PRESSURE_EXP,
                        ),
                    )
                wtp = (
                    player["projected_value"]
                    * arc["aggression"]
                    * need
                    * overseas_bias
                    * jitter
                    * pressure
                )
                wtp = min(wtp, spendable)
                if wtp < player["base_price"]:
                    continue
                if wtp > best_bid:
                    second_bid = best_bid if best_bid > 0 else player["base_price"]
                    best_bid = wtp
                    best_team = i
                elif wtp > second_bid:
                    second_bid = wtp
            if best_team >= 0:
                price = min(PRICE_CAP, player["price_cap"], best_bid, second_bid * 1.02)
                buy(best_team, player, max(player["base_price"], price))
                sold.add(player["cricsheet_id"])

    bid_round(MIN_SQUAD)  # everyone reaches the minimum first
    bid_round(opts["squad_size"])  # then top up toward the cap

    # Safety: any team still under MIN gets the cheapest leftovers at base.
    leftovers = sorted(
        (p for p in order if p["cricsheet_id"] not in sold), key=lambda p: p["base_price"]
    )
    for player in leftovers:
        pick = -1
        fewest = float("inf")
        for i in range(len(states)):
            if filled_of(states[i]) >= MIN_SQUAD:
                continue
            if player["is_overseas"] and states[i]["overseas"] >= opts["overseas_cap"]:
                continue
            if rem_purse_of(i) < player["base_price"]:
                continue
            if filled_of(states[i]) < fewest:
                fewest = filled_of(states[i])
                pick = i
        if pick >= 0:
            buy(pick, player, player["base_price"])
            sold.add(player["cricsheet_id"])
    return states


# Lots per auction: the most valuable unretained players (a real auction lists far more, most go unsold).
AUCTION_LOTS = 200


def simulate_auction(pool: list[dict], team_cfg: list[dict], opts: dict) -> dict:
    bases, auction_pool = _build_franchises(pool, team_cfg, opts)
    use_pool = auction_pool[:AUCTION_LOTS]
    agg = [
        {
            "team": b["team"],
            "personality": b["personality"],
            "retained": len(b["retained"]),
            "ret_val": sum(p["projected_value"] for p in b["retained"]),
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
            agg[i]["value"] += agg[i]["ret_val"] + sum(p["projected_value"] for p in st["bought"])
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
            "personality": a["personality"],
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
        for i, p in enumerate(b["retained"]):
            cost = (
                opts["real_prices"].get(p["cricsheet_id"], slab_cost(i))
                if opts["mode"] != "mini"
                else 0
            )
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
