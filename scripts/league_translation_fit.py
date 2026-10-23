"""Fit, validate and ship the league translations: how a rating in another league carries over to
the IPL, per league and per role (docs/METHODOLOGY.md §6d; `src/cricdex/scout/translation.py`).

Until 2026-10-23 a league's rating was moved onto the IPL by one hand-set number per league (SMAT −17,
BBL / SA20 −6, CPL / Blast −8.5, eight leagues borrowing one of those), with a guessed translation sd
and a 300-ball switch that ignored every other league once a player had 300 IPL balls in a role
(audit item 5). This script replaces all of it with a fitted model.

The mechanism
-------------
For every IPL season S, a player's **observed IPL value in S** (runs per 100 balls above that season's
average ball, `runs_value.observed_value`, from n balls) is modelled from what was known before S:

    y = α_k + β_k · x + e,    Var(e) = τ_k² + β_k² · sd_x² + κ / n

where x (sd_x) is his rating in source k fitted on matches before S: the IPL itself (his IPL rating
as of the S auction) or a league L (its rating as of 1 January of S, the newcomer backtest's cached
fits). κ / n is the ball-to-ball noise of a season's numbers (one κ per role), τ_k² everything a
rating in k doesn't know about his next IPL season. A league pair counts only when he played L in
the two calendar years before S (time-matched), and only seasons with n ≥ MIN_N balls in the role.

Leagues are pooled hierarchically, per role: α_L ~ N(μ_α[g], σ_α²), β_L ~ N(μ_β[g], σ_β²), log τ_L ~
N(m_τ, s_τ²), the pooling group g from `config/leagues.toml` (`[tiers.*] group`), so a league with few
players who also reached the IPL (MLC, ILT20, SA20, LPL) is pulled to its group instead of borrowing a
copied number. Fitted by NUTS (NumPyro).

**Selection.** Players reach the IPL because their league numbers were good. Regressing on the
rating (a posterior mean, already shrunk) makes selection *on the rating* harmless — a raw mean
difference would not be — and every IPL season with MIN_N+ balls counts, so a newcomer dropped after
a bad month still counts. A declared candidate re-weights pairs by the inverse chance of reaching the
IPL given the league rating (IPW, as the form forecast does).

**Onto the IPL rating's scale.** The pool compares league players with IPL players on the IPL
*rating* scale, and an IPL rating itself predicts the next season with a slope β_IPL < 1. So a league
rating is translated to the IPL rating that predicts the same season:

    t = a_L + b_L · x,   a_L = (α_L − α_IPL) / β_IPL,   b_L = β_L / β_IPL,
    translation sd = √max(τ_L² − τ_IPL², 0) / β_IPL     (what L knows less than the IPL does)

computed per posterior draw; the parameter uncertainty (the posterior covariance of a_L, b_L) is kept
too, so a thin league's translation is less certain.

**The blend** (replacing the 300-ball switch): every source as a Gaussian on the IPL rating scale —
the IPL rating (value, sd) and each league's (t, √(b_L² sd_x² + tsd_L² + parameter variance)) —
combined by precision. Candidate B also divides out the population prior that each source's posterior
already contains (an exact Gaussian product of posteriors).

Frozen protocol (declared 2026-10-23, before any test number)
---------------------------------------------------------------
* Candidates (below) are compared by rolling-origin validation: for V = 2022, 2023, 2024, fit on
  seasons < V, score season V. The choice is by the mean predictive log score per player-season
  (players with league ratings: newcomers and returners), both roles.
* The chosen candidate is refitted on seasons ≤ 2024 and scored **once** on the 2025 and 2026 IPL
  seasons, against the scheme it replaces (the hand-set discounts with the 300-ball switch) and "no
  translation" (league ratings taken as IPL ratings). Reported: level calibration (bias and MAE of the
  predicted IPL value per 100 balls, the calibration slope, a calibration table by predicted level),
  rank (Spearman) and the log score.
* The shipped translation is refitted on every season ≤ 2026.

    uv run python scripts/league_translation_fit.py pairs      # ~1 min: the pairs and outcomes
    uv run python scripts/league_translation_fit.py fit        # ~15 min: validate, test, ship

Writes config/league_translation.json (read by `cricdex.scout.translation`) and
data/metrics/league_translation_ipl.json (every table).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import typer
from loguru import logger

from cricdex import leagues
from cricdex.common.sql import keyed_balls, materialize_keyed
from cricdex.config import DATA_DIR
from cricdex.scout import translation
from cricdex.scout.ratings import bayesian, runs_value

app = typer.Typer(add_completion=False)

ROOT = Path(__file__).resolve().parents[1]
CACHE = DATA_DIR / "metrics" / ".backtest_cache" / bayesian.MODEL_VERSION / "v2"
WORK = DATA_DIR / "metrics" / ".translation"
REPORT = DATA_DIR / "metrics" / "league_translation_ipl.json"
MODEL_PATH = ROOT / "config" / "league_translation.json"
SEED = 42  # the seed of the cached fits the price model and the export also use
SEASONS = range(2015, 2027)  # IPL seasons with as-of fits on both sides
OTHER = [lg.key for lg in leagues.auction_pool() if not lg.auction_target]
TARGET = leagues.auction_target().key
ROLES = ("batter", "bowler")
MIN_N = 20  # IPL balls in the season in the role for a season to be scored or fitted on
RECENT_YEARS = 2  # a league pair is time-matched when he played it in the 2 years before S
NEW_BALLS = (
    60  # fewer prior IPL balls in the role than this = a newcomer (the newcomer backtest's bar)
)
VALID = (2022, 2023, 2024)
TEST = (2025, 2026)
LAST_TRAIN = 2024

# The scheme this replaces (config/leagues.toml until 2026-10-23), kept only as the baseline: one
# discount per league, translation sd 6.5 / 10.5, a role record of 300+ IPL balls standing alone
# (cricdex.scout.translation.legacy_blend).

# Candidates, declared before any test number (2026-10-23). `groups`: how leagues are pooled
# ("registry" = the [tiers.*] group in config/leagues.toml; "one" = every non-IPL league in one group).
CANDIDATES = {
    "T1 hierarchical, registry groups, precision blend": {"groups": "registry", "blend": "precision"},
    "T2 T1 with the prior divided out of the blend": {"groups": "registry", "blend": "product"},
    "T3 T1, one pooling group": {"groups": "one", "blend": "precision"},
    "T4 T1 + phase mix (death / powerplay share)": {"groups": "registry", "blend": "precision",
                                                     "phase": True},
    "T5 T1 with selection weights (IPW)": {"groups": "registry", "blend": "precision", "ipw": True},
}  # fmt: skip
NUTS_WARMUP, NUTS_SAMPLES = 800, 800


# ---- 1. pairs -------------------------------------------------------------------------------------


@app.command()
def pairs() -> None:
    """Every rating as of each IPL season (the cached fits), each player's activity per league and
    year, and every IPL season's observed values: data/metrics/.translation/*.parquet."""
    WORK.mkdir(parents=True, exist_ok=True)
    db = bayesian.DEFAULT_DB_PATH
    act = []
    with duckdb.connect(str(db), read_only=True) as con:
        have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for col in OTHER + [TARGET]:
            if f"balls_{col}" not in have:
                continue
            materialize_keyed(con, col)
            kb = keyed_balls(con, col)
            for role, key in (("batter", "batter"), ("bowler", "bowler")):
                d = con.execute(
                    f"""SELECT {key} AS cid, CAST(LEFT(CAST(match_date AS VARCHAR), 4) AS INT) AS yr,
                           COALESCE(phase, 'middle') AS phase,
                           CAST(SUM(CASE WHEN extras_type = 'wides' THEN 0 ELSE 1 END) AS DOUBLE)
                             AS balls
                    FROM {kb} WHERE {key} IS NOT NULL AND innings_idx <= 1 GROUP BY 1, 2, 3"""
                ).pl()
                act.append(d.with_columns(pl.lit(col).alias("col"), pl.lit(role).alias("role")))
    pl.concat(act).write_parquet(WORK / "activity.parquet")

    ys = []
    for s in SEASONS:
        tab = runs_value.league_tables(db, TARGET, since=f"{s}-01-01", before=f"{s + 1}-01-01")
        for role in ROLES:
            ids = list(tab.totals.get(role, {}).keys())
            if not ids:
                continue
            v = runs_value.observed_value(tab, role, ids)
            n = [float(tab.totals[role][i][:, 3].sum()) for i in ids]
            ys.append(
                pl.DataFrame({"cid": ids, "y": v, "n": n}).with_columns(
                    pl.lit(s).alias("season"), pl.lit(role).alias("role")
                )
            )
        logger.info(f"IPL {s}: observed values")
    pl.concat(ys).filter(pl.col("n") > 0).write_parquet(WORK / "ipl_seasons.parquet")

    fits = []
    for s in SEASONS:
        for col in OTHER + [TARGET]:
            name = f"ipl_auction{s}" if col == TARGET else f"{col}_{s}"
            p = CACHE / f"{name}_s{SEED}_12000.parquet"
            if not p.exists():
                continue
            r = pl.read_parquet(p)
            if "balls" not in r.columns:
                r = r.with_columns(pl.lit(None, pl.Float64).alias("balls"))
            fits.append(
                r.select(
                    pl.col("cricsheet_id").alias("cid"), "role", "value", "value_sd",
                    pl.col("balls").cast(pl.Float64),
                ).with_columns(pl.lit(col).alias("col"), pl.lit(s).alias("season"))
            )  # fmt: skip
    fits = pl.concat(fits, how="vertical_relaxed").filter(
        pl.col("value").is_not_null()
        & pl.col("cid").is_not_null()
        & pl.col("value_sd").is_not_null()
    )
    fits.write_parquet(WORK / "fits.parquet")
    logger.info(f"wrote {WORK} ({fits.height} as-of ratings)")


