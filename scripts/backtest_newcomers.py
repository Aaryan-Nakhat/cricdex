"""Newcomer backtest: can other leagues predict a player's first IPL season?

For each season S, players new to the IPL (fewer than --max-ipl-prior balls in
that role before S) who then got a real go in S (at least --min-balls) are
rated from the other auction-pool leagues only — BBL, SA20, CPL, T20 Blast,
SMAT — each fitted on matches before S. Their value there, minus the same
tier penalty the auction pool uses, is compared with how the IPL season went.

Baseline: what a scout could work out by hand — the player's raw numbers
pooled across those leagues before S, with no opponent or tier adjustment.

Seasons are pooled (each predictor and outcome is z-scored within its season
so a high-scoring year doesn't skew the ranking). Agreement is a Spearman rank
correlation (1 = same order, 0 = no link).

Example:
    uv run python scripts/backtest_newcomers.py --seasons 2021-2026
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import typer
from backtest_ratings import AXES, LABEL, _raw, _spearman, _totals, _z
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.scout.ratings import bayesian
from cricdex.web_parity.pricing import TIER_PENALTY

app = typer.Typer(add_completion=False)

# other auction-pool leagues → pricing tier (same table the auction pool uses)
LEAGUES = {
    "bbl": "bbl",
    "sa20": "sa20",
    "cpl": "cpl",
    "blast": "blast",
    "indian_domestic_male": "smat",
}
ROLES = (
    ("batter", "batter_id", 1.0, -1.0, "survival_skill"),
    ("bowler", "bowler_id", -1.0, 1.0, "strike_skill"),
)


def _other_league_view(season: int, advi_steps: int, seed: int) -> dict[str, pl.DataFrame]:
    """Per role: each player's best tier-penalised rating across the other
    leagues (the auction pool's rule), plus his raw pooled totals there."""
    start = f"{season}-01-01"
    rated: list[pl.DataFrame] = []
    edges: list[pl.DataFrame] = []
    for col, tier in LEAGUES.items():
        e = bayesian._load_edges(bayesian.DEFAULT_DB_PATH, col, before=start)
        if e.is_empty():
            continue
        edges.append(e)
        logger.info(f"  {season}: fitting {col} on matches before {start}")
        r = bayesian.fit(collection=col, before=start, advi_steps=advi_steps, seed=seed)
        pen = TIER_PENALTY[tier]
        rated.append(
            r.select(
                "cricsheet_id",
                "role",
                pl.col("skill"),
                pl.col("survival_skill")
                if "survival_skill" in r.columns
                else pl.lit(None).alias("survival_skill"),
                pl.col("strike_skill")
                if "strike_skill" in r.columns
                else pl.lit(None).alias("strike_skill"),
                (pl.col("value") - pen).alias("value"),
            )
        )
    allr = pl.concat(rated, how="diagonal_relaxed")
    alle = pl.concat(edges, how="diagonal_relaxed")
    out = {}
    for role, key, *_ in ROLES:
        best = (
            allr.filter(pl.col("role") == role)
            .sort("value", descending=True)
            .unique("cricsheet_id", keep="first")
        )
        out[role] = best.join(_totals(alle, key, "o_"), on="cricsheet_id", how="left")
    return out


@app.command()
def run(
    seasons: str = typer.Option("2021-2026", "--seasons", help="first-last, e.g. 2021-2026"),
    min_balls: int = typer.Option(60, "--min-balls", help="IPL balls in the season to be scored"),
    max_ipl_prior: int = typer.Option(60, "--max-ipl-prior", help="'new' = fewer prior IPL balls"),
    advi_steps: int = typer.Option(12000, "--advi-steps"),
    seed: int = typer.Option(42, "--seed"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    first, last = (int(x) for x in seasons.split("-"))
    db = bayesian.DEFAULT_DB_PATH
    pooled: dict[str, dict[str, list]] = {
        role: {f"{who}_{a}": [] for who in ("act", "model", "raw") for a in AXES} | {"rows": []}
        for role, *_ in ROLES
    }
    for s in range(first, last + 1):
        start, end = f"{s}-01-01", f"{s + 1}-01-01"
        view = _other_league_view(s, advi_steps, seed)
        ipl_prior = bayesian._load_edges(db, "ipl", before=start)
        ipl_season = bayesian._load_edges(db, "ipl", since=start, before=end)
        for role, key, rate_sign, odds_sign, odds_col in ROLES:
            prior_ipl = _totals(ipl_prior, key, "p_").select("cricsheet_id", "p_balls")
            df = (
                _totals(ipl_season, key)
                .filter(pl.col("balls") >= min_balls)
                .join(prior_ipl, on="cricsheet_id", how="left")
                .filter(pl.col("p_balls").fill_null(0) < max_ipl_prior)
                .join(view[role], on="cricsheet_id", how="inner")  # needs other-league history
                .filter(pl.col("o_balls") > 0)
            )
            if df.height < 3:
                continue
            act_rate = rate_sign * (df["runs"] / df["balls"]).to_numpy()
            act_odds = odds_sign * (df["outs"] / df["trials"].clip(1)).to_numpy()
            raw = _raw(df, "o_", rate_sign, odds_sign, (0.0, 0.0))
            model = {
                "rate": df["skill"].to_numpy(),
                "odds": df[odds_col].to_numpy(),
                "all": df["value"].to_numpy(),
            }
            act = {"rate": act_rate, "odds": act_odds, "all": _z(act_rate) + _z(act_odds)}
            p = pooled[role]
            for a in AXES:  # z within the season, then pool
                p[f"act_{a}"].extend(_z(act[a]))
                p[f"model_{a}"].extend(_z(model[a]))
                p[f"raw_{a}"].extend(_z(raw[a]))
            p["rows"].extend({"season": s, "cricsheet_id": c} for c in df["cricsheet_id"])
            logger.info(f"{s} {role}s: {df.height} IPL newcomers with other-league history")

    result: dict = {"min_balls": min_balls, "max_ipl_prior": max_ipl_prior, "seasons": seasons}
    typer.echo(
        "\nIPL newcomers, rated from other leagues only  ·  model | raw other-league numbers"
    )
    for role, *_ in ROLES:
        p = pooled[role]
        n = len(p["rows"])
        res: dict = {"n": n}
        for a in AXES:
            act = np.asarray(p[f"act_{a}"])
            res[a] = {
                "model": _spearman(np.asarray(p[f"model_{a}"]), act) if n >= 10 else None,
                "raw": _spearman(np.asarray(p[f"raw_{a}"]), act) if n >= 10 else None,
            }
        result[role] = res
        cells = "  ".join(
            f"{LABEL[a]} {res[a]['model']:+.2f} | {res[a]['raw']:+.2f}"
            for a in AXES
            if res[a]["model"] is not None
        )
        typer.echo(f"{role}s  n={n:>3}  {cells}")
    out_path = out_json or (DATA_DIR / "metrics" / "newcomer_backtest_ipl.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    logger.info(f"wrote {out_path}")


if __name__ == "__main__":
    app()
