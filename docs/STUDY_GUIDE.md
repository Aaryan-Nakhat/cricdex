# CricDex — Study Guide

A deep-dive technical reference covering every algorithm, design
choice, and data pipeline in this repository. Written so a reader
who hasn't touched Bayesian inference can still follow along and
present the work to others.

Sections are roughly ordered shallow → deep. If you want to skim,
the **Overview** and **Architecture** sections give the high-level
picture; the algorithm chapters (5–9) are the meat.

---

## 0. Table of Contents

1. Project overview — what CricDex is, what problem it solves
2. Architecture — module layout, data flow, how pieces fit
3. Data layer — Cricsheet, People Register, Wikidata
4. The 10 novel cricket metrics — formula + intuition each
5. Bayesian scout ratings — hierarchical NegBin + dismissal Binomial, NumPyro, ADVI vs NUTS
6. NGI / Net Game Impact — XGBoost win-prob + isotonic calibration + ΔWP
7. Scout — cross-competition look-alikes + cosine style twins
8. Auction room — real-rules Monte-Carlo, shared with the web via web_parity
9. Wikidata bridge — P2697 statsguru ID + Entity API workaround
10. Surfaces — web (canonical) + CLI / TUI / Streamlit / API at parity
11. Deployment + CI/CD
12. vNext / TODOs — what didn't make v1 and why

---

## 1. Project overview