def _load() -> tuple[pl.DataFrame, pl.DataFrame]:
    """(league observations: every league rating as of S with his activity, outcome and IPL rating;
    units: every IPL player-season with its outcome and IPL rating as of S)."""
    act = pl.read_parquet(WORK / "activity.parquet")
    ys = pl.read_parquet(WORK / "ipl_seasons.parquet")
    fits = pl.read_parquet(WORK / "fits.parquet")
    ay = act.group_by("col", "cid", "role", "yr").agg(
        pl.col("balls").sum(),
        pl.col("balls").filter(pl.col("phase") == "death").sum().alias("death"),
        pl.col("balls").filter(pl.col("phase") == "powerplay").sum().alias("pp"),
    )
    win = []
    for s in SEASONS:
        w = (
            ay.filter(pl.col("yr") < s)
            .group_by("col", "cid", "role")
            .agg(
                pl.col("balls").sum().alias("l_balls"),
                pl.col("balls").filter(pl.col("yr") >= s - RECENT_YEARS).sum().alias("l_recent"),
                pl.col("yr").max().alias("l_last_yr"),
                (pl.col("death").sum() / pl.col("balls").sum().clip(lower_bound=1)).alias("death"),
                (pl.col("pp").sum() / pl.col("balls").sum().clip(lower_bound=1)).alias("pp"),
            )
        )
        win.append(w.with_columns(pl.lit(s).alias("season")))
    win = pl.concat(win)
    ipl = fits.filter(pl.col("col") == TARGET).select(
        "cid", "role", "season", pl.col("value").alias("ipl_v"), pl.col("value_sd").alias("ipl_sd"),
        pl.col("balls").fill_null(0.0).alias("ipl_balls"),
    )  # fmt: skip
    lg = (
        fits.filter(pl.col("col") != TARGET)
        .drop("balls")
        .join(win, on=["col", "cid", "role", "season"], how="left")
        .with_columns(pl.col("l_balls").fill_null(0.0), pl.col("l_recent").fill_null(0.0))
        .join(
            ys.select("cid", "role", "season", "y", "n"), on=["cid", "role", "season"], how="left"
        )
        .join(ipl, on=["cid", "role", "season"], how="left")
        .with_columns(pl.col("ipl_balls").fill_null(0.0))
    )
    units = ys.filter(pl.col("n") >= MIN_N).join(ipl, on=["cid", "role", "season"], how="left")
    units = units.with_columns(pl.col("ipl_balls").fill_null(0.0))
    return lg, units


