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

Fit
---
Two samplers are wired:

- `advi` (default) — mean-field variational. ~1-3 min on the full
  IPL collection (~30k edges). Posterior variance is
  under-estimated, so `skill_sd` is directional rather than
  calibrated. Good for development and weekly refresh cycles.
- `nuts` — full No-U-Turn HMC, 2 chains × 1000 draws + 500 tune.
  ~20-30 min on the same IPL corpus. Produces a properly calibrated
  posterior — use this when the consumer cares about confidence
  intervals (player-profile uncertainty bars, wager-grade analytics).

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
    is the calibrated full-Bayes run.
    """
    import pymc as pm  # heavy import — keep lazy

    if sampler not in ("advi", "nuts"):
        raise ValueError(f"sampler must be 'advi' or 'nuts', got {sampler!r}")

    edges, batter_idx, bowler_idx = _load_edges(db_path, collection, min_balls)
    if edges.is_empty():
        return pl.DataFrame()

    n_batters = len(batter_idx)
    n_bowlers = len(bowler_idx)

    # DuckDB returns sum() as Decimal; cast so PyTensor accepts the arrays.
    bi = edges["bi"].cast(pl.Int64).to_numpy()
    ki = edges["ki"].cast(pl.Int64).to_numpy()
    balls = edges["balls"].cast(pl.Int64).to_numpy()
    runs = edges["runs"].cast(pl.Int64).to_numpy()

    with pm.Model():
        sigma_b = pm.HalfNormal("sigma_b", 1.0)
        sigma_k = pm.HalfNormal("sigma_k", 1.0)
        b_skill = pm.Normal("b_skill", mu=0.0, sigma=sigma_b, shape=n_batters)
        k_skill = pm.Normal("k_skill", mu=0.0, sigma=sigma_k, shape=n_bowlers)
        intercept = pm.Normal("intercept", mu=0.0, sigma=3.0)
        alpha = pm.HalfNormal("alpha", 5.0)

        log_mu = intercept + b_skill[bi] - k_skill[ki]
        mu = pm.math.exp(log_mu) * balls
        pm.NegativeBinomial("y", mu=mu, alpha=alpha, observed=runs)

        if sampler == "advi":
            approx = pm.fit(n=advi_steps, method="advi", progressbar=False, random_seed=seed)
            trace = approx.sample(500, random_seed=seed)
        else:
            trace = pm.sample(
                draws=nuts_draws,
                tune=nuts_tune,
                chains=nuts_chains,
                target_accept=nuts_target_accept,
                random_seed=seed,
                progressbar=False,
                compute_convergence_checks=False,
            )

    b_mean = np.asarray(trace.posterior["b_skill"]).reshape(-1, n_batters).mean(axis=0)
    b_sd = np.asarray(trace.posterior["b_skill"]).reshape(-1, n_batters).std(axis=0)
    k_mean = np.asarray(trace.posterior["k_skill"]).reshape(-1, n_bowlers).mean(axis=0)
    k_sd = np.asarray(trace.posterior["k_skill"]).reshape(-1, n_bowlers).std(axis=0)

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
