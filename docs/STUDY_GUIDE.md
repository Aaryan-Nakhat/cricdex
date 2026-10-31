# CricDesk — Study Guide

A deep-dive technical reference covering every algorithm, design
choice, and data pipeline in this repository. Written so a reader
who hasn't touched Bayesian inference can still follow along and
present the work to others.

Sections are roughly ordered shallow → deep. If you want to skim,
the **Overview** and **Architecture** sections give the high-level
picture; the algorithm chapters (5–9) are the meat. For the same models
explained without the maths, with worked examples and the backtest
results, read [`METHODOLOGY.md`](METHODOLOGY.md) first.

---

## 0. Table of Contents

1. Project overview — what CricDesk is, what problem it solves
2. Architecture — module layout, data flow, how pieces fit
3. Data layer — Cricsheet, People Register, Wikidata
4. The 10 novel cricket metrics — formula + intuition each
5. Bayesian scout ratings — hierarchical NegBin + dismissal Binomial + context terms, NumPyro, ADVI vs NUTS
6. NGI / Net Game Impact — XGBoost win-prob (monotone, beta-calibrated, out-of-fold) + ΔWP credit
7. Scout — cross-competition look-alikes + style twins
8. Auction room — real-rules Monte-Carlo, shared with the web via web_parity
9. Wikidata bridge — P2697 statsguru ID + Entity API workaround
10. Surfaces — web (canonical) + CLI / TUI / Streamlit / API at parity
11. Deployment + CI/CD
12. Roadmap — what's next (pointer to ROADMAP.md)

---

## 1. Project overview

**CricDesk** is an open cricket intelligence platform that sits on top
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
3. **Scout** — cross-competition look-alikes across every Scout pool
   in the league registry (IPL, SMAT, BBL, SA20, CPL, T20 Blast, PSL,
   ILT20, The Hundred, MLC and more) ranked by within-tier Bayesian
   skill-standing z-score, plus style twins on the Player
   Profile. File-driven (DuckDB + exported JSON; no graph database).
4. **Auction room** — a real-rules IPL auction Monte-Carlo over a
   cross-collection pool with editable retentions, overseas cap,
   second-price clearing and a two-phase fill.

The web app is the **canonical surface**; a single `cricdesk` console
script, a Streamlit dashboard, and a Textual TUI mirror the same
analytical pages. Scout and the Auction room run identical logic on
every surface via `cricdesk.web_parity` (a Python port of the web's
TypeScript, locked by `test_scripts/test_web_parity.py`), so behaviour
stays in lockstep.

**Why open?** Existing cricket platforms (Cricbuzz, CricViz, ESPN)
hide methodology behind paywalls. CricDesk publishes the formulas, the
Cricsheet-only inputs, a live static demo
(aaryan-nakhat.github.io/cricdesk), and the full stack reproducible via
`make docker-up`.

**Why the obsession with context-adjusted metrics?** A 25-ball 40 in
a slack chase scores the same as a 25-ball 40 chasing 12 an over.
Standard scorecards are context-blind. CricDesk's metrics put context
back in (venue median, phase, partnership state, opponent skill).

---

## 2. Architecture

Top-level layout:

```
src/cricdesk/
├── api/                   FastAPI REST surface + /docs
├── auction/               IPL team list (the sim is in web_parity/)
├── cli/                   typer console script (one file per command group)
├── common/                shared: db, llm.py (LiteLLM client), filters, metric catalog, sql, spark, venue_names
├── comparator/            Side-by-side metric table + skill head-to-head
├── config.py              Pydantic settings + DATA_DIR resolution
├── dashboard/             Streamlit pages (mirror the web + TUI)
├── metrics/               10 context metrics + fielding/keeping, matchups, phase, dismissal_fingerprint
├── profiles/              Single-player profile assembler + fuzzy name resolution
├── records/               9 record SQL queries + on-this-day digest
├── scout/
│   ├── ingest/            Cricsheet → DuckDB; people_register.py; Wikidata enrichment
│   ├── ratings/           NumPyro hierarchical Bayes (dismissal-aware) + head-to-head
│   ├── search/            Style twins
│   └── cohort.py          co-faced cohort (plain DuckDB SQL)
├── web_parity/            Python port of the web's TS auction + scout
└── venues/                Per-venue conditions (innings totals, phase rates)
```

Everything is Cricsheet-derived. There are no live-feed, scrape, or
non-Cricsheet-source modules — those were intentionally removed — and
the stack is file-driven (DuckDB + exported JSON; no vector or graph
database).

**Data flow**:

```
Cricsheet JSON ──> scripts/ingest_cricsheet.py ──> DuckDB (~100 MB, all collections)
                                                       │
        ┌─────────────────────────┬────────────────────┼──────────────────┐
        ▼                         ▼                    ▼                  ▼
   metrics/*.py            scout/ratings              records/         venues/
   (12 boards JSON)        (Bayes JSON)               (on-this-day)    (innings/phase)
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

Two storage roots. The pipeline writes to `DATA_DIR` — the repo's
`data/` when running from a clone (`CRICDESK_DATA_DIR` overrides; an
installed package falls back to `~/.cricdesk/data/`). The read-only
surfaces (web, Streamlit, TUI and the JSON-backed CLI commands) read the
exported snapshot in `site/public/data/`, so a refresh only shows up
after an export — `cricdesk data ingest metrics` re-exports for you. The
CLI `profile` / `compare` / `records` / `venues` commands and the
FastAPI app query `DATA_DIR` (DuckDB + `data/metrics/`) directly.

---

## 3. Data layer

### 3.1 Cricsheet

[Cricsheet](https://cricsheet.org/) is a community-maintained archive
of ball-by-ball data for ~all professional cricket since 2002. Each
match is a JSON file with `info` block (teams, venue, dates,
outcome) plus an `innings` list where every ball is an object with
`runs_total/batter/extras`, `wicket` info, and `phases` cues.

`scout/ingest/cricsheet.py` downloads a *collection* (e.g.
`ipl` = 1,243 matches, a few MB) as a single zip, expands each match
JSON, flattens every ball into a polars row, writes Parquet, then
materialises four DuckDB tables per collection so SQL queries run in
single-digit seconds: `matches_<col>`, `balls_<col>` (one row per
delivery, keeping its first wicket), `wickets_<col>` (every wicket, since
a delivery can have two) and `players_<col>` (each match's own
name → Cricsheet-id registry). After every ingest,
`common/venue_names.py` rewrites venues to one `"<ground>, <city>"` per
ground (renamed grounds under their current name, old spellings kept in
`venue_aliases`).

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

Names in the ball data resolve to ids through each match's own
registry first (`players_<col>`, which knows that "Navdeep Saini" and
"NA Saini" are one player), then the People Register's `unique_name`
(`common/sql.py::player_ids`). See [`IDENTITY.md`](IDENTITY.md).

### 3.3 Wikidata enrichment

`cricdesk data ingest wikidata` enriches each cricketer with DOB,
country / birthplace Q-ids, profile photo URL, Twitter / Instagram
handles, and ESPNcricinfo / Cricbuzz IDs. See §9 for the technical
bridge (the public SPARQL endpoint rate-limits datacenter IPs, so we use
the entity API instead). 342 players are cached today, 331 of them found
on Wikidata (all with a DOB).

---

## 4. The 10 novel cricket metrics

Each metric outputs a polars DataFrame and writes to
`data/metrics/<slug>_<collection>.json`. `scripts/export_site.py`
cooks those into `site/public/data/<collection>/leaderboards/`, which
the web, the Streamlit Leaderboards page, the TUI and the CLI
`cricdesk leaderboard <slug>` all read. Wicketkeeping and Fielding
dismissal boards make 12 leaderboards in all.

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

For each `(format, venue, phase)` compute `median(required_rpb)`
across every chase ball. Then flag a ball as "under pressure" if
`required_rpb > 1.5 × median_required_rpb(format, venue, phase)`.

**Why 1.5× venue median?** Different grounds demand wildly different
chase rates (Bangalore vs Lord's). The venue median normalises that
out — "pressure" means hard *for that ground*. The 1.5× threshold is
a deliberately loose cut: tighter (e.g. 2×) and you get only the
slog-overs death scenarios; looser and the metric loses signal.

**Filters.** `min_balls_faced=20` (chase balls); T20 / ODI only;
innings 2 only; `runs_needed > 0` (no ball already-won situations).

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

**Math.** For every dot ball (no runs off the bat, not a wide or
no-ball), sum the runs off the bat over the *next 6 deliveries the
batter is on strike for* (same innings; wides included). Aggregate per batter:

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
innings. Keep only balls faced by the batter who was **already at the
crease** when the wicket fell: not the dismissed batter, and not the new
arrival who's still gauging conditions. A ball inside two wickets'
windows counts once. Aggregate:

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
`dismissals >= 5`. `longevity_index = avg_balls_per_dismissal /
cohort_avg`.

A longevity index of 1.5 means this batter faces 50% more balls per
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

> **Retired from the site, 2026-10-29.** It failed a split-half reliability test (a player's odd and even
> matches don't rank bowlers alike: r −0.18) even after a rebuild; see METHODOLOGY section 3. Kept here
> for the method and its lesson: a rare event needs far more chances than a season gives.

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
dismissal, look up the dismissed batter's Bayes **scoring** skill
(`skill`, not the complete `value`). Aggregate:

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
no neural network. You give the model every `(batter, bowler)` matchup
in a league, split by season, phase, innings and ground (about 73,000
cells for the IPL, built from ~296,000 deliveries), with its balls, runs
and dismissals, and it returns a posterior distribution over each
player's *skill* parameters. Players are registry ids resolved per match
(`common/sql.py::keyed_balls`), so two namesakes are two players.

§5.2 and §5.7 build the model up from its simplest form; §5.8 adds the context
terms, the dispersion fix, the role-level priors and the extras model
that the shipped fit uses.

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
b_skill[i] ~ Normal(0, sigma_b)      (written non-centred: sigma_b · z, z ~ Normal(0, 1))
k_skill[j] ~ Normal(0, sigma_k)
sigma_b, sigma_k ~ HalfNormal(1)
intercept ~ Normal(0, 3)
alpha ~ HalfNormal(5)
```