# ---- 2. the model ---------------------------------------------------------------------------------


def _groups(kind: str) -> dict[str, str]:
    reg = leagues.load()
    out = {}
    for col in OTHER:
        out[col] = "all" if kind == "one" else reg.tiers[leagues.get(col).tier].group
    return out


def _ipw(lg: pl.DataFrame, role: str, last: int) -> pl.DataFrame:
    """Inverse chance of reaching the IPL (MIN_N+ balls in S) given the league rating: a logistic
    regression per role on every time-matched league rating of seasons ≤ last (rating, its sd, log
    balls in the league, the league)."""
    from sklearn.linear_model import LogisticRegression

    d = lg.filter(
        (pl.col("role") == role) & (pl.col("season") <= last) & (pl.col("l_recent") > 0)
    ).with_columns((pl.col("n").fill_null(0) >= MIN_N).alias("sel"))
    cols = sorted(d["col"].unique())
    X = np.c_[
        d["value"].to_numpy(), d["value_sd"].to_numpy(), np.log1p(d["l_balls"].to_numpy()),
        np.array([[c == k for k in cols] for c in d["col"]], dtype=float),
    ]  # fmt: skip
    m = LogisticRegression(C=1.0, max_iter=2000).fit(X, d["sel"].to_numpy())
    p = m.predict_proba(X)[:, 1]
    w = 1.0 / np.clip(p, 0.02, 1.0)
    return (
        d.with_columns(pl.Series("w", w)).filter(pl.col("sel")).select("col", "cid", "season", "w")
    )