**CricDex** is an open cricket intelligence platform that sits on top
of publicly available cricket data (primarily
[Cricsheet's](https://cricsheet.org/) ball-by-ball JSON dumps) and
emits four things — all from Cricsheet ball-by-ball, no live feeds or
scrapes:

1. **Novel sabermetrics** — context-adjusted player metrics that
   scorecards miss (NGI, Pressure Runs, Crease Longevity, etc).
2. **Bayesian player ratings** — dismissal-aware opponent-adjusted
   skill scores fit with NumPyro/JAX (scoring + survival for batters,
   economy + strike for bowlers) so a player who only ever faced weak
   attacks doesn't outrank one who's faced everyone.
3. **Scout** — cross-competition look-alikes across six pools (IPL,
   SMAT, BBL, SA20, CPL, T20 Blast) ranked by within-tier Bayesian
   skill-standing z-score, plus cosine style-twins on the Player
   Profile. File-driven (DuckDB + exported JSON; no graph database).
4. **Auction room** — a real-rules IPL auction Monte-Carlo over a
   cross-collection pool with editable retentions, overseas cap,
   second-price clearing and a two-phase fill.

The web app is the **canonical surface**; a single `cricdex` console
script, a Streamlit dashboard, and a Textual TUI mirror the same
analytical pages. Scout and the Auction room run identical logic on
every surface via `cricdex.web_parity` (a Python port of the web's
TypeScript, locked by `test_scripts/test_web_parity.py`), so behaviour
stays in lockstep.

**Why open?** Existing cricket platforms (Cricbuzz, CricViz, ESPN)
hide methodology behind paywalls. CricDex publishes the formulas, the
Cricsheet-only inputs, a live static demo
(aaryan-nakhat.github.io/cricdex), and the full stack reproducible via
`make docker-up`.

**Why the obsession with context-adjusted metrics?** A 25-ball 40 in
a slack chase scores the same as a 25-ball 40 chasing 12 an over.
Standard scorecards are context-blind. CricDex's metrics put context
back in (venue median, phase, partnership state, opponent skill).

---

## 2. Architecture

Top-level layout:

```
src/cricdex/
├── api/                   FastAPI REST surface + /docs
├── auction/               real-rules Monte-Carlo pool builder
├── cli/                   typer console script (one file per command group)
├── comparator/            Side-by-side metric table + skill head-to-head
├── config.py              Pydantic settings + DATA_DIR resolution
├── dashboard/             Streamlit pages (mirror the web + TUI)
├── llm/                   Gemini wrapper (work-proxy URL or personal key)
├── metrics/               The 10 novel metrics + dismissal_fingerprint
├── people/                Cricsheet People Register loader
├── profiles/              Single-player JSON assembler (used by all surfaces)
├── records/               9 record SQL queries + on-this-day digest
├── scout/
│   ├── ingest/            Cricsheet → DuckDB; Wikidata enrichment
│   ├── ratings/           NumPyro hierarchical Bayes (dismissal-aware)
│   └── search/            Cosine style-twin
├── web_parity/            Python port of the web's TS auction + scout
└── venues/                Per-venue conditions (innings totals, phase rates)
```

Everything is Cricsheet-derived. There are no live-feed, scrape, or
non-Cricsheet-source modules — those were intentionally removed — and
the stack is file-driven (DuckDB + exported JSON; no vector or graph
database).

**Data flow**:

```
Cricsheet JSON ──> scripts/ingest_cricsheet.py ──> DuckDB (~600 MB)
                                                       │
        ┌─────────────────────────┬────────────────────┼──────────────────┐
        ▼                         ▼                    ▼                  ▼
   metrics/*.py            scout/ratings              records/         venues/
   (10 metrics JSON)       (Bayes JSON)               (on-this-day)    (innings/phase)
        │                         │
        ▼                         ▼
   profiles/builder.py     scripts/export_site.py ──> site/public/data/*.json
        │                         (auction pool + retentions + scout index)
        ▼                                  │
              ┌────────────────────────────┘
              ▼
   web (canonical) + CLI / TUI / Streamlit / FastAPI
   (scout + auction run web_parity over the same exported JSON)

People Register (cricsheet) ──> cross-source ID bridge ──> Wikidata enrichment
                                                              (DOB, photo, socials)
```

Single canonical storage root: `~/.cricdex/data/` (or
`$CRICDEX_HOME/data/`). Every surface reads from there directly, so
running `cricdex data ingest metrics --force` then opening the TUI
shows fresh JSON without restarting.

---

## 3. Data layer

### 3.1 Cricsheet

[Cricsheet](https://cricsheet.org/) is a community-maintained archive
of ball-by-ball data for ~all professional cricket since 2002. Each
match is a JSON file with `info` block (teams, venue, dates,
outcome) plus an `innings` list where every ball is an object with
`runs_total/batter/extras`, `wicket` info, and `phases` cues.

`scout/ingest/cricsheet.py` downloads a *collection* (e.g.
`ipl` = 1097 matches, ~600 MB) as a single zip, expands each match
JSON, flattens every ball into a polars row, writes one Parquet
file per collection, then materialises into a DuckDB table named
`balls_<collection>` so SQL queries run in single-digit seconds.

DuckDB is the only OLAP engine we use. It's a column-store with
zero-config that beats Postgres + Pandas for analytic workloads on
files like this. No server, just `duckdb.connect(path)`.

### 3.2 People Register

Cricsheet ships a `people.csv` that resolves names across sources —
`unique_name` (the canonical Cricsheet handle), `identifier`
(Cricsheet's own UUID short-hash, `cricsheet_id`), `key_cricinfo`
(ESPNcricinfo player ID, **same as the Statsguru ID we use to bridge
to Wikidata**), `key_cricbuzz`, `key_cricheroes`, `key_bigbash`.
This is the rosetta stone for cross-source joins.

Two manual overrides ship because Cricsheet uses initials-style
names that collide: `Rashid Khan` → Afghanistan (not Nepal),
`Mohsin Khan` → Pakistan (not India).

### 3.3 Wikidata enrichment

`cricdex data ingest wikidata` enriches each cricketer with DOB,
country / birthplace Q-ids, profile photo URL, Twitter / Instagram
handles, and ESPNcricinfo / Cricbuzz IDs. See §9 for the technical
bridge (the SPARQL endpoint blocks GCP IPs so we use the action API
with a P2697-statsguru-ID search instead). 289 / 300 active players
are enriched today.

---

## 4. The 10 novel cricket metrics

Each metric outputs a polars DataFrame and writes to
`data/metrics/<slug>_<collection>.json`. The Streamlit Leaderboards
page auto-discovers them; the CLI `cricdex leaderboard <slug>` reads
the same files.

Common scaffolding: every metric SQL excludes wides from the legal
ball count, treats `runs_batter` (the runs the *batter* gets credit
for, after subtracting byes/leg-byes) as the headline stat, and
applies a minimum sample-size filter so an outlier 5-ball innings
doesn't crown someone King of T20.

### 4.1 Pressure Runs — `metrics/batter.py:pressure_runs`

**Intuition.** Runs scored on chase deliveries where the required run
rate is meaningfully harder than the venue historically demands at
the same phase.

**Math.** For every 2nd-innings ball in T20 / ODI:

```
required_rpb = (1st_innings_total + 1 − runs_before_ball) / balls_remaining
```

For each `(venue, phase)` compute `median(required_rpb)` across
every chase ball. Then flag a ball as "under pressure" if
`required_rpb > 1.5 × median_required_rpb(venue, phase)`.

**Why 1.5× venue median?** Different grounds demand wildly different
chase rates (Bangalore vs Lord's). The venue median normalises that
out — "pressure" means hard *for that ground*. The 1.5× threshold is
a deliberately loose cut: tighter (e.g. 2×) and you get only the
slog-overs death scenarios; looser and the metric loses signal.

**Filters.** `min_balls_faced=20`; T20 / ODI only; innings 2 only;
`runs_needed > 0` (no ball already-won situations).

**Output columns:** `pressure_balls`, `pressure_runs`,
`pressure_sr_per_100_balls`, `pct_balls_under_pressure`.

### 4.2 Intent Curve — `metrics/batter.py:intent_curve`

**Intuition.** How a batter's strike rate changes as their innings
progresses. Slow starters who heat up look very different to
immediate aggressors.

**Math.** For every `(batter, innings)` compute `balls_faced_to_date`
per ball. Bucket into `0-5 / 6-10 / 11-20 / 21-30 / 31-50 / 51+`.
Per `(batter, bucket)` emit `SR = 100 × runs / legal_balls`.

**Reading.** Rising curve = grower. Flat-high = aggressor. Flat-mid =
grinder. Falling = tires. The shape is the metric — there's no
scalar headline.

**Filter.** `min_balls_in_bucket=200` so a single freak innings
doesn't dominate a bucket.

### 4.3 Dot-Ball Recovery — `metrics/batter.py:dot_ball_recovery`

**Intuition.** A batter's ability to re-engage after a dot ball.
Mental-reset proxy.

**Math.** For every dot ball, sum runs scored in the *next 6 balls
faced* (same innings, same batter). Aggregate per batter:

```
runs_per_6_after_dot = 6 × Σ runs / Σ following_balls
```

A value of 9 means the batter averages 9 runs over the next 6 balls
after eating a dot — strong re-engagement. A value of 4 means the
dot tends to spread.

**Filter.** `min_dot_balls=100`.

### 4.4 Counter-Attack Coefficient — `metrics/batter.py:counter_attack_coefficient`

**Intuition.** SR in the 12 balls right after a *partner* wicket
falls. Who absorbs collapse pressure vs who freezes.

**Math.** For each wicket, mark the next 12 balls in the same
innings. Attribute runs to the batter *facing* — **excluding** the
dismissed striker (so we measure the survivor, not the new arrival
who's still gauging conditions). Aggregate:

```
counter_attack_sr = 100 × Σ runs / Σ legal_balls
```

**Filter.** `min_partner_wickets=20`.

### 4.5 Boundary Dependency — `metrics/batter.py:boundary_dependency`

**Intuition.** What fraction of career runs come from 4s / 6s vs
running between wickets.

**Math.** `bdr_pct = 100 × Σ runs_from_4_or_6 / Σ runs`.

**Reading.** High BDR = boundary-or-bust profile (vulnerable when
the boundary isn't there — small grounds shrink, defensive lines).
Low BDR = strike-rotator. Neither is "better"; the metric
distinguishes *style*.

**Filter.** `min_runs=200`.

### 4.6 Crease Longevity — `metrics/batter.py:crease_longevity`

**Intuition.** How much longer a batter survives at the crease
versus the cohort average.

**Math.** `avg_balls_per_dismissal = total_balls / dismissals` per
batter. Cohort average = mean of that across batters with
`dismissals >= 5`. `dilation_index = avg_balls_per_dismissal /
cohort_avg`.

A dilation index of 1.5 means this batter faces 50% more balls per
dismissal than the cohort. Anchor batters score high here.

**Filter.** `min_dismissals=10`.

### 4.7 Slow-Start Cost — `metrics/batter.py:slow_start_cost`

**Intuition.** The cost (in SR points) of "setting up" an innings —
how much slower a batter scores in the first 20 balls vs their
career.

**Math.** `slow_start_cost = career_sr − setting_sr` where `setting_sr`
covers balls where `balls_faced_to_date <= 20`.

A slow-start cost of 30 means the batter scores 30 SR points slower in
the first 20 balls than their career average — a heavy starter cost.
A negative slow-start cost means they start *faster* than their career
norm (rare; opener territory).

**Filter.** `min_career_balls=200`, `min_setting_balls=50`.

### 4.8 Pressure Conversion — `metrics/bowler.py:pressure_conversion`

**Intuition.** A bowler's wicket rate on the delivery immediately
after they've built a streak of 4+ consecutive dots in the same
over.

**Math.** Walk every over delivered by each bowler. Track
`streak_len` of consecutive dot balls. When `streak_len ≥ 4`, look
at the next delivery in the same over and check `is_wicket`.

```
wicket_rate_pct = 100 × Σ wickets_after_streak / Σ post_streak_balls
```

**Why same over?** The streak resets across overs because the field
+ batter context changes. Within an over the bowler is genuinely
sustaining pressure.

**Reading.** Distinct from raw economy — a tight 4-dot bowler who
never converts pressure into a wicket scores low here even though
their economy looks great.

**Filter.** `min_pressure_balls` is adaptive — `max(5, round(0.5 ×
p75(pressure_balls)))`, so small corpora (689-match SMAT) don't
filter to zero rows; manual override defaults to 30.

### 4.9 Wicket Quality — `metrics/bowler_wicket_quality.py`

**Intuition.** Not every wicket is equal. A Kohli wicket weighs more
than a No.11's.

**Math.** Load Bayes skill scores (see §5). For every legitimate
dismissal, look up the dismissed batter's Bayes skill. Aggregate:

```
wicket_quality_bowler = mean(dismissed_batter_bayes_skill)
```

A bowler with `wq=+0.15` is taking wickets of clearly above-average
batters; `wq=-0.15` is feasting on tail-enders.

**Filter.** `min_wickets=15`. Excludes run-out, retired-hurt,
retired-out, obstructing-the-field dismissals because they don't
test the bowler's craft.

**Why it needs Bayes ratings.** Raw average won't do — a tail-ender
who scored 35 once doesn't have a representative number.

### 4.10 NGI / Net Game Impact — `metrics/ngi.py` (the flagship)

See §6 for the full deep-dive — it's complex enough to be its own
chapter.

---

## 5. Bayesian scout ratings — `scout/ratings/bayesian.py`

This is the heart of the player-quality estimate. Pure statistics:
no neural network, no gradient descent. You give the model 1M+ rows
of `(batter, bowler, balls, runs)` and it returns a posterior
distribution over each player's *skill* parameter.

### 5.1 What is Bayesian inference, exactly?

In plain English: instead of asking "what's the *one number* that
best fits the data?" (frequentist), you ask "given the data, what's
the *distribution* of plausible numbers?" (Bayesian).

You start with a **prior** — your belief before seeing the data
("most cricketers are average; skills cluster around zero with
some spread"). You combine it with the **likelihood** — how likely
the data is given a particular skill value. The output is the
**posterior** — your updated belief after seeing the data.

For a player with a lot of data, the posterior is tight (we know
their skill well). For a player with 5 balls of evidence, the
posterior is wide (could be anywhere — better trust the prior). This
*shrinkage toward zero* is exactly what we want for cricket: a guy
who hit 35 off 10 once doesn't deserve a 5σ rating.

### 5.2 The model

```
runs_ij ~ NegativeBinomial(mu_ij, alpha)
mu_ij   = exp(intercept + b_skill[i] − k_skill[j]) × balls_ij
b_skill[i] ~ Normal(0, sigma_b)
k_skill[j] ~ Normal(0, sigma_k)
sigma_b, sigma_k ~ HalfNormal(1)
intercept ~ Normal(0, 3)
alpha ~ HalfNormal(5)
```

The data is one row per `(batter i, bowler j)` edge with `balls_ij`
balls and `runs_ij` runs. The mean run rate on that edge is
`exp(intercept + batter_skill − bowler_skill)`, multiplied by
`balls_ij` to get expected total runs.

**Why log-link `exp(...)`?** Skills are additive on the log scale —
a batter with `b_skill = +0.5` scores `exp(0.5) ≈ 1.65×` more runs
per ball than the league average. Bowlers subtract — a bowler with
`k_skill = +0.5` saves `exp(0.5)` of those runs. The two are on a
common natural-log scale of run rate.

**Why Negative-Binomial, not Poisson?** Cricket scoring has
over-dispersion — variance > mean. Sixes and dots dominate; a
4-runs-per-ball innings followed by 3 dots is wildly unlike a
Poisson(1.2) draw. NegBin's extra `alpha` (overdispersion) parameter
absorbs that.

**Why hierarchical priors `Normal(0, sigma_b)` with `sigma_b`
estimated**? This is *partial pooling*: the model learns the spread
of skills across players from the data, rather than fixing it
arbitrarily. Newcomers borrow strength from the cohort — they're
shrunk toward the population mean (0) until they accumulate enough
balls to overcome the prior.

**Opponent bridging — the magic.** Because `mu_ij` depends on both
`b_skill[i]` *and* `k_skill[j]`, a batter who faced both a marquee
bowler (`k_skill=+0.3`) and a part-timer (`k_skill=-0.2`) gets his
skill estimate informed by *both* matchups. He doesn't get punished
for facing a hard attack the way raw average would.

### 5.3 NumPyro / JAX — why this stack

`numpyro` is a probabilistic programming language that sits on top of
JAX (Google's autodiff + XLA-compiled numerical computing). It was
chosen over the older PyMC for a 10-50× speed-up on this exact
class of hierarchical GLM. The fit on the IPL collection (~6k
batters × bowlers, 1M+ edges) runs in ~30 s on CPU.

### 5.4 ADVI vs NUTS

Two inference engines are exposed. Both end up with samples from the
posterior, but they get there differently:

**ADVI (Automatic Differentiation Variational Inference).** Fits a
*surrogate* normal distribution to the posterior by minimising
KL-divergence via gradient descent. Fast (~10 s for IPL). The
output `skill_sd` is *under-estimated* compared to truth because
the variational family is constrained to mean-field normal (no
correlations between parameters). Default for daily updates.

```python
guide = AutoNormal(model)
svi = SVI(model, guide, Adam(0.01), Trace_ELBO())
state = svi.init(...)
for _ in range(12000):
    state, loss = svi.update(state, ...)
```

**NUTS (No-U-Turn Sampler).** Runs Hamiltonian Monte Carlo with
adaptive trajectory length — the gold standard for posterior
sampling. Output is calibrated (the SDs match truth). Slow (~5 min
on IPL with 2 chains × 1000 draws + 500 warmup).

```python
kernel = NUTS(model, target_accept_prob=0.9)
mcmc = MCMC(kernel, num_warmup=500, num_samples=1000, num_chains=2)
mcmc.run(rng_key, bi=bi, ki=ki, balls=balls, runs=runs, ...)
```

We default to ADVI for the daily fit and surface NUTS when
publishing leaderboards — the skill *ranking* is identical to 3
decimals between the two engines; only the uncertainty widths differ.

### 5.5 Key snippet — the model definition

```python
def _model(bi, ki, balls, runs, n_batters, n_bowlers):
    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    with numpyro.plate("batters", n_batters):
        b_skill = numpyro.sample("b_skill", dist.Normal(0.0, sigma_b))
    with numpyro.plate("bowlers", n_bowlers):
        k_skill = numpyro.sample("k_skill", dist.Normal(0.0, sigma_k))
    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha     = numpyro.sample("alpha",     dist.HalfNormal(5.0))
    log_mu = intercept + b_skill[bi] - k_skill[ki]
    mu = jnp.exp(log_mu) * balls
    numpyro.sample("y", dist.NegativeBinomial2(mean=mu, concentration=alpha), obs=runs)
```

The `plate` context tells NumPyro the parameters are vectorised
(one per batter/bowler) — under the hood it generates the JAX
shape semantics correctly.

### 5.6 Output

With the dismissal-aware joint model (§5.7) each batter row also
carries `survival_skill`, each bowler row `strike_skill`, plus a
composite `value` (the two axes summed):

```json
[
  {"cricsheet_id": "ba607b88", "name": "V Kohli", "role": "batter",
   "skill": 0.051, "skill_sd": 0.023,
   "survival_skill": 0.212, "survival_skill_sd": 0.060,
   "value": 0.263, "balls": 6499},
  {"cricsheet_id": "ba607b88", "name": "V Kohli", "role": "bowler",
   "skill": -0.037, "skill_sd": 0.062,
   "strike_skill": -0.190, "strike_skill_sd": 0.174,
   "value": -0.227, "balls": 172},
  ...
]
```

Two rows per cross-role player (Kohli has both because he bowls
occasionally). The `*_sd` columns are standard errors — pair them
with `balls` to read confidence: a tight σ on thousands of balls is
rock-solid; a wide σ on a handful is barely better than the prior.
(`dismissal_aware=False` falls back to the legacy two-column
`skill` + `skill_sd` output.)

### 5.7 Dismissal-aware extension (the joint model)

The runs-only model above has a blind spot: it scores **scoring
rate**, not **getting out**. A slogger who smashes 1.8 runs/ball but
is dismissed every 8 balls looks "high skill" — clearly wrong for a
complete batting rating.

The fix is a **second, coupled likelihood**. Alongside the runs
Negative-Binomial we add a per-ball **dismissal Binomial** on the same
(batter, bowler) edges:

```
# scoring sub-model (as before)
runs_ij ~ NegBin(exp(r_int + bat_score[i] − bowl_econ[j]) × balls, alpha)

# dismissal sub-model (new)
outs_ij ~ Binomial(balls_ij,
                   sigmoid(w_int + bowl_strike[j] − bat_survive[i]))
```

Now each player carries up to **four** latent skills (all higher =
better):

| Skill | Axis | Meaning |
|---|---|---|
| `bat_score` | batting | scoring rate (existing) |
| `bat_survive` | batting | dismissal resistance (NEW) |
| `bowl_econ` | bowling | run suppression (existing) |
| `bowl_strike` | bowling | wicket-taking rate (NEW) |

`outs_ij` = bowler-credited dismissals of batter i by bowler j
(caught / bowled / lbw / c&b / stumped / hit-wicket — excludes run-out
& retired). The two sub-models share the edge structure but have
independent latents, so a single ADVI/NUTS run fits all four at once.

**Why a Binomial?** Each ball is a Bernoulli "out / not out"; summed
over the edge's balls it's Binomial. The logit (`sigmoid`) keeps the
probability in [0, 1]. Baseline dismissal rate in T20 ≈ 1/25, so the
intercept prior is `Normal(−3, 2)` (log-odds of ~1/25).

**What it fixes — validated on IPL:**

| Player | score | survive | complete value |
|---|---|---|---|
| AB de Villiers | +0.18 | +0.17 | **+3.56** (top) |
| V Kohli | +0.05 | +0.21 | +2.93 (anchor) |
| KA Pollard | +0.12 | **−0.14** | **−0.57** (slogger!) |

Pollard's high scoring rate no longer wins — his poor survival drags
his **complete value** negative, while De Villiers (elite on both)
tops the table. Same split for bowlers distinguishes wicket-takers
(Chahal: weak economy, top strike) from control bowlers (Ashwin:
elite economy, near-zero strike) — the old single-skill model
couldn't tell them apart.

**Complete value** = raw sum of the two axes (both log-scale, both
higher = better, empirically comparable magnitude). This is what the
head-to-head (§ surfaces) and the leaderboard's `value` column rank
on. Output JSON gains `survival_skill` / `strike_skill` (+ SDs) and
`value` per row; legacy readers that only want `skill` keep working.

---

## 6. NGI / Net Game Impact — `metrics/ngi.py`

The flagship metric. WPA-style. This is the one that gets the most
attention because it gives a single number to attribute to every
ball: how much did *this* player move the needle on win probability?

### 6.1 The Win Probability concept

WP (Win Probability) is the probability the batting team wins *given
the current game state*. WPA (Win Probability Added) is the change
in WP from one ball to the next. Borrowed from baseball
(FanGraphs / Tom Tango). A 95% → 99% boundary scores `+0.04`. A
50% → 30% wicket scores `-0.20`.

NGI takes per-ball WPA and credits it to the batter (positive) and
bowler (negative, with sign flip). Summed across a career and
normalised per match.

### 6.2 The WP model

The model is a binary XGBoost classifier — given the game state at
ball `t`, predict `P(batting team wins eventually)`.

**Features (10).** All numeric, all derivable from ball-by-ball:
- `innings_idx` (0 or 1)
- `balls_remaining` in the innings
- `wickets_left`
- `score_before` this ball
- `target` (1st innings + 1; NaN in 1st innings)
- `runs_needed` (target − score; NaN in 1st innings)
- `required_rr` (runs/over needed to chase)
- `current_rr` (runs/over the team has been scoring)
- `innings1_total` (only meaningful in 2nd innings)
- `current_rr_minus_venue` — how far above/below the venue's
  historical median current RR

**Holdout split — match-id, not ball-id.** Critical methodological
choice. If you split balls randomly, the model sees balls 1-99 of a
match in training and ball 100 in validation — trivial leakage. We
split *matches* 85/15 so the val set is held-out games entirely.

**Hyperparameters.**

```python
xgb.XGBClassifier(
    n_estimators=600, max_depth=6, learning_rate=0.05,
    subsample=0.9, colsample_bytree=0.9,
    early_stopping_rounds=30, eval_metric="logloss",
    tree_method="hist",
)
```

XGBoost is the right tool: tree-based ensembles handle the
non-linear interactions (`balls_remaining × wickets_left ×
required_rr` jointly decide WP in ways linear models can't capture)
without needing manual feature engineering.

### 6.3 Isotonic calibration

The raw XGBoost probabilities are *good rankings* but *bad
probabilities* — when the model says "70% chance to win" the batting
team actually wins 75% of the time (or whatever the bias is).
Isotonic regression fits a monotonic step function from raw → true
probability:

```python
val_raw = base.predict_proba(X[va_mask])[:, 1]
calibrator = IsotonicRegression(out_of_bounds="clip")
calibrator.fit(val_raw, y[va_mask])
```

After calibration the reliability is perfect: bin by predicted
probability, the actual win rate in that bin equals the predicted
midpoint. This matters because we're going to *subtract* WP values
to get ΔWP — if the scale is non-linear in true probability, the
subtractions become meaningless.

### 6.4 ΔWP attribution

For each ball:
```
delta_wp = wp_after − wp_before
```

Terminal correction: at the last ball of an innings,
`wp_after = 1.0` if batting team won, `0.0` if not. (Otherwise the
model's last predicted WP isn't exactly 0/1 and you get drift.)

Per-ball credit:
- batter gets `+delta_wp` for the strike ball
- bowler gets `-delta_wp` for the same ball

### 6.5 Career aggregation

```python
batter_match = df.group_by(["match_id","batter"]) \
    .agg(pl.col("delta_wp").sum().alias("ngi_batting"))
bowler_match = df.group_by(["match_id","bowler"]) \
    .agg((-pl.col("delta_wp")).sum().alias("ngi_bowling"))
career = batter_match.join(bowler_match, on="match_id", how="full") \
    .group_by("player").agg([
        pl.col("ngi_batting").sum(),
        pl.col("ngi_bowling").sum(),
        pl.col("match_id").n_unique().alias("matches"),
    ]).with_columns(
        ngi_total = pl.col("ngi_batting") + pl.col("ngi_bowling"),
        ngi_per_match = (pl.col("ngi_batting") + pl.col("ngi_bowling"))
                        / pl.col("matches"),
    )
```

`ngi_per_match` is the headline — a value of `+0.05` means the
player adds an average of 5 percentage points to their team's win
probability per match they play.

---

## 7. Scout — cross-competition look-alikes

Scout answers "who plays like X, that I could realistically sign?"
across six competition pools (IPL, SMAT, BBL, SA20, CPL, T20 Blast).
It is **file-driven** — DuckDB + an exported JSON index, no graph
database — and shares one implementation with the web via
`cricdex.web_parity` (a Python port of `site/src/pages/Scout.tsx`,
locked by `test_scripts/test_web_parity.py`).

### 7.1 The look-alike formula

The hard part of cross-competition comparison is that raw numbers
aren't comparable — a SMAT strike rate and an IPL strike rate measure
different attacks. So each player is reduced to a **within-tier
skill-standing z-score** off the dismissal-aware Bayes skill (§5): how
many standard deviations above his own competition's mean does he
stand? A SMAT prospect and an IPL star can then be lined up despite
incomparable raw stats. Candidates must also share the picked player's
**archetype** (role + seam/spin from the Gemini taxonomy).

### 7.2 The three tiers + pricing

For an active IPL pick, Scout surfaces three tiers in order: similar
**IPL peers**, then uncapped **SMAT** prospects, then overseas options
(**BBL / SA20 / CPL / T20 Blast**). Each row carries:

- an **estimated crore price** from the Auction room's skill→price
  curve (a shared `estValue`, tier-discounted so SMAT/BBL is comparable
  to IPL),
- the **saving** vs the picked player (budget swap),
- an uncapped-**gem** flag for SMAT prospects with high standing on
  below-median exposure (the moneyball signal),
- **role / batting-slot** filters to narrow or re-target a tier,
- a one-click **Draft** that drops the prospect into the Auction room
  as a retention (`/auction?draft=<id>`).

The scout index emits per-player `balls` for the gem cutoff. The CLI
entry point is `cricdex scout look-alikes`; the same view ships on the
web, Streamlit, and the TUI **Scout** tab.

### 7.3 Cosine style-twins (Player Profile)

Separately from the cross-competition look-alikes, every Player Profile
shows **cosine style-twins** — feature-space nearest neighbours over
the metric + rating vector (`scout/search/`). These are purely
descriptive ("who has a similar shot/skill profile") and have never
relied on a graph.

---

## 8. Auction room — `auction/` + `web_parity/auction.py`

The auction is a **real-rules IPL auction Monte-Carlo** — a market
simulation, not a squad optimiser. The same logic runs in the browser
(`site/src/lib/auction.ts`) and on the CLI / TUI / Streamlit (Python,
`cricdex.web_parity`), over the **same** exported JSON and with a
**bit-exact seeded LCG RNG**, so a run reproduces everywhere
trial-for-trial (locked by `test_scripts/test_web_parity.py`). The CLI
entry point is `cricdex auction room`. The plain-words walkthrough is
in [`AUCTION_MATH.md`](AUCTION_MATH.md); this section is the technical
summary.

### 8.1 Skill → crore price

The pool has skill but no cost, so step zero invents a fair price from
skill, calibrated to recent real auctions:

```
value = clamp(1.6 · e^(5.8 · skill) · roleMult, 0.3, 27)
```

The `5.8` stretches the curve so the spread matches recent money (top
names ~27 cr, the 2025 ceiling; median ~3–4 cr); `roleMult` weights up
scarcer all-rounders / keepers. A **recency decay** then subtracts a
penalty scaled by months since the player's last match (capped at
−0.30) so dormant/retired names don't top the buys. The opening **base
price** snaps to the real IPL bands (0.3 / 0.5 / 0.75 / 1.0 / 1.5 / 2.0
cr).

### 8.2 The cross-collection pool

The pool is the active T20 world, not just past IPL squads:

- **IPL players** — retainable, each carrying his current franchise.
- **Free agents** — overseas via BBL / SA20 / CPL / T20 Blast, and
  uncapped Indians via SMAT.

Guardrails: active only (last ~3 yrs), ≥150 balls of evidence,
associate/non-IPL-nation noise excluded, and a **tier penalty** applied
to cross-tier skill before pricing (BBL −0.07, SA20 −0.07, CPL −0.10,
T20 Blast −0.10, SMAT −0.20; IPL 0).

### 8.3 Retentions, then bidding

**Retentions** are editable per team. Mega = the real 2025 retention
lists (~5 players), slab-priced (18 / 14 / 11 / 18 / 14 cr capped, 4 cr
uncapped) from the 120 cr purse; Mini = teams keep most of their squad
free and bid only a small leftover purse. Retained players leave the
pool and count toward the overseas cap (8).

**Bidding** runs player-by-player, stars first. Each team's max bid is
`value × aggression × need × overseas-bias × luck`, bounded by
remaining money / squad cap / overseas cap. The highest max bid wins
but pays just **above the second-highest** (second-price clearing). A
**two-phase fill** runs the auction so the pool is shared fairly: round
1 fills every team to a 20-man minimum, round 2 tops up toward the 25
cap, and a safety pass guarantees no team is left below 20.

### 8.4 ~300 trials + post-sim search

One mock auction is run ~300 times with the bid order reshuffled each
time, then averaged: each team's typical spend / squad size / value /
overseas count, and for each star the **% of trials each team won him**
("Bumrah → MI 62%, CSK 21%"). The sim emits a per-player `outcomes`
summary across all trials, which powers a **post-sim search** (web,
Streamlit, and the TUI Sim tab): after a run, look up any player —
retained (by which team), sold (most-likely buyers, sold-%, avg price),
or unsold. The RNG is seeded, so identical settings reproduce identical
results.

---

## 9. Wikidata bridge — `scout/ingest/wikidata.py`

The data layer ran into a fun infrastructure problem worth knowing
about.

### 9.1 The blocker

Wikidata's SPARQL endpoint (`query.wikidata.org`) returns HTTP 429
(Too Many Requests) from any GCP / AWS / datacenter IP — they have
a separate rate-limit pool for datacenter traffic. Our VM is on GCP.

### 9.2 The bridge

Two pieces of fortune:
1. The Wikidata **action API** (`www.wikidata.org/w/api.php`) is on
   a *different* rate-limit pool and works from datacenter IPs.
2. There's a Wikidata property `P2697` — "Statsguru ID" — that's
   the **same** as Cricsheet's `key_cricinfo` for cricketers. ESPN
   Cricinfo's player URLs use this ID, and the Wikidata editors
   diligently link it.

So we use the action API's `haswbstatement` search to find a player
by their Statsguru ID directly:

```python
def _qid_via_statsguru(statsguru_id, cx):
    r = cx.get(WD_SEARCH_URL, params={
        "action": "query", "format": "json", "list": "search",
        "srsearch": f"haswbstatement:P2697={statsguru_id}",
        "srlimit": 1,
    })
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None
```

This 1:1 maps Cricsheet `key_cricinfo` → Wikidata Q-id without ever
touching SPARQL. 289 / 300 active IPL players resolved this way.

### 9.3 Fallback — name search

For the 11 misses we fall back to `wbsearchentities` (free-text
name search), filtered to entries whose descriptions mention
`cricket | batsman | bowler | wicket`. Catches a few more; messy for
players named with initials (`"Z Khan"`) because Wikidata search
matches initials poorly.

### 9.4 What we fetch

For each Q-id we hit the entity API
(`Special:EntityData/{qid}.json`) and extract claims at fixed
properties:
- P569 — date of birth
- P27 — country of citizenship (Q-id, e.g. Q668 = India)
- P19 — place of birth (Q-id)
- P21 — gender
- P18 — Wikimedia Commons image filename
- P3526 — ESPNcricinfo numeric ID
- P2697 — Statsguru ID
- P2698 — Cricbuzz ID
- P2002 — Twitter handle
- P2003 — Instagram handle

Throttle: 0.6 s between requests (~100 req/min). Checkpoint to disk
every 25 players so a crash doesn't lose progress.

---

## 10. Surfaces — web canonical, the rest at parity

The React web app is the source of truth; the CLI, TUI, and Streamlit
dashboard mirror its analytical pages, and Scout + the Auction room run
identical logic on every surface via `cricdex.web_parity`.

### 10.1 CLI — `cricdex/cli/`

`typer`-backed console script; full reference in `docs/CLI.md`. Every
command renderer uses the shared `_render.py` helpers (Rich Panels,
`pretty_table`, `bayes_sentence`, `wikidata_block`, `sparkline`,
`spinner`) and pulls explainer strings from `_copy.py` so the prose
stays at parity with the Streamlit dashboard.

### 10.2 TUI — `cricdex/cli/tui.py`

Textual app whose tabs mirror the web pages:
1. Leaderboard
2. Records
3. Compare
4. Venues
5. Profile
6. Scout
7. Auction (Sim) — with the post-sim player search + Mega/Mini toggle
8. Update Data — buttons that shell into `data_cmd.run_ingest`

Default behaviour: `cricdex` (no args) launches TUI. `cricdex
--help` lists subcommands as before.

### 10.3 Streamlit dashboard — `cricdex/dashboard/`

Pages mirroring the web + TUI: Leaderboards, Player Profile, Compare,
Head-to-head, Scout, Auction room, Records, Venues, Update Data. Same
`_widgets.py` helpers (`collection_picker`, `fuzzy_player_input`,
`provenance_banner`) across pages so the chrome stays uniform.

### 10.4 FastAPI — `cricdex/api/`

REST endpoints (records / venues / players / compare) + OpenAPI at
`/docs`. Public surface for programmatic access. Currently no auth
(vNext §E.2 — Cloudflare Worker + API keys table).

---

## 11. Deployment + CI/CD

### 11.1 GitHub Actions

Workflows in `.github/workflows/`:

- `ci.yml` — ruff lint + format + pre-commit + pytest on every push
  / PR to main. Runs in ~90 s.
- `deploy.yml` — builds the static `site/` and publishes it to
  GitHub Pages on pushes touching `site/**`.
- `refresh-data.yml` — manual ("Run workflow"): re-ingest + recompute +
  re-cook the snapshot, then redeploy.

### 11.2 Docker

`docker-compose.yml` brings up the app for local dev / the pipeline.
The stack is file-driven (DuckDB + exported JSON), so there is no
vector or graph DB service. `make docker-up` builds + runs it.

### 11.3 Off-VM persistence

`data/` is gitignored. The DuckDB + metrics + Bayes JSONs are the only
copies on disk. `make backup WHAT=all` tarballs them and pushes to
Cloudflare R2 (always-free 10 GB / zero egress).

---

## 12. vNext / TODO

Items intentionally left out of v0.1.0. Grouped by what unblocks
them; see `docs/VNEXT.md` for the full table and
`docs/DEFERRED.md` for the per-item fix paths.

**Scope note:** CricDex is deliberately **Cricsheet-only**. Live
feeds, scrapes, and other non-Cricsheet sources (Reddit sentiment,
Cricbuzz live, ESPNcricinfo scrape, BCCI Ranji/Hazare, WPL/SA20 PC
PDFs) and the LLM-convenience features they fed (commentary translate,
match reports, newsletter digest) were **removed**, not deferred —
they're out of scope.

### Group A — grassroots + identity (year 2)

- **CricHeroes grassroots tier** — amateur ball-by-ball, if a
  partner API or Cricsheet-compatible export becomes available.
- **Photo-CLIP identity disambiguation** (depends on CricHeroes).
- **Replacement Delta** metric — `NGI − NGI(replacement-level
  domestic player)`. Cricket WAR. Needs a domestic-tier baseline.

### Group B — auction-v2 (GPU compute)

- **Multi-agent PettingZoo self-play** — every franchise slot trains
  its own policy concurrently (the shipped room uses fixed bidding
  archetypes, not learned policies).
- **Bid-history-mined personality YAMLs** — replace the hand-
  authored archetypes with personalities extracted from real IPL
  auction bid logs.

### Group C — year-2 advanced (CV)

- **OpenBoundary Hawk-Eye OSS** — ball tracking + pitch map + speed
  from broadcast video.
- **ChuckCheck** — elbow flex from monocular pose (15° legality test).
- **ScoutVLM** — broadcast → ball-by-ball via a Vision Language Model.
- **Highlight CV** — auto-clip key moments from broadcast.

### Group D — API + infra

- **GraphQL** layer (Strawberry on top of existing FastAPI).
- **Auth + rate-limit** — Cloudflare Worker + API keys table.
  Mandatory before any public deploy.
- **Public deploy** — HuggingFace Spaces or Oracle Cloud Always Free.

### Group F — maintenance cadence

Rolling work the v1 release surfaces but doesn't automate:
- People Register monthly refresh.
- Cricsheet ETL on new-match drops.
- Metrics + records JSON refresh after Cricsheet updates.
- WP / Bayes refits when underlying data shifts materially.

---

## Appendix A — How the pieces connect

A worked example: "Who plays like Kohli that I could realistically
sign?"

1. **CLI / TUI / web** call the Scout look-alike search for "V Kohli"
   in `cricdex.web_parity` (the same code the React `Scout.tsx` page
   runs), reading the exported `scout_index.json`.
2. Kohli's archetype (role + seam/spin) is read from the Gemini
   taxonomy, and his **within-tier skill-standing z-score** is computed
   off the dismissal-aware Bayes fit (§5).
3. Candidates sharing his archetype are ranked by how close their own
   within-tier z-score is, surfaced as three tiers: IPL peers → uncapped
   SMAT → overseas BBL / SA20 / CPL / Blast.
4. Each row gets an **estimated crore price** from the shared
   skill→price curve (`estValue`, tier-discounted), the **saving** vs
   Kohli, and an uncapped-**gem** flag where applicable.
5. The CLI renders a Rich Panel + a `pretty_table`; the web renders the
   same rows; a one-click **Draft** can push a prospect into the Auction
   room.

Every step traces back to the underlying Cricsheet ball-by-ball + the
Bayes fit. No magic, no proprietary feeds, no opaque "impact score".

---

## Appendix B — Glossary

- **WPA** — Win Probability Added. Per-event change in
  P(team wins). Borrowed from baseball.
- **Monte-Carlo** — Run a random simulation many times, gather
  statistics. Used for the auction room's price/odds estimates.
- **Second-price clearing** — The winner pays just above the
  second-highest bid, not their own max. Real auction behaviour.
- **NumPyro** — JAX-backed probabilistic programming language.
- **NegBin** — Negative Binomial distribution. Poisson with extra
  over-dispersion parameter.
- **ADVI** — Automatic Differentiation Variational Inference.
  Approximate Bayes via gradient descent on a surrogate
  distribution.
- **NUTS** — No-U-Turn Sampler. Adaptive Hamiltonian Monte Carlo.
- **web_parity** — The Python port of the web's TypeScript auction +
  scout logic, locked bit-exact by `test_scripts/test_web_parity.py`.
- **Statsguru ID / P2697** — ESPNcricinfo player ID, used as the
  Wikidata bridge property.

---

End of guide. Open `docs/METRICS.md`, `docs/SCOUT.md`,
`docs/DECISIONS.md`, and `docs/ARCHITECTURE.md` for narrower
deep-dives on specific subsystems.
