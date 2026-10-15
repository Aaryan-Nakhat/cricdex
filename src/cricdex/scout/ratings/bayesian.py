"""Bayesian opponent-adjusted batter / bowler ratings.

Model
-----
For each (batter i, bowler j) edge with `balls_ij` legal balls faced
and `runs_ij` runs scored, we model the runs count as Negative-Binomial
with mean proportional to `balls_ij`:

    runs_ij ~ NegBin(mu_ij, alpha)
    mu_ij    = exp(intercept + b_skill[i] - k_skill[j]) * balls_ij

`b_skill` and `k_skill` carry hierarchical N(0, sigma) priors (written
non-centred) so any batter / bowler with thin sample shrinks toward the
global mean (zero on the log scale). That is why every matchup is kept,
even a 1-ball one: shrinkage, not a cut-off, handles small samples. This
is also the "opponent bridging" effect — playing a known-strong bowler
raises the inferred batter skill more than playing a journeyman.

Engine
------
NumPyro (JAX backend). 10-50x faster than the previous PyMC + PyTensor
implementation on the same model thanks to JIT-compiled gradients and
vectorised NUTS. Two samplers are wired:

- `advi` (default) — mean-field stochastic VI via `AutoNormal` guide
  + `Trace_ELBO`, ~1-2.5 min on IPL (~31k edges). Checked against NUTS
  on IPL: sds within 1-5% on every axis, `value_sd` within ~1%, P(A>B)
  a median 1-2 points apart. (The old centred form mis-fitted the strike
  axis: its sds were ~25% too wide and its sigma ~30% off.)
- `nuts` — full No-U-Turn HMC, 2 chains × 1000 draws + 500 warmup,
  logs r-hat / ESS / divergences. ~15 min on IPL at 500 + 500 per chain,
  so all 8 refresh collections would overrun the CI budget — opt-in for
  spot checks.

The default fit (`dismissal_aware=True`) adds a per-ball dismissal
Binomial to the runs model — see `_model_dismissal`.

Output
------
polars DataFrame keyed by `cricsheet_id` with columns:
    role            "batter" | "bowler"
    skill           posterior mean (scoring / economy)
    skill_sd        posterior std-dev (proxy for confidence)
    balls           career legal balls in this role (every matchup)
    runs            career runs off the bat in this role
    survival_skill(_sd) / strike_skill(_sd)   batter / bowler dismissal axis
    value(_sd)      complete value: both axes in population-sd units,
                    summed (dismissal-aware fit only; see `_value_draws`)
    unique_name     the player's scorecard name in this collection (else the People Register's)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdex.common.sql import player_ids, scorecard_names, table_suffix
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


# Wicket kinds credited to the bowler (exclude run out / retired /
# obstructing — those don't test the batter-vs-bowler contest).
_BOWLER_WICKET_KINDS = (
    "bowled",
    "caught",
    "lbw",
    "caught and bowled",
    "stumped",
    "hit wicket",
)


def _load_edges(
    db_path: Path | str,
    collection: str,
    since: str | None = None,
    before: str | None = None,
    by_year: bool = False,
) -> pl.DataFrame:
    """Every (batter, bowler) matchup with its legal balls, runs off the bat,
    bowler-credited dismissals and dismissal trials — nothing dropped.

    `since` / `before` (ISO dates) keep only matches played in that window —
    the ratings backtest fits on everything before a season, then scores it.
    `by_year` splits each matchup by calendar year (a `yr` column), so the fit
    can weight recent seasons more."""
    safe = table_suffix(collection)
    kinds_sql = ", ".join(f"'{k}'" for k in _BOWLER_WICKET_KINDS)
    window = ""
    if since or before:
        conds = []
        if since:
            conds.append(f"m.match_date >= '{date.fromisoformat(since).isoformat()}'")
        if before:
            conds.append(f"m.match_date < '{date.fromisoformat(before).isoformat()}'")
        window = (
            f"AND b.match_id IN (SELECT m.match_id FROM matches_{safe} m "
            f"WHERE {' AND '.join(conds)})"
        )
    year_col = year_join = year_key = ""
    if by_year:
        year_col = ", my.yr"
        year_join = (
            " LEFT JOIN (SELECT match_id, CAST(LEFT(match_date, 4) AS INTEGER) AS yr"
            f" FROM matches_{safe}) my ON my.match_id = b.match_id"
        )
        year_key = ", yr"
    with duckdb.connect(str(db_path), read_only=True) as con:
        ids = player_ids(con, collection) or "(SELECT NULL AS name, NULL AS identifier)"
        df = con.execute(
            f"""
            WITH labelled AS (
                SELECT
                    COALESCE(rb.identifier, 'unresolved:' || b.batter) AS batter_id,
                    COALESCE(rk.identifier, 'unresolved:' || b.bowler) AS bowler_id,
                    b.runs_batter,
                    CASE WHEN b.extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball,
                    -- A dismissal counts for this edge only when the striker
                    -- (batter) is the one out AND the kind is bowler-credited.
                    CASE
                        WHEN b.wicket_kind IN ({kinds_sql})
                         AND b.player_out = b.batter
                        THEN 1 ELSE 0
                    END AS is_out{year_col}
                FROM balls_{safe} b{year_join}
                LEFT JOIN {ids} rb ON rb.name = b.batter
                LEFT JOIN {ids} rk ON rk.name = b.bowler
                WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL {window}
            )
            SELECT batter_id, bowler_id{year_key},
                   SUM(legal_ball) AS balls,
                   SUM(runs_batter) AS runs,
                   SUM(is_out) AS outs,
                   -- Dismissal trials: legal balls plus the rare bowler-credited
                   -- dismissal off a wide (a stumping), so outs <= trials always.
                   SUM(CASE WHEN legal_ball = 1 OR is_out = 1 THEN 1 ELSE 0 END) AS trials
            FROM labelled
            GROUP BY ALL
            """
        ).pl()
    return df


def _index_edges(
    edges: pl.DataFrame, min_balls: int
) -> tuple[pl.DataFrame, dict[str, int], dict[str, int]]:
    """Edges the model fits on, with integer player indices.

    Every matchup with at least one dismissal trial is kept: the hierarchical
    prior already shrinks thin samples, so dropping them only throws data
    away. `min_balls` is a speed knob for experiments (it never changes the
    reported career balls, which come from all edges)."""
    df = edges.filter((pl.col("trials") > 0) & (pl.col("balls") >= min_balls))
    batters = sorted(set(df["batter_id"].to_list()))
    bowlers = sorted(set(df["bowler_id"].to_list()))
    batter_idx = {b: i for i, b in enumerate(batters)}
    bowler_idx = {k: i for i, k in enumerate(bowlers)}
    df = df.with_columns(
        pl.col("batter_id").replace_strict(batter_idx).alias("bi"),
        pl.col("bowler_id").replace_strict(bowler_idx).alias("ki"),
    )
    return df, batter_idx, bowler_idx


def _skill(site: str, plate: str, n: int, sigma):
    """Hierarchical skill, non-centred: `site = sigma * raw`, raw ~ N(0, 1).

    The centred form (`site ~ N(0, sigma)`) puts the many thin-sample
    players in a funnel with `sigma`, which NUTS samples badly. The
    non-centred form has the same prior and is recorded under the same
    site name, so downstream code reads `b_skill` etc. unchanged."""
    import numpyro
    import numpyro.distributions as dist

    with numpyro.plate(plate, n):
        raw = numpyro.sample(f"{site}_raw", dist.Normal(0.0, 1.0))
    return numpyro.deterministic(site, sigma * raw)


def _runs_likelihood(site: str, bi, ki, balls, runs, b_skill, k_skill, weight=None):
    """NegBin runs on each edge. Edges with no legal ball (a wide-only
    dismissal edge) carry no runs information and are masked out. `weight`
    (per edge, optional) scales each edge's log-likelihood — recency decay."""
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha = numpyro.sample("alpha", dist.HalfNormal(5.0))
    has_balls = balls > 0
    mu = jnp.where(has_balls, jnp.exp(intercept + b_skill[bi] - k_skill[ki]) * balls, 1.0)
    with numpyro.handlers.mask(mask=has_balls), numpyro.handlers.scale(scale=_scale(weight)):
        numpyro.sample(site, dist.NegativeBinomial2(mean=mu, concentration=alpha), obs=runs)


