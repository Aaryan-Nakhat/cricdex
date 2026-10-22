"""Form forecast: 3-season player value projections for the IPL (docs/METHODOLOGY.md §11).

Three steps, each resumable:

1. `fits` — the IPL ratings as they stood at the end of every season: the Bayesian model fitted on
   matches before each auction date 2009-2026 (= everything through the season before; there are
   no IPL matches between a season's end and the next auction), one ADVI fit per seed. Shares the
   price model's cache (`data/metrics/.backtest_cache/<model version>/v2/ipl_auction<S>_s<seed>_
   12000.parquet`): seed 42 is usually already there; seeds 43 and 44 (for the backtest's seed
   range) take ~1.5 h. Safe to stop and resume.
2. `backtest` — projections made with data through 2021, 2022 and 2023 checked against what
   players actually did in 2022-2026, per horizon (1, 2, 3 seasons ahead), against three naive
   baselines, for each seed → `data/metrics/forecast_backtest_ipl.json`.
3. `build` — the shipped forecast for every active IPL player from the current ratings
   (`data/metrics/scout_ratings_ipl.json`) → `data/metrics/forecast_ipl.json`, which
   `export_forecast` copies (trimmed) to `site/public/data/ipl/forecast.json`.

Run:
    uv run python scripts/form_forecast.py fits --seeds 42,43,44     # long the first time
    uv run python scripts/form_forecast.py backtest
    uv run python scripts/form_forecast.py build
    uv run python scripts/form_forecast.py export --out site/public/data
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
import typer
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cricdex.config import DATA_DIR  # noqa: E402
from cricdex.scout import forecast  # noqa: E402
from cricdex.scout.ratings import bayesian  # noqa: E402

app = typer.Typer(add_completion=False)

CACHE = DATA_DIR / "metrics" / ".backtest_cache"
STEPS = 12000
VARIANT = "v2"
KEEP = ["cricsheet_id", "role", "balls", "skill", "skill_sd", "value", "value_sd"]
BACKTEST_PATH = DATA_DIR / "metrics" / "forecast_backtest_ipl.json"
FORECAST_PATH = DATA_DIR / "metrics" / "forecast_ipl.json"
HISTORY_PATH = DATA_DIR / "metrics" / ".forecast_history_ipl.parquet"


def auction_dates() -> dict[int, str]:
    from ipl_auction_history import AUCTIONS

    return {y: a["date"] for y, a in AUCTIONS.items()}


def fit_path(season: int, seed: int) -> Path:
    """The IPL fitted before the `season` auction (the price model's cache, same file names)."""
    return CACHE / bayesian.MODEL_VERSION / VARIANT / f"ipl_auction{season}_s{seed}_{STEPS}.parquet"


@app.callback()
def _main() -> None:
    """Form forecast: fits → backtest → build → export."""


def _say(msg: str, log_file: Path | None) -> None:
    logger.info(msg)
    if log_file:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


@app.command()
def fits(
    first: int = typer.Option(2009, "--first"),
    last: int = typer.Option(2026, "--last"),
    seeds: str = typer.Option("42,43,44", "--seeds"),
    log_file: Path | None = typer.Option(None, "--log", help="Also append progress here."),
) -> None:
    """Fit the IPL before every auction date, per seed (cached; resumable)."""
    dates = auction_dates()
    for seed in (int(s) for s in seeds.split(",")):
        for season in range(first, last + 1):
            path = fit_path(season, seed)
            if path.exists():
                _say(f"{season} s{seed}: cached", log_file)
                continue
            t = time.time()
            r = bayesian.fit(
                collection="ipl", before=dates[season], advi_steps=STEPS, seed=seed, variant=VARIANT
            )
            for c in KEEP:
                if c not in r.columns:
                    r = r.with_columns(pl.lit(None, pl.Float64).alias(c))
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            r.select(KEEP).write_parquet(tmp)
            tmp.replace(path)
            _say(
                f"{season} s{seed}: fitted before {dates[season]} in {time.time() - t:.0f}s "
                f"({r.height} rows)",
                log_file,
            )
    _say("done", log_file)


# ---- shared inputs ---------------------------------------------------------------------------------


def _history(refresh: bool, last: int) -> pl.DataFrame:
    if HISTORY_PATH.exists() and not refresh:
        h = pl.read_parquet(HISTORY_PATH)
        if int(h["season"].max()) >= last:
            return h
    logger.info("computing every IPL season's values 2008-{} (~40 s)", last)
    h = forecast.season_history(bayesian.DEFAULT_DB_PATH, "ipl", 2008, last)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    h.write_parquet(HISTORY_PATH)
    return h


def _dobs() -> dict[str, str]:
    from cricdex.scout.identity import master

    return {cid: r["dob"] for cid, r in master.load().items() if r.get("dob")}


def _ratings(seed: int, last_end: int) -> dict[int, pl.DataFrame]:
    """Season-end t → the ratings fitted through t (the fit before auction t + 1)."""
    out = {}
    for t in range(2008, last_end + 1):
        p = fit_path(t + 1, seed)
        if not p.exists():
            raise typer.BadParameter(f"missing fit {p.name}: run `form_forecast.py fits` first")
        out[t] = pl.read_parquet(p)
    return out


def _newest_season(history: pl.DataFrame) -> int:
    return int(history["season"].max())


# ---- backtest --------------------------------------------------------------------------------------

NAMES = ("model", "same_as_now", "current_level", "career_average", "age_curve", "last_season")


def _metrics(pred: np.ndarray, y: np.ndarray, groups: np.ndarray) -> dict:
    """MAE, bias and the mean over origins of the Spearman rank correlation."""
    rs = [forecast.spearman(pred[groups == g], y[groups == g]) for g in np.unique(groups)]
    return {
        "mae": float(np.mean(np.abs(pred - y))),
        "bias": float(np.mean(pred - y)),
        "spearman": float(np.nanmean(rs)),
    }


def _backtest_seed(
    sts: dict[int, pl.DataFrame],
    history: pl.DataFrame,
    origins: list[int],
    career: dict,
    min_balls: float,
) -> dict:
    """One seed's cells. `sts[T]`: the states as known at origin T (levels fitted on seasons <= T)."""
    from cricdex.scout.ratings import runs_value

    last = _newest_season(history)
    models = {T: forecast.fit_all(sts[T], history, T) for T in origins}
    curves = {
        (T, role): forecast.naive_age_curve(sts[T], history, role, T)
        for T in origins
        for role in forecast.ROLES
    }
    cells: dict = {}
    for role in forecast.ROLES:
        for k in forecast.HORIZONS:
            acc: dict[str, list] = {n: [] for n in NAMES}
            for extra in ("y", "g", "in80", "in80_level", "p_reg", "reg", "reg_base"):
                acc[extra] = []
            for T in origins:
                if T + k > last:
                    continue
                m = models[T][role]
                now = sts[T].filter((pl.col("t") == T) & (pl.col("role") == role))
                d = forecast.with_targets(now, history, k)
                mu = m.median(d, k)
                n = d["n"].to_numpy()
                # P(regular): model vs the training rate among players who are / aren't regulars now
                tr = forecast.with_targets(
                    sts[T].filter((pl.col("role") == role) & (pl.col("t") + k <= T)), history, k
                )
                tr_now = tr["n0"].to_numpy() >= forecast.REGULAR_BALLS
                tr_reg = tr["n"].to_numpy() >= forecast.REGULAR_BALLS
                now_reg = d["n0"].to_numpy() >= forecast.REGULAR_BALLS
                acc["p_reg"] += list(m.p_regular(d, k))
                acc["reg"] += list((n >= forecast.REGULAR_BALLS).astype(float))
                acc["reg_base"] += list(
                    np.where(now_reg, tr_reg[tr_now].mean(), tr_reg[~tr_now].mean())
                )
                # value, scored on the players who played the target season
                ok = n >= min_balls
                if ok.sum() < 5:
                    continue
                y = d["y"].to_numpy()[ok]
                v = d["v"].to_numpy()[ok]
                lvl = m.level_var(d, k)[ok]
                sd_season = m.scale[k] * np.sqrt(lvl + m.c * 100.0 / n[ok])
                ids = d["cricsheet_id"].to_list()
                age = d["age_t"].to_numpy().astype(float)[ok]
                curve = curves[(T, role)]
                shift = np.array([
                    0.0 if np.isnan(a) else sum(curve.get(int(a) + j, 0.0) for j in range(k))
                    for a in age
                ])  # fmt: skip
                y0 = d["y0"].to_numpy().astype(float)[ok]
                acc["model"] += list(mu[ok])
                acc["same_as_now"] += list(v)
                acc["career_average"] += list(
                    np.nan_to_num(runs_value.observed_value(career[T], role, ids))[ok]
                )
                acc["age_curve"] += list(v + shift)
                acc["last_season"] += list(np.where(np.isnan(y0), v, y0))
                acc["current_level"] += list(d["lvl"].to_numpy()[ok])
                acc["y"] += list(y)
                acc["g"] += [T] * int(ok.sum())
                acc["in80"] += list(np.abs(y - mu[ok]) <= forecast.Z80 * sd_season)
                acc["in80_level"] += list(
                    np.abs(y - mu[ok]) <= forecast.Z80 * m.scale[k] * np.sqrt(lvl)
                )
            y, g = np.array(acc["y"]), np.array(acc["g"])
            cell: dict = {"n": len(y), "origins": sorted({int(x) for x in g})}
            for nm in NAMES:
                cell[nm] = _metrics(np.array(acc[nm]), y, g)
            cell["coverage80_season"] = float(np.mean(acc["in80"]))
            cell["coverage80_level"] = float(np.mean(acc["in80_level"]))
            p, r = np.array(acc["p_reg"]), np.array(acc["reg"])
            cell["regular"] = {
                "n": len(r),
                "rate": float(r.mean()),
                "brier_model": float(np.mean((p - r) ** 2)),
                "brier_regular_now": float(np.mean((np.array(acc["reg_base"]) - r) ** 2)),
                "brier_base_rate": float(np.mean((r.mean() - r) ** 2)),
            }
            cells[f"{role}_{k}"] = cell
    return cells


@app.command()
def backtest(
    origins: str = typer.Option("2021,2022,2023", "--origins", help="last season of data used"),
    seeds: str = typer.Option("42,43,44", "--seeds"),
    min_balls: float = typer.Option(
        60, "--min-balls", help="balls in the target season to be scored"
    ),
    refresh: bool = typer.Option(False, "--refresh", help="recompute the season history"),
    out_json: Path = typer.Option(BACKTEST_PATH, "--json"),
) -> None:
    """Projections made with data through each origin, scored against what happened next."""
    from cricdex.scout.ratings import runs_value

    history = _history(refresh, 2026)
    dob = _dobs()
    origin_list = [int(x) for x in origins.split(",")]
    seed_list = [int(x) for x in seeds.split(",")]
    career = {
        T: runs_value.league_tables(bayesian.DEFAULT_DB_PATH, "ipl", before=f"{T + 1}-01-01")
        for T in origin_list
    }
    # the current-level model's parameters as they could be estimated at each origin
    lp = {T: forecast.fit_level_params(history, T, dob) for T in origin_list}
    per_seed: dict = {}
    for seed in seed_list:
        ratings = _ratings(seed, max(origin_list))
        sts = {
            T: forecast.states({t: r for t, r in ratings.items() if t <= T}, history, dob, lp[T])
            for T in origin_list
        }
        per_seed[str(seed)] = _backtest_seed(sts, history, origin_list, career, min_balls)
        logger.info(f"seed {seed} done")
    summary = summarise(per_seed)
    payload = {
        "collection": "ipl",
        "model_version": bayesian.MODEL_VERSION,
        "forecast_version": forecast.VERSION,
        "origins": origin_list,
        "seeds": seed_list,
        "min_balls": min_balls,
        "regular_balls": forecast.REGULAR_BALLS,
        "baselines": {
            "same_as_now": "the current rating (value) for every future season",
            "current_level": "his current level (the random-walk filter over his seasons) for every future season",
            "career_average": "raw career numbers through the origin, same runs currency",
            "age_curve": "the current rating plus the naive (survivors-only) average change by age",
            "last_season": "his value in the origin season (the rating if he didn't play it)",
        },
        "summary": summary,
        "by_seed": per_seed,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2))
    logger.info(f"wrote {out_json}")
    print_backtest(summary)


