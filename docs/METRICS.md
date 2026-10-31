# CricMetrics — formulas

The plain-English version of every metric, with worked examples, is in
[METHODOLOGY.md §3](METHODOLOGY.md#3-the-nine-context-metrics--fielding); this page is the
reference: exact computation, filters and output columns.

Standard cricket scorecards (average, strike rate, economy) are
context-blind: a 25-ball 40 in a slack chase scores the same as a
25-ball 40 chasing 12 an over. The metrics in this module are designed
to put context back in. Every formula is computable directly from
Cricsheet ball-by-ball data — no scraping, no proprietary feeds.

All metrics output a polars DataFrame and are dumped to
`data/metrics/<slug>_<collection>.json`; `scripts/export_site.py` then cooks
them into the `site/public/data/<collection>/leaderboards/` snapshot that the
web app, dashboard, TUI and leaderboard CLI read.

---

## Pressure Runs — `cricdesk.metrics.batter.pressure_runs`

**What it captures:** runs scored by a batter on chase deliveries where
the required run rate per ball is meaningfully higher than the venue
historically demands at the same phase.

**Computation:**
1. For each 2nd-innings ball in T20 / ODI matches:
   - `runs_needed = (1st_innings_total + 1) − runs_before_ball`
   - `balls_remaining = innings_balls_allotted − legal_balls_bowled_before`
   - `required_rpb = runs_needed / balls_remaining`
2. Compute `median_required_rpb` per (format, venue, phase) across the
   whole collection — a T20 and an ODI chase at the same ground aren't
   one benchmark.
3. A ball is **under pressure** if
   `required_rpb > 1.5 × median_required_rpb(format, venue, phase)`.
4. Aggregate per batter: `pressure_balls`, `pressure_runs`,
   `pressure_sr_per_100_balls`, `pct_balls_under_pressure`. Wides aren't
   balls faced; no-balls are. Filter: `min_balls_faced` (default 20 chase
   balls).

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

## Intent Curve — `cricdesk.metrics.batter.intent_curve`

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

## Dot-Ball Recovery — `cricdesk.metrics.batter.dot_ball_recovery`

**What it captures:** a batter's ability to re-engage after a dot ball.
Mental-reset proxy.

**Computation:**
1. Identify every dot ball faced by the batter (no runs off the bat, not
   a wide or no-ball).
2. For each, sum the runs they scored off the bat over the *next 6
   deliveries they were on strike for* in the same innings (wides
   included; a ball inside two dots' windows counts for both).
3. Aggregate per batter: `runs_per_6_after_dot = 6 × Σruns / Σfollowing_balls`.

**Reading:** a value of 9 means the batter averages 9 runs over the
next 6 balls after eating a dot — strong re-engagement. A value of 4
means the dot tends to spread into more dots.

**Filter:** `min_dot_balls` (default 100) for sample-size safety.

---

## Counter-Attack Coefficient — `cricdesk.metrics.batter.counter_attack_coefficient`

**What it captures:** the surviving batter's strike rate in the 12
balls immediately after a *partner* wicket. Quantifies who absorbs
collapse pressure vs who freezes.

**Computation:**
1. For each ball where a wicket fell, mark the next 12 balls in the
   same innings.
2. For each such ball, attribute the runs to the batter facing — only
   the batter who was already at the crease when the wicket fell (not
   the dismissed one, not the new arrival who's still gauging
   conditions). A ball after two quick wickets counts once.
3. Aggregate: `counter_attack_sr = 100 × runs / legal_balls`.

**Filter:** `min_partner_wickets` (default 20) — partner wickets the
batter has survived.

---

## Boundary Dependency Ratio — `cricdesk.metrics.batter.boundary_dependency`

**What it captures:** what fraction of a batter's career runs come
from boundaries vs running between wickets.

**Computation:** `bdr_pct = 100 × Σrunsfrom4or6 / Σruns`.

**Reading:** high BDR = boundary-or-bust profile, vulnerable when the
boundary isn't there (small grounds shrink, bowlers wide); low BDR =
rotator who keeps the strike turning. Neither is "better" — the metric
exists to distinguish *style*.

**Filter:** `min_runs` (default 200).

---

## Pressure Conversion — retired 2026-10-29

Wicket rate on balls bowled after a pressure spell. The v1 board counted the ball after 4+ dots inside
one bowler's over (a handful of chances a season); `cricdesk.metrics.bowler.pressure_conversion` now
counts every ball after the batting side's 4+ ball drought (no run, no wicket, across overs and
bowlers), shrunk toward the league rate by a fitted beta-binomial prior (`conversion_pct`; raw
`wicket_rate_pct`, `league_pct`, `prior_balls`). Even so the fitted spread between bowlers is zero and a
player's odd and even matches don't agree (split-half r −0.18), so no board is published.

---

## Dot-Ball Avoidance — `cricdesk.metrics.splits.dot_avoidance`

Per batter, over legal balls faced (wides excluded): `dots_avoided_raw` = 100 × mean(league dot rate in
the ball's phase − dot), `dots_avoided_per100` = that shrunk toward 0 (`_shrink`: × n / (n + k),
k = per-ball residual variance ÷ the spread of true player means, method of moments). Also `dot_pct`,
`expected_dot_pct`, `balls`. Minimum 150 balls (last 3 yrs 100, last year 60). Split-half r 0.70.

## Pace vs Spin — `cricdesk.metrics.splits.pace_spin`

Per batter, against each bowling type (player master `bowling_category`: seam / spin): runs per 100
balls above the league against that type in the same phase (`above_vs_spin(_raw)`,
`above_vs_pace(_raw)`, each shrunk as above, τ² fitted on players with the minimum), strike rates and
balls. `spin_edge` = (raw spin − raw pace) × τ² / (τ² + its noise), its noise s²_spin/n_spin +
s²_pace/n_pace and τ² the spread of true edges (`_shrink_edge`); `spin_edge_raw` unshrunk. Minimum 100
balls against each (70 / 40). Split-half r 0.37 (0.66 for scoring against spin alone).

## Finisher Index — `cricdesk.metrics.splits.finisher`

Per batter, legal balls faced in overs 17–20 of the second innings: `above_raw` = 100 × mean(runs − the
league's average in that over of a chase), `above_per100` shrunk as above; `sr`, `balls`, `innings`
(chases he faced a ball in those overs) and `not_out_pct` (of those, not dismissed). Minimum 40 balls
(25 / 15). Split-half r 0.44.

## Left vs Right — `cricdesk.metrics.splits.hand_split`

Per bowler, legal balls against each batting hand (player master `batting_hand`): runs saved per 100
balls against the league on that hand in the same phase (`saved_vs_left(_raw)`, `saved_vs_right(_raw)`,
each shrunk), balls against each; `left_edge` = left − right shrunk as a difference (`_shrink_edge`).
Minimum 90 balls against each hand (60 / 36). Split-half r 0.30, the weakest that passed.

---

## Shipped after v1

- **NGI (Net Game Impact)** ✅ — WPA-style player impact. XGBoost
  win-probability model trained on Cricsheet T20 ball-by-ball (only
  information known before each delivery, including three features relative to the league's
  recent scoring level), with monotone constraints and smooth beta calibration; ties are labelled
  0.5. Every ball is scored **out of fold** (5 folds by match: a model that never saw that match);
  a separate 70 / 15 / 15 split reports accuracy, Brier, log loss and ECE. Each ball's ΔWP is split
  into play (runs off the bat + the ball used), wicket and extras, then credited:
  `striker += play`, `player_out += wicket`, `bowler −= play + extras × (wides+no-ball runs ÷ all
  extras) + wicket × w`, `fielder −= wicket × f ÷ n_fielders`, with `(w, f)` = (1, 0) for bowled /
  lbw / hit wicket / caught and bowled, (0.8, 0.2) for caught / stumped, (0, 1) for a run out and
  (0, 0) for retired out / obstructing; byes, leg-byes and penalty runs go to nobody. Columns:
  `ngi_batting`, `ngi_bowling`, `ngi_fielding`, `ngi_total` (their sum), `matches` (appearances in
  the playing XI, `match_players_<col>`, plus any match played unlisted), `ngi_per_match` =
  `ngi_total ÷ matches`. Time-window and era boards reuse the whole league's out-of-fold scores;
  leaderboards keep a matches floor (25 all-time, 6 for 3 years and eras, 3 for 1 year). Career
  table at `data/metrics/ngi_<collection>.json`, dashboard tab "NGI (Net Game Impact)";
  `scripts/compute_metrics.py ngi-diagnostics` prints the model checks.
- **Wicket Quality** ✅ — the mean Bayes batting skill of the batters a
  bowler dismissed (run outs, retirements and obstructing the field
  excluded); higher = harder wickets. It uses the batter's scoring
  `skill`, not the complete `value`. Filter: `min_wickets` (default 15).
  Lives in `cricdesk.metrics.bowler_wicket_quality`. Needs the
  scout NumPyro ratings (`scout_ratings_<collection>.json`) — see
  `docs/SCOUT.md`.
- **Crease Longevity** ✅ — crease longevity: a batter's average balls
  faced per dismissal (run outs at the non-striker's end included,
  retired hurt not) divided by the cohort average. >1 = bats longer
  than the typical qualifying batter; <1 = shorter, higher-tempo
  innings. The cohort is batters with 5+ dismissals; the board needs
  `min_dismissals` (default 10). Lives in `cricdesk.metrics.batter`.
- **Slow-Start Cost** ✅ — career strike rate minus strike rate over the
  first 20 balls of an innings. Positive = slow starts cost tempo;
  ~0 or negative = aggressive from ball one. Filters: 200 career balls,
  50 balls inside the first 20. Lives in `cricdesk.metrics.batter`.
- **Wicketkeeping** ✅ — dismissals a keeper is credited with: catches +
  stumpings + run-out involvements, from every wicket's `fielders` (a second
  wicket off one delivery counts too). A fielder is a keeper if the player
  master (by registry id) says so or they have any stumping.
  Lives in `cricdesk.metrics.fielding.keeping`.
- **Fielding** ✅ — outfield dismissals: catches + run-out involvements
  (caught-and-bowled is a bowling wicket, excluded; every fielder in a
  multi-fielder run-out is credited). A dismissal *count*, not diving range
  (that needs video). Lives in `cricdesk.metrics.fielding.fielding`.

## Still planned

- **Replacement Delta** — NGI − NGI of a replacement-level domestic
  player. Cricket WAR. Sits on NGI (✅) plus a domestic-tier baseline;
  deferred until a sub-IPL tier exists to define replacement
  ([`ROADMAP.md`](ROADMAP.md#next)).
- **Disguise Coefficient** (bowler) — outcome variance for same
  line / length. Needs CV-derived release-point data (OpenBoundary,
  [`ROADMAP.md`](ROADMAP.md#later)).

---

## Output schema

Every metric writes a flat JSON list of records. Columns documented in
each metric function's docstring and in `cricdesk/metrics/README.md`.
The leaderboard surfaces don't read `data/metrics/` directly: they (and the
Streamlit Leaderboards page's collection list) come from the exported
`site/public/data/` snapshot, so
re-run `scripts/export_site.py` (or `cricdesk data ingest metrics`, which
exports for you) after recomputing.

## Common rules (all metrics, records and boards)

- Every player is keyed by his Cricsheet registry id, resolved per match (`common/sql.py::keyed_balls`:
  each match's `players_<col>` registry maps that match's scorecard names to ids). Two different players
  who share a scorecard name in one league (among players who batted or bowled: 38 names in men's T20Is, 7 in the BPL, 7 in SMAT, 3 in the PSL, 1 each in the IPL and The Hundred) are two rows. Each row
  carries `cricsheet_id`, the scorecard name (`batter` / `bowler` / `fielder` / `name`) and `display_name`.

- Super overs decide a tie and aren't part of anyone's batting or bowling record, so they're left out
  everywhere: NGI, records, venue profiles, phase boards, profiles, every metric here, the fielding boards,
  matchups, partnerships, aging, cohorts and the rating model (175 of ~296,000 IPL deliveries).
- Runs charged to a bowler (economy, runs conceded, best figures, aging) are runs off the bat plus wides and
  no-balls; byes and leg-byes aren't the bowler's.
- Retired hurt / retired not out isn't a dismissal.
- Records are per innings (a Test match's two innings are two records).
