"""Bayesian opponent-adjusted batter / bowler ratings, judged against each ball's own context.

Model (the default, `variant="v2"`)
-----------------------------------
Every ball in a league is grouped into a *cell*: (batter i, bowler j, season s, phase p,
innings c, venue v). For each cell with `balls` legal balls faced, `runs` off the bat,
bowler-credited dismissals `outs` out of `trials`:

    runs ~ NegBin(mean = exp(r0 + ctx_r + b_skill[i] − k_skill[j]) · balls,
                  concentration = alpha · balls)
    outs ~ Binomial(trials, sigmoid(w0 + ctx_w + bowl_strike[j] − bat_survive[i]))
    ctx  = season[s] + phase[p] + innings[c] + venue[v]

and, per (bowler, season), the wides and no-ball runs he gave away over his deliveries:

    extras ~ NegBin(mean = exp(x0 + x_season[s] − bowl_extras[j]) · deliveries,
                    concentration = alpha_x · deliveries)

- **Context.** `season` is a Gaussian random walk over the league's seasons (each season's
  scoring level starts from the last one's), `phase` (powerplay / middle / death) and `innings`
  (setting / chasing) are fixed effects, `venue` is hierarchical (a ground with few matches
  shrinks to the league). So a 2009 strike rate and a 2026 one are each judged against their own
  season, a death bowler against death overs and an opener against the powerplay.
- **Dispersion scales with balls.** The sum of n roughly independent balls has variance ∝ n, so
  the Negative-Binomial concentration is `alpha · balls` (variance = mean · (1 + rate / alpha)),
  not a single `alpha` that made a 150-ball cell look as noisy as 150 one-ball cells.
- **Role-level prior means.** A batter's skills shrink toward the mean of his *batting slot*
  (top order 1–3, middle 4–5, lower middle 6–7, tail 8–11, from his median position in the data),
  not toward the average batter — so a tail-ender with 30 balls isn't rated an average batter. A
  bowler's shrink toward frontline bowlers' or part-timers' mean (frontline = 15+ deliveries per
  match bowled).
- **Extras.** A bowler's economy counts his wides and no-ball runs: `skill` for a bowler is the
  log of his total runs conceded per ball (off the bat + extras) against the average bowler's.

All skills are higher = better and carry hierarchical priors written non-centred. Every matchup
is kept, even a 1-ball one: shrinkage, not a cut-off, handles small samples, and is what makes
"opponent bridging" work — a batter who scores off strong bowlers gains more than one who scores
the same off part-timers.

`variant="legacy"` is the earlier model (one global intercept, a single NegBin `alpha`, one
population prior per role, runs off the bat only) — kept to measure what each change did.

Engine
------
NumPyro (JAX). `advi` (default) is mean-field stochastic VI (`AutoNormal`, 12,000 steps); `nuts`
is full No-U-Turn HMC (2 chains × 1000 draws + 500 warmup), logs r-hat / ESS / divergences.

Output
------
polars DataFrame keyed by `cricsheet_id` (a player's registry id resolved per match, so two
players sharing a scorecard name are two players) with columns:
    role            "batter" | "bowler"
    skill           posterior mean: scoring (batter) / economy incl. extras (bowler), log scale,
                    centred on the average player of the role
    skill_sd        posterior std-dev
    balls           career legal balls in this role (every matchup)
    runs            career runs off the bat in this role
    survival_skill(_sd) / strike_skill(_sd)   batter / bowler dismissal axis
    value(_sd)      complete value: both axes in population-sd units, summed (see `_value_draws`)
    slot            batter's median batting position (batters), `extras_skill(_sd)` (bowlers)
    unique_name     the player's scorecard name in this collection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdex.common.sql import (
    UNRESOLVED,
    _columns,
    _tables,
    keyed_balls,
    label_map,
    table_suffix,
)
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# Bump whenever the model or its inputs change: cached fits (e.g. the backtests') are keyed by it,
# so a fit from an older model can never be reused by mistake.
MODEL_VERSION = "2026.10-era"
VARIANTS = ("v2", "legacy")

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
PHASES = ("powerplay", "middle", "death")
SLOT_GROUPS = ("top (1-3)", "middle (4-5)", "lower middle (6-7)", "tail (8-11)")
BOWLER_GROUPS = ("frontline", "part-time")
FRONTLINE_BALLS = 15  # deliveries per match bowled that make a frontline bowler


@dataclass
class Flags:
    """Which parts of the model are on (the legacy model has them all off)."""

    context: bool = True
    nb_scale: bool = True
    slot_prior: bool = True
    extras: bool = True

    @classmethod
    def of(cls, variant: str) -> Flags:
        if variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
        return cls() if variant == "v2" else cls(False, False, False, False)


def _slot_group(slot: float | None) -> int:
    if slot is None or slot <= 3:
        return 0
    if slot <= 5:
        return 1
    if slot <= 7:
        return 2
    return 3


def _window_sql(safe: str, have_matches: bool, since: str | None, before: str | None) -> str:
    if not (since or before):
        return ""
    conds = []
    col = "m.match_date" if have_matches else "match_date"
    if since:
        conds.append(f"{col} >= '{date.fromisoformat(since).isoformat()}'")
    if before:
        conds.append(f"{col} < '{date.fromisoformat(before).isoformat()}'")
    if have_matches:
        return (
            f"AND b.match_id IN (SELECT m.match_id FROM matches_{safe} m "
            f"WHERE {' AND '.join(conds)})"
        )
    return "AND " + " AND ".join(c.replace("match_date", "b.match_date") for c in conds)


def _load_edges(
    db_path: Path | str,
    collection: str,
    since: str | None = None,
    before: str | None = None,
    by_year: bool = False,
) -> pl.DataFrame:
    """Every (batter, bowler, season, phase, innings, venue) cell with its legal balls, runs off
    the bat, bowler-credited dismissals and dismissal trials, plus the bowler's wides / no-ball
    runs (`ext_runs`) over his deliveries — nothing dropped. Players are registry ids, resolved
    per match.

    `since` / `before` (ISO dates) keep only matches played in that window — the ratings backtest
    fits on everything before a season, then scores it. `by_year` adds a `yr` column (calendar
    year), so the fit can weight recent seasons more."""
    safe = table_suffix(collection)
    kinds_sql = ", ".join(f"'{k}'" for k in _BOWLER_WICKET_KINDS)
    with duckdb.connect(str(db_path), read_only=True) as con:
        have = _columns(con, f"balls_{safe}")
        tables = _tables(con)
        has_m = f"matches_{safe}" in tables and "match_id" in have
        mcols = _columns(con, f"matches_{safe}") if has_m else set()
        window = _window_sql(safe, has_m, since, before)
        date_col = "m.match_date" if has_m else ("b.match_date" if "match_date" in have else None)
        season = (
            "COALESCE(m.season, LEFT(CAST(m.match_date AS VARCHAR), 4))"
            if "season" in mcols
            else (f"LEFT(CAST({date_col} AS VARCHAR), 4)" if date_col else "'all'")
        )
        yr = f"CAST(LEFT(CAST({date_col} AS VARCHAR), 4) AS INTEGER)" if date_col else "0"
        phase = "COALESCE(b.phase, 'middle')" if "phase" in have else "'middle'"
        inn = "LEAST(COALESCE(b.innings_idx, 0), 1)" if "innings_idx" in have else "0"
        venue = "COALESCE(b.venue, '?')" if "venue" in have else "'?'"
        ext = (
            "COALESCE(b.extras_wides, 0) + COALESCE(b.extras_noballs, 0)"
            if {"extras_wides", "extras_noballs"} <= have
            else (
                "CASE WHEN b.extras_type IN ('wides', 'noballs') THEN COALESCE(b.runs_extras, 0) "
                "ELSE 0 END"
                if "runs_extras" in have
                else "0"
            )
        )
        join_m = f"LEFT JOIN matches_{safe} m ON m.match_id = b.match_id" if has_m else ""
        main = "(b.innings_idx <= 1 OR b.match_type IN ('Test', 'MDM'))"
        if "innings_idx" not in have:
            main = "TRUE"
        kb = keyed_balls(con, collection)
        df = con.execute(
            f"""
            WITH labelled AS (
                SELECT
                    b.batter AS batter_id,
                    b.bowler AS bowler_id,
                    {season} AS season, {phase} AS phase, {inn} AS inn, {venue} AS venue,
                    {yr} AS yr,
                    b.runs_batter,
                    {ext} AS ext,
                    CASE WHEN b.extras_type IN ('wides') THEN 0 ELSE 1 END AS legal_ball,
                    -- A dismissal counts for this edge only when the striker
                    -- (batter) is the one out AND the kind is bowler-credited.
                    CASE
                        WHEN b.wicket_kind IN ({kinds_sql})
                         AND b.player_out = b.batter
                        THEN 1 ELSE 0
                    END AS is_out
                FROM {kb} b {join_m}
                WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL
                  AND {main} {window}
            )
            SELECT batter_id, bowler_id, season, phase, inn, venue{", yr" if by_year else ""},
                   SUM(legal_ball) AS balls,
                   SUM(runs_batter) AS runs,
                   SUM(is_out) AS outs,
                   -- Dismissal trials: legal balls plus the rare bowler-credited
                   -- dismissal off a wide (a stumping), so outs <= trials always.
                   SUM(CASE WHEN legal_ball = 1 OR is_out = 1 THEN 1 ELSE 0 END) AS trials,
                   SUM(ext) AS ext_runs,
                   COUNT(*) AS deliveries
            FROM labelled
            GROUP BY ALL
            """
        ).pl()
    return df


def _batting_slots(
    db_path: Path | str, collection: str, since: str | None = None, before: str | None = None
) -> dict[str, float]:
    """batter id -> his median batting position (1 = opener) over the innings in the window."""
    safe = table_suffix(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        have = _columns(con, f"balls_{safe}")
        need = {"match_id", "innings_idx", "over", "ball_in_over", "non_striker", "batter"}
        if not need <= have:
            return {}
        has_m = f"matches_{safe}" in _tables(con)
        window = _window_sql(safe, has_m, since, before)
        kb = keyed_balls(con, collection)
        order = "b.over, b.ball_in_over" + (", b.ball_id" if "ball_id" in have else "")
        rows = con.execute(
            f"""
            WITH seq AS (
                SELECT b.match_id, b.innings_idx, b.batter, b.non_striker,
                       ROW_NUMBER() OVER (PARTITION BY b.match_id, b.innings_idx ORDER BY {order}) AS n
                FROM {kb} b WHERE b.innings_idx <= 1 {window}
            ),
            firsts AS (
                SELECT match_id, innings_idx, p, MIN(n * 2 + ns) AS first FROM (
                    SELECT match_id, innings_idx, batter AS p, n, 0 AS ns FROM seq
                    UNION ALL SELECT match_id, innings_idx, non_striker, n, 1 FROM seq
                ) WHERE p IS NOT NULL GROUP BY 1, 2, 3
            ),
            pos AS (
                SELECT p, ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx ORDER BY first)
                       AS position
                FROM firsts
            )
            SELECT p, MEDIAN(position) FROM pos GROUP BY p
            """
        ).fetchall()
    return {p: float(s) for p, s in rows if p is not None and s is not None}


def _bowler_rates(
    db_path: Path | str, collection: str, since: str | None = None, before: str | None = None
) -> dict[str, float]:
    """bowler id -> deliveries per match he bowled in (over the window): frontline vs part-time."""
    safe = table_suffix(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        have = _columns(con, f"balls_{safe}")
        if "match_id" not in have:
            return {}
        window = _window_sql(safe, f"matches_{safe}" in _tables(con), since, before)
        rows = con.execute(
            f"SELECT b.bowler, COUNT(*) * 1.0 / COUNT(DISTINCT b.match_id) "
            f"FROM {keyed_balls(con, collection)} b WHERE b.bowler IS NOT NULL {window} GROUP BY 1"
        ).fetchall()
    return {k: float(r) for k, r in rows}


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


# ---- model pieces -----------------------------------------------------------------------------


def _skill(site: str, plate: str, n: int, sigma, mean=None):
    """Hierarchical skill, non-centred: `site = mean + sigma * raw`, raw ~ N(0, 1).

    The centred form (`site ~ N(mean, sigma)`) puts the many thin-sample
    players in a funnel with `sigma`, which NUTS samples badly. The
    non-centred form has the same prior and is recorded under the same
    site name, so downstream code reads `b_skill` etc. unchanged."""
    import numpyro
    import numpyro.distributions as dist

    with numpyro.plate(plate, n):
        raw = numpyro.sample(f"{site}_raw", dist.Normal(0.0, 1.0))
    return numpyro.deterministic(site, (0.0 if mean is None else mean) + sigma * raw)


def _levels(site: str, n: int, scale: float = 1.0):
    """`n` levels of a factor with the first as the reference (0) and N(0, scale) priors on the rest."""
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    if n <= 1:
        return numpyro.deterministic(site, jnp.zeros(max(n, 1)))
    with numpyro.plate(f"{site}_levels", n - 1):
        rest = numpyro.sample(f"{site}_free", dist.Normal(0.0, scale))
    return numpyro.deterministic(site, jnp.concatenate([jnp.zeros(1), rest]))


def _random_walk(site: str, n: int, tau_scale: float = 0.1):
    """A Gaussian random walk over `n` ordered seasons, anchored at 0 for the first (non-centred)."""
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    tau = numpyro.sample(f"{site}_tau", dist.HalfNormal(tau_scale))
    if n <= 1:
        return numpyro.deterministic(site, jnp.zeros(max(n, 1)))
    with numpyro.plate(f"{site}_steps", n - 1):
        z = numpyro.sample(f"{site}_raw", dist.Normal(0.0, 1.0))
    return numpyro.deterministic(site, jnp.concatenate([jnp.zeros(1), jnp.cumsum(tau * z)]))


def _context(prefix: str, ctx: dict):
    """season (random walk) + phase + innings + venue (hierarchical) for one sub-model."""
    import numpyro
    import numpyro.distributions as dist

    season = _random_walk(f"{prefix}season", ctx["n_seasons"])
    phase = _levels(f"{prefix}phase", ctx["n_phases"])
    innings = _levels(f"{prefix}innings", 2)
    sigma_v = numpyro.sample(f"{prefix}sigma_venue", dist.HalfNormal(0.2))
    venue = _skill(f"{prefix}venue", f"{prefix}venues", ctx["n_venues"], sigma_v)
    return season[ctx["si"]] + phase[ctx["pi"]] + innings[ctx["ci"]] + venue[ctx["vi"]]


def _scale(weight):
    return 1.0 if weight is None else weight


def _model(
    bi,
    ki,
    balls,
    runs,
    outs=None,
    trials=None,
    n_batters: int = 0,
    n_bowlers: int = 0,
    weight=None,
    flags: Flags | None = None,
    ctx: dict | None = None,
    bgrp=None,
    kgrp=None,
    n_bgrp: int = 1,
    n_kgrp: int = 1,
    extras: dict | None = None,
    dismissal: bool = True,
):
    """The joint runs + dismissals (+ extras) model — see the module docstring."""
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    flags = flags or Flags.of("legacy")
    use_ctx = flags.context and ctx is not None
    slots = flags.slot_prior and bgrp is not None

    # --- scoring-rate sub-model ---
    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    mu_b = _levels("mu_b", n_bgrp, 0.5) if slots else None
    mu_k = _levels("mu_k", n_kgrp, 0.5) if slots else None
    b_skill = _skill("b_skill", "batters", n_batters, sigma_b, mu_b[bgrp] if slots else None)
    k_skill = _skill("k_skill", "bowlers", n_bowlers, sigma_k, mu_k[kgrp] if slots else None)
    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha = numpyro.sample("alpha", dist.HalfNormal(5.0))
    eta = intercept + b_skill[bi] - k_skill[ki]
    if use_ctx:
        eta = eta + _context("r_", ctx)
    has_balls = balls > 0
    mu = jnp.where(has_balls, jnp.exp(eta) * balls, 1.0)
    conc = alpha * jnp.where(has_balls, balls, 1.0) if flags.nb_scale else alpha
    with numpyro.handlers.mask(mask=has_balls), numpyro.handlers.scale(scale=_scale(weight)):
        numpyro.sample("y_runs", dist.NegativeBinomial2(mean=mu, concentration=conc), obs=runs)

    if dismissal:
        # --- dismissal sub-model ---
        sigma_surv = numpyro.sample("sigma_surv", dist.HalfNormal(1.0))
        sigma_strike = numpyro.sample("sigma_strike", dist.HalfNormal(1.0))
        mu_s = _levels("mu_surv", n_bgrp, 0.5) if slots else None
        mu_t = _levels("mu_strike", n_kgrp, 0.5) if slots else None
        bat_survive = _skill(
            "bat_survive", "batters_surv", n_batters, sigma_surv, mu_s[bgrp] if slots else None
        )
        bowl_strike = _skill(
            "bowl_strike", "bowlers_strike", n_bowlers, sigma_strike, mu_t[kgrp] if slots else None
        )
        # Baseline dismissal log-odds. Per-ball dismissal prob in T20 ~ 1/25,
        # so logit ≈ log(1/24) ≈ -3.2 — a Normal(-3, 2) prior covers it.
        w_intercept = numpyro.sample("w_intercept", dist.Normal(-3.0, 2.0))
        logit_p = w_intercept + bowl_strike[ki] - bat_survive[bi]
        if use_ctx:
            logit_p = logit_p + _context("w_", ctx)
        with numpyro.handlers.scale(scale=_scale(weight)):
            numpyro.sample(
                "y_outs",
                dist.Binomial(total_count=trials.astype(jnp.int32), logits=logit_p),
                obs=outs,
            )

    if flags.extras and extras is not None:
        # --- the bowler's wides and no-ball runs, per (bowler, season) ---
        sigma_x = numpyro.sample("sigma_x", dist.HalfNormal(1.0))
        bowl_extras = _skill("bowl_extras", "bowlers_extras", n_bowlers, sigma_x)
        x_int = numpyro.sample("x_intercept", dist.Normal(-3.0, 2.0))
        alpha_x = numpyro.sample("alpha_x", dist.HalfNormal(5.0))
        x_eta = x_int - bowl_extras[extras["k"]]
        if use_ctx:
            x_eta = x_eta + _random_walk("x_season", ctx["n_seasons"])[extras["s"]]
        n_del = extras["n"]
        numpyro.sample(
            "y_extras",
            dist.NegativeBinomial2(
                mean=jnp.exp(x_eta) * n_del,
                concentration=alpha_x * n_del if flags.nb_scale else alpha_x,
            ),
            obs=extras["runs"],
        )


# Sites summarised for the NUTS convergence check (and returned by ADVI).
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
_EXTRA_SITES = (
    "bowl_extras",
    "sigma_x",
    "x_intercept",
    "alpha_x",
    "intercept",
    "w_intercept",
    "alpha",
    "mu_b",
    "mu_k",
    "mu_surv",
    "mu_strike",
    "r_season",
    "w_season",
    "x_season",
    "r_phase",
    "w_phase",
    "r_innings",
    "w_innings",
    "r_venue",
    "w_venue",
    "r_season_tau",
    "w_season_tau",
    "r_sigma_venue",
    "w_sigma_venue",
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
    # Run the model under the guide's draws so the deterministic sites
    # (mean + sigma * raw, the context levels) are returned alongside the latent ones.
    # draws in batches of 100: one vectorised pass over every cell for all 500 draws at once
    # needs gigabytes on a big league
    batch = 100
    predictive = Predictive(
        model_fn,
        guide=guide,
        params=svi_result.params,
        num_samples=batch,
        return_sites=list(_DIAG_SITES + _EXTRA_SITES),
    )
    chunks = [
        {
            k: np.asarray(v)
            for k, v in predictive(jax.random.PRNGKey(seed + 1 + i), **model_kwargs).items()
        }
        for i in range(max(1, post_samples // batch))
    ]
    return {k: np.concatenate([c[k] for c in chunks]) for k in chunks[0]}


def _value_draws(
    rate_draws: np.ndarray,
    odds_draws: np.ndarray,
    samples: dict,
    rate_sigma: str | float,
    odds_sigma: str | float,
) -> np.ndarray:
    """Per-draw complete value: both axes in population-sd units, then summed.

    The scoring/economy axis is a log runs-per-ball effect and the
    survival/strike axis a log-odds dismissal effect — different units, so
    adding them raw would let whichever scale happens to be wider dominate.
    Each axis is divided by its population sd (the posterior mean of its
    hierarchical `sigma`, or a number: with role-level prior means it is the
    spread across *all* players of the role, within and between groups), so
    1.0 means "one typical player-to-player spread better" on either axis and
    the two count equally. Doing it per draw keeps the posterior sd of the sum
    honest (`value_sd`)."""

    def _sd(s):
        return float(s) if isinstance(s, int | float) else float(np.mean(np.asarray(samples[s])))

    return rate_draws / _sd(rate_sigma) + odds_draws / _sd(odds_sigma)


def _centre(draws: np.ndarray, sigma: np.ndarray, mu: np.ndarray | None, grp: np.ndarray) -> tuple:
    """Centre player draws on the role's population mean and give the population sd.

    With group prior means the population mean is the group means weighted by how many players
    are in each, and the population sd adds the spread between groups to `sigma`."""
    sig = np.asarray(sigma).reshape(-1)
    if mu is None:
        return draws - 0.0, float(sig.mean())
    mu = np.asarray(mu).reshape(draws.shape[0], -1)
    w = np.bincount(grp, minlength=mu.shape[1]).astype(float)
    w /= w.sum()
    mean = mu @ w  # per draw
    between = ((mu - mean[:, None]) ** 2) @ w
    return draws - mean[:, None], float(np.sqrt(sig**2 + between).mean())


@dataclass
class FitResult:
    """Posterior summaries a held-out evaluation needs (plug-in posterior means)."""

    variant: str
    flags: Flags
    batter_idx: dict[str, int]
    bowler_idx: dict[str, int]
    seasons: list[str]
    venues: list[str]
    means: dict[str, np.ndarray]
    bgrp: np.ndarray
    kgrp: np.ndarray
    context: dict = field(default_factory=dict)


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
    variant: str = "v2",
    return_fit: bool = False,
) -> Any:
    """Fit the model and return one row per (cricsheet_id, role) — with `return_fit`, the tuple
    `(table, FitResult, samples)`.

    `before` (ISO date) fits on matches before that date only — used by the
    backtests; the normal fit uses every match.

    `half_life` (years, optional) weights each season's matchups by
    0.5 ** (age / half_life), age counted back from the latest season fitted,
    so old form fades. None = every season counts the same.

    `sampler` ∈ {"advi", "nuts"}. ADVI is fast and approximate, NUTS
    is the calibrated full-Bayes run. Both run through NumPyro / JAX.

    `variant` ∈ {"v2", "legacy"}: the context-adjusted model (default) or the earlier one.

    `dismissal_aware` (default True) fits the joint runs + dismissals
    model so each batter also gets a `survival_skill` (resistance to
    getting out) and each bowler a `strike_skill` (wicket-taking), plus
    a derived `value` that combines both axes. Set False for a runs-only
    fit (only `skill` is emitted).
    """
    import jax.numpy as jnp

    if sampler not in ("advi", "nuts"):
        raise ValueError(f"sampler must be 'advi' or 'nuts', got {sampler!r}")
    flags = Flags.of(variant)

    all_edges = _load_edges(db_path, collection, before=before, by_year=True)
    edges, batter_idx, bowler_idx = _index_edges(all_edges, min_balls)
    if edges.is_empty():
        empty = pl.DataFrame()
        return (empty, None, None) if return_fit else empty

    n_batters = len(batter_idx)
    n_bowlers = len(bowler_idx)
    seasons = sorted(set(all_edges["season"].to_list()))
    venues = sorted(set(edges["venue"].to_list()))
    s_idx = {s: i for i, s in enumerate(seasons)}
    v_idx = {v: i for i, v in enumerate(venues)}
    p_idx = {p: i for i, p in enumerate(PHASES)}
    edges = edges.with_columns(
        pl.col("season").replace_strict(s_idx).alias("si"),
        pl.col("venue").replace_strict(v_idx).alias("vi"),
        pl.col("phase").replace_strict(p_idx, default=1).alias("pi"),
    )

    # role groups for the prior means: batting slot (median position) and frontline / part-time
    slots = _batting_slots(db_path, collection, before=before) if flags.slot_prior else {}
    bgrp = np.zeros(n_batters, dtype=np.int32)
    for b, i in batter_idx.items():
        bgrp[i] = _slot_group(slots.get(b))
    rates = _bowler_rates(db_path, collection, before=before) if flags.slot_prior else {}
    kgrp = np.ones(n_bowlers, dtype=np.int32)
    for k, i in bowler_idx.items():
        if rates.get(k, 0.0) >= FRONTLINE_BALLS:
            kgrp[i] = 0

    model_kwargs: dict[str, Any] = {
        "bi": jnp.asarray(edges["bi"].cast(pl.Int32).to_numpy()),
        "ki": jnp.asarray(edges["ki"].cast(pl.Int32).to_numpy()),
        "balls": jnp.asarray(edges["balls"].cast(pl.Float32).to_numpy()),
        "runs": jnp.asarray(edges["runs"].cast(pl.Int32).to_numpy()),
        "n_batters": n_batters,
        "n_bowlers": n_bowlers,
        "flags": flags,
        "dismissal": dismissal_aware,
    }
    if dismissal_aware:
        model_kwargs["outs"] = jnp.asarray(edges["outs"].cast(pl.Int32).to_numpy())
        model_kwargs["trials"] = jnp.asarray(edges["trials"].cast(pl.Int32).to_numpy())
    if flags.context:
        model_kwargs["ctx"] = {
            "si": jnp.asarray(edges["si"].cast(pl.Int32).to_numpy()),
            "pi": jnp.asarray(edges["pi"].cast(pl.Int32).to_numpy()),
            "ci": jnp.asarray(edges["inn"].cast(pl.Int32).to_numpy()),
            "vi": jnp.asarray(edges["vi"].cast(pl.Int32).to_numpy()),
            "n_seasons": len(seasons),
            "n_phases": len(PHASES),
            "n_venues": len(venues),
        }
    if flags.slot_prior:
        model_kwargs.update(
            bgrp=jnp.asarray(bgrp),
            kgrp=jnp.asarray(kgrp),
            n_bgrp=len(SLOT_GROUPS),
            n_kgrp=len(BOWLER_GROUPS),
        )
    if flags.extras:
        cells = (
            all_edges.filter(pl.col("bowler_id").is_in(list(bowler_idx)))
            .group_by("bowler_id", "season")
            .agg(pl.col("ext_runs").sum(), pl.col("deliveries").sum())
            .filter(pl.col("deliveries") > 0)
        )
        model_kwargs["extras"] = {
            "k": jnp.asarray(
                cells["bowler_id"].replace_strict(bowler_idx).cast(pl.Int32).to_numpy()
            ),
            "s": jnp.asarray(cells["season"].replace_strict(s_idx).cast(pl.Int32).to_numpy()),
            "n": jnp.asarray(cells["deliveries"].cast(pl.Float32).to_numpy()),
            "runs": jnp.asarray(cells["ext_runs"].cast(pl.Int32).to_numpy()),
        }
    if half_life is not None:
        age = (edges["yr"].max() - edges["yr"]).fill_null(0)
        weight = (0.5 ** (age.cast(pl.Float32) / half_life)).to_numpy()
        model_kwargs["weight"] = jnp.asarray(weight)

    if sampler == "nuts":
        samples, _ = _run_nuts(
            _model,
            model_kwargs,
            draws=nuts_draws,
            chains=nuts_chains,
            tune=nuts_tune,
            target_accept=nuts_target_accept,
            seed=seed,
        )
    else:
        samples = _run_advi(_model, model_kwargs, steps=advi_steps, seed=seed)

    def _draws(key: str, n: int) -> np.ndarray:
        return np.asarray(samples[key]).reshape(-1, n)

    def _get(key: str):
        return np.asarray(samples[key]) if key in samples else None

    def _stats(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return arr.mean(axis=0), arr.std(axis=0)

    slot_on = flags.slot_prior
    b_c, b_scale = _centre(
        _draws("b_skill", n_batters), _get("sigma_b"), _get("mu_b") if slot_on else None, bgrp
    )
    k_c, k_scale = _centre(
        _draws("k_skill", n_bowlers), _get("sigma_k"), _get("mu_k") if slot_on else None, kgrp
    )
    # economy: runs off the bat and, with the extras sub-model, wides + no-balls on top
    econ, econ_scale = k_c, k_scale
    if flags.extras and "bowl_extras" in samples:
        x = _draws("bowl_extras", n_bowlers)
        legal_share = float(all_edges["balls"].sum()) / max(
            float(all_edges["deliveries"].sum()), 1.0
        )
        bat_rate = np.exp(np.asarray(samples["intercept"]).reshape(-1, 1))
        ext_rate = np.exp(np.asarray(samples["x_intercept"]).reshape(-1, 1)) / legal_share
        econ = -np.log((bat_rate * np.exp(-k_c) + ext_rate * np.exp(-x)) / (bat_rate + ext_rate))
        w = float((bat_rate / (bat_rate + ext_rate)).mean())
        sx = float(np.asarray(samples["sigma_x"]).mean())
        econ_scale = float(np.sqrt((w * k_scale) ** 2 + ((1 - w) * sx) ** 2))
        xm, xs = _stats(x)
    b_mean, b_sd = _stats(b_c)
    k_mean, k_sd = _stats(econ)
    if dismissal_aware:
        surv_c, surv_scale = _centre(
            _draws("bat_survive", n_batters),
            _get("sigma_surv"),
            _get("mu_surv") if slot_on else None,
            bgrp,
        )
        strike_c, strike_scale = _centre(
            _draws("bowl_strike", n_bowlers),
            _get("sigma_strike"),
            _get("mu_strike") if slot_on else None,
            kgrp,
        )
        surv_mean, surv_sd = _stats(surv_c)
        strike_mean, strike_sd = _stats(strike_c)
        bv, bv_sd = _stats(_value_draws(b_c, surv_c, samples, b_scale, surv_scale))
        kv, kv_sd = _stats(_value_draws(econ, strike_c, samples, econ_scale, strike_scale))

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
            "slot": slots.get(name),
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
        if flags.extras and "bowl_extras" in samples:
            row["extras_skill"] = float(xm[idx])
            row["extras_skill_sd"] = float(xs[idx])
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

    # The player's scorecard name in this collection (per-match registry resolution), so the saved
    # JSON is self-contained; an unresolved player keeps his name and gets no id.
    with duckdb.connect(str(db_path), read_only=True) as con:
        labels = label_map(con, collection)
    _free_jax()
    df = df.with_columns(
        pl.col("cricsheet_id")
        .map_elements(
            lambda k: labels.get(k) or str(k).removeprefix(UNRESOLVED), return_dtype=pl.String
        )
        .alias("unique_name")
    )
    if not return_fit:
        return df

    means = {k: np.asarray(v).mean(axis=0) for k, v in samples.items()}
    context = _context_summary(means, seasons, venues, flags)
    res = FitResult(
        variant=variant,
        flags=flags,
        batter_idx=batter_idx,
        bowler_idx=bowler_idx,
        seasons=seasons,
        venues=venues,
        means=means,
        bgrp=bgrp,
        kgrp=kgrp,
        context=context,
    )
    return df, res, samples


def _free_jax() -> None:
    """Drop JAX's compiled-function caches: every fit has new array shapes, so a process that fits
    many leagues / seasons (the backtests) would otherwise keep every compiled program in memory."""
    try:
        import jax

        jax.clear_caches()
    except Exception:  # noqa: BLE001 — memory housekeeping only
        pass


def _context_summary(means: dict, seasons: list[str], venues: list[str], flags: Flags) -> dict:
    """The fitted context effects in plain numbers (runs per ball and dismissal odds multipliers)."""
    out: dict[str, Any] = {"seasons": seasons}
    if not flags.context:
        return out
    for pre, what in (("r_", "runs"), ("w_", "wickets")):
        if f"{pre}season" in means:
            out[f"{what}_season"] = dict(
                zip(seasons, map(float, means[f"{pre}season"]), strict=True)
            )
            out[f"{what}_phase"] = dict(zip(PHASES, map(float, means[f"{pre}phase"]), strict=True))
            out[f"{what}_innings"] = {
                "first": 0.0,
                "chase": float(np.asarray(means[f"{pre}innings"]).reshape(-1)[-1]),
            }
            out[f"{what}_season_step_sd"] = float(means.get(f"{pre}season_tau", np.nan))
            out[f"{what}_venue_sd"] = float(means.get(f"{pre}sigma_venue", np.nan))
    if "intercept" in means:
        out["runs_per_ball_base"] = float(np.exp(means["intercept"]))
    if flags.slot_prior and "mu_b" in means:
        out["batting_slot_means"] = dict(zip(SLOT_GROUPS, map(float, means["mu_b"]), strict=True))
        out["batting_slot_survival_means"] = dict(
            zip(SLOT_GROUPS, map(float, means["mu_surv"]), strict=True)
        )
    return out


def heldout_loglik(res: FitResult, edges: pl.DataFrame) -> dict:
    """Plug-in (posterior-mean) log predictive density of held-out cells: runs (Negative-Binomial)
    and dismissals (Binomial), per ball. A player the fit hasn't seen gets his role's population
    mean, an unseen season the last season's level, an unseen ground the league average."""
    from jax.scipy.special import gammaln

    m = res.means
    e = edges.filter(pl.col("trials") > 0)
    if e.is_empty():
        return {"n_balls": 0}

    def pop_mean(mu_key: str, grp: np.ndarray) -> float:
        if not res.flags.slot_prior or mu_key not in m:
            return 0.0
        w = np.bincount(grp, minlength=len(m[mu_key])).astype(float)
        return float(np.asarray(m[mu_key]) @ (w / w.sum()))

    def lookup(ids, idx, arr, default):
        return np.array([arr[idx[x]] if x in idx else default for x in ids])

    b = lookup(e["batter_id"], res.batter_idx, m["b_skill"], pop_mean("mu_b", res.bgrp))
    k = lookup(e["bowler_id"], res.bowler_idx, m["k_skill"], pop_mean("mu_k", res.kgrp))
    s_idx = {s: i for i, s in enumerate(res.seasons)}
    v_idx = {v: i for i, v in enumerate(res.venues)}
    last = len(res.seasons) - 1
    si = np.array([s_idx.get(s, last) for s in e["season"]])
    pi = np.array([PHASES.index(p) if p in PHASES else 1 for p in e["phase"]])
    ci = e["inn"].to_numpy().astype(int)

    def ctx(pre: str) -> np.ndarray:
        if not res.flags.context or f"{pre}season" not in m:
            return np.zeros(e.height)
        venue = np.array([m[f"{pre}venue"][v_idx[v]] if v in v_idx else 0.0 for v in e["venue"]])
        inn = np.asarray(m[f"{pre}innings"]).reshape(-1)
        return m[f"{pre}season"][si] + m[f"{pre}phase"][pi] + inn[ci] + venue

    balls = e["balls"].to_numpy().astype(float)
    runs = e["runs"].to_numpy().astype(float)
    mu = np.exp(m["intercept"] + ctx("r_") + b - k) * np.maximum(balls, 1)
    conc = m["alpha"] * np.maximum(balls, 1) if res.flags.nb_scale else np.full(len(mu), m["alpha"])
    nb = (
        gammaln(runs + conc)
        - gammaln(conc)
        - gammaln(runs + 1)
        + conc * np.log(conc / (conc + mu))
        + runs * np.log(mu / (conc + mu))
    )
    nb = np.asarray(nb)[balls > 0]
    out = {"n_balls": int(balls.sum()), "runs_ll_per_ball": float(nb.sum() / balls.sum())}
    if "bat_survive" in m:
        surv = lookup(
            e["batter_id"], res.batter_idx, m["bat_survive"], pop_mean("mu_surv", res.bgrp)
        )
        strike = lookup(
            e["bowler_id"], res.bowler_idx, m["bowl_strike"], pop_mean("mu_strike", res.kgrp)
        )
        z = m["w_intercept"] + ctx("w_") + strike - surv
        n = e["trials"].to_numpy().astype(float)
        y = e["outs"].to_numpy().astype(float)
        logp, log1mp = -np.logaddexp(0, -z), -np.logaddexp(0, z)
        bl = gammaln(n + 1) - gammaln(y + 1) - gammaln(n - y + 1) + y * logp + (n - y) * log1mp
        out["outs_ll_per_ball"] = float(np.asarray(bl).sum() / n.sum())
    return out