def summarise(per_seed: dict) -> dict:
    """Mean over seeds of every cell (and the seed range of MAE and Spearman)."""
    seeds = list(per_seed)
    summary: dict = {}
    for key in per_seed[seeds[0]]:
        rows = [per_seed[s][key] for s in seeds]
        out: dict = {"n": rows[0]["n"], "origins": rows[0]["origins"]}
        for nm in NAMES:
            out[nm] = {
                mt: float(np.mean([r[nm][mt] for r in rows])) for mt in ("mae", "bias", "spearman")
            }
            for mt in ("mae", "spearman"):
                vals = [r[nm][mt] for r in rows]
                out[nm][f"{mt}_seed_range"] = [float(min(vals)), float(max(vals))]
        for c in ("coverage80_season", "coverage80_level"):
            out[c] = float(np.mean([r[c] for r in rows]))
        out["regular"] = {
            mt: float(np.mean([r["regular"][mt] for r in rows])) for mt in rows[0]["regular"]
        }
        summary[key] = out
    return summary


def print_backtest(summary: dict) -> None:
    typer.echo(
        "\nrole    k  n     MAE model/now/career/age/last   "
        "rho model/now/level/career/age/last   cover80  Brier regular model/now-status/base"
    )
    for key, c in summary.items():
        role, k = key.rsplit("_", 1)
        mae = "/".join(f"{c[n]['mae']:.1f}" for n in NAMES)
        rho = "/".join(f"{c[n]['spearman']:.2f}" for n in NAMES)
        r = c["regular"]
        typer.echo(
            f"{role:7} {k}  {c['n']:4}  {mae:30}  {rho:30}  {c['coverage80_season']:.2f}     "
            f"{r['brier_model']:.3f}/{r['brier_regular_now']:.3f}/{r['brier_base_rate']:.3f}"
        )


