"""Smoke tests for the real-IPL auction pool generator."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from cricdex.auction import real_pool

RATINGS = Path("data/metrics/scout_ratings_ipl.json")
DB = Path("data/cricsheet/cricsheet.duckdb")


needs_data = pytest.mark.skipif(
    not (RATINGS.exists() and DB.exists()),
    reason="needs data/metrics/scout_ratings_ipl.json + data/cricsheet/cricsheet.duckdb",
)


def test_role_floor_keys_match_canonical_roles():
    assert set(real_pool.ROLE_FLOOR) == {"batter", "bowler", "all_rounder"}


def test_franchise_archetypes_shape():
    assert len(real_pool.FRANCHISE_ARCHETYPES) >= 4
    needed = {"id", "purse", "aggression", "risk", "role_mins"}
    for spec in real_pool.FRANCHISE_ARCHETYPES:
        assert needed.issubset(spec), spec
        assert spec["purse"] > 0
        assert 0.0 < spec["aggression"] <= 2.0


def test_project_value_monotone_in_value():
    # Higher complete value → higher cr price (monotone).
    a = real_pool._project_value(-0.1, role="batter")
    b = real_pool._project_value(0.1, role="batter")
    c = real_pool._project_value(0.3, role="batter")
    assert a < b < c


def test_project_value_role_floor():
    # all_rounder floor (0.8) > batter floor (0.5) at the same skill.
    assert real_pool._project_value(0.0, "all_rounder") > real_pool._project_value(0.0, "batter")


def test_base_price_clamps_to_tiers():
    for v in (-1.0, 0.0, 0.5, 3.0, 50.0):
        assert real_pool._base_price(v) in real_pool.PRICE_TIERS


def test_nationality_overrides_present():
    # The two People-Register collisions we fixed in the last commit.
    assert real_pool.NATIONALITY_OVERRIDES["Rashid Khan"] == "AF"
    assert real_pool.NATIONALITY_OVERRIDES["Mohsin Khan"] == "PK"


@needs_data
def test_build_pool_smoke():
    df = real_pool.build_pool(min_balls=200)
    assert df.height > 200, "expected at least 200 IPL players over 200-ball floor"
    for col in (
        "name",
        "cricsheet_id",
        "role",
        "country",
        "is_overseas",
        "base_price",
        "price",
        "projected_value",
        "skill",
        "balls_faced",
        "balls_bowled",
    ):
        assert col in df.columns
    # Role values restricted to the canonical set.
    assert set(df["role"].to_list()).issubset({"batter", "bowler", "all_rounder"})
    # Indian share should dominate after country-code normalisation.
    indian = df.filter(pl.col("country") == "IN").height
    assert indian / df.height > 0.4, (
        f"Indian share {indian / df.height:.2%} unexpectedly low — "
        f"country-code normalisation may have regressed"
    )
    # Override applied: Rashid Khan country=AF (not Nepal).
    rk = df.filter(pl.col("name") == "Rashid Khan")
    if rk.height:
        assert rk["country"][0] == "AF"
        assert rk["is_overseas"][0] is True
