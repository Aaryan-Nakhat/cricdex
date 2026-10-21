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

## `value` — runs per 100 balls (`runs_value.py`)

`value` puts both axes in one currency, **runs**: runs per 100 balls above the league's average
ball, with a wicket priced at the run cost of losing it where the player actually plays.

**Wicket cost.** From every first innings of a full-length, non-rain-affected match in the window
(the chase is shaped by its target, so it isn't used), per state (over bucket o = 0..19 of the
scheduled innings, wickets down w = 0..9): legal balls, all runs (extras included) and wickets (any
dismissal except retired hurt / not out). Smoothed as `A_o · C_phase(o),w` (over level × a
wickets-down factor per phase, each phase's factor shrunk to the all-overs one with a Poisson–gamma
pseudo-count of ~250 balls for runs and ~300 for wickets) for both runs and wickets per ball. Then

```
V(b, w) = r(b, w) + p(b, w) · V(b+1, w+1) + (1 − p(b, w)) · V(b+1, w)     V(end, ·) = V(·, 10) = 0
λ(b, w) = V(b+1, w) − V(b+1, w+1)          run cost of a wicket on ball b with w down (≥ 0)
```

over the 120 balls of an innings (each step is `balls / 120` of a ball for The Hundred's 100). The
IPL table: par first-innings total 168; λ ≈ 13–14 in the powerplay with 0–3 down, 7–8 in the middle
overs, 2–3 at the death, more with more wickets down (a wicket costs more when the tail is next).
A chase uses the first-innings λ of the same state (an approximation). Fewer than 20 qualifying
first innings → a default table (13 / 9 / 3.5 by phase, the IPL's).

**Per player.** His balls by phase × innings (`π`, six cells) and, per cell, his wicket cost: the
average λ over the states he actually played in, each ball weighted by the chance of a wicket in that
state. League baselines per cell from the same window: runs off the bat per legal ball `r`, runs a
bowler is charged (bat + wides + no-balls) per legal ball `R`, bowler-credited dismissals per trial
`q`. Then per posterior draw

```
batter: 100 · Σ_c π_c [ r_c (m − 1)  −  λ_c (σ(logit q_c − Δs) − q_c) ]
bowler: 100 · Σ_c π_c [ R_c (1 − m)  +  λ_c (σ(logit q_c + Δt) − q_c) ]

m  = e^skill / (ball-weighted mean of e^skill)   his run-rate multiplier vs the average ball
                                                 (bowler: from e^−economy, extras included)
Δs = survival − its ball-weighted mean;  Δt = strike − its ball-weighted mean
```

and each part is re-centred so the league's balls average 0. Output columns: `value` (= `value_rate`
+ `value_wkts`), `value_sd` (posterior sd, from the draws), the two parts (posterior means) and
`wicket_cost` (his ball-weighted λ, runs). `scout_context_<collection>.json` carries the wicket-cost
table (`runs_value`: par, λ by phase × wickets down, λ by over at 2 down, the baselines).

Baselines and λ are pooled over every season in the window, so a 2009 player and a 2026 one are
converted at the same rate; their skills are already judged against their own season. To read a
value per 4-over spell multiply by 0.24; per innings, by his balls per innings / 100.

*IPL, current fit:* KL Rahul +19.4 (scoring +8.9, staying in +10.5 at a wicket cost of 9.6), Kohli
+13.6 (+4.6, +9.0), Dhoni +1.1 (−6.8, +7.9 at 4.7: he rarely gets out, but at the death that is
worth little and he scores below the death-overs rate), Russell +24.5 (+24.7, −0.2), Narine as a
batter +0.1 (+31.8, −31.8 as an opener who gets out often); bowlers Narine +24.0, Bumrah +23.2,
Rashid +20.3, Chahal +10.1 (+6.6 economy, +3.5 wickets).

Before October 2026 `value` was each axis divided by its population sd, then added (equal weight):
a +1 sd survivor counted exactly as much as a +1 sd scorer, which made Dhoni the best active IPL
batter. The auction price curve (`web_parity/pricing.py` ⇄ `site/src/lib/auction.ts`), the tier
discounts and the IPL-relevance penalty were converted with one factor (13.3) and the curve re-fitted
to the same pool median and 10 cr+ count; prices are set on the cautious estimate `value − 0.5 ×
value_sd`; see [AUCTION_MATH.md](../../../../docs/AUCTION_MATH.md).

## Fit

NumPyro (JAX). Two samplers wired behind `--sampler`:

- `advi` (default) — mean-field variational (`AutoNormal`, `--advi-steps`, default 12000), the
  posterior summarised from 500 draws taken 100 at a time. ~2–3 min for the IPL, most of it JAX
  compiling the model for the league's shapes; the compiled programs are dropped after each fit
  (`jax.clear_caches`) so a long backtest's memory stays flat. Re-checked against NUTS on the IPL
  after the context terms went in (2026-10-18; 2 chains × 500 + 500): for players with 100+ balls
  ADVI's sds are a median 98% of NUTS's for batters, 92–95% for bowlers, the earlier sd-sum `value_sd` 101% / 96%, point
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
`cricsheet_id, unique_name, role, skill, skill_sd, balls, runs, value, value_sd, value_rate,
value_wkts, wicket_cost` plus `survival_skill(_sd), slot` (batters) or `strike_skill(_sd),
extras_skill(_sd)` (bowlers); and `scout_context_<collection>.json` (season / phase / innings levels,
venue spread, slot means, the wicket-cost table).

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

| | Overall (runs) | Overall (z-sum) | Scoring / economy | Survival / strike |
|---|---|---|---|---|
| Batters | 0.19 vs 0.15 | 0.20 vs 0.15 | 0.13 vs 0.13 | 0.30 vs 0.34 |
| Bowlers | 0.15 vs 0.11 | 0.10 vs 0.07 | 0.31 vs 0.30 | 0.05 vs 0.05 |

"Overall (runs)" scores the season in runs per 100 balls above average with wickets priced at the
player's wicket cost (`runs_value.observed_value`), the baseline the same from raw career totals;
"overall (z-sum)" is the earlier yardstick (with the earlier sd-sum value it was 0.14 vs 0.15 and
0.12 vs 0.07).

Held-out log-likelihood per ball, current vs legacy model: runs −0.6212 vs −0.6255, dismissals
−0.1467 vs −0.1480; the current model is better in every season on both.

IPL newcomers rated only from other leagues, 2014–26, overall in runs, model vs league-adjusted baseline:

| Leagues | Batters | Bowlers |
|---|---|---|
| All 13 non-IPL pool leagues | 0.08 vs 0.10 (n=103; ahead in 38%) | 0.22 vs 0.26 (n=132; ahead in 32%) |
| Original 5 (BBL, SA20, CPL, Blast, SMAT) | 0.11 vs 0.06 (n=96; ahead in 78%, p=0.22) | 0.22 vs 0.25 (n=110; ahead in 27%) |

Every Holm-adjusted p is 1.0 (single axes, all 13 leagues: batter scoring 0.13 vs 0.19, survival
0.29 vs 0.27; bowler economy 0.25 vs 0.26, strike 0.08 vs 0.07). Read: the runs value beats career
averages for established IPL players; for newcomers rated from other leagues it is no better than the
players' own league-adjusted numbers (a lean for batters with the original five leagues only, not
significant). The earlier newcomer-batter edges, first from an unfair baseline and then from the old
sd-sum value, don't survive. Full tables, the sensitivity runs and the caveats: METHODOLOGY §8. Outputs:
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
- A chase-aware wicket cost (target and resources left), and per-player form drift.