The skills are written **non-centred** (`b_skill = sigma_b · z`). It's the
same prior, but it keeps the many thin-sample players from trapping the
sampler in a "funnel" with `sigma_b`; the old centred form mis-fitted the
strike axis (sds ~25% too wide). Every matchup is fitted, even a 1-ball
one; the prior does the shrinking.

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
JAX (autodiff + XLA-compiled numerical computing). It was
chosen over the older PyMC for a 10-50× speed-up on this exact
class of hierarchical GLM. The full fit on the IPL collection (~73k
context cells) takes about 2–3 minutes on CPU with ADVI, most of it JAX
compiling the model for that league's shapes.

### 5.4 ADVI vs NUTS

Two inference engines are exposed. Both end up with samples from the
posterior, but they get there differently:

**ADVI (Automatic Differentiation Variational Inference).** Fits a
*surrogate* normal distribution to the posterior by minimising
KL-divergence via gradient descent. Fast (2–3 minutes for IPL). The
variational family is mean-field normal (no correlations between
parameters), which in general under-states uncertainty, so it is
checked against NUTS on the IPL. After the context terms went in
(2026-10-18): for players with 100+ balls ADVI's sds were a median 98%
of NUTS's for batters and 92–95% for bowlers, `value_sd` 101% / 96%,
point estimates correlated ≥ 0.994, and head-to-head P(A>B) differed by
a median 2–2.5 points (95th percentile ~7). ADVI is the default for
every refresh.

```python
guide = AutoNormal(model)
svi = SVI(model, guide, Adam(0.01), Trace_ELBO())
state = svi.init(...)
for _ in range(12000):
    state, loss = svi.update(state, ...)
```

**NUTS (No-U-Turn Sampler).** Runs Hamiltonian Monte Carlo with
adaptive trajectory length — the gold standard for posterior
sampling. Much slower: with the context terms, about two hours for the
IPL at 500 warmup + 500 draws per chain on a busy laptop (worst r-hat
1.02, min ESS 187, 0 divergences), so it is opt-in. The defaults are 2 chains × 1000 draws + 500 warmup, and the run
logs r-hat, ESS and divergences.

```python
kernel = NUTS(model, target_accept_prob=0.9)
mcmc = MCMC(kernel, num_warmup=500, num_samples=1000, num_chains=2)
mcmc.run(rng_key, bi=bi, ki=ki, balls=balls, runs=runs, ...)
```

ADVI is the default everywhere, including the `refresh-data`
workflow and `make refresh`. Run `scripts/scout_rate.py --sampler nuts`
when calibrated uncertainty widths matter.

### 5.5 Key snippet — the model definition

```python
def _skill(site, plate, n, sigma):
    # non-centred: site = sigma * raw, raw ~ N(0, 1)
    with numpyro.plate(plate, n):
        raw = numpyro.sample(f"{site}_raw", dist.Normal(0.0, 1.0))
    return numpyro.deterministic(site, sigma * raw)

def _model(bi, ki, balls, runs, n_batters, n_bowlers, weight=None):
    sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(1.0))
    sigma_k = numpyro.sample("sigma_k", dist.HalfNormal(1.0))
    b_skill = _skill("b_skill", "batters", n_batters, sigma_b)
    k_skill = _skill("k_skill", "bowlers", n_bowlers, sigma_k)
    intercept = numpyro.sample("intercept", dist.Normal(0.0, 3.0))
    alpha     = numpyro.sample("alpha",     dist.HalfNormal(5.0))
    mu = jnp.exp(intercept + b_skill[bi] - k_skill[ki]) * balls
    numpyro.sample("y", dist.NegativeBinomial2(mean=mu, concentration=alpha), obs=runs)
```

(Simplified from `_model` / `_runs_likelihood`: the real code also masks
edges with no legal ball and accepts an optional per-edge `weight` for
recency experiments.)

The `plate` context tells NumPyro the parameters are vectorised
(one per batter/bowler) — under the hood it generates the JAX
shape semantics correctly.

### 5.6 Output

With the dismissal-aware joint model (§5.7) each batter row also
carries `survival_skill`, each bowler row `strike_skill`, plus a
composite `value` (both axes in runs per 100 balls, a wicket priced where
the player plays; §5.7) with its `value_sd`, its two parts `value_rate` /
`value_wkts` and his `wicket_cost`. Current IPL fit, rounded:

```json
[
  {"cricsheet_id": "ba607b88", "unique_name": "V Kohli", "role": "batter",
   "skill": 0.262, "skill_sd": 0.017, "slot": 2.0,
   "survival_skill": 0.429, "survival_skill_sd": 0.067,
   "value": 13.64, "value_sd": 2.75, "value_rate": 4.64, "value_wkts": 9.00,
   "wicket_cost": 9.29, "balls": 6926, "runs": 9336},
  {"cricsheet_id": "ba607b88", "unique_name": "V Kohli", "role": "bowler",
   "skill": -0.090, "skill_sd": 0.048,
   "extras_skill": -0.116, "extras_skill_sd": 0.263,
   "strike_skill": -0.137, "strike_skill_sd": 0.069,
   "value": -23.42, "value_sd": 7.57, "value_rate": -18.98, "value_wkts": -4.44,
   "wicket_cost": 6.91, "balls": 257, "runs": 354},
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
outs_ij ~ Binomial(trials_ij,
                   sigmoid(w_int + bowl_strike[j] − bat_survive[i]))
```

