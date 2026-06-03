# CricMetrics — methodology

Standard cricket scorecards (average, strike rate, economy) are
context-blind: a 25-ball 40 in a slack chase scores the same as a
25-ball 40 chasing 12 an over. The metrics in this module are designed
to put context back in. Every formula is computable directly from
Cricsheet ball-by-ball data — no scraping, no proprietary feeds.

All metrics output a polars DataFrame and are dumped to
`data/metrics/<slug>_<collection>.json` for the dashboard to consume.

---

## Pressure Runs — `cricdex.metrics.batter.pressure_runs`

**What it captures:** runs scored by a batter on chase deliveries where
the required run rate per ball is meaningfully higher than the venue
historically demands at the same phase.

**Computation:**
1. For each 2nd-innings ball in T20 / ODI matches:
   - `runs_needed = (1st_innings_total + 1) − runs_before_ball`
   - `balls_remaining = innings_balls_allotted − balls_bowled_before`
   - `required_rpb = runs_needed / balls_remaining`
2. Compute `median_required_rpb` per (venue, phase) across the whole
   collection.
3. A ball is **under pressure** if
   `required_rpb > 1.5 × median_required_rpb(venue, phase)`.
4. Aggregate per batter: `pressure_balls`, `pressure_runs`,
   `pressure_sr_per_100_balls`, `pct_balls_under_pressure`.

**Why 1.5× venue median (not absolute threshold):** different venues
demand wildly different chase rates (Bangalore vs Lord's). The venue's
own historical median normalises that out — "pressure" means hard
*for that ground*, not above some hand-picked global cut-off.

**Why chase-only:** required RPB has no clean definition outside a
chase, so Pressure Runs only covers the second innings. A
batting-first pressure counterpart isn't yet shipped (Crease Longevity
and Slow-Start Cost measure crease longevity and slow starts, not
batting-first chase pressure — see below).

**CLI:** `make docker-pressure-runs COLLECTION=ipl TOP_N=50`

---

## Intent Curve — `cricdex.metrics.batter.intent_curve`

**What it captures:** how a batter's strike rate changes as they spend
more time at the crease. Slow starters who heat up look very different
to immediate aggressors.

**Computation:**
1. For each (batter, innings) compute `balls_faced_to_date` per ball.
2. Bucket: `0-5`, `6-10`, `11-20`, `21-30`, `31-50`, `51+`.
3. Per (batter, bucket): `SR = 100 × runs / legal_balls`.

**Reading:** rising curve = grower; flat-high = aggressor;
flat-medium = grinder; falling = tires.

**Filter:** `min_balls_in_bucket` (default 200) so single innings don't
dominate.

**Web leaderboard:** intent_curve is a *shape*, not a per-player ranking,
so the static site pivots it to one row per batter — ranked by **early SR**
(the balls-weighted SR over balls 1–10, i.e. who comes out firing) with the
full 6-bucket curve drawn as an inline sparkline. A naive sort on raw bucket
SR instead duplicated each batter across buckets and let late-innings
buckets (plain strike rate, once set) dominate the top.

---

## Dot-Ball Recovery — `cricdex.metrics.batter.dot_ball_recovery`

**What it captures:** a batter's ability to re-engage after a dot ball.
Mental-reset proxy.

**Computation:**
1. Identify every dot ball faced by the batter.
2. For each, sum the runs they scored in the *next 6 balls they faced*
   in the same innings.
3. Aggregate per batter: `runs_per_6_after_dot = 6 × Σruns / Σfollowing_balls`.

**Reading:** a value of 9 means the batter averages 9 runs over the
next 6 balls after eating a dot — strong re-engagement. A value of 4
means the dot tends to spread into more dots.

**Filter:** `min_dot_balls` (default 100) for sample-size safety.

---

## Counter-Attack Coefficient — `cricdex.metrics.batter.counter_attack_coefficient`

**What it captures:** the surviving batter's strike rate in the 12
balls immediately after a *partner* wicket. Quantifies who absorbs
collapse pressure vs who freezes.

**Computation:**
1. For each ball where a wicket fell, mark the next 12 balls in the
   same innings.
2. For each such ball, attribute the runs to the batter facing —
   *excluding* the dismissed striker (so we measure the survivor, not
   the new arrival who's still gauging conditions).
3. Aggregate: `counter_attack_sr = 100 × runs / legal_balls`.

**Filter:** `min_partner_wickets` (default 20).

---

## Boundary Dependency Ratio — `cricdex.metrics.batter.boundary_dependency`

**What it captures:** what fraction of a batter's career runs come
from boundaries vs running between wickets.

**Computation:** `bdr_pct = 100 × Σrunsfrom4or6 / Σruns`.

**Reading:** high BDR = boundary-or-bust profile, vulnerable when the
boundary isn't there (small grounds shrink, bowlers wide); low BDR =
rotator who keeps the strike turning. Neither is "better" — the metric
exists to distinguish *style*.

**Filter:** `min_runs` (default 200).

---

## Pressure Conversion — `cricdex.metrics.bowler.pressure_conversion`

**What it captures:** a bowler's wicket rate on the delivery immediately
after building a streak of 4+ consecutive dots in the same over.

**Computation:**
1. Walk every over delivered by each bowler, tracking running
   `streak_len` of consecutive dot balls.
2. When `streak_len ≥ threshold` (default 4), look at the next
   delivery in the same over.
3. Wicket rate = wickets on that "post-pressure" ball ÷ total
   post-pressure balls.

**Why "same over":** the streak resets across overs because the field +
batter context is different. Within an over the bowler is genuinely
sustaining the pressure.

**Reading:** different from raw economy — a tight 4-dot bowler who
never converts the pressure into a wicket scores low here even though
their economy looks great.

**Filter:** `min_pressure_balls` (default 30).

---

## Shipped after v1

- **NGI (Net Game Impact)** ✅ — WPA-style player impact. XGBoost
  win-probability model trained on Cricsheet ball-by-ball,
  isotonically calibrated, per-ball ΔWP credited to batter (+) and
  bowler (−). Career table at `data/metrics/ngi_<collection>.json`,
  dashboard tab "NGI (Net Game Impact)".
- **Wicket Quality** ✅ — Σ(opponent Bayes skill) / wickets taken.
  Lives in `cricdex.metrics.bowler_wicket_quality`. Needs the
  scout NumPyro ratings (`scout_ratings_<collection>.json`) — see
  `docs/SCOUT.md`.
- **Crease Longevity** ✅ — crease longevity: a batter's average balls
  faced per dismissal divided by the cohort average. >1 = bats longer
  than the typical qualifying batter; <1 = shorter, higher-tempo
  innings. Lives in `cricdex.metrics.batter`.
- **Slow-Start Cost** ✅ — career strike rate minus strike rate over the
  first 20 balls of an innings. Positive = slow starts cost tempo;
  ~0 or negative = aggressive from ball one. Lives in
  `cricdex.metrics.batter`.

## Still planned

- **Replacement Delta** — NGI − NGI of a replacement-level domestic
  player. Cricket WAR. Sits on NGI (✅) plus a domestic-tier baseline;
  deferred until a sub-IPL tier exists to define replacement
  (`docs/DEFERRED.md` §grassroots).
- **Disguise Coefficient** (bowler) — outcome variance for same
  line / length. Needs CV-derived release-point data (OpenBoundary,
  `docs/DEFERRED.md` §cv).

---

## Output schema

Every metric writes a flat JSON list of records. Columns documented in
each metric function's docstring and in `cricdex/metrics/README.md`.
The Streamlit dashboard auto-discovers any
`data/metrics/<slug>_<collection>.json` file.