def fit_role(lg: pl.DataFrame, units: pl.DataFrame, role: str, last: int, spec: dict) -> dict:
    """Fit the season-outcome model for one role on seasons ≤ last; returns the translation table
    (rating scale) and the IPL line, from the posterior draws."""
    import jax
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.infer import MCMC, NUTS

    groups = _groups(spec["groups"])
    gnames = sorted(set(groups.values()))
    pairs_ = lg.filter(
        (pl.col("role") == role) & (pl.col("season") <= last) & (pl.col("l_recent") > 0)
        & (pl.col("n") >= MIN_N) & pl.col("y").is_not_null()
    )  # fmt: skip
    if spec.get("ipw"):
        pairs_ = pairs_.join(_ipw(lg, role, last), on=["col", "cid", "season"], how="left")
        pairs_ = pairs_.with_columns(pl.col("w").fill_null(1.0))
        pairs_ = pairs_.with_columns(pl.col("w") / pl.col("w").mean().over("col"))
    else:
        pairs_ = pairs_.with_columns(pl.lit(1.0).alias("w"))
    ipl_u = units.filter(
        (pl.col("role") == role) & (pl.col("season") <= last) & pl.col("ipl_v").is_not_null()
    )
    cols = [c for c in OTHER if c in set(pairs_["col"])]
    li = {c: i for i, c in enumerate(cols)}
    gi = {g: i for i, g in enumerate(gnames)}
    L, G = len(cols), len(gnames)
    lg_idx = jnp.array([li[c] for c in pairs_["col"]])
    g_of_l = jnp.array([gi[groups[c]] for c in cols])
    xl = jnp.array(pairs_["value"].to_numpy(), dtype=jnp.float32)
    sl = jnp.array(pairs_["value_sd"].to_numpy(), dtype=jnp.float32)
    nl = jnp.array(pairs_["n"].to_numpy(), dtype=jnp.float32)
    yl = jnp.array(pairs_["y"].to_numpy(), dtype=jnp.float32)
    wl = jnp.array(pairs_["w"].to_numpy(), dtype=jnp.float32)
    dl = jnp.array(pairs_["death"].fill_null(0.0).to_numpy() - 0.25, dtype=jnp.float32)
    pl_ = jnp.array(pairs_["pp"].fill_null(0.0).to_numpy() - 0.3, dtype=jnp.float32)
    xi = jnp.array(ipl_u["ipl_v"].to_numpy(), dtype=jnp.float32)
    si = jnp.array(ipl_u["ipl_sd"].to_numpy(), dtype=jnp.float32)
    ni = jnp.array(ipl_u["n"].to_numpy(), dtype=jnp.float32)
    yi = jnp.array(ipl_u["y"].to_numpy(), dtype=jnp.float32)
    phase = bool(spec.get("phase"))

    def model():
        kappa_sd = numpyro.sample("kappa_sd", dist.HalfNormal(500.0))  # per-ball noise, runs/100
        a_i = numpyro.sample("a_ipl", dist.Normal(0.0, 10.0))
        b_i = numpyro.sample("b_ipl", dist.Normal(0.7, 0.5))
        t_i = numpyro.sample("tau_ipl", dist.HalfNormal(25.0))
        var_i = t_i**2 + (b_i * si) ** 2 + kappa_sd**2 / ni
        numpyro.sample("y_ipl", dist.Normal(a_i + b_i * xi, jnp.sqrt(var_i)), obs=yi)
        mu_a = numpyro.sample("mu_a", dist.Normal(0.0, 15.0).expand([G]))
        mu_b = numpyro.sample("mu_b", dist.Normal(0.5, 0.5).expand([G]))
        s_a = numpyro.sample("s_a", dist.HalfNormal(5.0))
        s_b = numpyro.sample("s_b", dist.HalfNormal(0.25))
        m_t = numpyro.sample("m_t", dist.Normal(math.log(20.0), 1.0))
        s_t = numpyro.sample("s_t", dist.HalfNormal(0.3))
        with numpyro.plate("league", L):
            za = numpyro.sample("za", dist.Normal(0.0, 1.0))
            zb = numpyro.sample("zb", dist.Normal(0.0, 1.0))
            zt = numpyro.sample("zt", dist.Normal(0.0, 1.0))
        a_l = numpyro.deterministic("a_l", mu_a[g_of_l] + s_a * za)
        b_l = numpyro.deterministic("b_l", mu_b[g_of_l] + s_b * zb)
        t_l = numpyro.deterministic("tau_l", jnp.exp(m_t + s_t * zt))
        mean = a_l[lg_idx] + b_l[lg_idx] * xl
        if phase:
            c_d = numpyro.sample("c_death", dist.Normal(0.0, 20.0))
            c_p = numpyro.sample("c_pp", dist.Normal(0.0, 20.0))
            mean = mean + c_d * dl + c_p * pl_
        var = t_l[lg_idx] ** 2 + (b_l[lg_idx] * sl) ** 2 + kappa_sd**2 / nl
        lp = dist.Normal(mean, jnp.sqrt(var)).log_prob(yl)
        numpyro.factor("y_league", jnp.sum(wl * lp))

    mcmc = MCMC(
        NUTS(model, target_accept_prob=0.9), num_warmup=NUTS_WARMUP, num_samples=NUTS_SAMPLES,
        progress_bar=False,
    )  # fmt: skip
    mcmc.run(jax.random.PRNGKey(SEED))
    s = {k: np.asarray(v, dtype=float) for k, v in mcmc.get_samples().items()}
    b_i, a_i, t_i = s["b_ipl"], s["a_ipl"], s["tau_ipl"]
    b_i = np.where(np.abs(b_i) < 0.05, 0.05, b_i)
    out = {
        "role": role,
        "trained_through": last,
        "n_pairs": int(pairs_.height),
        "n_ipl": int(ipl_u.height),
        "ipl_line": {"a": float(a_i.mean()), "b": float(b_i.mean()), "tau": float(t_i.mean())},
        "kappa_sd": float(s["kappa_sd"].mean()),
        "leagues": {},
        "groups": {},
    }
    if phase:
        out["phase"] = {"death": float(s["c_death"].mean()), "pp": float(s["c_pp"].mean()),
                        "death_sd": float(s["c_death"].std()), "pp_sd": float(s["c_pp"].std())}  # fmt: skip

    def table(alpha, beta, tau):
        a = (alpha - a_i) / b_i
        b = beta / b_i
        tsd = np.sqrt(np.maximum(tau**2 - t_i**2, 0.0)) / b_i
        cov = np.cov(np.vstack([a, b]))
        return {
            "a": float(a.mean()), "b": float(b.mean()), "tsd": float(np.sqrt(np.mean(tsd**2))),
            "cov": [[float(cov[0, 0]), float(cov[0, 1])], [float(cov[1, 0]), float(cov[1, 1])]],
            "alpha": float(alpha.mean()), "beta": float(beta.mean()), "tau": float(tau.mean()),
        }  # fmt: skip

    counts = pairs_.group_by("col").agg(pl.len().alias("n"), pl.col("cid").n_unique().alias("p"))
    cnt = {c: (n, p) for c, n, p in counts.iter_rows()}
    for c, i in li.items():
        row = table(s["a_l"][:, i], s["b_l"][:, i], s["tau_l"][:, i])
        row["pairs"], row["players"] = cnt.get(c, (0, 0))
        row["group"] = groups[c]
        out["leagues"][c] = row
    # a group's typical league (a league with no pairs yet): its means, with the league spread
    rng = np.random.default_rng(SEED)
    for g, j in gi.items():
        k = len(s["s_a"])
        alpha = s["mu_a"][:, j] + s["s_a"] * rng.standard_normal(k)
        beta = s["mu_b"][:, j] + s["s_b"] * rng.standard_normal(k)
        tau = np.exp(s["m_t"] + s["s_t"] * rng.standard_normal(k))
        out["groups"][g] = table(alpha, beta, tau)
    for c in OTHER:  # a league with no pairs at all takes its group's typical league
        if c not in out["leagues"]:
            out["leagues"][c] = {**out["groups"][groups[c]], "pairs": 0, "players": 0,
                                 "group": groups[c]}  # fmt: skip
    # the population prior on the IPL rating scale (candidate T2 divides it out): IPL ratings of the
    # players who played the seasons it was fitted on
    out["prior"] = {"mean": float(ipl_u["ipl_v"].mean()),
                    "sd": float(math.sqrt(ipl_u["ipl_v"].var() + (ipl_u["ipl_sd"] ** 2).mean()))}  # fmt: skip
    return out


