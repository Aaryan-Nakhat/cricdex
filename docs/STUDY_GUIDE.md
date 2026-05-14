# CricDex — Study Guide

A deep-dive technical reference covering every algorithm, design
choice, and data pipeline in this repository. Written so a reader
who hasn't touched Bayesian inference or reinforcement learning can
still follow along and present the work to others.

Sections are roughly ordered shallow → deep. If you want to skim,
the **Overview** and **Architecture** sections give the high-level
picture; the algorithm chapters (5–9) are the meat.

---

## 0. Table of Contents

1. Project overview — what CricDex is, what problem it solves
2. Architecture — module layout, data flow, how pieces fit
3. Data layer — Cricsheet, People Register, Wikidata, Rules PDFs
4. The 10 novel cricket metrics — formula + intuition each
5. Bayesian scout ratings — hierarchical NegBin, NumPyro, ADVI vs NUTS
6. NGI / Net Game Impact — XGBoost win-prob + isotonic calibration + ΔWP
7. Scout graph — Neo4j model + cohort traversal + archetype detection
8. Auction stack — MILP solver, Monte Carlo simulator, GRPO RL, advisor
9. Rules Q&A — embeddings, BM25, RRF fusion, cross-encoder rerank
10. Wikidata bridge — P2697 statsguru ID + Entity API workaround
11. Surfaces — CLI / TUI / Streamlit / API
12. Deployment + CI/CD
13. vNext / TODOs — what didn't make v1 and why

---

## 1. Project overview

