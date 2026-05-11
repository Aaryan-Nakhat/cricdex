# scout/ratings

Bayesian opponent-adjusted skill ratings.

## Model

Negative-Binomial regression on (batter, bowler) edges:

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

ADVI mean-field, single-threaded. ~1-3 min on IPL all-time (~30k edges
with `min_balls=6`). Switch to NUTS for the final v2 release.

```bash
make docker-scout-rate                       # COLLECTION=ipl, 12k ADVI steps
COLLECTION=ipl STEPS=20000 make docker-scout-rate
```

Output: `data/metrics/scout_ratings_<collection>.json` with columns
`cricsheet_id, role, skill, skill_sd, balls, runs`.

## Caveats

- Single global skill per role today — no era / venue / format break-out
  yet. Easy to add as fixed effects in the linear predictor (`+ era[e]`).
- ADVI under-estimates posterior variance. Confidence intervals are
  directional, not calibrated. NUTS run planned.
- Players present only as bowler (or only as batter) get one role row;
  all-rounders get two rows in the output.

## Next

- Add venue + phase fixed effects.
- Switch to NUTS with 2 chains × 1000 draws (≈20 min, acceptable for
  weekly refresh).
- Use the resulting opponent strengths as the bridge that lifts
  grassroots (CricHeroes) ratings — this is the Opposition-Adjusted
  Rating (OAR) referenced in `docs/METRICS.md`.
