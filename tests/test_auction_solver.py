"""Smoke tests for the auction MILP squad optimiser."""

from __future__ import annotations

import polars as pl

from cricdex.auction import solver


def test_sample_pool_shape():
    pool = solver.sample_pool(n=40, seed=7)
    assert pool.height == 40
    for col in ("name", "role", "country", "is_overseas", "price", "projected_value"):
        assert col in pool.columns
    # Role values are within the canonical set.
    assert set(pool["role"].to_list()).issubset(set(solver.ROLE_LABELS))


def test_solve_feasible_on_default_demo():
    pool = solver.sample_pool(seed=42)
    result = solver.solve(pool, purse=200.0, squad_size=20)
    assert result["feasible"], result.get("reason")
    selected = result["selected"]
    assert selected.height == 20
    assert result["total_price"] <= 200.0 + 1e-6
    # Default role mins: 5 batter + 5 bowler + 3 all_rounder + 2 keeper = 15.
    by_role = dict(selected.group_by("role").len().iter_rows())
    assert by_role.get("batter", 0) >= 5
    assert by_role.get("bowler", 0) >= 5
    assert by_role.get("all_rounder", 0) >= 3
    assert by_role.get("keeper", 0) >= 2


def test_solve_returns_infeasible_when_pool_too_small():
    pool = pl.DataFrame(
        {
            "name": ["A", "B"],
            "role": ["batter", "bowler"],
            "country": ["IN", "IN"],
            "is_overseas": [False, False],
            "price": [1.0, 1.0],
            "projected_value": [5.0, 5.0],
        }
    )
    result = solver.solve(pool, purse=100.0, squad_size=20)
    assert result["feasible"] is False
