# scout/ratings

Bayesian opponent-adjusted skill ratings.

## Model

The default fit is **dismissal-aware**: two coupled likelihoods on the same
(batter, bowler) edges — a runs Negative-Binomial (below) plus a per-ball
dismissal Binomial,

```
outs_ij ~ Binomial(balls_ij, sigmoid(w_int + bowl_strike[j] − bat_survive[i]))
```

— so each batter gets a scoring `skill` and a `survival_skill`, and each
bowler an economy `skill` and a `strike_skill` (four latent axes, all
higher = better). The runs part on its own:

```
runs_ij ~ NegBin(mu_ij, alpha)
mu_ij   = exp(intercept + b_skill[i] − k_skill[j]) * balls_ij
b_skill ~ Normal(0, sigma_b)        sigma_b ~ HalfNormal(1)
k_skill ~ Normal(0, sigma_k)        sigma_k ~ HalfNormal(1)
```

Each batter / bowler gets a latent skill on the log-runs scale.
Hierarchical priors pull thin-sample players toward the global mean,
which is what gives the "opponent bridging" effect — a batter who
dominates a known-strong bowler gets a meaningful uplift; a batter who
dominates only journeymen is shrunk back.

## Why this isn't average / SR

- **Average**: dismissed-runs ratio. Ignores opponent strength entirely.
- **SR**: runs per ball. Same problem. A 200 SR vs minnows isn't 200 vs
  Bumrah.
- **This rating**: every edge weighs both opponent identity and sample
  size. Posterior std-dev is reported so the consumer knows confidence.

## Fit

NumPyro (JAX). Two samplers wired behind `--sampler`:

- `advi` (default) — mean-field variational (`--advi-steps`, default
  12000). Fast; under-estimates posterior variance, so `skill_sd` is
  directional. Use for routine refreshes.
- `nuts` — full No-U-Turn HMC, `--nuts-chains 2` × `--nuts-draws 1000`
  + `--nuts-tune 500` by default. Slower; produces a properly calibrated
  posterior — use this when downstream consumers actually plot
  confidence bars (player-profile uncertainty).

```bash
make docker-scout-rate COLLECTION=ipl STEPS=12000          # advi, fast default
uv run python scripts/scout_rate.py --collection ipl --sampler nuts   # nuts, calibrated
uv run python scripts/scout_rate.py -c ipl --sampler nuts --nuts-draws 2000 --nuts-chains 4
```

There is no `make` target for NUTS; call the script directly.

Output: `data/metrics/scout_ratings_<collection>.json` (one row per
player-role) with columns `cricsheet_id, unique_name, role, skill,
skill_sd, balls, runs, value` plus `survival_skill, survival_skill_sd`
(batters) or `strike_skill, strike_skill_sd` (bowlers). `value` is the sum
of the role's two axes (a player's complete value).

## Caveats

- One skill set per role today — no era / venue / format break-out
  yet. Easy to add as fixed effects in the linear predictor (`+ era[e]`).
- ADVI (the default) under-estimates posterior variance, so its
  confidence intervals are directional, not calibrated; run with
  `--sampler nuts` when calibration matters.
- Players present only as bowler (or only as batter) get one role row;
  all-rounders get two rows in the output.

## Next

- Add venue + phase fixed effects.
- Use the resulting opponent strengths as the bridge that lifts
  grassroots (CricHeroes) ratings — this is the Opposition-Adjusted
  Rating (OAR) referenced in `docs/METRICS.md`.