# ---- build the shipped forecast ---------------------------------------------------------------------


@app.command()
def build(
    seed: int = typer.Option(42, "--seed", help="the walk-forward fits to train on"),
    refresh: bool = typer.Option(False, "--refresh", help="recompute the season history"),
    out_json: Path = typer.Option(FORECAST_PATH, "--json"),
) -> None:
    """Train on every season pair 2008-latest and project every active player from the current
    ratings (`data/metrics/scout_ratings_ipl.json`)."""
    history = _history(refresh, 2026)
    last = _newest_season(history)
    ratings = _ratings(seed, last - 1)
    current = pl.DataFrame(
        json.loads((DATA_DIR / "metrics" / "scout_ratings_ipl.json").read_text(encoding="utf-8")),
        infer_schema_length=None,
    )
    ratings[last] = current.select("cricsheet_id", "role", "value", "value_sd", "balls")
    from cricdex.scout.identity import master

    retired = [cid for cid, r in master.load().items() if r.get("retired")]
    payload = forecast.build_forecast(ratings, history, _dobs(), last, exclude=retired)
    payload["model_version"] = bayesian.MODEL_VERSION
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=1))
    logger.info(f"wrote {out_json}: {len(payload['players'])} players")


@app.command()
def export(
    out: Path = typer.Option(Path("site/public/data"), "--out", help="the site's data folder"),
    src: Path = typer.Option(FORECAST_PATH, "--src"),
) -> None:
    """Write the site's `ipl/forecast.json` (small: per player and role, the three seasons)."""
    path = forecast.export_site(src, out / "ipl" / "forecast.json")
    logger.info(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    app()
