"""Ratings backtest: do pre-season ratings predict how a player's season goes?

Walk-forward, out of sample. For each season S the Bayesian model is fitted on
matches BEFORE S only, then compared with what each player actually did in S:

    batters  scoring rate (runs per ball)   vs `skill`
             staying in (balls per out)     vs `survival_skill`
             both together                  vs `value`
    bowlers  economy (runs off the bat per ball, lower = better) vs `skill`
             wicket-taking (outs per ball)  vs `strike_skill`
             both together                  vs `value`

"Both together" scores the season the way `value` is built: each axis as a
z-score among the qualified players, summed. Two baselines, both what a fan
could work out by hand from the same matches:

    career   raw career numbers before S (league average if none)
    recent   the same, each season weighted by the model's recency half-life
             (only with --half-life; shows whether any gain is just recency)

Agreement is a Spearman rank correlation (1 = same order, 0 = no link).

Example:
    uv run python scripts/backtest_ratings.py --collection ipl --seasons 2021-2026 --half-life 2
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.scout.ratings import bayesian

app = typer.Typer(add_completion=False)

AXES = ("rate", "odds", "all")
LABEL = {"rate": "scoring/economy", "odds": "out/wickets", "all": "overall"}


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = pl.Series(a).rank("average").to_numpy()
    rb = pl.Series(b).rank("average").to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else x * 0


def _totals(edges: pl.DataFrame, key: str, prefix: str = "") -> pl.DataFrame:
    cols = ("balls", "runs", "outs", "trials")
    w = pl.col("w") if "w" in edges.columns else pl.lit(1.0)
    return (
        edges.group_by(key)
        .agg((pl.col(c).cast(pl.Float64) * w).sum().alias(prefix + c) for c in cols)
        .rename({key: "cricsheet_id"})
    )


def _raw(df: pl.DataFrame, p: str, rate_sign: float, odds_sign: float, league: tuple) -> dict:
    """Raw-number predictor from prior totals with column prefix `p`."""
    balls, runs = df[p + "balls"], df[p + "runs"]
    outs, trials = df[p + "outs"], df[p + "trials"]
    rate = rate_sign * np.where(
        (balls > 0).to_numpy(), (runs / balls.clip(1e-9)).to_numpy(), league[0]
    )
    odds = odds_sign * np.where(
        (trials > 0).to_numpy(), (outs / trials.clip(1e-9)).to_numpy(), league[1]
    )
    return {"rate": rate, "odds": odds, "all": _z(rate) + _z(odds)}


def _season(
    collection: str,
    season: int,
    min_balls: int,
    low_prior: int,
    advi_steps: int,
    seed: int,
    half_life: float | None,
) -> dict:
    start, end = f"{season}-01-01", f"{season + 1}-01-01"
    db = bayesian.DEFAULT_DB_PATH
    ratings = bayesian.fit(
        collection=collection, before=start, advi_steps=advi_steps, seed=seed, half_life=half_life
    )
    prior_edges = bayesian._load_edges(db, collection, before=start, by_year=True)
    season_edges = bayesian._load_edges(db, collection, since=start, before=end)
    league = (
        float(prior_edges["runs"].sum()) / max(float(prior_edges["balls"].sum()), 1.0),
        float(prior_edges["outs"].sum()) / max(float(prior_edges["trials"].sum()), 1.0),
    )
    recent_edges = None
    if half_life is not None:
        age = (season - 1 - prior_edges["yr"]).fill_null(0).cast(pl.Float64)
        recent_edges = prior_edges.with_columns((0.5 ** (age / half_life)).alias("w"))

    out: dict = {"season": season}
    for role, key, rate_sign, odds_sign, odds_col in (
        ("batter", "batter_id", 1.0, -1.0, "survival_skill"),
        ("bowler", "bowler_id", -1.0, 1.0, "strike_skill"),
    ):
        df = _totals(season_edges, key).filter(pl.col("balls") >= min_balls)
        df = df.join(_totals(prior_edges, key, "p_"), on="cricsheet_id", how="left")
        if recent_edges is not None:
            df = df.join(_totals(recent_edges, key, "r_"), on="cricsheet_id", how="left")
        rated = ratings.filter(pl.col("role") == role).select(
            "cricsheet_id", "skill", odds_col, "value"
        )
        df = df.join(rated, on="cricsheet_id", how="left").fill_null(0)
        if df.height < 10:
            continue
        # what happened in the season (higher = better on every axis)
        act_rate = rate_sign * (df["runs"] / df["balls"]).to_numpy()
        act_odds = odds_sign * (df["outs"] / df["trials"].clip(1)).to_numpy()
        act = {"rate": act_rate, "odds": act_odds, "all": _z(act_rate) + _z(act_odds)}
        preds = {
            "model": {
                "rate": df["skill"].to_numpy(),
                "odds": df[odds_col].to_numpy(),
                "all": df["value"].to_numpy(),
            },
            "career": _raw(df, "p_", rate_sign, odds_sign, league),
        }
        if recent_edges is not None:
            preds["recent"] = _raw(df, "r_", rate_sign, odds_sign, league)
        thin = (df["p_balls"] < low_prior).to_numpy()
        res: dict = {"n": df.height, "n_thin": int(thin.sum())}
        for axis in AXES:
            res[axis] = {name: _spearman(p[axis], act[axis]) for name, p in preds.items()}
            if thin.sum() >= 10:
                res[axis].update(
                    {
                        f"{name}_thin": _spearman(p[axis][thin], act[axis][thin])
                        for name, p in preds.items()
                    }
                )
        # quintiles by pre-season value: how each fifth actually did
        balls, runs = df["balls"].to_numpy(), df["runs"].to_numpy()
        outs, trials = df["outs"].to_numpy(), df["trials"].to_numpy()
        res["quintiles"] = [
            {
                "fifth": i + 1,
                "n": len(ix),
                "runs_per_100": float(runs[ix].sum() * 100 / balls[ix].sum()),
                "balls_per_out": float(trials[ix].sum() / max(outs[ix].sum(), 1)),
            }
            for i, ix in enumerate(np.array_split(np.argsort(-preds["model"]["all"]), 5))
        ]
        out[role] = res
    return out


@app.command()
def run(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    seasons: str = typer.Option("2021-2026", "--seasons", help="first-last, e.g. 2021-2026"),
    min_balls: int = typer.Option(60, "--min-balls", help="balls in the season to be scored"),
    low_prior: int = typer.Option(300, "--low-prior", help="'thin history' = fewer prior balls"),
    half_life: float | None = typer.Option(
        None, "--half-life", help="recency half-life in years (model + 'recent' baseline)"
    ),
    advi_steps: int = typer.Option(12000, "--advi-steps"),
    seed: int = typer.Option(42, "--seed"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    first, last = (int(x) for x in seasons.split("-"))
    results = []
    for s in range(first, last + 1):
        logger.info(f"season {s}: fitting on matches before {s}")
        results.append(_season(collection, s, min_balls, low_prior, advi_steps, seed, half_life))
    out_path = out_json or (DATA_DIR / "metrics" / f"ratings_backtest_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "collection": collection,
        "min_balls": min_balls,
        "low_prior": low_prior,
        "half_life": half_life,
    }
    out_path.write_text(json.dumps({**meta, "seasons": results}, indent=2))
    logger.info(f"wrote {out_path}")

    names = ["model", "career"] + (["recent"] if half_life is not None else [])
    typer.echo(
        f"\nhalf-life: {half_life or 'none (every season equal)'}  ·  columns: {' | '.join(names)}"
    )
    for role in ("batter", "bowler"):
        rows = [r[role] for r in results if role in r]
        typer.echo(f"\n=== {role}s ===")
        for r in results:
            if role in r:
                x = r[role]
                cells = "  ".join(
                    f"{LABEL[a]} " + " | ".join(f"{x[a][n]:+.2f}" for n in names) for a in AXES
                )
                typer.echo(f"{r['season']}  n={x['n']:>3}  {cells}")
        for a in AXES:
            mean = " | ".join(f"{np.mean([x[a][n] for x in rows]):+.2f}" for n in names)
            thin_rows = [x for x in rows if "model_thin" in x[a]]
            thin = (
                " | ".join(f"{np.mean([x[a][n + '_thin'] for x in thin_rows]):+.2f}" for n in names)
                if thin_rows
                else "—"
            )
            typer.echo(f"  mean {LABEL[a]:>15}: {mean}   (thin history: {thin})")


if __name__ == "__main__":
    app()
