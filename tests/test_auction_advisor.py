"""Integration tests for the auction strategy advisor.

Skipped unless a populated Neo4j is reachable. Same skip pattern as
`test_scout_graph_similar.py`.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

pytest.importorskip("neo4j", reason="neo4j extra not installed")

from cricdex.auction import advisor, real_pool  # noqa: E402


def _neo4j_alive() -> bool:
    try:
        from neo4j.exceptions import ServiceUnavailable

        from cricdex.scout.graph.schema import driver

        drv = driver()
        try:
            with drv.session() as s:
                s.run("RETURN 1").consume()
            return True
        finally:
            drv.close()
    except ServiceUnavailable:
        return False
    except Exception:
        return False


RATINGS = Path("data/metrics/scout_ratings_ipl.json")
DB = Path("data/cricsheet/cricsheet.duckdb")


needs_stack = pytest.mark.skipif(
    not (_neo4j_alive() and RATINGS.exists() and DB.exists()),
    reason="needs populated Neo4j + real_pool data",
)


@needs_stack
def test_recommend_substitutes_for_bumrah_under_8cr():
    pool = real_pool.build_pool(min_balls=200)
    rec = advisor.recommend_substitutes(
        "JJ Bumrah",
        budget=8.0,
        role="bowler",
        n=5,
        pool=pool,
    )
    assert not rec.is_empty(), "expected at least one substitute under 8 cr"
    # Every candidate must be a bowler within budget.
    for row in rec.iter_rows(named=True):
        assert row["role"] == "bowler"
        assert row["price"] <= 8.0
    # composite_score is in [0, 1].
    assert rec["composite_score"].min() >= 0
    assert rec["composite_score"].max() <= 1.0
    # Sorted descending.
    scores = rec["composite_score"].to_list()
    assert scores == sorted(scores, reverse=True)


@needs_stack
def test_recommend_substitutes_unknown_target_returns_empty():
    pool = real_pool.build_pool(min_balls=200)
    rec = advisor.recommend_substitutes(
        "Definitely Not A Player",
        budget=10.0,
        n=5,
        pool=pool,
    )
    assert isinstance(rec, pl.DataFrame)
    assert rec.is_empty()


@needs_stack
def test_recommend_substitutes_tight_budget_yields_few_or_zero():
    pool = real_pool.build_pool(min_balls=200)
    rec = advisor.recommend_substitutes(
        "JJ Bumrah",
        budget=0.4,  # below the 0.5 / 0.75 / 1.0 IPL base tiers
        role="bowler",
        n=5,
        pool=pool,
    )
    # Either empty (no <=0.4 bowlers in cohort) or all under budget.
    if not rec.is_empty():
        for row in rec.iter_rows(named=True):
            assert row["price"] <= 0.4