def _scale(weight):
    return 1.0 if weight is None else weight


def _model(bi, ki, balls, runs, n_batters: int, n_bowlers: int, weight=None):
    """NumPyro model — hierarchical NegBin GLM on (batter, bowler) edges.

    Runs-only model (legacy). Kept for `dismissal_aware=False`.
    """
    import numpyro
    import numpyro.distributions as dist

    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    b_skill = _skill("b_skill", "batters", n_batters, sigma_b)
    k_skill = _skill("k_skill", "bowlers", n_bowlers, sigma_k)
    _runs_likelihood("y", bi, ki, balls, runs, b_skill, k_skill, weight)


def _model_dismissal(
    bi, ki, balls, runs, outs, trials, n_batters: int, n_bowlers: int, weight=None
):
    """Joint runs + dismissals model — two GLMs sharing the same
    (batter, bowler) edge structure.

    Runs sub-model (scoring rate):
        runs_ij ~ NegBin(exp(r_int + bat_score[i] - bowl_econ[j]) * balls, alpha)

    Dismissal sub-model (survival vs strike), per-ball Binomial:
        outs_ij ~ Binomial(trials_ij,
                           sigmoid(w_int + bowl_strike[j] - bat_survive[i]))

    Four latent skills per player (where applicable), all with
    higher = better (sign convention matches the runs model — bowler
    terms are added in their own favour):
      bat_score   — scoring rate (higher = scores faster)
      bat_survive — dismissal resistance (higher = harder to get out)
      bowl_econ   — run suppression (higher = concedes fewer)
      bowl_strike — wicket-taking (higher = dismisses faster)
    """
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    # --- scoring-rate sub-model ---
    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    b_skill = _skill("b_skill", "batters", n_batters, sigma_b)
    k_skill = _skill("k_skill", "bowlers", n_bowlers, sigma_k)
    _runs_likelihood("y_runs", bi, ki, balls, runs, b_skill, k_skill, weight)

    # --- dismissal sub-model ---
    sigma_surv = numpyro.sample("sigma_surv", dist.HalfNormal(1.0))
    sigma_strike = numpyro.sample("sigma_strike", dist.HalfNormal(1.0))
    bat_survive = _skill("bat_survive", "batters_surv", n_batters, sigma_surv)
    bowl_strike = _skill("bowl_strike", "bowlers_strike", n_bowlers, sigma_strike)
    # Baseline dismissal log-odds. Per-ball dismissal prob in T20 ~ 1/25,
    # so logit ≈ log(1/24) ≈ -3.2 — a Normal(-3, 2) prior covers it.
    w_intercept = numpyro.sample("w_intercept", dist.Normal(-3.0, 2.0))

    logit_p = w_intercept + bowl_strike[ki] - bat_survive[bi]
    with numpyro.handlers.scale(scale=_scale(weight)):
        numpyro.sample(
            "y_outs",
            dist.Binomial(total_count=trials.astype(jnp.int32), logits=logit_p),
            obs=outs,
        )


