"""Ratings backtest: do pre-season ratings predict how a player's season goes?

Walk-forward, out of sample. For each season S the Bayesian model is fitted on
matches BEFORE S only, then compared with what each player actually did in S:

    batters  scoring rate (runs per ball)   vs `skill`
             staying in (balls per out)     vs `survival_skill`
             both together                  vs `value`
    bowlers  economy (runs per ball, lower = better) vs `skill`
             wicket-taking (outs per ball)  vs `strike_skill`
             both together                  vs `value`

"Both together" scores the season in the currency `value` is built in: runs
per 100 balls above the league's average ball that season, each bowler-credited
dismissal above or below the league's rate priced at the run cost of a wicket
where the player played (`runs_value.observed_value`). The earlier yardstick,
each axis as a z-score among the qualified players, summed, is kept as
"overall (z-sum)" so the numbers can be compared with the published ones.
Baselines, both what a fan could work out by hand from the same matches:

    career   raw career numbers before S (league average if none); for the
             overall axis the same runs currency computed from those raw numbers
    recent   the same, each season weighted by the model's recency half-life
             (only with --half-life; shows whether any gain is just recency)

Agreement is a Spearman rank correlation (1 = same order, 0 = no link). The
model is fitted with `--seeds` ADVI seeds (default 3); the table shows the
mean over seeds and the seed range.

A second, sharper yardstick: the held-out log-likelihood of every ball of
season S (runs as a Negative-Binomial, dismissals as a Binomial, per ball)
under the model fitted before S — a proper scoring rule that uses every ball,
not a rank of noisy season totals. `--compare legacy` also fits the earlier
model (no context terms, one dispersion, one prior per role) on the same
seasons, so the two can be compared on both yardsticks.

Example:
    uv run python scripts/backtest_ratings.py --collection ipl --seasons 2021-2026 --compare legacy
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.scout.ratings import bayesian, runs_value

app = typer.Typer(add_completion=False)

AXES = ("rate", "odds", "all", "all_z")
LABEL = {
    "rate": "scoring/economy",
    "odds": "out/wickets",
    "all": "overall (runs)",
    "all_z": "overall (z-sum)",
}


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = pl.Series(a).rank("average").to_numpy()
    rb = pl.Series(b).rank("average").to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def _wslope(pred: np.ndarray, act: np.ndarray, w: np.ndarray) -> float:
    """Weighted least-squares slope of `act` on `pred`."""
    pm, am = np.average(pred, weights=w), np.average(act, weights=w)
    var = np.average((pred - pm) ** 2, weights=w)
    return float(np.average((pred - pm) * (act - am), weights=w) / var) if var > 0 else float("nan")


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else x * 0


def holm(pvals: list[float]) -> list[float]:
    """Holm–Bonferroni adjusted p-values (same order as given)."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return [float(x) for x in adj]


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
    return {"rate": rate, "odds": odds, "all_z": _z(rate) + _z(odds)}