**CricDex** is an open cricket intelligence platform that sits on top
of publicly available cricket data (primarily
[Cricsheet's](https://cricsheet.org/) ball-by-ball JSON dumps) and
emits seven things:

1. **Novel sabermetrics** — context-adjusted player metrics that
   scorecards miss (NGI, Pressure Runs, Phase Dilation, etc).
2. **Bayesian player ratings** — opponent-adjusted skill scores fit
   with NumPyro/JAX so a player who only ever faced weak attacks
   doesn't outrank one who's faced everyone.
3. **A scout graph** — Neo4j of every IPL player + their FACED
   bowling edges, TEAMMATE_OF overlaps, and PLAYED_IN matches. Powers
   "find me a substitute for Bumrah".
4. **Auction tooling** — MILP squad optimiser, Monte-Carlo price
   simulator, GRPO reinforcement-learning self-play, war-room
   substitute advisor.
5. **Rules Q&A** — natural-language search over 21 official rulebook
   PDFs (MCC Laws, ICC Playing Conditions, IPL, BBL, SA20, etc.) with
   citations.
6. **A multilingual commentary translator** — English → Hindi /
   Tamil / Bengali / Urdu / Sinhala / Marathi / Telugu / Kannada.
7. **A daily digest** — On-This-Day records, match reports, headline
   metric movements.

The distribution is **terminal-first**. A single `cricdex` console
script fronts all of it. A Streamlit dashboard is the parallel
browser surface; a Textual TUI is the in-terminal cockpit. The same
library functions back all three surfaces, so behaviour stays in
lockstep.

**Why open?** Existing cricket platforms (Cricbuzz, CricViz, ESPN)
hide methodology behind paywalls. CricDex publishes the formulas,
the Cricsheet-only inputs, and a Docker image you can `make
docker-up-prod` in 30 seconds.

**Why the obsession with context-adjusted metrics?** A 25-ball 40 in
a slack chase scores the same as a 25-ball 40 chasing 12 an over.
Standard scorecards are context-blind. CricDex's metrics put context
back in (venue median, phase, partnership state, opponent skill).

---

## 2. Architecture

Top-level layout:

```
src/cricdex/
├── api/                   FastAPI REST surface (12 endpoints + /docs)
├── auction/               MILP solver + MC sim + GRPO RL + advisor
├── cli/                   typer console script (one file per command group)
├── commentary_translate/  English → 8 Indic languages
├── comparator/            Side-by-side player metric tables
├── config/                Pydantic settings + DATA_DIR resolution
├── dashboard/             Streamlit pages (12 of them, mirror the TUI)
├── llm/                   Gemini wrapper (work-proxy URL or personal key)
├── metrics/               The 10 novel metrics (batter.py + bowler.py + ngi.py)
├── newsletter/            Markdown digest compiler
├── people/                Cricsheet People Register loader
├── pulse/                 Reddit sentiment (datacenter-IP blocked, deferred)
├── profiles/              Single-player JSON assembler (used by all surfaces)
├── records/               9 record SQL queries + on-this-day digest
├── reports/               LLM match-report generator
├── rules/                 21 PDFs → 11k clauses → Qdrant + RAG
├── scout/
│   ├── graph/             Neo4j writer + similar.py cohort traversal
│   ├── ingest/            Cricsheet → DuckDB; Wikidata enrichment
│   ├── ratings/           NumPyro hierarchical Bayes
│   └── search/            Cosine style-twin
├── tui_helpers/           (small) styling helpers for Textual
└── venues/                Per-venue conditions (innings totals, phase rates)
```

**Data flow**:

```
Cricsheet JSON ──> scripts/ingest_cricsheet.py ──> DuckDB (~600 MB)
                                                       │
        ┌─────────────────────────┬────────────────────┼──────────────────┐
        ▼                         ▼                    ▼                  ▼
   metrics/*.py            scout/ratings              records/         venues/
   (10 metrics JSON)       (Bayes JSON)               (on-this-day)    (innings/phase)
        │                         │
        │                         └────> scout/graph/writer
        │                                    (Neo4j FACED + TEAMMATE)
        ▼
   profiles/builder.py  ──> JSON per player
                          │
                          ▼
              CLI / TUI / Streamlit / FastAPI

People Register (cricsheet) ──> cross-source ID bridge ──> Wikidata enrichment
                                                              (DOB, photo, socials)

Rules PDFs (21) ──> rules/ingest+parse ──> rules/embed
                                              │
                                              ▼
                              Qdrant (snowflake-arctic-embed-l-v2 @ 384-dim)
                                              │
                                              ▼
                              rules/retrieval (BM25 + dense + RRF + Jina)
                                              │
                                              ▼
                              rules/qa (Gemini-synthesised answer)
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
handles, and ESPNcricinfo / Cricbuzz IDs. See §10 for the technical
bridge (the SPARQL endpoint blocks GCP IPs so we use the action API
with a P2697-statsguru-ID search instead). 289 / 300 active players
are enriched today.

### 3.4 Rules PDFs

21 official rulebook PDFs span: MCC Laws of Cricket 2022; ICC
Playing Conditions (Tests, ODIs, T20Is — men's + women's); IPL 2024
PCs; The Hundred 2023; BBL + WBBL 2024; SA20 2023; Cricket Australia
domestic (Marsh One-Day Cup, Sheffield Shield, BBL); ICC Code of
Conduct; ICC Anti-Corruption Code. Total ~11k clauses parsed via
`pdfplumber` into `data/rules/parsed/*.jsonl`. Each clause:

```json
{
  "source_id": "icc_pc_men_t20i_2025",
  "edition": "2025",
  "page": 47,
  "law_number": "21.5.2",
  "parent_chain": ["21. Wide Ball", "21.5 Definition"],
  "title": "Adjudication of wides at the start of an over",
  "text": "If the ball passes wider than the wide guideline ..."
}
```

A separate `data/rules/curated/` directory holds hand-curated
supplementary clauses for gaps the PDFs leave (IPL Impact Player
rule, etc.).

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

### 4.3 Recoverability — `metrics/batter.py:recoverability_index`

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

### 4.6 Phase Dilation — `metrics/batter.py:phase_dilation`

**Intuition.** How much longer a batter survives at the crease
versus the cohort average.

**Math.** `avg_balls_per_dismissal = total_balls / dismissals` per
batter. Cohort average = mean of that across batters with
`dismissals >= 5`. `dilation_index = avg_balls_per_dismissal /
cohort_avg`.

A dilation index of 1.5 means this batter faces 50% more balls per
dismissal than the cohort. Anchor batters score high here.

**Filter.** `min_dismissals=10`.

### 4.7 Setting Tax — `metrics/batter.py:setting_tax`

**Intuition.** The cost (in SR points) of "setting up" an innings —
how much slower a batter scores in the first 20 balls vs their
career.

**Math.** `setting_tax = career_sr − setting_sr` where `setting_sr`
covers balls where `balls_faced_to_date <= 20`.

A setting tax of 30 means the batter scores 30 SR points slower in
the first 20 balls than their career average — a heavy starter cost.
A negative setting tax means they start *faster* than their career
norm (rare; opener territory).

**Filter.** `min_career_balls=200`, `min_setting_balls=50`.

### 4.8 Sticky Dot Pressure — `metrics/bowler.py:sticky_dot_pressure`

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

```json
[
  {"cricsheet_id": "ba607b88", "name": "V Kohli", "role": "batter",
   "skill": 0.118, "skill_sd": 0.029, "balls": 6499},
  {"cricsheet_id": "ba607b88", "name": "V Kohli", "role": "bowler",
   "skill": -0.162, "skill_sd": 0.343, "balls": 172},
  ...
]
```

Two rows per cross-role player (Kohli has both because he bowls
occasionally). The `skill_sd` is the standard error — pair it with
the `balls` to read confidence: `balls=6499, sd=0.029` is rock
solid; `balls=172, sd=0.343` is barely better than the prior.

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

## 7. Scout graph — `scout/graph/`

Neo4j stores three edge types so we can answer "show me players in
the same competitive neighbourhood as Bumrah" without ad-hoc SQL.

### 7.1 Schema

**Nodes — `Player`:**
```
cricsheet_id (PK), unique_name, key_cricinfo, key_cricbuzz,
unresolved, balls_faced, balls_bowled, last_match_date,
role, bowling_style, bowling_style_source, middle_overs_pct
```

**Nodes — `Match`, `Venue`** (lighter; used for graph context).

**Edges:**
- `FACED` — batter → bowler, properties `balls_faced`, `runs_scored`,
  `dismissals`.
- `TEAMMATE_OF` — unordered pair (dedupe via `LEAST/GREATEST`),
  property `matches_together`.
- `PLAYED_IN` — player → match, property `team`.
- `AT` — match → venue.

### 7.2 Role classifier

A player's `role` is decided at graph-population time:
- `all_rounder` if `balls_bowled ≥ 60 AND balls_faced ≥ 60`
- else `bowler` if `balls_bowled ≥ balls_faced`
- else `batter`

This is intentionally lenient — `60` is a low threshold so part-time
options surface. **But** it mis-tags Bumrah as `all_rounder` because
he batted ~86 times. So `role` is unreliable for downstream cohort
selection, which is why §7.4 uses ball-volume directly.

### 7.3 Bowling-style classifier — `writer.py`

For every bowler, classify into `pace | spin | unknown`. Three-way
priority:

1. **Curated override** (`data/curated/bowling_styles.json`): hand-
   maintained list for known mis-classifications (HV Patel, DJ
   Bravo, G Coetzee, V Vyshak, A Madhwal, T Deshpande, etc., all
   pace).
2. **Middle-overs heuristic**: pace bowlers bowl the powerplay +
   death; spinners bowl the middle. Compute `mid_pct =
   middle_balls / balls_bowled`. `spin` if `≥ 0.55`, `pace` if
   `< 0.50`, `unknown` borderline. Requires `balls_bowled ≥ 120`
   else tagged `insufficient_balls`.
3. **Fallback** `unknown`.

**Why heuristic and not "look it up"?** Wikidata's P5125 (bowling
style) is sparse for cricketers, and ESPNcricinfo (the only source
with reliable style tags) blocks GCP IPs (see §10). The heuristic
gets ~85% accuracy; curated overrides cover the rest.

### 7.4 Cohort traversal — `similar.py`

The interesting algorithmic bit. The function `co_faced_bowlers`
returns *similar players* by graph traversal:
- bowler target → walk `(p)<-FACED-(batter)-FACED->(q)`, count
  distinct shared batters per `q`, sort by count.
- batter target → walk `(p)-FACED->(b)<-FACED-(q)`, count distinct
  shared bowlers, sort.

**The auto-flip.** This was a v1b fix. Two earlier heuristics
failed:
- `role == 'bowler'` failed because Bumrah's `role` is `all_rounder`
  (lenient threshold).
- `bowling_style IN ['pace','spin']` failed because Kohli and Rohit
  crossed the 120-ball middle-overs threshold and got tagged as
  `spin`.

The fix uses raw ball volume:

```python
target_is_bowler = target_bb > target_bf   # actual ratio
cohort_pred = (
    "q.balls_bowled > q.balls_faced" if target_is_bowler
    else "q.balls_faced >= q.balls_bowled"
)
```

Unambiguous. Bumrah's `balls_bowled = 7100 > balls_faced = 86`; he's
a bowler. Kohli's `balls_faced = 6754 > balls_bowled = 251`; he's a
batter. Cohort surface matches archetype every time.

---

## 8. Auction stack — `auction/`

Four interlocking pieces. They share `real_pool.build_pool()` for
the player pool but serve different decision contexts.

### 8.1 MILP squad solver — `auction/solver.py`

**Problem.** Pick `squad_size=25` players to maximise total
`projected_value` subject to a purse + role + overseas
constraints. Integer Linear Programming (specifically MILP because
the `x_i` are binary).

**Decision variables.** `x_i ∈ {0, 1}` for each player `i` (1 = pick).

**Objective.**
```
maximise  Σ value_i · x_i
```
Equivalently `minimise  Σ -value_i · x_i`, which is what scipy
wants.

**Constraints.**
- Budget: `Σ price_i · x_i ≤ purse`
- Overseas cap: `Σ overseas_i · x_i ≤ overseas_cap`
- Squad size (equality): `Σ x_i = squad_size`
- Per-role minimums: for each role `r`, `Σ x_i · [role_i==r] ≥
  role_mins[r]`

**Engine.** `scipy.optimize.milp` with HiGHS backend. No OR-Tools
dependency — keeps the install lean.

**Why MILP, not greedy?** Greedy picking-highest-value-first can hit
infeasible role minimums or overshoot budget. MILP gives the
optimal solution in seconds for a 429-player pool.

```python
c = -value  # flip sign: milp minimises
constraints = [
    LinearConstraint(price.reshape(1,-1), ub=purse),
    LinearConstraint(overseas.reshape(1,-1), ub=overseas_cap),
    LinearConstraint([1.0]*n, lb=squad_size, ub=squad_size),
]
for role, vec in role_vec.items():
    if role_mins.get(role, 0) > 0:
        constraints.append(LinearConstraint(vec.reshape(1,-1), lb=role_mins[role]))
res = milp(c=c, constraints=constraints, integrality=[1]*n,
           bounds=Bounds(lb=[0]*n, ub=[1]*n))
picks = [i for i, x in enumerate(res.x) if x > 0.5]
```

### 8.2 Monte Carlo auction simulator — `auction/simulator.py`

**Problem.** What's the *distribution* of sale prices for each
player given a pool of franchise bidders with different
personalities?

**Method.** Monte Carlo — simulate the auction many times (default
`n_sims=200`) with randomised bid jitter, count outcomes.

**What's Monte Carlo?** Run a random simulation, gather statistics,
repeat. Named after the casino because it's roulette-style sampling.
For analytics with no closed-form solution it's the workhorse.

**Per-player price draw.** Shuffle the pool. For each player,
every franchise computes a `bid_ceiling`:

```python
def _bid_ceiling(franchise, player, rng):
    if franchise["slots_left"] <= 0: return 0.0
    if franchise["need"][player["role"]] <= 0 and tight_slots: return 0.0
    if player["is_overseas"] and franchise["overseas_left"] <= 0: return 0.0
    jitter = rng.gauss(1.0, franchise["risk"])
    ceiling = player["projected_value"] * franchise["aggression"] * jitter
    return min(franchise["purse"], max(0.0, ceiling))
```

**Clearing rule** — second-price + 0.1 tick:
```
sale_price = max(player.price, second_ceiling + 0.1) capped at top_ceiling
```

**Franchise behaviour model.** Six hand-tuned archetype dicts in
`real_pool.FRANCHISE_ARCHETYPES`:
- `MarqueeChaser` (aggression=1.35, risk=0.20)
- `ValueHunter` (0.85 / 0.30)
- `OverseasHeavy` (1.15 / 0.18, overseas slots = 8)
- `IndianFocus` (1.05 / 0.15, overseas slots = 3)
- `AllRounderStack` (1.10 / 0.22, role_min all_rounder = 6)
- `Balanced` (1.00 / 0.15)

Output: per-player `mean_price`, `price_p10`, `price_p90`,
`sold_pct` across simulations.

### 8.3 GRPO reinforcement-learning self-play — `auction/grpo.py`

**Problem.** Train a single agent to bid optimally in a multi-round
auction.

**What's reinforcement learning?** An agent observes a *state*,
picks an *action*, gets a *reward*, transitions to a new state.
Train it to pick actions that maximise long-term reward. For
auctions: state = "you have 60 cr left, 18 slots open, Kohli is up,
your competitors have X/Y/Z purses"; action = "bid 12 cr / pass /
bid 8 cr".

**Why GRPO and not the more famous PPO?**

PPO (Proximal Policy Optimization) is the standard policy-gradient
algorithm. It uses two networks: a *policy* (picks actions) and a
*value head* (estimates how good the current state is). The value
head provides a *baseline* for the advantage `A = R − V(s)` that
reduces variance.

GRPO (Group Relative Policy Optimization, introduced by DeepSeek
in 2024 for math/code reasoning RL) drops the value head entirely.
Instead it samples **G trajectories from the same state**, computes
each one's total return, and z-scores those returns within the
group to get a baseline-free advantage:

```
A_i = (R_i − mean(R_group)) / (std(R_group) + ε)
```

**Why drop the value head?**
- Value heads are hard to fit on sparse / terminal-heavy rewards
  (which auction is — most balls give 0 reward, terminal squad
  bonus is huge).
- Group sampling is a low-variance baseline by construction
  (z-score is zero-mean by definition).
- ~30% fewer parameters / faster training.

**The objective** (same clipped surrogate as PPO):
```
ratio       = exp(log_p_new(a) − log_p_old(a))
L_policy    = -E[min(ratio · A, clip(ratio, 1−ε, 1+ε) · A)]
L           = L_policy − β · H(policy)
```

The clip prevents the policy from moving too far in one update
(stability). `β · H` adds entropy regularisation so the policy
doesn't collapse to a single action prematurely.

**Architecture.** Tiny MLP: `state_dim=16 → 64 → 64 → n_actions=11`
with Tanh activations. Small because the auction state space is
small.

**Hyperparameters.** `epochs=200, group_size=8, lr=3e-4,
entropy_beta=0.01, clip_eps=0.2, grad_norm=0.5`.

```python
for epoch in range(epochs):
    for _ in range(group_size):
        obs, act, logp, rew = _rollout(env, policy)
        group_obs.append(obs); group_act.append(act)
        group_logp.append(logp); group_R.append(rew.sum())

    R = np.array(group_R, dtype=np.float32)
    adv = (R - R.mean()) / (R.std() + 1e-6)         # GRPO advantage
    flat_adv = np.concatenate([np.full(len(o), adv[i])
                              for i, o in enumerate(group_obs)])

    logits = policy(x); dist = Categorical(logits=logits)
    ratio = torch.exp(dist.log_prob(a) - old_logp)
    unclipped = ratio * adv_t
    clipped = torch.clamp(ratio, 1-clip_eps, 1+clip_eps) * adv_t
    policy_loss = -torch.min(unclipped, clipped).mean()
    loss = policy_loss - entropy_beta * dist.entropy().mean()
```

### 8.4 The RL environment — `auction/rl_env.py`

**State (16 dims).** Own purse-norm, slots-left-norm, per-role need
(4), overseas-left-norm, current-player one-hot role (4) + overseas
flag + price-norm + value-norm, max-opponent-ceiling, pool-remaining
fraction.

**Action (11 discrete buckets).** `0` = pass; `k ≥ 1` →
`bid = max(player.price, k × 0.3 × projected_value)`.

**Per-step reward.**
- Win: `+(projected_value − sale_price)`
- Illegal bid (over purse): `−5.0`
- Otherwise: `0`

**Terminal bonus** — *critical*. Without it the agent learns to
always pass (no reward for taking on cost). With it:
```
terminal_reward = +0.5 × Σ acquired_value − 5.0 × unfilled_role_slots
```

The training log shows entropy falling from ~2.39 (uniform over 11
buckets) toward 1.0-1.5 (decided policy) and mean episode return
crossing 0 around epoch 4000 — that's where the agent figures out
which Indian high-skill players are worth committing to.

### 8.5 Project Bayes skill → IPL crore value — `auction/real_pool.py`

How do we turn a Bayes skill score into a "this player is worth
8 cr" number?

```python
def _project_value(skill, role, value_scale=10.0):
    floor = ROLE_FLOOR.get(role, 0.5)   # batter/bowler 0.5; all_rounder 0.8
    return round(math.exp(skill) * floor * value_scale, 2)
```

Log-skill is a multiplicative effect — `skill=+0.30` (marquee) gives
`exp(0.30) ≈ 1.35` and `× 0.5 × 10 = 6.7 cr`. Multiply by role floor
(all-rounders bid up because they're scarce) and a global
`value_scale=10` so marquee batters land around 8-12 cr.

**Base price tier:** the highest IPL tier `≤ value/6.0` from
`[0.30, 0.50, 0.75, 1.0, 1.5, 2.0]`. Approximates the real auction's
floor-price ladder.

**Nationality:** dominant team in `balls_t20s_male` (men's T20Is) →
country code; defaults `IN` if absent. Manual overrides for
namesake collisions.

### 8.6 War-room advisor — `auction/advisor.py`

**Problem.** "Bumrah is gone for 18 cr, I have 8 cr left, 1 bowler
slot. Find me a substitute."

**Method.** Combine relational similarity (graph cohort) with
absolute quality (Bayes-projected value).

```
shared_norm   = shared / max(shared)        ∈ [0, 1]
value_norm    = projected_value / max(value) ∈ [0, 1]
composite     = 0.5 × shared_norm + 0.5 × value_norm
```

Pipeline:
1. `similar.find_replacement(target, top_k=50)` — graph cohort,
   archetype-locked.
2. Inner-join with `real_pool.build_pool()` on `cricsheet_id`.
3. Filter `price ≤ budget` and optional `role` / `bowling_style`.
4. Normalise + score + sort.

The 50/50 weighting between graph proximity and Bayes value is a
deliberate v1 default — graph alone surfaces too many low-value
"played the same opponents" matches; value alone surfaces marquee
names you can't afford. The 50/50 mix gets actionable shortlists.

---

## 9. Rules Q&A — `rules/`

The hardest pipeline in the repo to get right because retrieval
quality cascades into LLM hallucination.

### 9.1 The corpus

21 PDFs → `data/rules/parsed/*.jsonl` (one row per clause via
`pdfplumber`). Plus `data/rules/curated/*.jsonl` for hand-authored
clauses covering gaps (IPL Impact Player rule, etc.). Total ~11k
clauses indexed in Qdrant.

### 9.2 Embedding model — Snowflake-arctic-embed-l-v2

**Why this model?**
- Multilingual (100+ languages, important when an IPL PC quotes a
  Hindi phrase or a player name).
- 8192-token context (long clauses don't get truncated).
- Matryoshka Representation Learning (MRL) trained — see below.
- Open-source under Apache-2.

**Matryoshka truncation.** MRL is a training technique where the
model is trained so that the **first N dimensions** of each
embedding work as a valid embedding on their own. Take the 1024-dim
vector, slice it to 384, and you get 96% of the retrieval quality
with 2.7× faster cosine + 2.7× smaller index.

```python
EMBED_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
EMBED_DIM = 384

model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True,
                            truncate_dim=EMBED_DIM)
client.create_collection(collection_name=COLLECTION,
    vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE))
```

The Qdrant index is 57 MB for 11k clauses at 384-dim.

### 9.3 Hybrid retrieval — `rules/retrieval.py`

Three-stage pipeline:

**Stage 1 — Dense retrieval.** Encode query → Qdrant top-K cosine
search. Captures semantic similarity (synonyms, paraphrasing).

**Stage 2 — Sparse retrieval (BM25).** `rank_bm25.BM25Okapi` over
lowercased `title + text` tokens. Captures exact term matches that
embeddings sometimes blur ("18.4" or "twelfth man" are literal
phrases that dense models can't outrank with paraphrases).

**Stage 3 — RRF fusion.** Reciprocal Rank Fusion combines the two
rankings:

```
score(doc) = Σ 1 / (k_const + rank_in_ranking)
```

With `k_const=60` (folklore default). De-duped via `(source_id,
law_number, page)` so the same clause doesn't get inflated.

```python
def rrf_fuse(dense_hits, sparse_hits, top_k=10, k_const=60):
    scores, payloads = {}, {}
    for rank, (_, p) in enumerate(dense_hits):
        k = (p["source_id"], p["law_number"], p.get("page"))
        scores[k] = scores.get(k, 0.0) + 1.0/(k_const + rank + 1)
    for rank, (_, p) in enumerate(sparse_hits):
        k = (p["source_id"], p["law_number"], p.get("page"))
        scores[k] = scores.get(k, 0.0) + 1.0/(k_const + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
```

**Stage 4 — Cross-encoder rerank.** Jina's
`jina-reranker-v2-base-multilingual` is a cross-encoder model — it
takes `(query, passage)` *together* and emits a single relevance
score. Slower than bi-encoders (one forward pass per pair) but much
more accurate because the model can attend across query and passage
jointly. We cut `top_k × 3` fused candidates down to `top_k=8` after
reranking. Falls back to RRF order on HTTP error so a flaky API
doesn't kill QA.

### 9.4 Answer synthesis — `rules/qa.py`

The retrieval output is `top_k=8` clauses. They get formatted and
passed to Gemini with a strict citation contract:

```
You answer cricket rule questions using ONLY the supplied passages.
- Every factual claim MUST be cited [source_id §law_number].
- Multiple sources should each get their own bracket.
- If passages partially cover, start with "Partial coverage in the parsed corpus:"
- If they don't cover at all: "This rule is not in CricDex's currently parsed corpus..."
```

Format-filter: the `formats` query parameter
(`'ipl'`, `'t20i'`, `'mcc_laws'`, ...) maps to a list of `source_id`s
that Qdrant filters with. So "impact player rule in IPL" with
`formats=['ipl']` only searches IPL-tagged clauses.

Citation parsing: the LLM output is regex-scanned for
`[source_id §law]` brackets and converted to publisher labels
(`"IPL 2024 Playing Conditions, clause 21.5.2"` with a publisher
URL) before display.

---

## 10. Wikidata bridge — `scout/ingest/wikidata.py`

The data layer ran into a fun infrastructure problem worth knowing
about.

### 10.1 The blocker

Wikidata's SPARQL endpoint (`query.wikidata.org`) returns HTTP 429
(Too Many Requests) from any GCP / AWS / datacenter IP — they have
a separate rate-limit pool for datacenter traffic. Our VM is on GCP.

### 10.2 The bridge

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

### 10.3 Fallback — name search

For the 11 misses we fall back to `wbsearchentities` (free-text
name search), filtered to entries whose descriptions mention
`cricket | batsman | bowler | wicket`. Catches a few more; messy for
players named with initials (`"Z Khan"`) because Wikidata search
matches initials poorly.

### 10.4 What we fetch

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

## 11. Surfaces — terminal-first distribution

### 11.1 CLI — `cricdex/cli/`

`typer`-backed console script. 13 subcommands; full reference in
`docs/CLI.md`. Every command renderer uses the shared
`_render.py` helpers (Rich Panels, `pretty_table`, `bayes_sentence`,
`wikidata_block`, `sparkline`, `spinner`) and pulls explainer
strings from `_copy.py` so the prose stays at parity with the
Streamlit dashboard.

### 11.2 TUI — `cricdex/cli/tui.py`

Textual app. 12 tabs:
1. 📊 Leaderboard
2. 📜 Rules
3. 🏆 Records
4. 📝 Match Report
5. 🆚 Compare
6. 🏟 Venues
7. 💸 Auction (Solve + Recommend in same panel)
8. 🪪 Profile
9. 🌐 Translate
10. 🎲 Auction Sim
11. 🔗 Twins
12. 🔄 Update Data — buttons that shell into `data_cmd.run_ingest`

Default behaviour: `cricdex` (no args) launches TUI. `cricdex
--help` lists subcommands as before.

### 11.3 Streamlit dashboard — `cricdex/dashboard/`

12 pages mirroring the TUI tabs 1-to-1. Same `_widgets.py` helpers
(`collection_picker`, `fuzzy_player_input`, `provenance_banner`)
across pages so the chrome stays uniform.

### 11.4 FastAPI — `cricdex/api/`

12 REST endpoints + OpenAPI at `/docs`. Public surface for
programmatic access. Currently no auth (vNext §E.2 — Cloudflare
Worker + API keys table).

---

## 12. Deployment + CI/CD

### 12.1 GitHub Actions

Two workflows in `.github/workflows/`:

- `ci.yml` — ruff lint + format + pre-commit + pytest on every push
  / PR to main. Runs in ~90 s.
- `docker-push.yml` — builds `ghcr.io/aaryan-nakhat/cricdex:latest`
  + `:sha-<short>` + `:vX.Y.Z` (on tag) and pushes to GitHub
  Container Registry. Free-disk-space step nukes the GitHub runner's
  .NET / Android / Haskell toolchains so the 9.8 GB image fits.

### 12.2 Docker

`docker-compose.yml` brings up Qdrant + the app. Pre-bakes the
Snowflake-arctic-embed-l-v2 weights so the container doesn't need
`HF_TOKEN`. `make docker-up-prod` pulls the pre-built image instead
of rebuilding locally (~10-min build skipped).

### 12.3 Off-VM persistence

`data/` is gitignored. The DuckDB + Qdrant + metrics + Bayes JSONs
are the only copies on disk. `make backup WHAT=all` tarballs them
and pushes to Cloudflare R2 (always-free 10 GB / zero egress).

---

## 13. vNext / TODO

Items intentionally left out of v0.1.0. Grouped by what unblocks
them; see `docs/VNEXT.md` for the full table and
`docs/DEFERRED.md` for the per-item fix paths.

### Group A — feeds blocked by datacenter IPs

Every pipeline below is shipped and tested; the upstream servers
refuse GCP/AWS traffic. Move to a residential uplink and they run.

- Wikidata enrichment **on the long tail** beyond the 300 active
  players (rate-limit-throttled there too).
- Reddit JSON pulse (sentiment + content).
- Cricbuzz live match API (ball-by-ball stream).
- ESPNcricinfo player scrape (would fill in handedness + bowling
  style natively — would let us drop the middle-overs heuristic).
- BCCI Domestic — Ranji + Hazare ball-by-ball (only SMAT is
  currently in Cricsheet).
- WPL 2026 + SA20 2023 PC PDFs (Playwright fallback needed).

### Group B — grassroots + identity

- `predict` daily-prediction game (depends on Group A live feed).
- CricHeroes grassroots scraper (long-tail player coverage).
- Photo-CLIP identity disambiguation (depends on CricHeroes).
- **Replacement Delta** metric — `NGI − NGI(replacement-level
  domestic player)`. Cricket WAR. Depends on Ranji + Hazare ingest.

### Group C — auction-v2 (GPU compute)

- **Multi-agent PettingZoo self-play** — every franchise slot trains
  its own policy concurrently (currently one learner + 5 MC
  opponents).
- **Bid-history-mined personality YAMLs** — replace the 6 hand-
  authored archetypes with personalities extracted from 10 years of
  real IPL auction bid logs via Gemini.
- **GRPO reward-shape A/B** — alternative reward designs (per-slot
  marginal value, replacement penalty, etc.).

### Group D — year-2 advanced (CV + voice)

- **OpenBoundary Hawk-Eye OSS** — ball tracking + pitch map + speed
  from broadcast video. Would replace the FAQ-based DRS Practice
  page with an actual ball-tracking simulator.
- **ChuckCheck** — elbow flex from monocular pose (15° legality
  test).
- **Voice analyst earpiece** — LiveKit + STT + LLM + TTS for live
  commentary insights.
- **ScoutVLM** — YouTube broadcast → ball-by-ball via a Vision
  Language Model (Gemini Pro Vision / Idefics2).
- **Highlight CV** — auto-clip key moments from broadcast.
- **Tournament management B2B** — turnkey scoring + analytics for
  domestic boards.
- **Voice-cloned commentary translation** — text → audio with the
  commentator's own voice across 8 Indic languages.

### Group E — API + infra

- **GraphQL** layer (Strawberry on top of existing FastAPI).
- **Auth + rate-limit** — Cloudflare Worker + API keys table.
  Mandatory before any public deploy.
- **Live → dashboard websocket** — push live-feed insights to a new
  dashboard page once the feed unblocks.
- **HF Datasets publish** — `cricdex-rules-clauses` open-benchmark.
- **Public deploy** — HuggingFace Spaces (16 GB free Docker,
  ephemeral disk) or Oracle Cloud Always Free (24 GB / 4 vCPU ARM,
  persistent). Both scoped.

### Group F — maintenance cadence

Rolling work the v1 release surfaces but doesn't automate:
- Rule corpus refresh whenever a PC drops a new edition (`cricdex
  data ingest rules --force`).
- People Register monthly refresh.
- Cricsheet ETL on new-match drops.
- Metrics + records JSON refresh after Cricsheet updates.
- WP / Bayes / GRPO refits when underlying data shifts materially.

---

## Appendix A — How the pieces connect

A worked example: "Who could replace Bumrah for under 8 cr?"

1. **CLI / TUI** call `auction.advisor.recommend_substitutes("JJ
   Bumrah", budget=8)`.
2. Advisor calls `scout.graph.similar.find_replacement("JJ Bumrah",
   top_k=50)`.
3. `find_replacement` reads Bumrah's Player node from Neo4j, finds
   `balls_bowled=7100 > balls_faced=86`, sets archetype=`bowler`,
   runs the Cypher query
   `MATCH (Bumrah)<-FACED-(batter)-FACED->(q) WHERE q.balls_bowled
   > q.balls_faced` and returns the top-50 by `COUNT(DISTINCT
   batter)`.
4. Advisor inner-joins those 50 with `real_pool.build_pool()` on
   `cricsheet_id`. The pool has each player's `projected_value =
   exp(bayes_skill) × role_floor × 10`.
5. Filter `price ≤ 8`, normalise `shared` and `projected_value`,
   compute `composite = 0.5 × shared_norm + 0.5 × value_norm`,
   sort, return top-5.
6. Returned to the CLI which renders a Rich Panel + a
   `pretty_table` with bolded names + composite score, plus a
   footnote on the formula.

Every step traces back to the underlying Cricsheet ball-by-ball +
the Bayes fit. No magic, no proprietary feeds, no opaque
"impact score".

---

## Appendix B — Glossary

- **WPA** — Win Probability Added. Per-event change in
  P(team wins). Borrowed from baseball.
- **MILP** — Mixed-Integer Linear Programming. Linear objective +
  constraints with some variables forced to integer values.
- **GRPO** — Group Relative Policy Optimization (DeepSeek 2024).
  PPO without a value head; baseline from group z-score.
- **NumPyro** — JAX-backed probabilistic programming language.
- **NegBin** — Negative Binomial distribution. Poisson with extra
  over-dispersion parameter.
- **ADVI** — Automatic Differentiation Variational Inference.
  Approximate Bayes via gradient descent on a surrogate
  distribution.
- **NUTS** — No-U-Turn Sampler. Adaptive Hamiltonian Monte Carlo.
- **MRL** — Matryoshka Representation Learning. Train embeddings
  so the first N dims of each vector are themselves a valid
  embedding.
- **RRF** — Reciprocal Rank Fusion. Combine rankings via
  `Σ 1/(k + rank)`.
- **BM25** — Best Match 25. Classical sparse term-weighting
  retrieval; an evolution of TF-IDF.
- **Cross-encoder** — Model that takes `(query, passage)` together
  and emits a single relevance score. More accurate than bi-encoder
  embeddings; slower because one forward pass per pair.
- **Statsguru ID / P2697** — ESPNcricinfo player ID, used as the
  Wikidata bridge property.

---

End of guide. Open `docs/METRICS.md`, `docs/SCOUT.md`,
`docs/DECISIONS.md`, and `docs/ARCHITECTURE.md` for narrower
deep-dives on specific subsystems.
