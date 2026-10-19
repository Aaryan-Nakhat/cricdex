# scout/ratings

Bayesian opponent- and context-adjusted skill ratings. The plain-English walkthrough, with a
worked example and the backtest results, is
[METHODOLOGY.md §4](../../../../docs/METHODOLOGY.md#4-bayesian-skill-ratings) and
[§8](../../../../docs/METHODOLOGY.md#8-does-it-predict-the-backtest).

## Model (`variant="v2"`, the default)

The data is every ball of a league grouped into **cells**: (batter i, bowler j, season s, phase
p, innings c, venue v), each with its legal balls, runs off the bat, bowler-credited dismissals
and dismissal trials. Players are Cricsheet registry ids resolved per match
(`common/sql.py::keyed_balls`), so two players who share a scorecard name are two players.

```
runs ~ NegBin(mean = exp(r0 + ctx_r + b_skill[i] − k_skill[j]) · balls,
              concentration = alpha · balls)
outs ~ Binomial(trials, sigmoid(w0 + ctx_w + bowl_strike[j] − bat_survive[i]))

ctx        = season[s] + phase[p] + innings[c] + venue[v]      (one set for runs, one for wickets)
season[s]  = season[s−1] + tau · z_s,  season[first] = 0          Gaussian random walk, tau ~ HalfNormal(0.1)
phase, innings: fixed effects (powerplay / first innings = 0), N(0, 1)
venue[v]   = sigma_v · z_v,  sigma_v ~ HalfNormal(0.2)

b_skill[i]     = mu_slot[slot(i)]  + sigma_b    · z     slot: top 1–3 / middle 4–5 / lower 6–7 / tail 8–11
bat_survive[i] = mus_slot[slot(i)] + sigma_surv · z     (median batting position in the data)
k_skill[j]     = mu_role[role(j)]  + sigma_k    · z     role: frontline (15+ deliveries per match) / part-time
bowl_strike[j] = mut_role[role(j)] + sigma_strike · z
mu_*[0] = 0, the other group means ~ N(0, 0.5); sigmas ~ HalfNormal(1)

extras_js ~ NegBin(mean = exp(x0 + x_season[s] − bowl_extras[j]) · deliveries_js,
                   concentration = alpha_x · deliveries_js)      wides + no-ball runs per (bowler, season)
bowl_extras[j] = sigma_x · z
```

All skills are higher = better and written **non-centred** (`mean + sigma · z`, z ~ N(0, 1)), so
the many thin-sample players don't trap the sampler in a funnel. `trials` is the legal balls plus
the rare bowler-credited dismissal off a wide (a stumping), so a wicket can never outnumber its
balls.

What each piece is for:

- **Context terms** — a 2009 strike rate and a 2026 one are judged against their own season's
  scoring level, a death bowler against death overs, an opener against the powerplay. The IPL fit
  puts 2026 runs per ball ~20% above 2008 (most of it since 2023); death overs ~50% above the
  powerplay, with about twice the wicket odds. `scripts/scout_rate.py` writes these to
  `data/metrics/scout_context_<collection>.json`.
- **`concentration = alpha · balls`** — a sum of n balls has variance ∝ n. With one `alpha` the
  variance grew with balls², so the high-volume cells (the best evidence) were down-weighted.
- **Role-level prior means** — a thin-sample tail-ender shrinks toward the tail's mean, not the
  average batter's (the IPL tail sits 0.50 below the top order on the log scale).
- **Extras** — a bowler's economy counts his wides and no-ball runs: his reported `skill` is
  `−log((B·e^(−k) + E·e^(−x)) / (B + E))`, B and E the base runs-off-the-bat and extras rates per
  legal ball, so it's his total runs conceded per ball against the average bowler's.

**Every matchup is fitted** — even a 1-ball meeting. The hierarchical prior already shrinks thin
samples, so nothing is dropped; `balls` / `runs` in the output are the player's true totals in the
collection. (`--min-balls` is only a speed knob for experiments.)

`variant="legacy"` is the earlier model (one intercept, one NegBin `alpha`, one population prior
per role, runs off the bat only), kept so the changes can be measured
(`scripts/backtest_ratings.py --compare legacy`).

## `value`

Each axis is centred on the role's average player and divided by the role's population sd —
`sqrt(sigma² + the spread of the group means)`, so between-slot differences count — then the two
are added, per posterior draw: `value = skill/σ_rate + second/σ_odds`. For bowlers σ_rate combines
the economy and extras spreads. 1.0 = one typical player-to-player spread better; 0 = the average
player of the role. `value_sd` is the posterior sd of that sum. The auction price curve
(`web_parity/pricing.py` ⇄ `site/src/lib/auction.ts`) is calibrated to these units.

## Fit

NumPyro (JAX). Two samplers wired behind `--sampler`:

- `advi` (default) — mean-field variational (`AutoNormal`, `--advi-steps`, default 12000), the
  posterior summarised from 500 draws taken 100 at a time. ~2–3 min for the IPL, most of it JAX
  compiling the model for the league's shapes; the compiled programs are dropped after each fit
  (`jax.clear_caches`) so a long backtest's memory stays flat. Re-checked against NUTS on the IPL
  after the context terms went in (2026-10-18; 2 chains × 500 + 500): for players with 100+ balls
  ADVI's sds are a median 98% of NUTS's for batters, 92–95% for bowlers, `value_sd` 101% / 96%, point
  estimates correlate ≥ 0.994, P(A>B) differs by a median 2–2.5 points (95th pct ~7). NUTS: r-hat
  1.02, min ESS 187, 0 divergences.
- `nuts` — full No-U-Turn HMC, `--nuts-chains 2` × `--nuts-draws 1000` + `--nuts-tune 500` by
  default; logs worst r-hat, smallest ESS and the divergence count (warns past r-hat 1.05).

```bash
make docker-scout-rate COLLECTION=ipl STEPS=12000          # advi, fast default
uv run python scripts/scout_rate.py --collection ipl --sampler nuts   # nuts, calibrated
uv run python scripts/scout_rate.py -c ipl --variant legacy  # the earlier model, for comparison
```

Output: `data/metrics/scout_ratings_<collection>.json` (one row per player-role) with columns
`cricsheet_id, unique_name, role, skill, skill_sd, balls, runs, value, value_sd` plus
`survival_skill(_sd), slot` (batters) or `strike_skill(_sd), extras_skill(_sd)` (bowlers); and
`scout_context_<collection>.json` (season / phase / innings levels, venue spread, slot means).

`fit(..., return_fit=True)` also returns a `FitResult` (posterior means and index maps) for
`heldout_loglik(result, edges)`: the plug-in log predictive density of a later season's cells, per
ball (runs as a Negative-Binomial, dismissals as a Binomial).

## Backtest

Two walk-forward scripts check the ratings out of sample:

```bash
# established players: fit on matches before each season, score that season (3 ADVI seeds),
# plus the held-out log-likelihood of every ball, against the legacy model
uv run python scripts/backtest_ratings.py -c ipl --seasons 2021-2026 --compare legacy
# IPL newcomers: rate from other leagues only, score the first IPL season
# (default: all 13 non-IPL auction-pool leagues; --leagues repeats the original five-league run)
uv run python scripts/backtest_newcomers.py --seasons 2014-2026 --jobs 4
uv run python scripts/backtest_newcomers.py --seasons 2014-2026 --leagues bbl,sa20,cpl,blast,indian_domestic_male
```

How it is scored: Spearman rank agreement with the season, seasons z-scored before pooling, 3 ADVI
seeds (42, 43, 44; the seed-averaged prediction is scored). The newcomer baseline gets the same league
adjustment as the model (each league's numbers relative to its average, minus the same tier discount);
a player's leagues are pooled by precision, not his best league; the gap is bootstrapped 2,000 times
with a one-sided p and a Holm adjustment over the six role × axis tests; 30- and 120-ball sensitivity
runs check selection on playing time. Fits are cached under `data/metrics/.backtest_cache/` keyed by
`bayesian.MODEL_VERSION`, so an older model's fits are never reused.

Established IPL players, 2021–26, model vs career average:

| | Overall | Scoring / economy | Survival / strike |
|---|---|---|---|
| Batters | 0.14 vs 0.15 | 0.13 vs 0.13 | 0.30 vs 0.34 |
| Bowlers | 0.12 vs 0.07 | 0.31 vs 0.30 | 0.05 vs 0.05 |

Held-out log-likelihood per ball, current vs legacy model: runs −0.6212 vs −0.6255, dismissals
−0.1467 vs −0.1480; the current model is better in every season on both.

IPL newcomers rated only from other leagues, 2014–26, overall axis, model vs league-adjusted baseline:

| Leagues | Batters | Bowlers |
|---|---|---|
| All 13 non-IPL pool leagues | 0.22 vs 0.10 (n=103; ahead in 96%, p=0.042, Holm 0.25) | 0.18 vs 0.24 (n=132; ahead in 20%) |
| Original 5 (BBL, SA20, CPL, Blast, SMAT) | 0.25 vs 0.09 (n=96; ahead in 98%, p=0.025, Holm 0.15) | 0.18 vs 0.22 (n=110; ahead in 27%) |

No scoring, survival, economy or strike test comes close after the Holm correction (the best is 0.93).
Read: the old "survival edge for newcomer batters" was mostly the league discount and doesn't survive
the fair baseline; the newcomer-batter overall edge is a lean, not proof; bowlers show no edge. Full
tables, the sensitivity runs and the caveats: METHODOLOGY §8. Outputs:
`data/metrics/ratings_backtest_ipl.json`, `newcomer_backtest_ipl.json`,
`newcomer_backtest_ipl_published.json`.

## Caveats

- One skill set per role per league for a whole career: context is adjusted for, but a player's
  own form isn't allowed to drift.
- ADVI (the default) is mean-field; re-check with `--sampler nuts` after model changes.
- Players present only as bowler (or only as batter) get one role row; all-rounders get two rows.
- Each league is fitted alone; cross-league comparison rests on the registry's tier discounts.

## Next

- A joint multi-league fit with league effects (replacing the hand-set tier discounts).
- A runs-currency value (runs per ball minus a phase-dependent wicket cost).