def _season(
    collection: str,
    season: int,
    min_balls: int,
    low_prior: int,
    advi_steps: int,
    seeds: list[int],
    half_life: float | None,
    variant: str,
    nation_prior: bool | None = None,
) -> dict:
    start, end = f"{season}-01-01", f"{season + 1}-01-01"
    db = bayesian.DEFAULT_DB_PATH
    prior_edges = bayesian._load_edges(db, collection, before=start, by_year=True)
    season_edges = bayesian._load_edges(db, collection, since=start, before=end)
    prior_tab = runs_value.league_tables(db, collection, before=start)
    season_tab = runs_value.league_tables(db, collection, since=start, before=end)
    fits, lls = [], []
    for sd in seeds:
        ratings, res, _ = bayesian.fit(
            collection=collection,
            before=start,
            advi_steps=advi_steps,
            seed=sd,
            half_life=half_life,
            variant=variant,
            return_fit=True,
            nation_prior=nation_prior,
        )
        fits.append(ratings)
        lls.append(bayesian.heldout_loglik(res, season_edges))
    league = (
        float(prior_edges["runs"].sum()) / max(float(prior_edges["balls"].sum()), 1.0),
        float(prior_edges["outs"].sum()) / max(float(prior_edges["trials"].sum()), 1.0),
    )
    recent_edges = None
    if half_life is not None:
        age = (season - 1 - prior_edges["yr"]).fill_null(0).cast(pl.Float64)
        recent_edges = prior_edges.with_columns((0.5 ** (age / half_life)).alias("w"))

    out: dict = {
        "season": season,
        "heldout": {k: float(np.mean([x[k] for x in lls])) for k in lls[0] if k != "n_balls"}
        | {"n_balls": lls[0]["n_balls"]},
    }
    for role, key, rate_sign, odds_sign, odds_col in (
        ("batter", "batter_id", 1.0, -1.0, "survival_skill"),
        ("bowler", "bowler_id", -1.0, 1.0, "strike_skill"),
    ):
        df = _totals(season_edges, key).filter(pl.col("balls") >= min_balls)
        df = df.join(_totals(prior_edges, key, "p_"), on="cricsheet_id", how="left")
        if recent_edges is not None:
            df = df.join(_totals(recent_edges, key, "r_"), on="cricsheet_id", how="left")
        for k, ratings in enumerate(fits):
            rated = ratings.filter(pl.col("role") == role).select(
                "cricsheet_id",
                pl.col("skill").alias(f"skill{k}"),
                pl.col(odds_col).alias(f"odds{k}"),
                pl.col("value").alias(f"value{k}"),
            )
            df = df.join(rated, on="cricsheet_id", how="left")
        df = df.fill_null(0)
        if df.height < 10:
            continue
        # what happened in the season (higher = better on every axis)
        act_rate = rate_sign * (df["runs"] / df["balls"]).to_numpy()
        act_odds = odds_sign * (df["outs"] / df["trials"].clip(1)).to_numpy()
        ids = df["cricsheet_id"].to_list()
        act = {
            "rate": act_rate,
            "odds": act_odds,
            "all": np.nan_to_num(runs_value.observed_value(season_tab, role, ids)),
            "all_z": _z(act_rate) + _z(act_odds),
        }
        preds = {
            f"model{k}": {
                "rate": df[f"skill{k}"].to_numpy(),
                "odds": df[f"odds{k}"].to_numpy(),
                "all": df[f"value{k}"].to_numpy(),
                "all_z": df[f"value{k}"].to_numpy(),
            }
            for k in range(len(fits))
        }
        # no prior record = the league's average ball (0 runs above average)
        career_runs = np.nan_to_num(runs_value.observed_value(prior_tab, role, ids))
        preds["career"] = _raw(df, "p_", rate_sign, odds_sign, league) | {"all": career_runs}
        if recent_edges is not None:
            # recency-weighted raw numbers: the z-sum only (the runs currency needs ball states)
            preds["recent"] = _raw(df, "r_", rate_sign, odds_sign, league)
            preds["recent"]["all"] = preds["recent"]["all_z"]
        thin = (df["p_balls"] < low_prior).to_numpy()
        res: dict = {"n": df.height, "n_thin": int(thin.sum())}
        for axis in AXES:
            cell = {name: _spearman(p[axis], act[axis]) for name, p in preds.items()}
            seed_r = [cell.pop(f"model{k}") for k in range(len(fits))]
            cell["model"] = float(np.mean(seed_r))
            cell["model_by_seed"] = seed_r
            if thin.sum() >= 10:
                thin_r = [
                    _spearman(preds[f"model{k}"][axis][thin], act[axis][thin])
                    for k in range(len(fits))
                ]
                cell["model_thin"] = float(np.mean(thin_r))
                for name in ("career", "recent"):
                    if name in preds:
                        cell[f"{name}_thin"] = _spearman(preds[name][axis][thin], act[axis][thin])
            res[axis] = cell
        # calibration of the value (runs per 100 balls), mean over seeds: the ball-weighted slope of
        # what each player did on what was predicted (1 = right spread, < 1 = predictions too
        # extreme), and the bias (predicted − did) of the top fifth by prediction among the thin
        # records (< `low_prior` balls before): where a short record of big hitting sits
        wt = df["balls"].to_numpy().astype(float)
        calib: dict = {}
        for k in range(len(fits)):
            pred = preds[f"model{k}"]["all"]
            for tag, m in (("all", np.ones(len(pred), bool)), ("thin", thin)):
                if m.sum() < 10:
                    continue
                calib.setdefault(f"slope_{tag}", []).append(_wslope(pred[m], act["all"][m], wt[m]))
            if thin.sum() >= 10:
                top = thin & (pred >= np.quantile(pred[thin], 0.8))
                calib.setdefault("bias_thin_top", []).append(
                    float(np.average(pred[top] - act["all"][top], weights=wt[top]))
                )
        res["calib"] = {k: float(np.mean(v)) for k, v in calib.items()}
        # quintiles by pre-season value (first seed): how each fifth actually did
        balls, runs = df["balls"].to_numpy(), df["runs"].to_numpy()
        outs, trials = df["outs"].to_numpy(), df["trials"].to_numpy()
        res["quintiles"] = [
            {
                "fifth": i + 1,
                "n": len(ix),
                "runs_per_100": float(runs[ix].sum() * 100 / balls[ix].sum()),
                "balls_per_out": float(trials[ix].sum() / max(outs[ix].sum(), 1)),
            }
            for i, ix in enumerate(np.array_split(np.argsort(-preds["model0"]["all"]), 5))
        ]
        out[role] = res
    return out


