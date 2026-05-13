"""Integration tests for the scout-graph similarity queries.

Skipped unless a populated Neo4j is reachable. The CI runner doesn't
host Neo4j, so these run locally on the dev container or against a
matching `bolt://` URL set in `.env`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("neo4j", reason="neo4j extra not installed")

from cricdex.scout.graph import similar  # noqa: E402


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


needs_neo4j = pytest.mark.skipif(
    not _neo4j_alive(),
    reason="needs a populated Neo4j at settings.neo4j_uri",
)


@needs_neo4j
def test_co_faced_bowlers_kohli_top_cohort():
    rows = similar.co_faced_bowlers("V Kohli", top_k=5)
    assert rows, "expected at least one neighbour for V Kohli"
    names = {r["name"] for r in rows}
    # At least one of Kohli's era IPL peers should appear in the top-5.
    expected = {"RG Sharma", "S Dhawan", "MS Dhoni", "RA Jadeja", "AM Rahane"}
    assert names & expected, f"none of {expected} in top-5: {names}"


@needs_neo4j
def test_teammate_overlap_dhoni_jadeja_first():
    rows = similar.teammate_overlap("MS Dhoni", top_k=1)
    assert rows
    assert (
        rows[0]["name"] == "RA Jadeja"
    ), f"expected RA Jadeja as MS Dhoni's #1 teammate, got {rows[0]['name']}"


@needs_neo4j
def test_find_replacement_bowler_filters_apply():
    rows = similar.find_replacement(
        "JJ Bumrah",
        top_k=10,
        role="bowler",
        max_balls_bowled=2000,
        min_last_match_date="2023-01-01",
    )
    assert rows
    for r in rows:
        assert r["role"] == "bowler"
        assert r["balls_bowled"] <= 2000
        assert r["last_match_date"] >= "2023-01-01"


@needs_neo4j
def test_find_replacement_unknown_name_returns_empty():
    assert similar.find_replacement("Definitely Not A Player", top_k=5) == []
