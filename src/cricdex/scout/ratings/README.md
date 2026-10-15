# scout/ratings

Bayesian opponent-adjusted skill ratings.

## Model

The default fit is **dismissal-aware**: two coupled likelihoods on the same
(batter, bowler) edges — a runs Negative-Binomial (below) plus a per-ball
dismissal Binomial,

```
outs_ij ~ Binomial(trials_ij, sigmoid(w_int + bowl_strike[j] − bat_survive[i]))
```

— so each batter gets a scoring `skill` and a `survival_skill`, and each
bowler an economy `skill` and a `strike_skill` (four latent axes, all
higher = better). The runs part on its own:

```
runs_ij ~ NegBin(mu_ij, alpha)
mu_ij   = exp(intercept + b_skill[i] − k_skill[j]) * balls_ij
b_skill = sigma_b · z_b,  z_b ~ Normal(0, 1)     sigma_b ~ HalfNormal(1)
k_skill = sigma_k · z_k,  z_k ~ Normal(0, 1)     sigma_k ~ HalfNormal(1)
```

(The same prior as `b_skill ~ Normal(0, sigma_b)`, written non-centred so
the many thin-sample players don't trap the sampler in a funnel.)

`trials_ij` is the legal balls plus the rare bowler-credited dismissal off
a wide (a stumping), so a wicket can never outnumber its balls.

**Every matchup is fitted** — even a 1-ball meeting. The hierarchical prior
already shrinks thin samples, so nothing is dropped; `balls` / `runs` in the
output are the player's true totals in the collection. (`--min-balls` is
only a speed knob for experiments; it never changes the reported balls.)

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
  12000). Checked against NUTS on IPL (2026-10): per-player sds are
  95–99% of NUTS's on every axis, `value_sd` ~99%, and P(A>B) differs by
  a median 1–2 points (95th pct ~6). A low-rank guide (rank 20) gave the
  same sds, slower. ~1.5-3 min for IPL; all 8 refresh collections ≈ 22 min.
- `nuts` — full No-U-Turn HMC, `--nuts-chains 2` × `--nuts-draws 1000`
  + `--nuts-tune 500` by default; logs worst r-hat, smallest ESS and the
  divergence count (warns past r-hat 1.05). IPL took ~15 min at 500+500
  per chain (r-hat 1.03, min ESS 101, 0 divergences) — all 8 collections
  would be 2–3 h, past the 120-min refresh budget, so it is opt-in.

```bash
make docker-scout-rate COLLECTION=ipl STEPS=12000          # advi, fast default
uv run python scripts/scout_rate.py --collection ipl --sampler nuts   # nuts, calibrated
uv run python scripts/scout_rate.py -c ipl --sampler nuts --nuts-draws 2000 --nuts-chains 4
```

There is no `make` target for NUTS; call the script directly.

Output: `data/metrics/scout_ratings_<collection>.json` (one row per
player-role) with columns `cricsheet_id, unique_name, role, skill,
skill_sd, balls, runs, value, value_sd` plus `survival_skill,
survival_skill_sd` (batters) or `strike_skill, strike_skill_sd` (bowlers).

`value` is the player's complete value for the role. Its two axes are in
different units — scoring/economy is a log runs-per-ball effect, survival/
strike a log-odds dismissal effect — so each is first divided by its fitted
population sd (`sigma_*`) and then added: `value = skill/σ_rate +
second/σ_odds`, per posterior draw. 1.0 = one typical player-to-player
spread better; 0 = the average player. `value_sd` is the posterior sd of
that sum. The auction price curve (`web_parity/pricing.py` ⇄
`site/src/lib/auction.ts`) is calibrated to these units.

## Backtest

Two walk-forward scripts check the ratings out of sample (Spearman rank
correlation with what happened):

```bash
# established players: fit on matches before each season, score that season
uv run python scripts/backtest_ratings.py -c ipl --seasons 2021-2026 [--half-life 2]
# IPL newcomers: rate from BBL/SA20/CPL/Blast/SMAT only (tier-penalised), score the first IPL season
uv run python scripts/backtest_newcomers.py --seasons 2014-2026
```

`fit(before=...)` fits on matches before a date; `fit(half_life=...)`
weights each season by `0.5 ** (age / half_life)` (off by default).

Results (2026-10, ADVI 12000 steps): for established IPL players the
ratings match raw career averages season-ahead (overall ~0.15 batters,
~0.07 bowlers, model and baseline within 0.04 on every axis); half-lives
of 1 / 2 / 4 years didn't help, so recency weighting stays off. For IPL
newcomers rated from other leagues, batters: model 0.18 vs raw 0.12
overall (0.20 vs 0.14 scoring, 0.34 vs 0.22 survival, n=96); bowlers:
model 0.20 vs raw 0.25 overall (n=110). Suggestive, not significant.

## Caveats

- One skill set per role today — no era / venue / format break-out
  yet. Easy to add as fixed effects in the linear predictor (`+ era[e]`).
- ADVI (the default) is mean-field; it matched NUTS closely on IPL (see
  above) but re-check with `--sampler nuts` after model changes.
- Players present only as bowler (or only as batter) get one role row;
  all-rounders get two rows in the output.

## Next

- Add venue + phase fixed effects.
- Use the resulting opponent strengths as the bridge that lifts
  grassroots (CricHeroes) ratings — this is the Opposition-Adjusted
  Rating (OAR) referenced in `docs/METRICS.md`.