def fit_all(lg, units, last: int, spec: dict) -> dict:
    return {role: fit_role(lg, units, role, last, spec) for role in ROLES}


# ---- 3. predictions per player-season under each scheme --------------------------------------------


def _evidence(lg: pl.DataFrame, units: pl.DataFrame, seasons) -> list[dict]:
    """One row per scored player-season (MIN_N+ IPL balls) with at least one league rating as of S:
    his IPL rating (if any) and every league rating he has as of S."""
    u = units.filter(pl.col("season").is_in(list(seasons)))
    lgs = lg.filter(pl.col("season").is_in(list(seasons))).select(
        "cid", "role", "season", "col", "value", "value_sd", "death", "pp"
    )
    by: dict[tuple, list] = {}
    for r in lgs.iter_rows(named=True):
        by.setdefault((r["cid"], r["role"], r["season"]), []).append(r)
    out = []
    for r in u.iter_rows(named=True):
        ev = by.get((r["cid"], r["role"], r["season"]))
        if not ev:
            continue
        out.append({**r, "leagues": ev, "new": r["ipl_balls"] < NEW_BALLS})
    return out


def predict(row: dict, scheme: str, model: dict | None, spec: dict | None) -> tuple[float, float]:
    """(value on the IPL rating scale, its sd) for one player-season."""
    ipl = None if row["ipl_v"] is None else (row["ipl_v"], row["ipl_sd"])
    if scheme == "legacy":
        v, sd, _ = translation.legacy_blend(
            (ipl[0], ipl[1], row["ipl_balls"]) if ipl else None,
            {e["col"]: (e["value"], e["value_sd"]) for e in row["leagues"]},
        )
        return v, sd
    if scheme == "none":
        ev = ([ipl] if ipl else []) + [(e["value"], e["value_sd"]) for e in row["leagues"]]
        w = sum(1 / s**2 for _, s in ev)
        return sum(v / s**2 for v, s in ev) / w, w**-0.5
    m = model[row["role"]]
    parts = {}
    for e in row["leagues"]:
        t = m["leagues"][e["col"]]
        shift = 0.0
        if spec.get("phase") and "phase" in m:
            shift = (m["phase"]["death"] * ((e["death"] or 0) - 0.25)
                     + m["phase"]["pp"] * ((e["pp"] or 0) - 0.3)) / m["ipl_line"]["b"]  # fmt: skip
        mu, var, tvar = translation.translate_parts(t, e["value"], e["value_sd"])
        parts[e["col"]] = (mu + shift, var, tvar)
    prior = (m["prior"]["mean"], m["prior"]["sd"]) if spec["blend"] == "product" else None
    v, sd, _ = translation.blend_parts(ipl, parts, prior)
    return v, sd


def score(rows: list[dict], preds: list[tuple[float, float]], line: dict, kappa: dict) -> dict:
    """Level calibration of the predicted IPL value per 100 balls (the IPL line applied to the
    value) against the season's real value."""
    out = {}
    for role in ROLES:
        for grp in ("newcomers", "returners", "all"):
            idx = [i for i, r in enumerate(rows) if r["role"] == role
                   and (grp == "all" or r["new"] == (grp == "newcomers"))]  # fmt: skip
            if len(idx) < 5:
                continue
            a, b, tau = line[role]["a"], line[role]["b"], line[role]["tau"]
            y = np.array([rows[i]["y"] for i in idx])
            n = np.array([rows[i]["n"] for i in idx])
            v = np.array([preds[i][0] for i in idx])
            sd = np.array([preds[i][1] for i in idx])
            yhat = a + b * v
            var = (b * sd) ** 2 + tau**2 + kappa[role] ** 2 / n
            ll = -0.5 * (np.log(2 * np.pi * var) + (y - yhat) ** 2 / var)
            wcal = 1 / (tau**2 + kappa[role] ** 2 / n)
            X = np.c_[np.ones_like(yhat), yhat]
            W = np.diag(wcal)
            try:
                _, slope = np.linalg.solve(X.T @ W @ X, X.T @ W @ y)
            except np.linalg.LinAlgError:
                slope = float("nan")
            big = n >= 60
            from scipy.stats import spearmanr

            out[f"{role}/{grp}"] = {
                "n": len(idx),
                "bias": float(np.average(y - yhat, weights=n)),  # real − predicted, ball-weighted
                "mae_60": float(np.mean(np.abs(y - yhat)[big])) if big.any() else None,
                "n_60": int(big.sum()),
                "slope": float(slope),
                "spearman": float(spearmanr(v, y).statistic) if len(idx) > 5 else None,
                "logscore": float(ll.mean()),
                "raw_bias": float(np.average(y - v, weights=n)),  # real − value itself
            }
    return out