# Sites summarised for the NUTS convergence check.
_DIAG_SITES = (
    "b_skill",
    "k_skill",
    "bat_survive",
    "bowl_strike",
    "sigma_b",
    "sigma_k",
    "sigma_surv",
    "sigma_strike",
)


def _nuts_diagnostics(mcmc) -> dict:
    """Worst split r-hat, smallest bulk ESS and the divergence count."""
    from numpyro.diagnostics import summary

    grouped = mcmc.get_samples(group_by_chain=True)
    stats = summary({k: v for k, v in grouped.items() if k in _DIAG_SITES})
    r_hat = max(float(np.nanmax(s["r_hat"])) for s in stats.values())
    n_eff = min(float(np.nanmin(s["n_eff"])) for s in stats.values())
    divergences = int(np.asarray(mcmc.get_extra_fields()["diverging"]).sum())
    return {"max_r_hat": r_hat, "min_ess": n_eff, "divergences": divergences}


def _run_nuts(
    model_fn,
    model_kwargs: dict,
    draws: int,
    chains: int,
    tune: int,
    target_accept: float,
    seed: int,
):
    import jax
    from numpyro.infer import MCMC, NUTS

    kernel = NUTS(model_fn, target_accept_prob=target_accept)
    mcmc = MCMC(
        kernel,
        num_warmup=tune,
        num_samples=draws,
        num_chains=chains,
        progress_bar=False,
        chain_method="sequential",
    )
    mcmc.run(jax.random.PRNGKey(seed), extra_fields=("diverging",), **model_kwargs)
    diag = _nuts_diagnostics(mcmc) if chains > 1 else {}
    if diag:
        logger.info(
            f"NUTS: max r-hat {diag['max_r_hat']:.3f}, min ESS {diag['min_ess']:.0f}, "
            f"{diag['divergences']} divergences"
        )
        if diag["max_r_hat"] > 1.05 or diag["divergences"]:
            logger.warning("NUTS did not converge cleanly — raise --nuts-tune / --nuts-draws")
    return mcmc.get_samples(), diag


