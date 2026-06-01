"""Bayesian opponent-adjusted batter / bowler ratings.

Model
-----
For each (batter i, bowler j) edge with `balls_ij` legal balls faced
and `runs_ij` runs scored, we model the runs count as Negative-Binomial
with mean proportional to `balls_ij`:

    runs_ij ~ NegBin(mu_ij, alpha)
    mu_ij    = exp(intercept + b_skill[i] - k_skill[j]) * balls_ij

`b_skill` and `k_skill` carry hierarchical N(0, sigma) priors so any
batter / bowler with thin sample shrinks toward the global mean (zero
on the log scale). This is the "opponent bridging" effect — playing a
known-strong bowler raises the inferred batter skill more than playing
a journeyman.

Engine
------
NumPyro (JAX backend). 10-50x faster than the previous PyMC + PyTensor
implementation on the same model thanks to JIT-compiled gradients and
vectorised NUTS. Two samplers are wired:

- `advi` (default) — mean-field stochastic VI via `AutoNormal` guide
  + `Trace_ELBO`. ~10-30 s on the full IPL collection (~30k edges).
  Posterior variance is under-estimated, so `skill_sd` is directional
  rather than calibrated. Good for development and weekly refresh.
- `nuts` — full No-U-Turn HMC, 2 chains × 1000 draws + 500 warmup.
  ~1-3 min on the same IPL corpus (down from ~20-30 min on PyMC).
  Produces a properly calibrated posterior — use this when the
  consumer cares about confidence intervals (player-profile
  uncertainty bars, wager-grade analytics).

Output
------
polars DataFrame keyed by `cricsheet_id` with columns:
    role            "batter" | "bowler"
    skill           posterior mean
    skill_sd        posterior std-dev (proxy for confidence)
    balls           total balls associated with this role
    runs            total runs associated with this role
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl

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
    min_balls: int,
) -> tuple[pl.DataFrame, dict[str, int], dict[str, int]]:
    safe = collection.replace("-", "_")
    kinds_sql = ", ".join(f"'{k}'" for k in _BOWLER_WICKET_KINDS)
    with duckdb.connect(str(db_path), read_only=True) as con:
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
                    END AS is_out
                FROM balls_{safe} b
                LEFT JOIN people rb ON rb.unique_name = b.batter
                LEFT JOIN people rk ON rk.unique_name = b.bowler
                WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL
            )
            SELECT batter_id, bowler_id,
                   SUM(legal_ball) AS balls,
                   SUM(runs_batter) AS runs,
                   SUM(is_out) AS outs
            FROM labelled
            GROUP BY batter_id, bowler_id
            HAVING SUM(legal_ball) >= {min_balls}
            """
        ).pl()
    batters = sorted(set(df["batter_id"].to_list()))
    bowlers = sorted(set(df["bowler_id"].to_list()))
    batter_idx = {b: i for i, b in enumerate(batters)}
    bowler_idx = {k: i for i, k in enumerate(bowlers)}
    df = df.with_columns(
        pl.col("batter_id").replace_strict(batter_idx).alias("bi"),
        pl.col("bowler_id").replace_strict(bowler_idx).alias("ki"),
    )
    return df, batter_idx, bowler_idx


def _model(bi, ki, balls, runs, n_batters: int, n_bowlers: int):
    """NumPyro model — hierarchical NegBin GLM on (batter, bowler) edges.

    Runs-only model (legacy). Kept for `dismissal_aware=False`.
    """
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    with numpyro.plate("batters", n_batters):
        b_skill = numpyro.sample("b_skill", dist.Normal(0.0, sigma_b))
    with numpyro.plate("bowlers", n_bowlers):
        k_skill = numpyro.sample("k_skill", dist.Normal(0.0, sigma_k))
    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha = numpyro.sample("alpha", dist.HalfNormal(5.0))

    log_mu = intercept + b_skill[bi] - k_skill[ki]
    mu = jnp.exp(log_mu) * balls
    numpyro.sample("y", dist.NegativeBinomial2(mean=mu, concentration=alpha), obs=runs)