def calib_table(rows, preds, line) -> dict:
    """Mean predicted vs mean real IPL value per 100 balls by fifth of the prediction (ball-weighted)."""
    out = {}
    for role in ROLES:
        idx = [i for i, r in enumerate(rows) if r["role"] == role]
        if len(idx) < 25:
            continue
        a, b = line[role]["a"], line[role]["b"]
        yhat = np.array([a + b * preds[i][0] for i in idx])
        y = np.array([rows[i]["y"] for i in idx])
        n = np.array([rows[i]["n"] for i in idx])
        qs = np.quantile(yhat, [0, 0.2, 0.4, 0.6, 0.8, 1.0])
        bins = []
        for k in range(5):
            m = (yhat >= qs[k]) & ((yhat < qs[k + 1]) if k < 4 else (yhat <= qs[k + 1]))
            if m.sum():
                bins.append({"pred": float(np.average(yhat[m], weights=n[m])),
                             "real": float(np.average(y[m], weights=n[m])), "n": int(m.sum())})  # fmt: skip
        out[role] = bins
    return out


def _evaluate(lg, units, seasons, model, spec) -> dict:
    rows = _evidence(lg, units, seasons)
    line = {r: model[r]["ipl_line"] for r in ROLES}
    kappa = {r: model[r]["kappa_sd"] for r in ROLES}
    res = {}
    for scheme in ("new", "legacy", "none"):
        preds = [predict(r, scheme, model, spec) for r in rows]
        res[scheme] = {"scores": score(rows, preds, line, kappa),
                       "calibration": calib_table(rows, preds, line)}  # fmt: skip
    return res


@app.command()
def fit(
    skip_validation: bool = typer.Option(False, help="reuse the report's chosen candidate"),
) -> None:
    lg, units = _load()
    report: dict = {
        "protocol": "candidates declared 2026-10-23; rolling-origin validation on 2022-2024 (fit on "
        "seasons before each), choice by mean log score; refit on <= 2024 and tested once on "
        "2025-2026; shipped = refit on <= 2026",
        "min_balls": MIN_N,
        "candidates": list(CANDIDATES),
    }
    prev = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    if skip_validation and prev.get("chosen"):
        chosen = prev["chosen"]
        report["validation"] = prev.get("validation")
    else:
        val: dict = {}
        for name, spec in CANDIDATES.items():
            per = []
            for v in VALID:
                m = fit_all(lg, units, v - 1, spec)
                ev = _evaluate(lg, units, [v], m, spec)
                per.append(ev)
                logger.info(f"{name} · valid {v}: " + ", ".join(
                    f"{k} {x['logscore']:.3f}" for k, x in ev["new"]["scores"].items()
                    if k.endswith("/all")))  # fmt: skip
            val[name] = _mean_scores(per)
        report["validation"] = val
        chosen = max(val, key=lambda k: val[k]["new"]["all_logscore"])
    report["chosen"] = chosen
    spec = CANDIDATES[chosen]
    logger.info(f"chosen: {chosen}")
    # the one test
    m24 = fit_all(lg, units, LAST_TRAIN, spec)
    report["test"] = _evaluate(lg, units, TEST, m24, spec)
    report["model_le2024"] = m24
    # shipped: every season
    mall = fit_all(lg, units, max(SEASONS), spec)
    report["model"] = mall
    REPORT.write_text(json.dumps(report, indent=1))
    ship = {
        "schema": 1,
        "fitted": dt.date.today().isoformat(),
        "method": "per league and role: IPL rating = a + b x league rating, translation sd from the "
        "fit (scripts/league_translation_fit.py, docs/METHODOLOGY.md section 6d); sources combined "
        "by precision",
        "candidate": chosen,
        "blend": spec["blend"],
        "trained_through": max(SEASONS),
        "roles": {r: _ship_role(mall[r]) for r in ROLES},
        # the same translation fitted on seasons <= 2024: backtests of later seasons use it
        "roles_le2024": {r: _ship_role(m24[r]) for r in ROLES},
    }
    MODEL_PATH.write_text(json.dumps(ship, indent=1) + "\n")
    logger.info(f"wrote {MODEL_PATH} and {REPORT}")
    _print(report)