def _run_advi(
    model_fn,
    model_kwargs: dict,
    steps: int,
    seed: int,
    post_samples: int = 500,
):
    import jax
    from numpyro.infer import SVI, Predictive, Trace_ELBO, autoguide
    from numpyro.optim import Adam

    guide = autoguide.AutoNormal(model_fn)
    svi = SVI(model_fn, guide, Adam(0.01), Trace_ELBO())
    svi_result = svi.run(jax.random.PRNGKey(seed), steps, progress_bar=False, **model_kwargs)
    # Run the model under the guide's draws so the deterministic skill sites
    # (sigma * raw) are returned alongside the latent ones.
    predictive = Predictive(
        model_fn,
        guide=guide,
        params=svi_result.params,
        num_samples=post_samples,
        return_sites=list(_DIAG_SITES),
    )
    return predictive(jax.random.PRNGKey(seed + 1), **model_kwargs)


def _value_draws(
    rate_draws: np.ndarray,
    odds_draws: np.ndarray,
    samples: dict,
    rate_sigma: str,
    odds_sigma: str,
) -> np.ndarray:
    """Per-draw complete value: both axes in population-sd units, then summed.

    The scoring/economy axis is a log runs-per-ball effect and the
    survival/strike axis a log-odds dismissal effect — different units, so
    adding them raw would let whichever scale happens to be wider dominate.
    Each axis is divided by its fitted population sd (the posterior mean of
    its hierarchical `sigma`), so 1.0 means "one typical player-to-player
    spread better" on either axis and the two count equally. Doing it per
    draw keeps the posterior sd of the sum honest (`value_sd`)."""
    rate_scale = float(np.mean(np.asarray(samples[rate_sigma])))
    odds_scale = float(np.mean(np.asarray(samples[odds_sigma])))
    return rate_draws / rate_scale + odds_draws / odds_scale


