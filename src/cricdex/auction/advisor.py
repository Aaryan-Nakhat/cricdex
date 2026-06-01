"""Auction strategy advisor — pick budget-fit replacements for a target.

The real auction war-room workflow is: "Bumrah just sold for 24 cr to
MI, I have 18 cr left and need a death-overs pacer — who's available?"

This module combines three signals that already exist independently:

1. **Graph similarity** (`scout.graph.similar.find_replacement`) —
   relational cohort: who operated in the same competitive
   neighbourhood as the target.
2. **Bayes-skill projected value** (`auction.real_pool.build_pool`) —
   the IPL pool with skill-driven cr value + base prices.
3. **Budget + role constraints** — only return candidates the user
   can actually afford and that match the role they're filling.

Output is a composite-scored DataFrame so the user can see at a
glance "this is the best graph-similar player I can still afford".
"""

from __future__ import annotations

import polars as pl

from cricdex.auction import real_pool
from cricdex.scout.graph import similar


def recommend_substitutes(
    target_name: str,
    budget: float,
    role: str | None = None,
    n: int = 5,
    pool: pl.DataFrame | None = None,
    graph_top_k: int = 50,
    min_last_match_date: str | None = "2023-01-01",
    max_balls_bowled: int | None = None,
    max_balls_faced: int | None = None,
    bowling_style: str | None = None,
    collection: str = "ipl",
) -> pl.DataFrame:
    """Return up to `n` graph-similar players within `budget`.

    `pool` defaults to `real_pool.build_pool()`. `role` defaults to the
    target's auto-detected role (from the graph).

    The composite score is:

        shared_norm = shared / max(shared)   ∈ [0, 1]
        value_norm  = projected_value / max(projected_value)  ∈ [0, 1]
        composite   = 0.5 * shared_norm + 0.5 * value_norm

    so a candidate has to be both *close* to the target *and* a
    high-value player in absolute terms to score highly. Tweak the
    weights here if the workflow ever prioritises one or the other.
    """
    if pool is None:
        pool = real_pool.build_pool()

    # Pull a generous graph cohort, then filter to affordable + on-role.
    candidates = similar.find_replacement(
        target_name,
        top_k=graph_top_k,
        role=role,
        max_balls_bowled=max_balls_bowled,
        max_balls_faced=max_balls_faced,
        min_last_match_date=min_last_match_date,
        bowling_style=bowling_style,
        collection=collection,
    )
    if not candidates:
        return pl.DataFrame()

    graph_df = pl.DataFrame(candidates).rename({"name": "graph_name"})
    joined = graph_df.join(
        pool,
        left_on="cricsheet_id",
        right_on="cricsheet_id",
        how="inner",
    )
    if joined.is_empty():
        return pl.DataFrame()

    joined = joined.filter(pl.col("price") <= budget)
    if role:
        joined = joined.filter(pl.col("role") == role)
    if joined.is_empty():
        return pl.DataFrame()

    shared_max = float(joined["shared"].max() or 1.0)
    value_max = float(joined["projected_value"].max() or 1.0)
    joined = joined.with_columns(
        (pl.col("shared") / shared_max).alias("shared_norm"),
        (pl.col("projected_value") / value_max).alias("value_norm"),
    )
    joined = joined.with_columns(
        (0.5 * pl.col("shared_norm") + 0.5 * pl.col("value_norm")).alias("composite_score")
    )
    return (
        joined.sort("composite_score", descending=True)
        .head(n)
        .select(
            [
                "name",
                "role",
                "country",
                "price",
                "projected_value",
                "shared",
                "composite_score",
                "last_match_date",
            ]
        )
    )
