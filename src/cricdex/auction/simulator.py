"""Monte-Carlo IPL auction simulator.

Lighter than full RL self-play but the same shape: every franchise is
its own agent with a budget, a roster need, and a value function over
the player pool. We run N auctions, each one bid-by-bid over the pool,
and report:

- per-player price distribution (min / 25th / median / 75th / max),
- per-franchise expected squad,
- "if I bid X for Bumrah, win probability" sweeps.

Why not full PettingZoo + SB3 self-play
---------------------------------------
PPO self-play on a 10-agent auction env takes hours to train, needs
careful state design + reward shaping, and the resulting policy is
hard to validate. Monte Carlo with parameterised franchise behaviour
(aggression, role priorities, RTM appetite) covers the
practitioner-facing question — "what's the realistic price band for
player X" — in seconds and is plug-in for the bid-strategy advisor.

Franchise policy
----------------
Each franchise has:

- `purse` cr
- `slots_left` — number of players still needed
- `need[role]` — minimum players still wanted per role
- `aggression` ∈ [0.5, 1.5] — multiplier on willingness-to-pay
- `risk` ∈ [0, 1] — std-dev jitter applied to its value estimate

For each player up for bid the franchise's `bid_ceiling` is

    min(purse, projected_value * aggression * jitter)
    s.t. slots_left > 0
    s.t. role-quota check (won't waste purse if role already full)

Highest-ceiling franchise wins at `second_ceiling + 0.1`.

Inputs
------
`pool` — DataFrame as accepted by `auction.solver` (name, role,
country, is_overseas, price, projected_value).

`franchises` — list of dicts with the policy params above. Default:
10 IPL franchises with mid-range params.
"""

from __future__ import annotations

import random

import polars as pl

DEFAULT_FRANCHISES = [
    {"id": f"F{i + 1}", "purse": 90.0, "aggression": 1.0, "risk": 0.15, "role_mins": None}
    for i in range(10)
]


def _default_role_mins() -> dict[str, int]:
    return {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2}


def _bid_ceiling(
    franchise: dict,
    player: dict,
    rng: random.Random,
) -> float:
    if franchise["slots_left"] <= 0:
        return 0.0
    if franchise["need"].get(player["role"], 0) <= 0 and franchise["slots_left"] <= sum(
        franchise["need"].values()
    ):
        return 0.0
    if player["is_overseas"] and franchise.get("overseas_left", 8) <= 0:
        return 0.0
    jitter = rng.gauss(1.0, franchise["risk"])
    ceiling = player["projected_value"] * franchise["aggression"] * jitter
    return float(min(franchise["purse"], max(0.0, ceiling)))


def _run_one_auction(
    pool: pl.DataFrame,
    franchises: list[dict],
    rng: random.Random,
) -> tuple[list[dict], dict[str, list[str]]]:
    players = pool.to_dicts()
    rng.shuffle(players)

    state = []
    for f in franchises:
        state.append(
            {
                "id": f["id"],
                "purse": f["purse"],
                "slots_left": f.get("slots_left", 11),
                "aggression": f["aggression"],
                "risk": f["risk"],
                "overseas_left": f.get("overseas_left", 8),
                "need": dict(f.get("role_mins") or _default_role_mins()),
                "roster": [],
            }
        )

    sales: list[dict] = []
    rosters: dict[str, list[str]] = {f["id"]: [] for f in state}

    for player in players:
        # Sort on the ceiling only — comparing the franchise dicts on a
        # tie raises TypeError (dicts aren't orderable). Ties at 0.0 are
        # common once role / overseas gates zero out multiple bidders.
        ceilings = sorted(
            ((_bid_ceiling(f, player, rng), f) for f in state),
            key=lambda x: x[0],
            reverse=True,
        )
        top_ceiling, top_franchise = ceilings[0]
        if top_ceiling < player["price"]:
            sales.append({"player": player["name"], "price": None, "winner": None})
            continue
        second_ceiling = ceilings[1][0] if len(ceilings) > 1 else player["price"]
        sale_price = round(max(player["price"], second_ceiling + 0.1), 2)
        sale_price = min(sale_price, top_ceiling)
        # Apply sale
        top_franchise["purse"] -= sale_price
        top_franchise["slots_left"] -= 1
        top_franchise["roster"].append(player["name"])
        if player["is_overseas"]:
            top_franchise["overseas_left"] -= 1
        if top_franchise["need"].get(player["role"], 0) > 0:
            top_franchise["need"][player["role"]] -= 1
        rosters[top_franchise["id"]].append(player["name"])
        sales.append({"player": player["name"], "price": sale_price, "winner": top_franchise["id"]})
    return sales, rosters


def simulate(
    pool: pl.DataFrame,
    franchises: list[dict] | None = None,
    n_sims: int = 200,
    seed: int = 42,
) -> dict:
    franchises = franchises or DEFAULT_FRANCHISES
    rng = random.Random(seed)

    per_player_prices: dict[str, list[float]] = {p: [] for p in pool["name"].to_list()}
    per_player_winners: dict[str, list[str]] = {p: [] for p in pool["name"].to_list()}

    for _ in range(n_sims):
        sales, _rosters = _run_one_auction(pool, franchises, rng)
        for s in sales:
            if s["price"] is not None:
                per_player_prices[s["player"]].append(s["price"])
                per_player_winners[s["player"]].append(s["winner"])

    rows: list[dict] = []
    for player, prices in per_player_prices.items():
        if not prices:
            rows.append(
                {
                    "player": player,
                    "sold_pct": 0.0,
                    "median_price": None,
                    "p25_price": None,
                    "p75_price": None,
                    "min_price": None,
                    "max_price": None,
                    "n_sold": 0,
                }
            )
            continue
        prices_s = pl.Series(prices)
        rows.append(
            {
                "player": player,
                "sold_pct": round(100 * len(prices) / n_sims, 1),
                "median_price": float(prices_s.median() or 0),
                "p25_price": float(prices_s.quantile(0.25) or 0),
                "p75_price": float(prices_s.quantile(0.75) or 0),
                "min_price": float(prices_s.min() or 0),
                "max_price": float(prices_s.max() or 0),
                "n_sold": len(prices),
            }
        )
    df = pl.DataFrame(rows).sort("median_price", descending=True, nulls_last=True)
    return {
        "per_player": df,
        "n_sims": n_sims,
        "winners": per_player_winners,
    }


def win_probability(
    pool: pl.DataFrame,
    target_player: str,
    your_bid: float,
    franchises: list[dict] | None = None,
    n_sims: int = 200,
    seed: int = 42,
) -> float:
    """Rough probability you win `target_player` at price ≤ `your_bid`.

    v1: linear interpolation of `your_bid` between the simulated
    min/max realised price for the player across `n_sims` auctions.
    A per-ball noisy-bidder estimator is a v2 enhancement.
    """
    franchises = franchises or DEFAULT_FRANCHISES
    summary = simulate(pool, franchises=franchises, n_sims=n_sims, seed=seed)
    row = summary["per_player"].filter(pl.col("player") == target_player)
    if row.is_empty():
        return 0.0
    if your_bid >= row["max_price"][0]:
        return 1.0
    if your_bid <= row["min_price"][0]:
        return 0.0
    mn = row["min_price"][0]
    mx = row["max_price"][0]
    if mx <= mn:
        return 0.5
    raw = (your_bid - mn) / (mx - mn)
    return round(min(1.0, max(0.0, raw)), 3)