`trials_ij` is the legal balls plus the rare bowler-credited dismissal off
a wide (a stumping), so a wicket can never outnumber its balls.

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

**What it fixes — current IPL fit (batting rows):**

| Player | score | survive | complete value (runs / 100 balls) |
|---|---|---|---|
| AB de Villiers | +0.36 | +0.44 | **+26.9** (elite on both) |
| V Kohli | +0.26 | +0.43 | +13.6 (anchor) |
| SP Narine | +0.45 | **−0.41** | **+0.1** (opening slogger) |

Narine scores faster than Kohli, but his poor survival pulls his
**complete batting value** down to about average, while De Villiers
(strong on both) tops the table. The same split for bowlers separates
wicket-takers (Chahal: ordinary economy, high strike) from control
bowlers (Ashwin: strong economy, below-average strike), which the old
single-skill model couldn't tell apart.

**Complete value, in runs** (`ratings/runs_value.py`). The two axes are
in different units: scoring / economy is a log runs-per-ball effect,
survival / strike a log-odds dismissal effect. The question that joins
them is what a wicket costs in runs, and that depends on when it falls.

1. *Wicket cost.* From first innings of full-length, non-rain matches,
   runs and wickets per ball by (over, wickets down), smoothed as an over
   level × a wickets-down factor per phase. A backward recursion gives
   the expected runs still to come, `V(b, w) = r + p·V(b+1, w+1) +
   (1−p)·V(b+1, w)`, and a wicket on ball b with w down costs
   `λ(b, w) = V(b+1, w) − V(b+1, w+1)` (the DP behind Duckworth–Lewis
   resources and "dismissal-adjusted runs", arXiv:2608.18020). IPL: ~14
   runs in the powerplay with few down, 7–8 in the middle, 2–3 at the
   death.
2. *His wicket cost.* λ averaged over the states he actually played in,
   each ball weighted by the chance of a wicket there, per phase × innings.
3. *Per posterior draw*, with league runs per ball `r`, dismissal rate
   `q` and his share of balls `π` per phase × innings, `m` his run-rate
   multiplier against the average ball and `Δs` his survival against it:
   `batting = 100 · Σ π [r (m − 1) − λ (σ(logit q − Δs) − q)]`; bowling
   uses runs saved `R (1 − m)` (wides and no-balls in `R`) plus
   `λ (σ(logit q + Δt) − q)`. Re-centred so the league's balls average 0.

So `value` = **runs per 100 balls above the league's average ball**.
Kohli: +4.6 from scoring + 9.0 from staying in (wicket cost 9.3) =
+13.6. Dhoni: −6.8 + 7.9 (wicket cost 4.7) = +1.1 — he rarely gets out,
but at the death that's worth little. The earlier value divided each axis
by its population sd and added them with equal weight, which made Dhoni
the best active IPL batter; that is what this replaced (roadmap review
item 14). Doing it per draw keeps `value_sd` honest. This is what the
Head-to-Head page (`ratings/head_to_head.py`), the scout z-scores (§7) and
the auction prices (§8) are built on.

### 5.8 Context, dispersion, role priors and extras (the shipped model)

Four changes turn the model above into the one `fit()` runs by default
(`variant="v2"`; `variant="legacy"` is §5.2, kept to measure the changes):

```
cell = (batter i, bowler j, season s, phase p, innings c, venue v)

runs ~ NegBin(mean = exp(r0 + ctx_r + b_skill[i] − k_skill[j]) · balls,
              concentration = alpha · balls)                     # (2)
outs ~ Binomial(trials, sigmoid(w0 + ctx_w + bowl_strike[j] − bat_survive[i]))
ctx  = season[s] + phase[p] + innings[c] + venue[v]              # (1)
season[s] = season[s−1] + tau · z_s,   season[first] = 0          # random walk
venue[v]  = sigma_v · z_v                                          # hierarchical

b_skill[i] = mu_slot[slot(i)] + sigma_b · z_i                     # (3)
k_skill[j] = mu_role[role(j)] + sigma_k · z_j

extras_js ~ NegBin(exp(x0 + x_season[s] − bowl_extras[j]) · deliveries_js,
                   alpha_x · deliveries_js)                        # (4)
```

1. **Context.** A season level per league (a random walk, so the model
   learns how fast scoring drifts; the IPL's 2026 runs-per-ball level sits
   ~20% above 2008), phase (death overs score ~50% more per ball than the
   powerplay and lose wickets about twice as often), innings and ground.
   Each player is judged against his own context.
2. **Dispersion ∝ balls.** With one `alpha`, a cell's variance grew with
   balls², so a 150-ball cell looked as noisy as 150 one-ball cells and the
   best evidence was under-weighted. `concentration = alpha · balls` makes
   variance = mean · (1 + rate/alpha): linear in balls, as a sum of balls
   should be.
3. **Role-level prior means.** Batters shrink toward their batting slot's
   mean (1–3, 4–5, 6–7, 8–11, from the median position in the data;
   the tail sits 0.50 below the top order on the log scale), bowlers toward
   frontline or part-timer (15+ deliveries per match bowled). A thin-sample
   tail-ender is no longer an "average batter".
4. **Extras.** Wides and no-ball runs per delivery get their own bowler
   skill; the reported economy `skill` is the log of total runs conceded per
   ball (off the bat + extras) against the average bowler's, and its
   population sd combines both parts.