def _ship_role(m: dict) -> dict:
    keep = ("a", "b", "tsd", "cov", "pairs", "players", "group")
    return {
        "leagues": {
            c: {k: (round(v, 5) if isinstance(v, float) else v) for k, v in t.items() if k in keep}
            for c, t in m["leagues"].items()
        },  # fmt: skip
        "groups": {
            g: {k: (round(v, 5) if isinstance(v, float) else v) for k, v in t.items() if k in keep}
            for g, t in m["groups"].items()
        },  # fmt: skip
        "prior": {k: round(v, 4) for k, v in m["prior"].items()},
        "ipl_line": {k: round(v, 4) for k, v in m["ipl_line"].items()},
        "kappa_sd": round(m["kappa_sd"], 2),
    }


def _mean_scores(per: list[dict]) -> dict:
    out: dict = {}
    for scheme in ("new", "legacy", "none"):
        keys = per[0][scheme]["scores"].keys()
        agg = {}
        for k in keys:
            xs = [p[scheme]["scores"][k] for p in per if k in p[scheme]["scores"]]
            n = sum(x["n"] for x in xs)
            agg[k] = {f: (sum(x[f] * x["n"] for x in xs if x[f] is not None) / n
                          if all(x[f] is not None for x in xs) else None)
                      for f in ("bias", "mae_60", "slope", "spearman", "logscore", "raw_bias")}  # fmt: skip
            agg[k]["n"] = n
        tot = sum(agg[f"{r}/all"]["n"] for r in ROLES if f"{r}/all" in agg)
        agg["all_logscore"] = (
            sum(
                agg[f"{r}/all"]["logscore"] * agg[f"{r}/all"]["n"]
                for r in ROLES
                if f"{r}/all" in agg
            )
            / tot
        )
        out[scheme] = agg
    return out


def _print(report: dict) -> None:
    def table(res: dict, title: str):
        typer.echo(f"\n{title}")
        typer.echo(f"{'':28s} {'scheme':7s} {'n':>5s} {'bias':>6s} {'MAE60':>6s} {'slope':>6s} "
                   f"{'rho':>5s} {'logS':>7s} {'rawbias':>7s}")  # fmt: skip
        for k in res["new"]["scores"] if "scores" in res["new"] else res["new"]:
            if k == "all_logscore":
                continue
            for scheme in ("new", "legacy", "none"):
                x = (res[scheme]["scores"] if "scores" in res[scheme] else res[scheme]).get(k)
                if not x:
                    continue
                f = lambda v, p=1: "  —" if v is None else f"{v:.{p}f}"  # noqa: E731
                typer.echo(f"{k:28s} {scheme:7s} {x['n']:5d} {f(x['bias']):>6s} {f(x['mae_60']):>6s} "
                           f"{f(x['slope'], 2):>6s} {f(x['spearman'], 2):>5s} "
                           f"{f(x['logscore'], 3):>7s} {f(x['raw_bias']):>7s}")  # fmt: skip

    for name, v in (report.get("validation") or {}).items():
        typer.echo(f"\nvalidation · {name}: mean log score {v['new']['all_logscore']:.4f}")
    table(report["test"], f"TEST 2025-26 (chosen: {report['chosen']})")
    typer.echo("\ntranslation (shipped, rating scale): league role a b tsd pairs")
    for role in ROLES:
        for c, t in report["model"][role]["leagues"].items():
            typer.echo(f"  {role:6s} {c:22s} a={t['a']:6.1f} b={t['b']:5.2f} tsd={t['tsd']:5.1f} "
                       f"pairs={t['pairs']}")  # fmt: skip


# ---- 4. the reality table ---------------------------------------------------------------------------

# Players whose league numbers came before an IPL record, chosen for the question (did the obvious
# cases come out right?), not for the answer: SMAT stars who did well or poorly in the IPL, overseas
# league stars new to the IPL, and established internationals at their IPL entry.
REALITY = [
    ("SMAT", "Priyansh Arya", "b5797845", "batter"),
    ("SMAT", "Ashutosh Sharma", "84d9c311", "batter"),
    ("SMAT", "Shashank Singh", "26989d80", "batter"),
    ("SMAT", "Abhinav Manohar", "0890552f", "batter"),
    ("SMAT", "Rahul Singh", "adf454e9", "batter"),
    ("SMAT", "Sameer Rizvi", "f89d3b11", "batter"),
    ("SMAT", "Shahrukh Khan", "7dcb9bc9", "batter"),
    ("SMAT", "Angkrish Raghuvanshi", "d7017798", "batter"),
    ("SMAT", "Ashwani Kumar", "d45c29b1", "bowler"),
    ("SMAT", "Vipraj Nigam", "5ffc0565", "bowler"),
    ("Overseas", "Jake Fraser-McGurk", "9b6e1b3f", "batter"),
    ("Overseas", "Will Jacks", "9caf69a1", "batter"),
    ("Overseas", "Rachin Ravindra", "ba5e1069", "batter"),
    ("Overseas", "Ryan Rickelton", "e66732f8", "batter"),
    ("Overseas", "Tristan Stubbs", "85b3fab2", "batter"),
    ("Overseas", "Tim David", "f1f99156", "batter"),
    ("Overseas", "Gerald Coetzee", "3204c99f", "bowler"),
    ("Overseas", "Spencer Johnson", "83c3e8e3", "bowler"),
    ("International", "Jos Buttler", "99b75528", "batter"),
    ("International", "Rashid Khan", "5f547c8b", "bowler"),
    ("International", "Nicholas Pooran", "3241e3fd", "batter"),
    ("International", "Liam Livingstone", "50c6bc2b", "batter"),
    ("International", "Phil Salt", "3d284ca3", "batter"),
    ("International", "Harry Brook", "4ae1755b", "batter"),
    ("International", "Devon Conway", "df5a6881", "batter"),
    ("International", "Mitchell Starc", "3fb19989", "bowler"),
]