def _summary(results: list[dict], names: list[str]) -> dict:
    s: dict = {}
    for role in ("batter", "bowler"):
        rows = [r[role] for r in results if role in r]
        s[role] = {}
        for a in AXES:
            s[role][a] = {n: float(np.mean([x[a][n] for x in rows])) for n in names}
            seeds = np.array([x[a]["model_by_seed"] for x in rows])  # season × seed
            per_seed = seeds.mean(axis=0)
            s[role][a]["model_seed_range"] = [float(per_seed.min()), float(per_seed.max())]
            thin_rows = [x for x in rows if "model_thin" in x[a]]
            if thin_rows:
                s[role][a]["thin"] = {
                    n: float(np.mean([x[a][f"{n}_thin"] for x in thin_rows])) for n in names
                }
    for role in ("batter", "bowler"):
        cal = [r[role]["calib"] for r in results if role in r and "calib" in r[role]]
        if cal:
            s[role]["calib"] = {k: float(np.mean([c[k] for c in cal if k in c])) for k in cal[0]}
    hs = [r["heldout"] for r in results]
    s["heldout"] = {
        k: float(np.average([h[k] for h in hs], weights=[h["n_balls"] for h in hs]))
        for k in hs[0]
        if k != "n_balls"
    }
    return s


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
    seed: int = typer.Option(42, "--seed", help="first ADVI seed"),
    seeds: int = typer.Option(3, "--seeds", help="ADVI seeds (seed, seed+1, ...)"),
    variant: str = typer.Option("v2", "--variant", help="v2 (default) | v3 | legacy"),
    compare: str = typer.Option(
        "", "--compare", help="also run this variant (e.g. legacy) with one seed, for comparison"
    ),
    out_json: Path | None = typer.Option(None, "--json"),
    nation: str = typer.Option(
        "auto", "--nation", help="nation prior: auto (international leagues) | on | off"
    ),
) -> None:
    nation_prior = {"auto": None, "on": True, "off": False}[nation]
    first, last = (int(x) for x in seasons.split("-"))
    seed_list = [seed + i for i in range(seeds)]
    names = ["model", "career"] + (["recent"] if half_life is not None else [])
    runs_by_variant: dict[str, list[dict]] = {}
    for var, sl in [(variant, seed_list)] + ([(compare, [seed])] if compare else []):
        results = []
        for s in range(first, last + 1):
            logger.info(f"[{var}] season {s}: fitting on matches before {s} ({len(sl)} seed(s))")
            results.append(
                _season(
                    collection,
                    s,
                    min_balls,
                    low_prior,
                    advi_steps,
                    sl,
                    half_life,
                    var,
                    nation_prior,
                )
            )
        runs_by_variant[var] = results
    out_path = out_json or (DATA_DIR / "metrics" / f"ratings_backtest_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "collection": collection,
        "min_balls": min_balls,
        "low_prior": low_prior,
        "half_life": half_life,
        "seeds": seed_list,
        "advi_steps": advi_steps,
    }
    payload = {
        **meta,
        "variants": {
            v: {"seasons": r, "summary": _summary(r, names)} for v, r in runs_by_variant.items()
        },
    }
    out_path.write_text(json.dumps(payload, indent=2))
    logger.info(f"wrote {out_path}")

    for v, results in runs_by_variant.items():
        summ = payload["variants"][v]["summary"]
        typer.echo(f"\n##### variant {v}  ·  columns: {' | '.join(names)}")
        for role in ("batter", "bowler"):
            typer.echo(f"\n=== {role}s ===")
            for r in results:
                if role in r:
                    x = r[role]
                    cells = "  ".join(
                        f"{LABEL[a]} " + " | ".join(f"{x[a][n]:+.2f}" for n in names) for a in AXES
                    )
                    typer.echo(f"{r['season']}  n={x['n']:>3}  {cells}")
            for a in AXES:
                m = summ[role][a]
                thin = " | ".join(f"{m['thin'][n]:+.2f}" for n in names) if "thin" in m else "—"
                lo, hi = m["model_seed_range"]
                typer.echo(
                    f"  mean {LABEL[a]:>15}: "
                    + " | ".join(f"{m[n]:+.2f}" for n in names)
                    + f"  (model seeds {lo:+.2f}..{hi:+.2f}; thin history: {thin})"
                )
        h = summ["heldout"]
        typer.echo(
            "  held-out log-likelihood per ball: "
            + ", ".join(f"{k} {val:.4f}" for k, val in h.items())
        )


if __name__ == "__main__":
    app()