`scripts/scout_rate.py` writes the fitted context to
`scout_context_<col>.json`; `bayesian.heldout_loglik` scores a later season
ball by ball, which `scripts/backtest_ratings.py --compare legacy` uses to
compare the two variants.

### 5.9 Does it predict? (the backtest, in brief)

Walk-forward: fit on matches before a season, rank players, compare with
the season (Spearman). 3 ADVI seeds; the newcomer baseline gets the same
league centring and tier discount as the model; leagues pooled by
precision; 2,000 bootstrap resamples with Holm-adjusted p over six tests.

- Established IPL players, 2021–26, overall in runs: batters 0.19 vs
  0.15 (career average), bowlers 0.15 vs 0.11 (with the earlier sd-sum
  value and z-sum target: 0.14 vs 0.15 and 0.12 vs 0.07). Held-out log-likelihood per ball beats
  the legacy model in every season (runs −0.6212 vs −0.6255, dismissals
  −0.1467 vs −0.1480).
- IPL newcomers rated from other leagues, 2014–26, overall in runs:
  batters 0.08 vs 0.10 and bowlers 0.22 vs 0.26 (all 13 leagues); with
  the original five, batters 0.11 vs 0.06 (model ahead in 78% of
  resamples) and bowlers 0.22 vs 0.25. Every Holm p is 1.0.

So the ratings beat career averages for established IPL players but are
no better than a newcomer's own league-adjusted numbers. The earlier
newcomer-batter edges (first the "97% of re-draws" survival edge, which
was the league discount; then a 96–98% overall lean, which came from the
old sd-sum value) don't survive. Full tables in [METHODOLOGY §8](METHODOLOGY.md#8-does-it-predict-the-backtest).

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

The model is a binary XGBoost booster — given the game state at
ball `t`, predict `P(batting team wins eventually)`. A tie is labelled 0.5
(the cross-entropy objective takes fractional labels); no-results are dropped.

**Features (12).** All numeric, all known *before* the delivery
(T20 only; innings 0 = first, 1 = chase; super overs dropped):
- `innings_idx` (0 or 1)
- `balls_remaining` — scheduled legal balls minus legal balls bowled
  (the DLS-revised ball count in a rain-hit chase)
- `wickets_left` (retired hurt isn't a wicket)
- `score_before` this ball
- `target` (the recorded chase target; 0 in the first innings)
- `runs_needed` (target − score; 0 in the first innings)
- `required_rr` (runs/over needed to chase)
- `current_rr` (runs per legal over so far)
- `current_rr_minus_venue` — how far above/below the ground's average
  first-innings run rate, from the training matches only
- `rr_vs_league`, `target_vs_par`, `rrr_vs_league` — the current rate,
  the target and the required rate against the league's recent scoring
  level (first-innings run rate over the previous 60 matches). Relative
  numbers carry over to a new high-scoring season; a raw scoring level
  doesn't (trees can't extrapolate past the highest value they saw).

**Monotone constraints.** `balls_remaining`, `wickets_left`, `score_before`,
`current_rr`, `current_rr_minus_venue`, `rr_vs_league` can only raise the
batting side's WP; `target`, `runs_needed`, `required_rr`, `target_vs_par`,
`rrr_vs_league` can only lower it. Unconstrained, 3.9% of IPL wicket balls
(no run scored) *raised* batting WP; constrained, 0.01%.

**Holdout split — match-id, not ball-id.** If you split balls randomly,
the model sees balls 1-99 of a match in training and ball 100 in
validation — trivial leakage. The *reporting* model splits matches
70/15/15: train, calibration (early stopping + calibration) and test —
accuracy, Brier, log loss, ECE and reliability are reported on the test
matches only.

**Out-of-fold scoring.** The NGI numbers don't come from that model.
Matches are dealt into 5 folds; each fold is scored by a model trained
on the other four (early-stopped and calibrated on an inner 15% of
their matches). So every ball's ΔWP comes from a model that never saw
its match. The scored balls are cached per league
(`data/metrics/.ngi_cache/`) and the time-window / era boards reuse them.

```python
params = {"objective": "binary:logistic", "max_depth": 6, "eta": 0.05,
          "subsample": 0.9, "colsample_bytree": 0.9, "tree_method": "hist",
          "monotone_constraints": "(0,1,1,1,-1,-1,-1,1,1,1,-1,-1)"}
xgb.train(params, dtrain, num_boost_round=600, evals=[(dcal, "cal")],
          early_stopping_rounds=30)
```

### 6.3 Smooth (beta) calibration