@app.command()
def reality() -> None:
    """Each REALITY player's value from what was known before his first IPL season with MIN_N+ balls
    in the role (the translation fitted on seasons ≤ 2024; in-sample for an entry before 2025),
    new scheme and old, against his IPL rating today (scout_ratings_ipl.json: every IPL ball since,
    the same scale) and his observed IPL value per 100 balls since. A player with no IPL go yet is
    valued now (the shipped translation). Adds `reality` to the report."""
    metrics = DATA_DIR / "metrics"
    fits = pl.read_parquet(WORK / "fits.parquet")
    ys = pl.read_parquet(WORK / "ipl_seasons.parquet")
    ipl_now = {
        (r["cricsheet_id"], r["role"]): r
        for r in json.loads((metrics / f"scout_ratings_{TARGET}.json").read_text())
    }
    cur: dict[tuple[str, str], dict] = {}
    for col in OTHER:
        p = metrics / f"scout_ratings_{col}.json"
        if p.exists():
            for r in json.loads(p.read_text()):
                if r.get("value") is not None:
                    cur.setdefault((r["cricsheet_id"], r["role"]), {})[col] = (
                        r["value"], r.get("value_sd") or 1.0)  # fmt: skip
    rows = []
    for grp, name, cid, role in REALITY:
        seas = ys.filter((pl.col("cid") == cid) & (pl.col("role") == role) & (pl.col("n") >= MIN_N))
        s0 = int(seas["season"].min()) if seas.height else None
        if s0 is not None and s0 >= min(SEASONS):
            f = fits.filter(
                (pl.col("cid") == cid) & (pl.col("role") == role) & (pl.col("season") == s0)
            )
            ipl = f.filter(pl.col("col") == TARGET)
            src = ((float(ipl["value"][0]), float(ipl["value_sd"][0]), int(ipl["balls"][0] or 0))
                   if ipl.height else None)  # fmt: skip
            oth = {c: (v, s) for c, v, s in
                   f.filter(pl.col("col") != TARGET).select("col", "value", "value_sd").iter_rows()}  # fmt: skip
            which, when = "roles_le2024", f"before IPL {s0}"
        else:
            src, oth, which, when = None, cur.get((cid, role), {}), "roles", "now (no IPL go yet)"
        if not oth and not src:
            continue
        new, nsd, _ = translation.blend(role, (src[0], src[1]) if src else None, oth, which=which)
        old, osd, _ = translation.legacy_blend(src, oth)
        now = ipl_now.get((cid, role))
        after = ys.filter((pl.col("cid") == cid) & (pl.col("role") == role)
                          & (pl.col("season") >= (s0 or 9999)))  # fmt: skip
        obs = float((after["y"] * after["n"]).sum() / after["n"].sum()) if after.height else None
        row = {
            "group": grp, "name": name, "role": role, "when": when, "in_sample": bool(s0 and s0 <= 2024),
            "leagues": {leagues.short(c): round(v, 1) for c, (v, _) in oth.items()},
            "ipl_balls_before": src[2] if src else 0,
            "new": round(new, 1), "new_sd": round(nsd, 1), "old": round(old, 1), "old_sd": round(osd, 1),
            "ipl_rating_now": round(now["value"], 1) if now else None,
            "ipl_balls_now": int(now["balls"]) if now else 0,
            "ipl_observed_since": round(obs, 1) if obs is not None else None,
        }  # fmt: skip
        if now:
            row["error_new"] = round(new - now["value"], 1)
            row["error_old"] = round(old - now["value"], 1)
        rows.append(row)
    summ = {}
    for g in ("SMAT", "Overseas", "International", "all"):
        rr = [r for r in rows if "error_new" in r and (g == "all" or r["group"] == g)]
        if rr:
            summ[g] = {
                "n": len(rr),
                "mae_new": round(float(np.mean([abs(r["error_new"]) for r in rr])), 1),
                "mae_old": round(float(np.mean([abs(r["error_old"]) for r in rr])), 1),
                "bias_new": round(float(np.mean([r["error_new"] for r in rr])), 1),
                "bias_old": round(float(np.mean([r["error_old"] for r in rr])), 1),
            }
    rep = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    rep["reality"] = {"rows": rows, "summary": summ}
    REPORT.write_text(json.dumps(rep, indent=1))
    typer.echo(f"{'player':22s} {'when':22s} {'new':>6s} {'old':>6s} {'IPL':>6s} {'balls':>5s} "
               f"{'err':>6s} {'old err':>7s}")  # fmt: skip
    for r in rows:
        f = lambda v: "     —" if v is None else f"{v:6.1f}"  # noqa: E731
        typer.echo(f"{r['name']:22s} {r['when']:22s} {f(r['new'])} {f(r['old'])} "
                   f"{f(r['ipl_rating_now'])} {r['ipl_balls_now']:5d} {f(r.get('error_new'))} "
                   f"{f(r.get('error_old')):>7s}")  # fmt: skip
    typer.echo(json.dumps(summ))


if __name__ == "__main__":
    app()