def _model_dismissal(bi, ki, balls, runs, outs, n_batters: int, n_bowlers: int):
    """Joint runs + dismissals model — two coupled GLMs sharing the
    same (batter, bowler) edge structure.

    Runs sub-model (scoring rate):
        runs_ij ~ NegBin(exp(r_int + bat_score[i] - bowl_econ[j]) * balls, alpha)

    Dismissal sub-model (survival vs strike), per-ball Binomial:
        outs_ij ~ Binomial(balls_ij,
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

    # --- scoring-rate sub-model (existing) ---
    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    with numpyro.plate("batters", n_batters):
        b_skill = numpyro.sample("b_skill", dist.Normal(0.0, sigma_b))
    with numpyro.plate("bowlers", n_bowlers):
        k_skill = numpyro.sample("k_skill", dist.Normal(0.0, sigma_k))
    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha = numpyro.sample("alpha", dist.HalfNormal(5.0))

    log_mu = intercept + b_skill[bi] - k_skill[ki]
    mu = jnp.exp(log_mu) * balls
    numpyro.sample("y_runs", dist.NegativeBinomial2(mean=mu, concentration=alpha), obs=runs)

    # --- dismissal sub-model (new) ---
    sigma_surv = numpyro.sample("sigma_surv", dist.HalfNormal(1.0))
    sigma_strike = numpyro.sample("sigma_strike", dist.HalfNormal(1.0))
    with numpyro.plate("batters_surv", n_batters):
        bat_survive = numpyro.sample("bat_survive", dist.Normal(0.0, sigma_surv))
    with numpyro.plate("bowlers_strike", n_bowlers):
        bowl_strike = numpyro.sample("bowl_strike", dist.Normal(0.0, sigma_strike))
    # Baseline dismissal log-odds. Per-ball dismissal prob in T20 ~ 1/25,
    # so logit ≈ log(1/24) ≈ -3.2 — a Normal(-3, 2) prior covers it.
    w_intercept = numpyro.sample("w_intercept", dist.Normal(-3.0, 2.0))

    logit_p = w_intercept + bowl_strike[ki] - bat_survive[bi]
    numpyro.sample(
        "y_outs",
        dist.Binomial(total_count=balls.astype(jnp.int32), logits=logit_p),
        obs=outs,
    )


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
    mcmc.run(jax.random.PRNGKey(seed), **model_kwargs)
    return mcmc.get_samples()


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
    predictive = Predictive(guide, params=svi_result.params, num_samples=post_samples)
    return predictive(jax.random.PRNGKey(seed + 1), **model_kwargs)


def fit(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 6,
    advi_steps: int = 12000,
    seed: int = 42,
    sampler: str = "advi",
    nuts_draws: int = 1000,
    nuts_chains: int = 2,
    nuts_tune: int = 500,
    nuts_target_accept: float = 0.9,
    dismissal_aware: bool = True,
) -> pl.DataFrame:
    """Fit the model and return one row per (cricsheet_id, role).

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

    edges, batter_idx, bowler_idx = _load_edges(db_path, collection, min_balls)
    if edges.is_empty():
        return pl.DataFrame()

    n_batters = len(batter_idx)
    n_bowlers = len(bowler_idx)

    bi = jnp.asarray(edges["bi"].cast(pl.Int32).to_numpy())
    ki = jnp.asarray(edges["ki"].cast(pl.Int32).to_numpy())
    balls = jnp.asarray(edges["balls"].cast(pl.Float32).to_numpy())
    runs = jnp.asarray(edges["runs"].cast(pl.Int32).to_numpy())

    model_kwargs = {
        "bi": bi,
        "ki": ki,
        "balls": balls,
        "runs": runs,
        "n_batters": n_batters,
        "n_bowlers": n_bowlers,
    }
    model_fn: Any
    if dismissal_aware:
        model_fn = _model_dismissal
        model_kwargs["outs"] = jnp.asarray(edges["outs"].cast(pl.Int32).to_numpy())
    else:
        model_fn = _model

    if sampler == "nuts":
        samples = _run_nuts(
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

    def _stats(key: str, n: int) -> tuple[np.ndarray, np.ndarray]:
        arr = np.asarray(samples[key]).reshape(-1, n)
        return arr.mean(axis=0), arr.std(axis=0)

    b_mean, b_sd = _stats("b_skill", n_batters)
    k_mean, k_sd = _stats("k_skill", n_bowlers)
    if dismissal_aware:
        surv_mean, surv_sd = _stats("bat_survive", n_batters)
        strike_mean, strike_sd = _stats("bowl_strike", n_bowlers)
        # Composite "value" = raw sum of the two axes. Both are on a
        # log scale, both higher = better, and empirically comparable in
        # magnitude (±0.2-0.3), so a plain sum keeps honest uncertainty
        # (z-scaling by the small population spread over-inflated
        # confidence). A pure slogger (high b_skill, low survival) no
        # longer outranks an anchor on `value`.
        bv = b_mean + surv_mean
        kv = k_mean + strike_mean

    batter_totals = (
        edges.group_by("batter_id")
        .agg(pl.col("balls").sum().alias("balls"), pl.col("runs").sum().alias("runs"))
        .to_pandas()
        .set_index("batter_id")
    )
    bowler_totals = (
        edges.group_by("bowler_id")
        .agg(pl.col("balls").sum().alias("balls"), pl.col("runs").sum().alias("runs"))
        .to_pandas()
        .set_index("bowler_id")
    )

    rows: list[dict] = []
    for name, idx in batter_idx.items():
        t = batter_totals.loc[name]
        row = {
            "cricsheet_id": name,
            "role": "batter",
            "skill": float(b_mean[idx]),
            "skill_sd": float(b_sd[idx]),
            "balls": int(t["balls"]),
            "runs": int(t["runs"]),
        }
        if dismissal_aware:
            row["survival_skill"] = float(surv_mean[idx])
            row["survival_skill_sd"] = float(surv_sd[idx])
            row["value"] = float(bv[idx])
        rows.append(row)
    for name, idx in bowler_idx.items():
        t = bowler_totals.loc[name]
        row = {
            "cricsheet_id": name,
            "role": "bowler",
            "skill": float(k_mean[idx]),
            "skill_sd": float(k_sd[idx]),
            "balls": int(t["balls"]),
            "runs": int(t["runs"]),
        }
        if dismissal_aware:
            row["strike_skill"] = float(strike_mean[idx])
            row["strike_skill_sd"] = float(strike_sd[idx])
            row["value"] = float(kv[idx])
        rows.append(row)
    # infer_schema_length=None scans every row — batters (added first)
    # lack the bowler-only `strike_skill` key, so a truncated scan would
    # silently drop that column.
    df = pl.DataFrame(rows, infer_schema_length=None)

    # Attach human-readable unique_name so the saved JSON is
    # self-contained (downstream readers + head-to-head resolve by name).
    with duckdb.connect(str(db_path), read_only=True) as con:
        ppl = con.execute("SELECT identifier, unique_name FROM people").pl()
    df = df.join(ppl, left_on="cricsheet_id", right_on="identifier", how="left")
    return df