The raw probabilities are good rankings but not exact probabilities.
CricDesk calibrates them with **beta calibration** (Kull et al. 2017):
`logit(p_cal) = a·ln p − b·ln(1 − p) + c`, fitted by Newton's method on
the calibration matches, with `a, b ≥ 0` so it stays monotone. It used to
be isotonic regression, a step function: two states on one step get the
same probability, so ΔWP reads exactly 0, and swings jump at step edges.
Every NGI number is a difference of two probabilities, so this matters:
on the IPL, balls with ΔWP exactly 0 fell from 70% to 23% (the rest are
the trees' own steps), with log loss 0.542 vs 0.548 and ECE 0.024 vs 0.024.

### 6.4 ΔWP and its credit

For each ball the model predicts four states: before; after the runs off
the bat and the legal ball used; after the wicket too; after everything.

```
play   = WP(bat)   − WP(before)
wicket = WP(mid)   − WP(bat)
extras = WP(after) − WP(mid)
```

Terminal correction: at the last ball of the **chase**, `wp_after` is the
result (1, 0, 0.5 for a tie). At the last ball of the **first innings**,
`wp_after = 1 − WP` of the chase's opening state. The correction joins the
part with the largest magnitude on that ball.

Credit (batting side's view; the fielding side gets the opposite sign):
- striker: `play` (a wide's play part is 0 — not a ball faced)
- the batter who is out (`player_out`, the non-striker in a run out at his
  end): `wicket`
- bowler: `−play − extras × (wides + no-ball runs) / all extras − w · wicket`
- each named fielder: `−f · wicket / n_fielders`

with `(w, f)` = (1, 0) for bowled / lbw / hit wicket / caught and bowled,
(0.8, 0.2) for caught / stumped, (0, 1) for a run out, (0, 0) for retired
out / obstructing. Byes, leg-byes and penalty runs go to nobody.

### 6.5 Career aggregation

Every credit row is `(match, player id, bat, bowl, field)`; a career sums
them into `ngi_batting`, `ngi_bowling`, `ngi_fielding` and `ngi_total`.
`matches` is **appearances**: places in the playing XI
(`match_players_<col>`) in the matches scored, plus any match the player
took part in without being listed (a substitute fielder), and

```
ngi_per_match = ngi_total / matches
```

`ngi_per_match` is the headline — `+0.05` means the player adds an
average of 5 percentage points to his team's win probability per match
he plays. `scripts/compute_metrics.py ngi-diagnostics -c ipl` prints the
before/after checks quoted above.

---

## 7. Scout — cross-competition look-alikes

Scout answers "who plays like X, that I could realistically sign?"
across six competition pools (IPL, SMAT, BBL, SA20, CPL, T20 Blast).
It is **file-driven** — DuckDB + an exported JSON index, no graph
database — and shares one implementation with the web via
`cricdesk.web_parity` (a Python port of `site/src/pages/Scout.tsx`,
locked by `test_scripts/test_web_parity.py`).

### 7.1 The look-alike formula

The hard part of cross-competition comparison is that raw numbers
aren't comparable — a SMAT strike rate and an IPL strike rate measure
different attacks. So each player is reduced to a **within-tier
skill-standing z-score** off the dismissal-aware Bayes skill (§5): how
many standard deviations above his own competition's mean does he
stand? A SMAT prospect and an IPL star can then be lined up despite
incomparable raw stats. Concretely: each player's standing is his Bayes
`value` on the role he's matched in (batters and keepers on batting value,
bowlers on bowling value, all-rounders on both added), z-scored among the
players of that role shown in that tier (recently active, ≥150 balls).
Candidates must share the picked player's role (from the AI-classified
taxonomy) and, for bowlers, seam or spin; an optional batting-slot filter
narrows further. Similarity is `max(0, 1 − |z_cand − z_pick| / 2.5)`.

### 7.2 The three tiers + pricing

For an active IPL pick, Scout surfaces three tiers in order: similar
**IPL peers**, then uncapped **SMAT** prospects, then overseas options
(**BBL / SA20 / CPL / T20 Blast**). Each row carries:

- an **estimated crore price** from the Auction room's skill→price
  curve (a shared `estValue`, tier-discounted so SMAT/BBL is comparable
  to IPL),
- the **saving** vs the picked player (budget swap),
- an uncapped-**gem** flag: z ≥ 0.6 on at most the median SMAT
  exposure (balls), i.e. high standing on a small sample (the moneyball
  signal),
- **role / batting-slot** filters to narrow or re-target a tier,
- a one-click **Draft** that drops the prospect into the Auction room
  as a retention (`/auction?draft=<id>`).

The scout index emits per-player `balls` for the gem cutoff. The CLI
entry point is `cricdesk scout look-alikes`; the same view ships on the
web, Streamlit, and the TUI **Scout** tab.

### 7.3 Style twins (Player Profile)

Separately from the cross-competition look-alikes, every Player Profile
shows **style twins** (`scout/search/style_twin.py`): the players whose
game looks most like his, built from the ball-by-ball. Batters: slot,
powerplay / death share, tempo by phase against par, boundaries, dots,
rotation, six share, spin against pace, risk, batting hand. Bowlers:
powerplay / death share, economy by phase against par, strike, dots,
boundaries, wicket types, pace and arm. Robust z-scores after
shrinking thin samples, fixed weights, an evidence bar, and gates (an
opener's twins are openers; a seamer's are seamers; a wrist spinner's
are wrist spinners first). "% alike" = 100 × (1 − weighted RMS z-gap ÷
2). Purely descriptive: style, not quality. Full method: METHODOLOGY §5a. The profile also shows a
**co-faced cohort** (`scout/cohort.py`): batters who faced the most of
the same bowlers, or bowlers who bowled to the most of the same batters,
computed in plain DuckDB SQL (it replaced the old graph traversal).

---

## 8. Auction room — `auction/` + `web_parity/auction.py`

The auction is a **real-rules IPL auction Monte-Carlo** — a market
simulation, not a squad optimiser. The same logic runs in the browser
(`site/src/lib/auction.ts`) and on the CLI / TUI / Streamlit (Python,
`cricdesk.web_parity`), over the **same** exported JSON and with a
**bit-exact seeded LCG RNG**, so a run reproduces everywhere
trial-for-trial (locked by `test_scripts/test_web_parity.py`). The CLI
entry point is `cricdesk auction room`. The plain-words walkthrough is
in [`AUCTION_MATH.md`](AUCTION_MATH.md); this section is the technical
summary.

### 8.1 Skill → crore price

The pool has skill but no cost, so step zero invents a fair price from
skill, calibrated to recent real auctions:

```
projected = clamp(4.03 · e^(0.0743 · (value − 0.5 · value_sd)) · roleMult, 0.3, 27)
```

`value` is the Bayes complete value in runs per 100 balls (§5.7), priced
on the cautious estimate `value − 0.5 · value_sd` (`PRICE_CAUTION_SD`), so a
thin record is priced below a proven one of the same central value, and
under a ceiling `27 · (0.5 + 0.5 · min(1, IPL balls in the role / 600))`
(13.5 cr with no IPL balls, 27 cr from 600). The
`0.0743` stretches the curve so the spread matches recent money (top
names in the 20s of crore, 27 cr — the 2025 ceiling — as the cap; the
typical pool player about 1.2 cr). (A hand-set `roleMult`, all-rounders
×1.15 and keepers ×1.05, was removed on 2026-10-22: an all-rounder's second
discipline counts in his contribution per match, METHODOLOGY §6c.) The two constants were
re-fitted when `value` moved to runs and the cautious price went in: same pool median and same number
of 10 cr+ players (25) as the earlier `1.1 · e^(0.95 · value)` on the
sd-unit value (docs/AUCTION_MATH.md). (Until 2026-10-22 the export also
took up to 36 runs per 100 balls off a player who hadn't featured in the
IPL lately, a hand-set IPL-relevance discount; it is replaced by a fitted
P(plays), below.) The opening **base price** snaps to the real IPL bands (0.3 /
0.5 / 0.75 / 1.0 / 1.5 / 2.0 cr) by projected price (<2, <4, <7, <11,
<16, else).

### 8.2 The cross-collection pool

The pool is the active T20 world, not just past IPL squads:

- **IPL players** — retainable, each carrying his current franchise.
- **Free agents** — overseas via BBL / SA20 / CPL / T20 Blast, and
  uncapped Indians via SMAT.

Guardrails: active only (last ~3 yrs), associate/non-IPL-nation free
agents excluded, the top 600 by **expected season value** (P(plays a
match) × runs above a replacement a match, both disciplines at the balls
he gets; `scout/playing_time.py`, METHODOLOGY §6c),
and a **tier penalty** applied to cross-tier value before pricing (in
runs per 100 balls: BBL −6.0, SA20 −6.0, CPL −8.5, T20 Blast −8.5, SMAT
−17.0; IPL 0 — the earlier sd-unit discounts × 13.3). A player in several leagues gets one value per role: his
IPL rating if he has 300+ IPL balls in that role, otherwise a blend of
his leagues weighted by 1 ÷ (rating sd² + tier `translation_sd`²).

### 8.3 Retentions, then bidding

**Retentions** are editable per team. Mega = the real 2025 retention
lists (~5 players), charged to the 120 cr purse at the real retention
price where known, else the slabs (18 / 14 / 11 / 18 / 14 cr, then 4 cr);
Mini = each team keeps its 18 most valuable players free and bids only a
small leftover purse (30 cr by default). Retained players leave the
pool and count toward the overseas cap (8).

**Bidding** (since 2026-10-23) runs over as many lots as real
shortlists held for the open squad places (`LOTS_PER_PLACE`: 4.6 a place
in a mini auction, 3.0 in a mega; at most `OVERSEAS_SHARE` 35.7%
overseas), capped sets before uncapped, dearest first, unsold lots once
more in an accelerated round. For each lot every team with a place, an
overseas place if needed and the purse for his base price draws whether
it bids at all (a logistic in his market and base price and its needs)
and how high: `ln bid = mu + heat + σ × Gumbel`, with `mu` from his
market, base and last price, the money per open place across the
market, the stage, and the team's places short in his role, open
overseas places, purse per place against the others' and the upgrade he
would be (`DEMAND`, fitted by `scripts/auction_demand_fit.py` on every
sold lot of 2019–2026 with each team's squad and purse rebuilt lot by
lot; METHODOLOGY §7). It's bounded by spendable money (remaining purse
minus the lowest base price for each place still needed to reach 18).
The highest bid wins at **the next IPL ladder step above the
second-highest** (`ladder_next`), never below base; no price cap. A team
still short of 18 at the end buys the cheapest leftovers at base. The
hand-set personalities, need 1.5 / 0.7, budget pressure, 1.02 clearing
and the two-phase fill are gone.

