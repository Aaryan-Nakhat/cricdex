"""Mixed-integer auction squad solver.

Given a pool of candidate players (price, role, country, projected
value), pick a squad that maximises expected value subject to:

- purse cap (total spend ≤ budget)
- exactly squad_size players
- at most overseas_cap overseas players
- per-role minimums (eg ≥4 bowlers, ≥1 keeper)

Uses scipy.optimize.milp under the hood — no heavy OR-Tools dep.
Empty / infeasible inputs return a clear marker instead of raising.
"""

from __future__ import annotations

import polars as pl
from loguru import logger
from scipy.optimize import Bounds, LinearConstraint, milp

ROLE_LABELS = ("batter", "bowler", "all_rounder", "keeper")


def solve(
    pool: pl.DataFrame,
    purse: float,
    squad_size: int = 25,
    overseas_cap: int = 8,
    role_mins: dict[str, int] | None = None,
) -> dict:
    """Pick optimal squad. Returns a dict with `selected` (polars DataFrame),
    `total_price`, `total_value`, and `feasible` flag.

    `pool` must contain: name, role, country (str), is_overseas (bool),
    price (float), projected_value (float).
    """
    role_mins = role_mins or {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2}

    required = {"name", "role", "is_overseas", "price", "projected_value"}
    missing = required - set(pool.columns)
    if missing:
        raise ValueError(f"pool missing columns: {missing}")
    if pool.is_empty():
        return {"feasible": False, "selected": pl.DataFrame(), "reason": "empty pool"}

    df = pool.with_row_index()
    n = df.height
    price = df["price"].to_numpy()
    value = df["projected_value"].to_numpy()
    overseas = df["is_overseas"].cast(pl.Int8).to_numpy()

    role_vec = {r: (df["role"] == r).cast(pl.Int8).to_numpy() for r in ROLE_LABELS}

    # milp minimises by default; flip sign to maximise value.
    c = -value

    constraints: list[LinearConstraint] = [
        LinearConstraint(price.reshape(1, -1), ub=purse),  # budget
        LinearConstraint((overseas.reshape(1, -1)), ub=overseas_cap),  # overseas cap
        # exactly squad_size players (binary x summed)
        LinearConstraint([1.0] * n, lb=squad_size, ub=squad_size),
    ]
    for role, vec in role_vec.items():
        m = role_mins.get(role, 0)
        if m > 0:
            constraints.append(LinearConstraint(vec.reshape(1, -1), lb=m))

    integrality = [1] * n
    res = milp(
        c=c,
        constraints=constraints,
        integrality=integrality,
        bounds=Bounds(lb=[0] * n, ub=[1] * n),
    )

    if not res.success:
        logger.warning(f"milp failed: {res.message}")
        return {"feasible": False, "selected": pl.DataFrame(), "reason": res.message}

    picks = [i for i, x in enumerate(res.x) if x > 0.5]
    selected = (
        df.filter(pl.col("index").is_in(picks))
        .drop("index")
        .sort("projected_value", descending=True)
    )
    return {
        "feasible": True,
        "selected": selected,
        "total_price": float(selected["price"].sum()),
        "total_value": float(selected["projected_value"].sum()),
    }


def sample_pool(n: int = 60, seed: int = 42) -> pl.DataFrame:
    """Synthetic pool for quick CLI / dashboard testing. Replace with a
    real IPL auction shortlist when one is wired up."""
    import random

    rng = random.Random(seed)
    names = [f"Player_{i:03d}" for i in range(n)]
    roles = rng.choices(ROLE_LABELS, weights=[4, 4, 2, 1], k=n)
    # IPL squad maths needs ≥12 Indians per team, so weight the synthetic
    # pool heavily towards India so the demo MILP isn't infeasible by
    # country composition alone.
    countries = rng.choices(
        ["IN", "AU", "NZ", "SA", "EN", "PK", "WI"],
        weights=[6, 2, 2, 2, 2, 1, 1],
        k=n,
    )
    is_overseas = [c != "IN" for c in countries]
    base_price = [rng.choice([0.5, 1.0, 1.5, 2.0]) for _ in range(n)]
    auction_mult = [rng.uniform(0.8, 8.0) for _ in range(n)]
    price = [round(b * m, 2) for b, m in zip(base_price, auction_mult, strict=True)]
    value = [round(rng.uniform(0.5, 9.0), 2) for _ in range(n)]
    return pl.DataFrame(
        {
            "name": names,
            "role": roles,
            "country": countries,
            "is_overseas": is_overseas,
            "base_price": base_price,
            "price": price,
            "projected_value": value,
        }
    )
