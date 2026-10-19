"""Newcomer backtest: can other leagues predict a player's first IPL season?

For each season S, players new to the IPL (fewer than --max-ipl-prior balls in
that role before S) who then got a real go in S (at least --min-balls) are
rated from the other auction-pool leagues only (every `auction_pool` league in
config/leagues.toml except the IPL; the first published run used BBL, SA20,
CPL, T20 Blast and SMAT — `--leagues` repeats it), each fitted on matches
before S. Their value there, minus the same tier discount the auction pool
uses, is compared with how the IPL season went.

A player with several leagues gets ONE number per axis, pooled by precision —
the same rule as the auction pool: each league's value minus its discount,
weighted by 1 / (value sd² + the tier's translation sd²); each axis skill by
1 / sd². (Taking the best league, as the first version did, is biased upward:
the max of noisy estimates.)

Baseline: what a scout could work out by hand from the same matches, given the
same league adjustment — each league's raw numbers relative to that league's
average (runs per ball ÷ league runs per ball, outs per ball ÷ league rate),
the overall axis as z-scores within the league minus the same tier discount,
pooled across leagues by balls. So a model win isn't just the tier discount.

Seasons are pooled (each predictor and outcome is z-scored within its season
so a high-scoring year doesn't skew the ranking). Agreement is a Spearman rank
correlation (1 = same order, 0 = no link). The model is fitted with several
ADVI seeds (`--seeds`, default 3): each seed's correlation is reported, and the
seed-averaged prediction is what the bootstrap resamples. All six tests (two
roles × three axes) are reported with a bootstrap one-sided p (model no better
than raw) and its Holm adjustment for six comparisons. A playing-time
sensitivity check re-scores with 30 and 120 IPL balls as the bar (newcomers who
start badly get dropped, so the 60-ball sample is selected on early form).

Fits are cached (`data/metrics/.backtest_cache/`), so a second run over more
leagues reuses the first run's fits; `--jobs` fits in parallel processes.

Example:
    uv run python scripts/backtest_newcomers.py --seasons 2014-2026 \
        --leagues bbl,sa20,cpl,blast,indian_domestic_male --jobs 4
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import polars as pl
import typer
from backtest_ratings import AXES, LABEL, _spearman, _totals, _z, holm
from loguru import logger

from cricdex import leagues
from cricdex.config import DATA_DIR
from cricdex.scout.ratings import bayesian

app = typer.Typer(add_completion=False)

# other auction-pool leagues (the registry the auction pool uses). The first published run used the
# five leagues of the time; pass `--leagues` to repeat it.
LEAGUES = [lg.key for lg in leagues.auction_pool() if not lg.auction_target]
PUBLISHED_LEAGUES = "bbl,sa20,cpl,blast,indian_domestic_male"
ROLES = (
    ("batter", "batter_id", 1.0, -1.0, "survival_skill"),
    ("bowler", "bowler_id", -1.0, 1.0, "strike_skill"),
)
CACHE = DATA_DIR / "metrics" / ".backtest_cache"
_KEEP = [
    "cricsheet_id", "role", "skill", "skill_sd", "survival_skill", "survival_skill_sd",
    "strike_skill", "strike_skill_sd", "value", "value_sd",
]  # fmt: skip


def _cache_path(variant: str, col: str, season: int, seed: int, steps: int) -> Path:
    # keyed by the model version, so fits from an older model are never reused
    return CACHE / bayesian.MODEL_VERSION / variant / f"{col}_{season}_s{seed}_{steps}.parquet"


def _fit_task(args: tuple) -> str:
    """One league fitted on matches before a season (run in a worker process; cached)."""
    variant, col, season, seed, steps = args
    path = _cache_path(variant, col, season, seed, steps)
    if path.exists():
        return str(path)
    r = bayesian.fit(
        collection=col, before=f"{season}-01-01", advi_steps=steps, seed=seed, variant=variant
    )
    for c in _KEEP:
        if c not in r.columns:
            r = r.with_columns(pl.lit(None, pl.Float64).alias(c))
    path.parent.mkdir(parents=True, exist_ok=True)
    r.select(_KEEP).write_parquet(path)
    return str(path)


def _pool_model(rated: list[tuple[str, pl.DataFrame]], role: str) -> pl.DataFrame:
    """Per player: value (minus each league's discount) pooled by 1 / (sd² + translation sd²),
    each axis skill by 1 / sd²."""
    parts = []
    for col, r in rated:
        pen, tsd = leagues.discount(col), leagues.translation_sd(col)
        odds = "survival_skill" if role == "batter" else "strike_skill"
        parts.append(
            r.filter(pl.col("role") == role).select(
                "cricsheet_id",
                (pl.col("value") - pen).alias("value"),
                (1.0 / (pl.col("value_sd") ** 2 + tsd**2)).alias("wv"),
                pl.col("skill"),
                (1.0 / pl.col("skill_sd").clip(lower_bound=1e-3) ** 2).alias("ws"),
                pl.col(odds).alias("odds"),
                (1.0 / pl.col(f"{odds}_sd").clip(lower_bound=1e-3) ** 2).alias("wo"),
            )
        )
    allr = pl.concat(parts, how="vertical_relaxed")
    return allr.group_by("cricsheet_id").agg(
        ((pl.col("value") * pl.col("wv")).sum() / pl.col("wv").sum()).alias("m_all"),
        ((pl.col("skill") * pl.col("ws")).sum() / pl.col("ws").sum()).alias("m_rate"),
        ((pl.col("odds") * pl.col("wo")).sum() / pl.col("wo").sum()).alias("m_odds"),
    )


def _pool_raw(
    edges: list[tuple[str, pl.DataFrame]], key: str, rate_sign: float, odds_sign: float
) -> pl.DataFrame:
    """Per player: each league's raw numbers relative to that league's average, the overall axis
    as within-league z-scores minus the league's discount, pooled across leagues by balls."""
    parts = []
    for col, e in edges:
        t = _totals(e, key)
        rate_l = float(t["balls"].sum()) and float(t["runs"].sum()) / float(t["balls"].sum())
        odds_l = float(t["trials"].sum()) and float(t["outs"].sum()) / float(t["trials"].sum())
        if not rate_l or not odds_l:
            continue
        t = t.filter(pl.col("balls") > 0).with_columns(
            (rate_sign * pl.col("runs") / pl.col("balls") / rate_l).alias("rate"),
            (odds_sign * pl.col("outs") / pl.col("trials").clip(lower_bound=1) / odds_l).alias(
                "odds"
            ),
        )
        # z within the league among players with a real sample, then the same tier discount
        ref = t.filter(pl.col("balls") >= 60)
        if ref.height < 5:
            ref = t
        zr = (pl.col("rate") - ref["rate"].mean()) / (ref["rate"].std() or 1.0)
        zo = (pl.col("odds") - ref["odds"].mean()) / (ref["odds"].std() or 1.0)
        parts.append(
            t.select(
                "cricsheet_id",
                "balls",
                "trials",
                "rate",
                "odds",
                (zr + zo - leagues.discount(col)).alias("all"),
            )
        )
    allr = pl.concat(parts, how="vertical_relaxed")
    return allr.group_by("cricsheet_id").agg(
        ((pl.col("rate") * pl.col("balls")).sum() / pl.col("balls").sum()).alias("r_rate"),
        ((pl.col("odds") * pl.col("trials")).sum() / pl.col("trials").sum()).alias("r_odds"),
        ((pl.col("all") * pl.col("balls")).sum() / pl.col("balls").sum()).alias("r_all"),
        pl.col("balls").sum().alias("o_balls"),
    )


@app.command()
def run(
    seasons: str = typer.Option("2021-2026", "--seasons", help="first-last, e.g. 2021-2026"),
    min_balls: int = typer.Option(60, "--min-balls", help="IPL balls in the season to be scored"),
    max_ipl_prior: int = typer.Option(60, "--max-ipl-prior", help="'new' = fewer prior IPL balls"),
    advi_steps: int = typer.Option(12000, "--advi-steps"),
    seed: int = typer.Option(42, "--seed", help="first ADVI seed"),
    seeds: int = typer.Option(3, "--seeds", help="ADVI seeds (seed, seed+1, ...)"),
    variant: str = typer.Option("v2", "--variant", help="v2 (default) | legacy"),
    boot: int = typer.Option(2000, "--boot", help="bootstrap resamples for the model-vs-raw gap"),
    jobs: int = typer.Option(1, "--jobs", help="fits in parallel processes"),
    out_json: Path | None = typer.Option(None, "--json"),
    league_keys: str = typer.Option(
        "",
        "--leagues",
        help="comma-separated league keys to rate newcomers from (blank = every non-IPL "
        f"auction-pool league in config/leagues.toml; the first published run: {PUBLISHED_LEAGUES})",
    ),
) -> None:
    first, last = (int(x) for x in seasons.split("-"))
    cols = [k for k in league_keys.split(",") if k] if league_keys else LEAGUES
    for k in cols:
        leagues.get(k)  # unknown key → error now, not after an hour of fitting
    logger.info(f"rating newcomers from: {', '.join(cols)} · {seeds} seed(s) · variant {variant}")
    db = bayesian.DEFAULT_DB_PATH
    seed_list = [seed + i for i in range(seeds)]

    # ---- 1. every (league, season, seed) fit, in parallel, cached ----
    prior_edges: dict[tuple[str, int], pl.DataFrame] = {}
    tasks = []
    for s in range(first, last + 1):
        for col in cols:
            try:
                e = bayesian._load_edges(db, col, before=f"{s}-01-01")
            except Exception as exc:  # a registry league that isn't ingested yet
                logger.warning(f"  {s}: skipping {col} ({exc})")
                continue
            if e.is_empty():
                continue
            prior_edges[(col, s)] = e
            tasks += [(variant, col, s, sd, advi_steps) for sd in seed_list]
    todo = [t for t in tasks if not _cache_path(*t).exists()]
    logger.info(f"{len(tasks)} fits ({len(tasks) - len(todo)} cached)")
    if todo:
        if jobs > 1:
            # fresh workers every few fits keep memory flat (each fit compiles new programs);
            # a new pool per chunk, since worker recycling (max_tasks_per_child) can hang on Windows
            chunk = jobs * 3
            done = 0
            for at in range(0, len(todo), chunk):
                with ProcessPoolExecutor(max_workers=jobs) as ex:
                    for p in ex.map(_fit_task, todo[at : at + chunk]):
                        done += 1
                        logger.info(f"  fit {done}/{len(todo)} → {Path(p).name}")
        else:
            for i, t in enumerate(todo, 1):
                logger.info(f"  fit {i}/{len(todo)}: {t[1]} before {t[2]} (seed {t[3]})")
                _fit_task(t)

    # ---- 2. score each season, for each playing-time bar ----
    def score(bar: int) -> dict:
        pooled: dict[str, dict[str, list]] = {
            role: {f"act_{a}": [] for a in AXES}
            | {f"raw_{a}": [] for a in AXES}
            | {f"model_{a}": [] for a in AXES}
            | {f"model{k}_{a}": [] for k in range(len(seed_list)) for a in AXES}
            | {"rows": []}
            for role, *_ in ROLES
        }
        for s in range(first, last + 1):
            start, end = f"{s}-01-01", f"{s + 1}-01-01"
            have = [c for c in cols if (c, s) in prior_edges]
            if not have:
                continue
            ipl_prior = bayesian._load_edges(db, "ipl", before=start)
            ipl_season = bayesian._load_edges(db, "ipl", since=start, before=end)
            for role, key, rate_sign, odds_sign, _ in ROLES:
                per_seed = []
                for sd in seed_list:
                    rated = [
                        (c, pl.read_parquet(_cache_path(variant, c, s, sd, advi_steps)))
                        for c in have
                    ]
                    per_seed.append(_pool_model(rated, role))
                raw = _pool_raw([(c, prior_edges[(c, s)]) for c in have], key, rate_sign, odds_sign)
                prior_ipl = _totals(ipl_prior, key, "p_").select("cricsheet_id", "p_balls")
                df = (
                    _totals(ipl_season, key)
                    .filter(pl.col("balls") >= bar)
                    .join(prior_ipl, on="cricsheet_id", how="left")
                    .filter(pl.col("p_balls").fill_null(0) < max_ipl_prior)
                    .join(raw, on="cricsheet_id", how="inner")  # needs other-league history
                    .filter(pl.col("o_balls") > 0)
                )
                for k, m in enumerate(per_seed):
                    df = df.join(
                        m.rename({f"m_{a}": f"m{k}_{a}" for a in AXES}),
                        on="cricsheet_id",
                        how="inner",
                    )
                if df.height < 3:
                    continue
                act_rate = rate_sign * (df["runs"] / df["balls"]).to_numpy()
                act_odds = odds_sign * (df["outs"] / df["trials"].clip(1)).to_numpy()
                act = {"rate": act_rate, "odds": act_odds, "all": _z(act_rate) + _z(act_odds)}
                p = pooled[role]
                for a in AXES:  # z within the season, then pool
                    seeds_a = [df[f"m{k}_{a}"].to_numpy() for k in range(len(seed_list))]
                    p[f"act_{a}"].extend(_z(act[a]))
                    p[f"raw_{a}"].extend(_z(df[f"r_{a}"].to_numpy()))
                    p[f"model_{a}"].extend(_z(np.mean(seeds_a, axis=0)))
                    for k, v in enumerate(seeds_a):
                        p[f"model{k}_{a}"].extend(_z(v))
                p["rows"].extend({"season": s, "cricsheet_id": c} for c in df["cricsheet_id"])
        out: dict = {}
        for role, *_ in ROLES:
            p = pooled[role]
            n = len(p["rows"])
            res: dict = {"n": n}
            rng = np.random.default_rng(seed)
            boots = [rng.integers(0, n, n) for _ in range(boot)] if n >= 10 else []
            for a in AXES:
                act = np.asarray(p[f"act_{a}"])
                mod, raw = np.asarray(p[f"model_{a}"]), np.asarray(p[f"raw_{a}"])
                res[a] = {
                    "model": _spearman(mod, act) if n >= 10 else None,
                    "raw": _spearman(raw, act) if n >= 10 else None,
                    "model_by_seed": [
                        _spearman(np.asarray(p[f"model{k}_{a}"]), act)
                        for k in range(len(seed_list))
                    ]
                    if n >= 10
                    else [],
                }
                if boots:
                    # resample players with replacement: how sure is the model − raw gap?
                    diffs = np.array(
                        [_spearman(mod[i], act[i]) - _spearman(raw[i], act[i]) for i in boots]
                    )
                    lo, hi = np.percentile(diffs, [2.5, 97.5])
                    res[a]["gap_ci95"] = [float(lo), float(hi)]
                    res[a]["p_model_better"] = float((diffs > 0).mean())
                    res[a]["p_one_sided"] = float((diffs <= 0).mean())
            res["players"] = [
                {**row, **{k: float(v[i]) for k, v in p.items() if k != "rows"}}
                for i, row in enumerate(p["rows"])
            ]
            out[role] = res
        tests = [
            (r, a) for r, *_ in ROLES for a in AXES if out[r][a].get("p_one_sided") is not None
        ]
        adj = holm([out[r][a]["p_one_sided"] for r, a in tests])
        for (r, a), q in zip(tests, adj, strict=True):
            out[r][a]["p_holm"] = q
        return out

    result: dict = {
        "min_balls": min_balls,
        "max_ipl_prior": max_ipl_prior,
        "seasons": seasons,
        "leagues": cols,
        "seeds": seed_list,
        "variant": variant,
        "advi_steps": advi_steps,
    }
    main = score(min_balls)
    result.update(main)
    result["sensitivity"] = {}
    for bar in sorted({30, 120} - {min_balls}):
        sens = score(bar)
        result["sensitivity"][str(bar)] = {
            role: {"n": sens[role]["n"]}
            | {a: {k: sens[role][a].get(k) for k in ("model", "raw")} for a in AXES}
            for role, *_ in ROLES
        }

    typer.echo(
        "\nIPL newcomers, rated from other leagues only  ·  model (seed range) | raw, league-adjusted"
    )
    for role, *_ in ROLES:
        res = result[role]
        typer.echo(f"\n{role}s  n={res['n']}")
        for a in AXES:
            x = res[a]
            if x["model"] is None:
                continue
            seeds_txt = (
                f" ({min(x['model_by_seed']):+.2f}..{max(x['model_by_seed']):+.2f})"
                if x["model_by_seed"]
                else ""
            )
            ci = x.get("gap_ci95")
            extra = (
                f"  gap {x['model'] - x['raw']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}],"
                f" better in {x['p_model_better']:.0%}, p={x['p_one_sided']:.3f},"
                f" Holm p={x.get('p_holm', float('nan')):.3f}"
                if ci
                else ""
            )
            typer.echo(
                f"  {LABEL[a]:>15}: model {x['model']:+.2f}{seeds_txt} | raw {x['raw']:+.2f}{extra}"
            )
    for bar, sens in result["sensitivity"].items():
        typer.echo(f"\nsensitivity: {bar}+ IPL balls")
        for role, *_ in ROLES:
            cells = "  ".join(
                f"{LABEL[a]} {sens[role][a]['model']:+.2f} | {sens[role][a]['raw']:+.2f}"
                for a in AXES
                if sens[role][a]["model"] is not None
            )
            typer.echo(f"  {role}s n={sens[role]['n']}: {cells}")
    out_path = out_json or (DATA_DIR / "metrics" / "newcomer_backtest_ipl.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    logger.info(f"wrote {out_path}")


if __name__ == "__main__":
    app()