### 8.4 ~300 trials + post-sim search

One mock auction is run ~300 times (trial `t` seeded `1000 + 7919·t`),
then averaged: each team's typical spend / squad size / value /
overseas count, and for each star the **% of trials each team won him**
("Bumrah → MI 62%, CSK 21%"). The sim emits a per-player `outcomes`
summary across all trials, which powers a **post-sim search** (web,
Streamlit, and the TUI Auction tab): after a run, look up any player —
retained (by which team), sold (most-likely buyers, sold-%, avg price),
or unsold. The RNG is seeded, so identical settings reproduce identical
results.

---

## 9. Wikidata bridge — `scout/ingest/wikidata.py`

The data layer ran into a fun infrastructure problem worth knowing
about.

### 9.1 The blocker

Wikidata's SPARQL endpoint (`query.wikidata.org`) returns HTTP 429
(Too Many Requests) from datacenter IPs — they have a separate
rate-limit pool for datacenter traffic, and the pipeline ran on a
cloud VM.

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
touching SPARQL. Of the 342 players cached today, 331 resolved.

### 9.3 Fallback — name search

For players without a Statsguru hit we fall back to `wbsearchentities` (free-text
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
identical logic on every surface via `cricdesk.web_parity`.

### 10.1 CLI — `cricdesk/cli/`

`typer`-backed console script; full reference in `docs/CLI.md`. Every
command renderer uses the shared `_render.py` helpers (Rich Panels,
`pretty_table`, `bayes_sentence`, `wikidata_block`, `sparkline`,
`spinner`) and pulls explainer strings from `_copy.py` so the prose
stays at parity with the Streamlit dashboard.

### 10.2 TUI — `cricdesk/cli/tui.py`

Textual app whose 14 tabs mirror the web pages: Leaders, Records,
Compare, H2H, Matchups, Phase, Form, Partners, Aging, Venues, Profile,
Auction (with the post-sim player search + Mega/Mini toggle), Scout,
and Update (buttons that shell into `data_cmd.run_ingest` and re-export).

Default behaviour: `cricdesk` (no args) launches TUI. `cricdesk
--help` lists subcommands as before.

### 10.3 Streamlit dashboard — `cricdesk/dashboard/`

Home + 14 pages mirroring the web + TUI: Leaderboards, Records,
Head-to-head, Compare, Venues, Auction, Player Profile, Scout, Update
Data, Matchups, Phase, Form, Partnerships, Aging. Same `_widgets.py`
helpers (`player_select`, `player_multiselect`, `collection_picker`,
`provenance_banner`) across pages so the chrome stays uniform.

### 10.4 FastAPI — `cricdesk/api/`

REST endpoints (records / venues / players / compare / NGI) over the
local DuckDB + OpenAPI at `/docs`. Public surface for programmatic access. Currently no auth
(auth + rate limiting are on the [roadmap](ROADMAP.md#later) before any public deploy).

---

## 11. Deployment + CI/CD

### 11.1 GitHub Actions

Workflows in `.github/workflows/`:

- `ci.yml` — pre-commit (ruff lint + format) + pytest (including the
  `test_scripts/` web ↔ Python parity tests, which need Node) + a
  TypeScript type-check of `site/`, on every push / PR to main.
- `deploy.yml` — builds the static `site/` and publishes it to
  GitHub Pages on pushes touching `site/**`.
- `docker.yml` — builds the Docker image (nothing is pushed) when
  anything that goes into it changes, to prove it still builds.
- `refresh-data.yml` — manual ("Run workflow"): re-download all 8
  collections, recompute metrics + ratings, re-cook the snapshot, run
  the LLM taxonomy only if the `LLM_MODEL` secret is set, commit, then
  call `deploy.yml` to redeploy.

### 11.2 Docker

`docker-compose.yml` brings up the app for local dev / the pipeline.
The stack is file-driven (DuckDB + exported JSON), so there is no
vector or graph DB service. `make docker-up` builds + runs it.

### 11.3 Persistence

`data/` is gitignored except the curated player facts
(`data/curated/player_taxonomy.json`, `wikidata_enrichment.json`). The
DuckDB, metrics and Bayes JSONs can always be rebuilt from Cricsheet
(`make refresh COLLECTION=<c>`), and the exported snapshot in
`site/public/data` is committed.

---

## 12. Roadmap

What's shipped, next, later and out of scope lives in one place:
[`ROADMAP.md`](ROADMAP.md). In short: CricDesk is deliberately
**Cricsheet-only** (scrapes, live feeds and the LLM-written features
built on them were removed, not deferred); fielder credit in NGI and
season / phase / innings / venue effects in the ratings have shipped;
near-term work is a joint multi-league fit, a runs-currency value and
women's collections; grassroots data,
auction self-play and the video / voice modules are year-2.

---

## Appendix A — How the pieces connect

A worked example: "Who plays like Kohli that I could realistically
sign?"

1. **CLI / TUI / web** call the Scout look-alike search for "V Kohli"
   in `cricdesk.web_parity` (the same code the React `Scout.tsx` page
   runs), reading the exported `scout_index.json`.
2. Kohli's archetype (role + seam/spin) is read from the LLM
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

End of guide. Open [`METHODOLOGY.md`](METHODOLOGY.md) for the
plain-English version with the backtest results, and
[`METRICS.md`](METRICS.md), [`SCOUT.md`](SCOUT.md),
[`AUCTION_MATH.md`](AUCTION_MATH.md), [`DECISIONS.md`](DECISIONS.md) and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for narrower deep-dives on specific
subsystems.