def fit(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 0,
    advi_steps: int = 12000,
    seed: int = 42,
    sampler: str = "advi",
    nuts_draws: int = 1000,
    nuts_chains: int = 2,
    nuts_tune: int = 500,
    nuts_target_accept: float = 0.9,
    dismissal_aware: bool = True,
    before: str | None = None,
    half_life: float | None = None,
) -> pl.DataFrame:
    """Fit the model and return one row per (cricsheet_id, role).

    `before` (ISO date) fits on matches before that date only — used by the
    ratings backtest; the normal fit uses every match.

    `half_life` (years, optional) weights each season's matchups by
    0.5 ** (age / half_life), age counted back from the latest season fitted,
    so old form fades. None = every season counts the same.

    `sampler` ∈ {"advi", "nuts"}. ADVI is fast and approximate, NUTS
    is the calibrated full-Bayes run. Both run through NumPyro / JAX.

    `dismissal_aware` (default True) fits the joint runs + dismissals
    model so each batter also gets a `survival_skill` (resistance to
    getting out) and each bowler a `strike_skill` (wicket-taking), plus
    a derived `value` that combines both axes. Set False for the legacy
    runs-only fit (only `skill` is emitted).
    """
    import jax.numpy as jnp

    if sampler not in ("advi", "nuts"):
        raise ValueError(f"sampler must be 'advi' or 'nuts', got {sampler!r}")

    all_edges = _load_edges(db_path, collection, before=before, by_year=half_life is not None)
    edges, batter_idx, bowler_idx = _index_edges(all_edges, min_balls)
    if edges.is_empty():
        return pl.DataFrame()

    n_batters = len(batter_idx)
    n_bowlers = len(bowler_idx)

    model_kwargs = {
        "bi": jnp.asarray(edges["bi"].cast(pl.Int32).to_numpy()),
        "ki": jnp.asarray(edges["ki"].cast(pl.Int32).to_numpy()),
        "balls": jnp.asarray(edges["balls"].cast(pl.Float32).to_numpy()),
        "runs": jnp.asarray(edges["runs"].cast(pl.Int32).to_numpy()),
        "n_batters": n_batters,
        "n_bowlers": n_bowlers,
    }
    if half_life is not None:
        age = (edges["yr"].max() - edges["yr"]).fill_null(0)
        weight = (0.5 ** (age.cast(pl.Float32) / half_life)).to_numpy()
        model_kwargs["weight"] = jnp.asarray(weight)
    model_fn: Any
    if dismissal_aware:
        model_fn = _model_dismissal
        model_kwargs["outs"] = jnp.asarray(edges["outs"].cast(pl.Int32).to_numpy())
        model_kwargs["trials"] = jnp.asarray(edges["trials"].cast(pl.Int32).to_numpy())
    else:
        model_fn = _model

    if sampler == "nuts":
        samples, _ = _run_nuts(
            model_fn,
            model_kwargs,
            draws=nuts_draws,
            chains=nuts_chains,
            tune=nuts_tune,
            target_accept=nuts_target_accept,
            seed=seed,
        )
    else:
        samples = _run_advi(model_fn, model_kwargs, steps=advi_steps, seed=seed)

    def _draws(key: str, n: int) -> np.ndarray:
        return np.asarray(samples[key]).reshape(-1, n)

    def _stats(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return arr.mean(axis=0), arr.std(axis=0)

    b_draws, k_draws = _draws("b_skill", n_batters), _draws("k_skill", n_bowlers)
    b_mean, b_sd = _stats(b_draws)
    k_mean, k_sd = _stats(k_draws)
    if dismissal_aware:
        surv_draws = _draws("bat_survive", n_batters)
        strike_draws = _draws("bowl_strike", n_bowlers)
        surv_mean, surv_sd = _stats(surv_draws)
        strike_mean, strike_sd = _stats(strike_draws)
        bv, bv_sd = _stats(_value_draws(b_draws, surv_draws, samples, "sigma_b", "sigma_surv"))
        kv, kv_sd = _stats(_value_draws(k_draws, strike_draws, samples, "sigma_k", "sigma_strike"))

    # Career totals come from EVERY matchup, not just the fitted ones, so the
    # reported balls are the player's true exposure in this collection.
    def _totals(key: str) -> dict[str, tuple[int, int]]:
        agg = all_edges.group_by(key).agg(pl.col("balls").sum(), pl.col("runs").sum())
        return {r[0]: (int(r[1]), int(r[2])) for r in agg.iter_rows()}

    batter_totals, bowler_totals = _totals("batter_id"), _totals("bowler_id")

    rows: list[dict] = []
    for name, idx in batter_idx.items():
        balls_n, runs_n = batter_totals[name]
        row = {
            "cricsheet_id": name,
            "role": "batter",
            "skill": float(b_mean[idx]),
            "skill_sd": float(b_sd[idx]),
            "balls": balls_n,
            "runs": runs_n,
        }
        if dismissal_aware:
            row["survival_skill"] = float(surv_mean[idx])
            row["survival_skill_sd"] = float(surv_sd[idx])
            row["value"] = float(bv[idx])
            row["value_sd"] = float(bv_sd[idx])
        rows.append(row)
    for name, idx in bowler_idx.items():
        balls_n, runs_n = bowler_totals[name]
        row = {
            "cricsheet_id": name,
            "role": "bowler",
            "skill": float(k_mean[idx]),
            "skill_sd": float(k_sd[idx]),
            "balls": balls_n,
            "runs": runs_n,
        }
        if dismissal_aware:
            row["strike_skill"] = float(strike_mean[idx])
            row["strike_skill_sd"] = float(strike_sd[idx])
            row["value"] = float(kv[idx])
            row["value_sd"] = float(kv_sd[idx])
        rows.append(row)
    # infer_schema_length=None scans every row — batters (added first)
    # lack the bowler-only `strike_skill` key, so a truncated scan would
    # silently drop that column.
    df = pl.DataFrame(rows, infer_schema_length=None)

    # Attach a human-readable unique_name so the saved JSON is self-contained (downstream readers +
    # head-to-head resolve by name). The collection's scorecard name comes first because that is the
    # name every other table keys on; the register's unique_name can differ ("NA Saini").
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        names = scorecard_names(con, collection)
        parts = []
        if names:
            parts.append(f"SELECT identifier, name AS unique_name, 0 AS pri FROM {names}")
        if "people" in tables:
            parts.append("SELECT identifier, unique_name, 1 AS pri FROM people")
        ppl = (
            con.execute(
                "SELECT identifier, FIRST(unique_name ORDER BY pri) AS unique_name "
                f"FROM ({' UNION ALL '.join(parts)}) GROUP BY identifier"
            ).pl()
            if parts
            else None
        )
    if ppl is not None:
        df = df.join(ppl, left_on="cricsheet_id", right_on="identifier", how="left")
    return df
