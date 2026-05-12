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

import duckdb
import numpy as np
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


def _load_edges(
    db_path: Path | str,
    collection: str,
    min_balls: int,
) -> tuple[pl.DataFrame, dict[str, int], dict[str, int]]:
    safe = collection.replace("-", "_")
    with duckdb.connect(str(db_path), read_only=True) as con:
        df = con.execute(
            f"""
            WITH labelled AS (
                SELECT
                    COALESCE(rb.identifier, 'unresolved:' || b.batter) AS batter_id,
                    COALESCE(rk.identifier, 'unresolved:' || b.bowler) AS bowler_id,
                    b.runs_batter,
                    CASE WHEN b.extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball
                FROM balls_{safe} b
                LEFT JOIN people rb ON rb.unique_name = b.batter
                LEFT JOIN people rk ON rk.unique_name = b.bowler
                WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL
            )
            SELECT batter_id, bowler_id,
                   SUM(legal_ball) AS balls,
                   SUM(runs_batter) AS runs
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
    """NumPyro model — hierarchical NegBin GLM on (batter, bowler) edges."""
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


def _run_nuts(
    bi,
    ki,
    balls,
    runs,
    n_batters,
    n_bowlers,
    draws: int,
    chains: int,
    tune: int,
    target_accept: float,
    seed: int,
):
    import jax
    from numpyro.infer import MCMC, NUTS

    kernel = NUTS(_model, target_accept_prob=target_accept)
    mcmc = MCMC(
        kernel,
        num_warmup=tune,
        num_samples=draws,
        num_chains=chains,
        progress_bar=False,
        chain_method="sequential",
    )
    mcmc.run(
        jax.random.PRNGKey(seed),
        bi=bi,
        ki=ki,
        balls=balls,
        runs=runs,
        n_batters=n_batters,
        n_bowlers=n_bowlers,
    )
    return mcmc.get_samples()


def _run_advi(
    bi,
    ki,
    balls,
    runs,
    n_batters,
    n_bowlers,
    steps: int,
    seed: int,
    post_samples: int = 500,
):
    import jax
    from numpyro.infer import SVI, Predictive, Trace_ELBO, autoguide
    from numpyro.optim import Adam

    guide = autoguide.AutoNormal(_model)
    svi = SVI(_model, guide, Adam(0.01), Trace_ELBO())
    svi_result = svi.run(
        jax.random.PRNGKey(seed),
        steps,
        bi=bi,
        ki=ki,
        balls=balls,
        runs=runs,
        n_batters=n_batters,
        n_bowlers=n_bowlers,
        progress_bar=False,
    )
    predictive = Predictive(guide, params=svi_result.params, num_samples=post_samples)
    return predictive(
        jax.random.PRNGKey(seed + 1),
        bi=bi,
        ki=ki,
        balls=balls,
        runs=runs,
        n_batters=n_batters,
        n_bowlers=n_bowlers,
    )


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
) -> pl.DataFrame:
    """Fit the model and return one row per (cricsheet_id, role).

    `sampler` ∈ {"advi", "nuts"}. ADVI is fast and approximate, NUTS
    is the calibrated full-Bayes run. Both run through NumPyro / JAX.
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

    if sampler == "nuts":
        samples = _run_nuts(
            bi,
            ki,
            balls,
            runs,
            n_batters,
            n_bowlers,
            draws=nuts_draws,
            chains=nuts_chains,
            tune=nuts_tune,
            target_accept=nuts_target_accept,
            seed=seed,
        )
    else:
        samples = _run_advi(
            bi,
            ki,
            balls,
            runs,
            n_batters,
            n_bowlers,
            steps=advi_steps,
            seed=seed,
        )

    b_arr = np.asarray(samples["b_skill"]).reshape(-1, n_batters)
    k_arr = np.asarray(samples["k_skill"]).reshape(-1, n_bowlers)
    b_mean = b_arr.mean(axis=0)
    b_sd = b_arr.std(axis=0)
    k_mean = k_arr.mean(axis=0)
    k_sd = k_arr.std(axis=0)

    batter_totals = (
        (
            edges.group_by("batter_id").agg(
                pl.col("balls").sum().alias("balls"),
                pl.col("runs").sum().alias("runs"),
            )
        )
        .to_pandas()
        .set_index("batter_id")
    )
    bowler_totals = (
        (
            edges.group_by("bowler_id").agg(
                pl.col("balls").sum().alias("balls"),
                pl.col("runs").sum().alias("runs"),
            )
        )
        .to_pandas()
        .set_index("bowler_id")
    )

    rows: list[dict] = []
    for name, idx in batter_idx.items():
        t = batter_totals.loc[name]
        rows.append(
            {
                "cricsheet_id": name,
                "role": "batter",
                "skill": float(b_mean[idx]),
                "skill_sd": float(b_sd[idx]),
                "balls": int(t["balls"]),
                "runs": int(t["runs"]),
            }
        )
    for name, idx in bowler_idx.items():
        t = bowler_totals.loc[name]
        rows.append(
            {
                "cricsheet_id": name,
                "role": "bowler",
                "skill": float(k_mean[idx]),
                "skill_sd": float(k_sd[idx]),
                "balls": int(t["balls"]),
                "runs": int(t["runs"]),
            }
        )
    return pl.DataFrame(rows)
