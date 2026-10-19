# How CricDex works — every model, in plain English

CricDex turns Cricsheet's ball-by-ball records into numbers a scorecard can't give you: how much a player
moved the result, how good he is once you account for who he faced, who plays like him in another league,
and what he might fetch at an IPL auction. This page explains every one of those models: **what it does,
how it does it, a small worked example, and where it falls short**. It was checked against the code in
October 2026, and file names are given so you can trace any claim.

No maths background is assumed. Where a formula helps, it comes after the plain-words version.

← back to the [README](../README.md) · the deeper technical tour: [STUDY_GUIDE.md](STUDY_GUIDE.md) ·
metric formulas in full: [METRICS.md](METRICS.md) · the auction step by step: [AUCTION_MATH.md](AUCTION_MATH.md)

| Section | What's in it |
|---|---|
| [1. Data and identity](#1-data-and-identity) | Where the balls come from, one id per player, merged venues, super overs, the one AI step |
| [2. Net Game Impact (NGI)](#2-net-game-impact-ngi) | Win probability added, ball by ball |
| [3. The nine context metrics + fielding](#3-the-nine-context-metrics--fielding) | Pressure Runs, Intent Curve, Dot-Ball Recovery and the rest; time windows and eras |
| [4. Bayesian skill ratings](#4-bayesian-skill-ratings) | Four skills per player, adjusted for the opposition, with honest uncertainty |
| [5. Scout look-alikes](#5-scout-look-alikes) | Who plays like X in another league, and what he'd cost |
| [6. From skill to crore](#6-from-skill-to-crore) | Turning a rating into an auction price |
| [7. The auction room](#7-the-auction-room) | Retentions, personalities, budget pressure, second-price clearing |
| [8. Does it predict? The backtest](#8-does-it-predict-the-backtest) | Fitted before each season, scored on that season |
| [9. Limits](#9-limits) | What the models can't see, and what's approximate |

---

## 1. Data and identity

**Where the balls come from.** Everything starts from [Cricsheet](https://cricsheet.org/), a free,
volunteer-maintained archive with one JSON file per match and one record per delivery: who bowled it, who
faced it, what was scored, whether a wicket fell and who took the catch. CricDex downloads a whole
*collection* at a time (the IPL, the BBL, men's T20Is and so on), flattens every delivery into a row and
stores the result in one local DuckDB database (`src/cricdex/scout/ingest/cricsheet.py`). Which
collections exist, which Cricsheet zip each comes from and which ones the site ships is one file, the
league registry [`config/leagues.toml`](../config/leagues.toml) ([LEAGUES.md](LEAGUES.md)). The site ships
the men's T20 leagues marked `export = true`: IPL, SMAT (Indian domestic), BBL, SA20, CPL, T20 Blast, PSL,
ILT20, The Hundred, MLC, BPL, LPL, Super Smash, CSA T20 Challenge, men's T20Is and "recently played". The
parser reads every field of Cricsheet's JSON format (every extras type, every wicket on a ball, DRS
reviews, Impact Player and other replacements, powerplays, the chase target, playing XIs, officials, season
and stage), versioned by `SCHEMA_VERSION`. There is no scraping and no live feed. Every number is computed
from these files.

**One id per player.** Scorecards spell names inconsistently ("Navdeep Saini" in one match, "NA Saini" in
another), and two players can share a name. Cricsheet solves this for us: every match file carries a
*registry* that maps each scorecard name to a stable Cricsheet identifier, and the separate
[People Register](https://cricsheet.org/register/) links that identifier to ESPNcricinfo and other sites.
CricDex keeps each match's registry in a `players_<collection>` table and resolves names through it first,
falling back to the People Register's `unique_name` (`src/cricdex/common/sql.py::player_ids`). Search
also understands the Register's ~7,500 name variants, so "Jasprit Bumrah" finds "JJ Bumrah". Details:
[IDENTITY.md](IDENTITY.md).

**Every number is keyed by that id, match by match.** The name→id lookup is done per match, not per name:
the ball table is read through `keyed_balls` (`src/cricdex/common/sql.py`), which swaps every player
column (batter, non-striker, bowler, the batter who is out, the fielders) for the id that *that match's*
registry gives, and keeps the scorecard spelling next to it. Every metric, rating, board, NGI total,
record, profile, matchup, partnership, phase board, aging curve, cohort and style twin groups by the id;
the name is only for display. So two different players who share a scorecard name in one league stay
two players: among players who batted or bowled, 38 such names in men's T20Is, 7 in the BPL, 7 in the SMAT,
3 in the PSL, one each in the IPL ("Harmeet Singh") and The Hundred.

**One name per ground.** Cricsheet records the same ground several ways: with or without the city
("Wankhede Stadium" / "Wankhede Stadium, Mumbai"), with punctuation ("M.Chinnaswamy Stadium"), or under a
former name ("Feroz Shah Kotla"). After every ingest, `src/cricdex/common/venue_names.py` rewrites every
venue to `"<ground>, <city>"`, gives renamed grounds their current name (Feroz Shah Kotla → Arun Jaitley
Stadium, Sardar Patel Stadium → Narendra Modi Stadium), and keeps every old spelling as a searchable alias.
The city stays in the name so that England's eight different "County Ground"s don't merge.

**Super overs.** A super over only decides a tie, so it isn't part of anyone's batting or bowling record.
Every stat leaves super overs out: NGI, records, venue profiles, phase boards, profiles, all nine metrics,
the fielding boards, matchups, partnerships, the aging curves, cohorts and the rating model. Only the two
main innings of a limited-overs match count (every innings of a multi-day match does). It's 175 deliveries
in the whole IPL history.

**The one AI step.** Ball-by-ball data can't tell you whether a bowler bowls seam or spin, where a batter
usually bats, or which country he plays for. For that, and only that, CricDex asks an LLM (via LiteLLM, so
any provider you set in `.env`) to tag each player's **primary role, bowling type, usual batting slot,
batting hand and country** (`scripts/enrich_taxonomy.py`). The answers are cached once in
`data/curated/player_taxonomy.json` (2,525 players) and every filter that uses them is labelled
**"AI-classified"**. The model is told to answer "unknown" rather than guess. The LLM never produces a
rating, a metric or a price; with no LLM configured, everything else still builds.

Dates of birth, photos and social handles come from a one-time Wikidata pull (342 players cached, 331
found), used for player profiles and the aging curves.

---

## 2. Net Game Impact (NGI)

**What it does.** NGI asks one question of every ball: *how much did this change the batting side's chance
of winning?* It credits that change to whoever caused it (the batter for his runs, the bowler for runs,
extras and wickets, the fielder for a catch or a run out) and averages it per match. A 30 not out that wins
a tight chase scores more than a hundred in a lost cause, and a wicket at 200/3 chasing 220 counts for more
than one at 50/3 chasing 250. Code: `src/cricdex/metrics/ngi.py`.

**How.**

1. **A win-probability model.** For every ball of every decided T20 match in a league, CricDex records the
   state *before* the ball: which innings, balls left (scheduled overs minus legal balls bowled), wickets
   left, the score, the target and runs still needed, the required rate, the current rate, how the current
   rate compares with that ground's usual first-innings rate, and three **era** features: the current rate,
   the target and the required rate each measured against the league's recent scoring level (the average
   first-innings run rate of the 60 matches before this one). A gradient-boosted tree model (XGBoost) learns
   how often the batting side went on to win from each kind of state. A tie counts as half a win (label 0.5);
   no-results are dropped; super overs are not used.
2. **Common sense built in.** The trees carry *monotone constraints*: more balls left, more wickets in hand,
   more runs or a higher run rate can never lower the batting side's chance, and a higher target, more runs
   needed or a higher required rate can never raise it. Without them, 3.9% of IPL wicket balls (with no run
   scored) *raised* the batting side's chance in sparse states; with them, 0.01%.
3. **Smooth calibration.** The raw tree output is calibrated so "70%" really means the side wins about 70% of
   the time, with *beta calibration* (a smooth three-number curve) rather than isotonic regression. Isotonic
   calibration is a staircase: two states on the same step get exactly the same probability, so a small but
   real swing scores exactly 0. Every NGI number is a *difference* of two probabilities, so this matters:
   on the IPL the share of balls with a ΔWP of exactly 0 fell from 70% to 23%. (The rest are tree steps:
   a dot ball early in an innings often doesn't cross any split.) Calibration stays good: expected
   calibration error 0.024 on unseen matches.
4. **Honest training, out-of-fold scoring.** Matches, not balls, are split. A *reporting* model learns on 70%
   of matches, stops early and is calibrated on the next 15%, and its accuracy is reported only on the last
   15% it never saw. For the NGI numbers themselves, **every ball is scored by a model that never saw its
   match**: matches are dealt into 5 folds, and each fold is scored by a model trained on the other four.
   (Before, one model trained on 70% of matches scored every match, so most NGI came from a model that had
   partly memorised those results. On the IPL the out-of-fold NGI per match correlates 0.94 with the old
   in-sample one; a typical player moved by 0.8 points of win chance per match.)
5. **Score every ball.** The model reads the state before the ball and after it. The difference is that
   ball's value, ΔWP. Two intermediate states split it into parts: **play** (the runs off the bat and the
   legal ball used), **wicket**, and **extras**. The last ball of the chase resolves to the actual result (1,
   0, or 0.5 for a tie); the last ball of the first innings hands over to the chase's opening position, so
   nobody is credited with the other team's innings. That end-of-innings resolution joins whichever part
   moved the needle most on that ball.
6. **Credit** (the fielding side always gets the opposite sign of what the batting side gets):

   | Part | Batting side | Fielding side |
   |---|---|---|
   | play (runs off the bat, the ball used) | the striker | the bowler |
   | wides and no-ball runs | nobody (the batter didn't earn them) | the bowler |
   | byes, leg-byes, penalty runs | nobody | nobody (the team's) |
   | wicket: bowled, lbw, hit wicket, caught and bowled | the batter who is out | the bowler |
   | wicket: caught, stumped | the batter who is out | bowler 80%, catcher / keeper 20% |
   | wicket: run out | the batter who is out (the non-striker in a run out at his end) | the named fielders, split equally |
   | wicket: retired out, obstructing | the batter who is out | nobody |

   A wide isn't a ball faced, so its play part is zero by construction. The 20% fielder share
   (`FIELDER_SHARE`) is a convention: ball-by-ball data can't tell a sitter from a screamer. Because the
   team's parts go to nobody, the credits on a ball don't always sum to zero.
7. **Average.** Summed over a match, then over a career, and divided by **appearances**, that's **NGI per
   match**. An appearance is a place in the playing XI (Cricsheet's `info.players`, which in the Impact
   Player era lists the twelfth man who came in), plus any match a player took part in without being listed
   (a fielding substitute). So a lower-order batter who didn't get in still counts the game. The all-time
   board needs 25 matches (6 for the last-3-years and era boards, 3 for the last year). Time-window boards
   reuse the whole league's out-of-fold scores, since a single year is too few matches to train a model.

**Worked example (illustrative numbers).** A side needs 12 off the last 6 balls with 5 wickets in hand;
the model gives them a 40% chance. The batter hits a six: now 6 off 5, and the model says 68%.

```
ΔWP = 0.68 − 0.40 = +0.28   →  batter +0.28, bowler −0.28
```

The same six in the second over of a first innings might move the needle from 50% to 52%: +0.02. Same
six, fourteen times the credit, because it mattered fourteen times as much. If that last-over ball had been
a wide instead, the +0.03 or so it was worth would be booked to the bowler alone.

**Reading it.** An NGI per match of +0.05 means the player adds, on average, five percentage points to his
side's chance of winning each game he plays.

**How good is the model?** IPL, unseen matches: accuracy 0.71, Brier score 0.185, log loss 0.542,
expected calibration error 0.024. The era features matter most out of time: trained on every season before
2026 and tested on 2026 (the highest-scoring IPL season), the log loss is 0.530 with them and 0.607
without; on 2025 0.541 against 0.542, on 2024 0.544 against 0.532. On a random split of matches they cost
a little (log loss 0.542 against 0.536 with a raw scoring-level feature), which we accept for a model that
holds up in a new season. All of these come from `scripts/compute_metrics.py ngi-diagnostics -c ipl`.

**Limits.** NGI is T20-only. Leverage is part of the number: finishers and death bowlers play more balls
that matter, so NGI rewards opportunity as well as skill. The fielding credit is a fixed share, not a catch
difficulty.

**Rain-reduced chases.** Cricsheet does flag Duckworth-Lewis-Stern results (`outcome.method = "D/L"`) and
records the target each chase actually faced (`innings[].target`: runs and overs). Both are ingested
(`matches_<col>.outcome_method`, `innings_<col>.target_runs` / `target_overs`), so a rain-hit chase is
scored against its revised target with the shortened over count (overs × balls per over, so The Hundred's
five-ball overs count right). A database ingested before the `innings_<col>` table existed falls back to
first-innings total + 1 and the scheduled overs. Pressure Runs uses the same target.

---

## 3. The nine context metrics + fielding

Standard averages and strike rates are context-blind. Each of these nine isolates one skill a scorecard
hides. They're all on the Leaderboards page (all-time, last 3 years, last year, and any **era** the
league registry defines: the IPL's "Impact Player era", every match since 2023-03-31, so Impact-era
numbers aren't ranked against pre-2023 ones), with the same explanations as below. Each period
recomputes the metric over only those matches. Exact formulas and column names: [METRICS.md](METRICS.md); code in
`src/cricdex/metrics/`. Every board has a minimum sample so a single freak innings can't top it.

**Pressure Runs** — *how fast does a batter score when a chase gets hard?* For every ball of a T20 or ODI
chase, work out the required runs per ball. A ball is "under pressure" when that's more than **1.5×** the
usual required rate at that ground, in that phase, in that format: hard *for that ground*, since a
Bengaluru chase and a Chennai chase aren't the same job. Pressure SR is runs per 100 such balls (wides
aren't balls faced). Needs 20 chase balls.
*Example:* 45 runs off 30 pressure balls is a Pressure SR of 150.

**Intent Curve** — *does he come out swinging or build up?* Split every ball a batter faced by how deep
into his innings it was (balls 0–5, 6–10, 11–20, 21–30, 31–50, 51+) and take his strike rate in each
bucket. The shape is the point: rising = builds up, flat-high = aggressor from ball one. The board ranks by
**early SR** (balls 1–10) and draws the full curve as a sparkline. Each bucket needs 200 balls (fewer on the
time-window boards).

**Dot-Ball Recovery** — *what does he do after a dot?* For every dot ball a batter faces, add up the runs
he scores off the next six deliveries he faces in that innings, expressed per six balls. A 9 means he
answers a dot with nine runs an over; a 4 means dots tend to snowball. Needs 100 dots.

**Counter-Attack** — *does he fight back when his partner falls?* Take the 12 deliveries after each
wicket and keep only those faced by the batter who was *already in*: not the one who got out, not the new
arrival still taking guard. Counter SR is his strike rate on those balls (a ball after two quick wickets
counts once). Needs 20 partner wickets survived.

**Boundary Dependency** — *how much of his scoring is fours and sixes?* Boundary runs ÷ all runs off the
bat. Neither high nor low is "better": high is boundary-or-bust, low means he keeps the strike turning.
The board lists low first. Needs 200 runs.
*Example:* 300 runs with 25 fours and 20 sixes = (100 + 120) ÷ 300 = 73%.

**Pressure Conversion** (bowlers) — *does he turn a squeeze into a wicket?* Within one over, once a
bowler has strung together **four or more** consecutive dots (nothing scored, no wide or no-ball), look at
each next ball in that over. Conversion % = wickets the bowler is credited with on those balls ÷ those balls (run-outs don't count). A tight bowler who
never breaks through scores low here even with a great economy. The sample floor adapts to the league
(half the 75th-percentile volume, at least 5 balls) so small competitions aren't emptied.

**Wicket Quality** (bowlers) — *whose wickets does he take?* For every wicket credited to the bowler (run
outs, retirements and obstructing the field excluded), look up the dismissed batter's Bayesian **scoring**
skill (section 4) and average them. Removing top-order stars scores high; mopping up the tail scores low.
Needs 15 wickets.

**Crease Longevity** — *how long does he last?* Balls faced per dismissal (a run-out at either end counts;
retired hurt doesn't), divided by the average for all batters with at least five dismissals. 1.3 means he
lasts 30% longer than a typical batter: an anchor's signature. Needs 10 dismissals.
*Example:* 1,200 balls, 40 dismissals = 30 balls per dismissal; if the cohort averages 20, the index is 1.5.

**Slow-Start Cost** — *what do cautious starts cost him?* Career strike rate minus his strike rate over the
first 20 balls of each innings. Positive = he starts slower than he finishes; zero or negative = he goes
from ball one. Lower is better. Needs 200 career balls and 50 early balls.
*Example:* career SR 140, first-20-balls SR 115 → a cost of 25.

**Wicketkeeping and Fielding boards.** From each dismissal's list of fielders (every wicket on a delivery,
including the rare second one): a catch, a stumping, or a run-out involvement (every fielder named in a
run-out gets one). A player is a keeper if the taxonomy says
so or he has any stumping; keepers get their own board so their catches don't swamp the outfield list.
Caught-and-bowled is a bowling wicket and isn't counted. These are *counts* of dismissals, not a
success rate or diving range; ball-by-ball data can't see dropped catches.

---

## 4. Bayesian skill ratings

**What it does.** A raw average treats a fifty against a great attack and a fifty against a weak one as
the same fifty, and a 2009 strike rate like a 2026 one. The rating model learns a skill for every batter
and every bowler *at the same time*, so each run is judged against who it came off **and the context it
came in**: the season's scoring level, the phase of the innings, setting or chasing, and the ground. It is
**dismissal-aware**: each player gets two skills per role, and every skill comes with a measure of how sure
the model is. Code: `src/cricdex/scout/ratings/bayesian.py`; model spec:
[ratings README](../src/cricdex/scout/ratings/README.md).

| Role | Skill | Plain meaning (higher = better) |
|---|---|---|
| Batter | **scoring** (`skill`) | scores faster than an average batter would against the same bowlers, in the same context |
| Batter | **survival** (`survival_skill`) | harder to get out |
| Bowler | **economy** (`skill`) | concedes fewer runs, wides and no-balls included, than an average bowler would to the same batters |
| Bowler | **strike** (`strike_skill`) | takes wickets more often |

**How.**

1. **Every matchup, in context.** For each batter–bowler pair in a league, the balls are grouped by season,
   phase (powerplay / middle / death), innings and ground, and for each group CricDex counts the legal
   balls, the runs off the bat and the dismissals the bowler was credited with (bowled, caught, lbw,
   stumped, hit wicket; run-outs don't test the duel). Every pairing is kept, even a single ball.
2. **Two linked models on those groups.** Expected runs per ball rise with the batter's scoring skill and
   fall with the bowler's economy skill (a Negative-Binomial count, which allows for cricket's lumpy
   scoring of dots and sixes). The chance of a dismissal on each ball rises with the bowler's strike skill
   and falls with the batter's survival skill (a Binomial on the balls, through a logistic link). A third,
   small model counts each bowler's wides and no-ball runs per delivery, season by season, so his economy
   includes them.
3. **Context terms.** Both models add a **season** level (a random walk: each season's scoring level starts
   from the one before, so the model learns how fast the game changes), a **phase** level, an **innings**
   level and a **ground** level (shrunk to the league's average when a ground has few matches). Players are
   then rated *against their own context*: a death bowler isn't penalised for bowling the hardest overs, an
   opener isn't flattered by the powerplay, and a 2026 batter isn't flattered by 2026. On the IPL the
   fitted season level puts 2026 runs per ball about 20% above 2008, with most of the rise since 2023; the
   death overs score about 50% more per ball than the powerplay and lose wickets about twice as often.
4. **Counting noise properly.** The variance of a sum of n balls grows like n, so the Negative-Binomial's
   dispersion scales with the balls in each group (`concentration = alpha × balls`). Before, one dispersion
   served a 1-ball group and a 150-ball group alike, which treated the big, informative groups as far
   noisier than they are.
5. **Shrinkage, toward the right average.** Each skill is assumed to come from a population with a spread
   the model also learns. A player with 30 balls is pulled strongly toward that average; one with 3,000 is
   barely moved. The average depends on the role: batters shrink toward their **batting slot's** mean (top
   order 1–3, middle 4–5, lower middle 6–7, tail 8–11, from his median position in the data), bowlers toward
   frontline bowlers' or part-timers' mean (frontline = 15+ deliveries per match bowled). So a tail-ender with
   30 balls is rated like a tail-ender, not like an average batter (on the IPL the tail's scoring mean sits
   0.50 below the top order's on the log scale, about 40% fewer runs per ball).
6. **Opponent bridging.** Because each skill is learned from every opponent at once, a batter who scored
   freely off strong bowlers gains more than one who scored the same off part-timers. Strength flows
   through the whole network of matchups.

**One number per role: `value`.** Scoring is measured in log runs per ball and survival in log-odds of
getting out, so they can't just be added. Each is first centred on the role's average player and divided by
the role's population spread (within and between slots), then summed. So `value` is in **"typical spreads
above average"**: 0 is an average player, +1 is one typical player-to-player spread better, the best in the
IPL sit near +3.

*Worked example (current IPL fit).* The scoring spread is about 0.25 and the survival spread about 0.22.

```
V Kohli     scoring +0.26 ÷ 0.25 ≈ +1.05    survival +0.43 ÷ 0.22 ≈ +1.92    value ≈ +2.97
SP Narine   scoring +0.45 ÷ 0.25 ≈ +1.78    survival −0.41 ÷ 0.22 ≈ −1.83    value ≈ −0.05
```

Narine (batting) scores much faster than Kohli but gets out far more often, so his complete batting value is
about average. A runs-only model would have rated him the better batter. The same split separates
bowlers: Chahal's economy is ordinary but his strike skill is high; Ashwin is the reverse.

**Uncertainty.** Every skill and `value` carries a standard deviation from the fit. The Head-to-Head page
uses it directly: treating two players' values as bell curves, the chance that A is better than B is
`Φ((value_A − value_B) / √(sd_A² + sd_B²))` (`src/cricdex/scout/ratings/head_to_head.py`). Two players
with close values and wide uncertainty come out near 50/50, as they should.

**How it's fitted, and how we checked the shortcut.** The fit runs in NumPyro (JAX). The default is
**ADVI**, a fast approximation (12,000 optimisation steps, about 2–3 minutes for the IPL). The exact
method, **NUTS** (Hamiltonian Monte Carlo), is opt-in (`scripts/scout_rate.py --sampler nuts`). With the
context terms in, we ran both on the IPL again (2 chains × 500 + 500 NUTS draws, about two hours on a busy laptop; worst r-hat 1.02, smallest effective sample 187, no divergences). For players with 100+ balls, ADVI's uncertainties are 98% of NUTS's for batters (scoring and survival) and 92–95% for bowlers (strike and economy), `value` uncertainty 101% (batters) and 96% (bowlers); the point estimates correlate 0.994 or better; and head-to-head probabilities differ by a median of 2–2.5 points (95th percentile 7). So the shortcut holds, a touch over-confident for bowlers.

**Does it fit better?** On every IPL season 2021–26, fitted only on the matches before it, the new model's
held-out log-likelihood per ball is higher than the old model's in **every season, for both runs and
dismissals**: −0.621 against −0.626 nats per ball for runs and −0.147 against −0.148 for dismissals
(averaged over the six seasons, ~100,000 balls). That's a proper scoring rule over every ball, so it's
a sharper test than a rank correlation of season totals: the context terms, the dispersion fix and the
role priors predict the next season's balls better. (`scripts/backtest_ratings.py --compare legacy`.)

**Limits.** Each league is fitted separately, so an IPL +2 and a BBL +2 aren't the same thing; the scout
and the auction correct for that with a tier discount (sections 5 and 6). There's one skill set per role
for a player's whole career in that league (the context is adjusted for, but a player's own form isn't
allowed to drift); batting slot comes from the data, so a player who moved up the order is grouped by his
median slot.

---

## 5. Scout look-alikes

**What it does.** Pick an active IPL player; Scout finds others of the same mould in every Scout pool of
the league registry: **IPL peers**, uncapped Indians from the **SMAT**, and overseas players from each
overseas league (BBL, SA20, CPL, T20 Blast, PSL, ILT20, The Hundred, MLC, BPL, LPL, Super Smash, CSA T20). Each comes with an estimated price and the saving against your pick. Code:
`src/cricdex/web_parity/scout.py` (Python) and `site/src/lib/scout.ts` (web), kept identical by a parity
test. More: [SCOUT.md](SCOUT.md).

**How.**

1. **A comparable standing.** Raw numbers don't travel between leagues; a SMAT strike rate was made
   against weaker attacks than an IPL one. So within each league, each player's rating on the role he's
   matched in (batters and keepers on batting value, bowlers on bowling value, all-rounders on both added)
   becomes a **z-score among that league's players of the same role**: how many spreads above his own
   competition's average he stands. Only recently active players with at least 150 balls are included.
2. **Same mould.** Candidates must share the pick's role (from the AI-classified taxonomy); bowlers must
   also share seam or spin. You can also filter by batting slot.
3. **Closeness.** Similarity = `1 − |z_candidate − z_pick| ÷ 2.5`, floored at 0. The top eight per pool
   are shown.
4. **Price and saving.** Each candidate is priced with the auction's skill-to-crore curve (section 6),
   after the league's tier discount, and the saving is your pick's price minus his.
5. **Gem flag.** A prospect is a "gem" when his standing is high (z ≥ 0.6) on at most the median SMAT
   exposure: punching above a small sample.

*Worked example.* Your pick stands at z = +1.8 among IPL batters. A SMAT batter at z = +1.6 among SMAT
batters has similarity 1 − 0.2 ÷ 2.5 = 0.92, a strong match. One at z = +0.3 has 1 − 1.5 ÷ 2.5 = 0.40.

Separately, every Player Profile shows **style twins** (nearest neighbours by cosine similarity over the
published metrics plus the Bayesian skill: 13 axes for batters, 3 for bowlers;
`src/cricdex/scout/search/style_twin.py`) and a **co-faced cohort** (who faced the most of the same
bowlers, or bowled to the most of the same batters; `src/cricdex/scout/cohort.py`).

**Limits.** "Same standing in his league" is not "same quality": a SMAT z of +1.6 is impressive, but the
tier discount is a single number per league, not a measured conversion rate (section 8 shows how well
that works for newcomers). Roles come from the AI-classified taxonomy; a player without one is treated as
a batter.

---

## 6. From skill to crore

**What it does.** The data says how good a player is, never what he costs. To run an auction, CricDex
invents a fair price from skill, tuned so the spread looks like recent real auctions. Code:
`src/cricdex/web_parity/pricing.py` ⇄ `site/src/lib/auction.ts`.

**How.**

1. **Tier discount.** A rating from a weaker league is lowered first (in `value` units): BBL −0.45,
   SA20 −0.45, CPL −0.64, T20 Blast −0.64, SMAT −1.28, IPL 0. A player in several leagues keeps his best
   discounted value. The discounts live in `[tiers.*]` of `config/leagues.toml`; the leagues added later
   borrow one by analogy until fitted (PSL, ILT20 and The Hundred −0.45 like BBL / SA20; MLC, BPL, LPL,
   Super Smash and CSA T20 −0.64 like CPL / Blast) and are marked `calibrated = false`.
2. **IPL relevance.** For the auction pool, a player who hasn't featured in the IPL lately loses up to
   2.7 from his value, scaled by an *IPL-relevance* weight between 0 and 1: about 1 for a current IPL
   regular (age barely matters while he's playing), fading with years since his last IPL game and with age
   past 32; 0.7 for an uncapped Indian who has never played the IPL. This is what stops a league-only
   veteran from topping an IPL auction.
3. **Exponential price curve.**

   ```
   projected price = 1.1 × e^(0.95 × value) × role weight     clamped to 0.3 – 27 cr
   ```

   All-rounders are weighted ×1.15 and keepers ×1.05, because they're scarcer. The top names land in the
   20s of crore; the typical pool player is around 1 crore; nobody passes 27 cr, the real record.
4. **Base price.** Each player enters the auction at a real IPL base-price band chosen from his projected
   price: 0.3, 0.5, 0.75, 1.0, 1.5 or 2.0 cr.

*Worked example.* Kohli's IPL value is +2.68 with full IPL relevance:
`1.1 × e^(0.95 × 2.68) ≈ 1.1 × 12.8 ≈ 14 cr` projected, entering at the 1.5 cr band.

**Limits.** These prices are **invented from skill**, calibrated to the level and spread of recent
auctions but not fitted to actual sale data. They're good for comparing players and testing auction
behaviour, not for predicting what a franchise will pay on the day.

---

## 7. The auction room

**What it does.** A Monte-Carlo of a real IPL auction: all ten teams keep their core, then bid for
everyone else under real rules, hundreds of times over. It answers *who probably lands which star, and
for roughly how much?* Code: `src/cricdex/web_parity/auction.py` ⇄ `site/src/lib/auction.ts`; the
step-by-step version is [AUCTION_MATH.md](AUCTION_MATH.md).

**The pool.** The active T20 world an IPL auction draws from: IPL players (each carrying his current
franchise, so he can be retained) plus free agents from every `auction_pool` league in the registry
(the overseas leagues and SMAT; men's T20Is are left out). Only
players active in the last three years with at least 150 balls in one of those leagues; free agents must
come from a nation whose players feature in IPL auctions (so not Pakistan or associate sides — the
`auction_nationalities` / `auction_excluded_nationalities` lists in the registry). A player in several
leagues gets one value per role: if he has 300+ balls in that role in the IPL, his IPL rating stands on
its own; otherwise his leagues are blended, each first discounted by its tier and weighted by
1 ÷ (rating sd² + the tier's `translation_sd`²), so thin IPL evidence still counts most and a hot spell
in a weaker or provisional league can't outrank it. His better role is kept. Priced as in section 6;
the top 600 by value make the pool.

**Retentions.** Editable per team.
- **Mega auction**: each franchise keeps its real 2025 retention list (about five players), paid at the
  real retention price where known, else the IPL slabs (18 / 14 / 11 / 18 / 14 cr, then 4), out of a
  120 cr purse.
- **Mini auction**: each team keeps its 18 most valuable players free (they were bought in earlier years)
  and tops up from a small purse (30 cr by default).

Retained overseas players count towards the overseas cap of 8.

**Personalities.** Each team bids in a style: MarqueeChaser (aggression 1.35, overpays for stars),
ValueHunter (0.85, walks away from bidding wars), OverseasHeavy, IndianFocus, AllRounderStack, Balanced.
Each style also sets how many batters, bowlers, all-rounders and keepers the team wants, how much it likes
overseas players, and how much its bids wobble. MI and RCB default to MarqueeChaser, PBKS and RR to
ValueHunter, and so on; you can change them.

**The bidding.** The 200 most valuable unretained players are the lots, stars first (the order is nudged
up to ±5% at random each run). For each lot, every team that still has room works out its maximum bid:

```
max bid = projected price × aggression × need × overseas bias × luck × budget pressure
```

- **need**: 1.5 if the team is still short of that role, 0.7 once it's covered.
- **overseas bias**: the team's overseas appetite × 1.4 for an overseas player; 1 for an Indian.
- **luck**: a random nudge, up to ± the team's risk setting (15–30%).
- **budget pressure**: the team's purse per open squad slot divided by the league average, square-rooted
  and clamped between **0.75 and 1.6**. A team that retained little and sits on a big purse bids harder;
  a stretched one bids softer. Without it, a rich team filled its squad with cheap players and finished
  with half its purse unspent.

A team can't bid more than it can spend while keeping 0.3 cr for each other slot it still has to fill,
can't pass the overseas cap, and won't bid below the base price.

**Second-price clearing.** The highest maximum bid wins, but, as in a real auction room, the winner pays
just above the second-highest bid (2% over it), never less than the base price and never more than
**27 cr**.

*Worked example.* A player projected at 10 cr:

```
MI  (MarqueeChaser, short of batters): 10 × 1.35 × 1.5 × 1 = 20.3
CSK (Balanced, batters covered):       10 × 1.00 × 0.7 × 1 =  7.0
(luck and budget pressure left at 1)
→ MI wins and pays about 7.1 cr (2% over CSK), not its own 20.3.
```

**Two-phase fill.** Round one runs through the lots until every team has 20 players; round two tops up
toward the 25-man cap. A final pass hands any team still under 20 the cheapest leftovers at base price.

**Many runs, one answer.** That's one mock auction. The room runs it **300 times** and reports each team's
typical spend, squad size and overseas count, each star's odds of landing at each team ("MI 62%, CSK
21%"), the average price per player, and one sample auction to browse. The randomness comes from a small
seeded generator (a linear congruential generator, run `t` seeded `1000 + 7919·t`), so the same settings
always give the same result, and the browser (TypeScript) and the CLI / TUI / Streamlit (Python) produce
**the same numbers trial for trial**. `test_scripts/test_web_parity.py` runs both and fails CI if they
ever differ.

**Limits.** Team personalities are hand-assigned, not learned from real bidding history. There's no
right-to-match card, no withdrawals, no injury news and no "capped vs uncapped" base-price rule. Prices are
section 6's invented prices, so the room models auction *behaviour* and relative outcomes, not the exact
crore figures of any real auction.

---

## 8. Does it predict? The backtest

A rating is only worth something if it says something about the future. Two walk-forward scripts check
that out of sample: for each season, the model is fitted **only on matches before it**, then its ranking
of players is compared with how that season actually went. Agreement is a Spearman rank correlation:
1 means the same order, 0 means no link. Both scripts are in the repo (`scripts/backtest_ratings.py`,
`scripts/backtest_newcomers.py`), so anyone can re-run them.

**How the test is run.**

- **Three ADVI seeds.** Every fit is repeated with seeds 42, 43 and 44. Each seed's correlation is kept;
  the seed-averaged prediction is what gets scored and resampled, so one lucky optimisation can't make
  the headline.
- **Seasons pooled fairly.** Every prediction and outcome is z-scored within its season before pooling,
  so a high-scoring year doesn't skew the ranking.
- **A fair baseline.** The baseline is what a scout could work out by hand from the same matches,
  *given the same league adjustment as the model*: each league's raw numbers relative to that league's
  average (runs per ball divided by the league's runs per ball, outs per ball divided by the league's
  rate), the overall axis as a z-score within the league minus the same tier discount the model gets,
  pooled across leagues by balls. The first version compared the tier-discounted model with raw numbers
  that had no league adjustment at all, so part of the "model edge" was just the discount.
- **One number per player, pooled by precision.** A newcomer with several leagues gets one value per axis:
  each league's value minus its discount, weighted by 1 / (value sd² + the tier's translation sd²), the
  same rule the auction pool uses. The first version took a player's *best* league, which is biased
  upward (the maximum of noisy estimates).
- **How sure, honestly.** The players are re-drawn 2,000 times (a bootstrap). For each of the six tests
  (batters: scoring, survival, overall; bowlers: economy, strike, overall) we report the 95% range of the
  gap (model minus baseline), the share of re-draws where the model came out ahead, a one-sided p (the
  model is no better than the baseline) and that p after a **Holm correction** for running six tests at
  once.
- **Selection on playing time.** A newcomer only counts if he got 60+ IPL balls in the role, and players
  who start badly get dropped, so that sample is chosen partly on early form. The script re-scores with
  30 and 120 balls as the bar to see whether the answer moves.
- **No stale fits.** Fits are cached by model version, so an older model's fits are never reused after a
  change.

**Established IPL players (2021–26).** Ratings fitted before each season versus each player's raw career
numbers before that season:

| | Model | Career average |
|---|---|---|
| Batters, overall | 0.14 | 0.15 |
| Batters, scoring | 0.13 | 0.13 |
| Batters, survival (staying in) | 0.30 | 0.34 |
| Bowlers, overall | 0.12 | 0.07 |
| Bowlers, economy | 0.31 | 0.30 |
| Bowlers, strike (wicket-taking) | 0.05 | 0.05 |

A tie for batters and a small edge for bowlers overall (0.12 against 0.07). For players with a long IPL
record, the opponent and context adjustment adds little that a career average doesn't already know. We
also tried weighting recent seasons more (half-lives of 1, 2 and 4 years); none helped, so recency
weighting is **off by default** (`fit(half_life=...)` is there to experiment with). Correlations this low
are the honest state of things: a single T20 season is mostly noise, for any method.

A sharper yardstick is the **held-out log-likelihood per ball** (section 4): the current model scores
−0.6212 nats per ball for runs against the old model's −0.6255, and −0.1467 against −0.1480 for
dismissals, and it is better in **every season 2021–26 on both**. So the model change predicts the next
season's balls better, even though season-total rankings barely move.

**IPL newcomers (2014–26).** The harder and more useful test: players new to the IPL (fewer than 60 IPL
balls in the role before the season), rated **only** from other leagues, scored on their first real IPL
season. We ran it twice: with all 13 non-IPL auction-pool leagues (the current default), and with the
original five (BBL, SA20, CPL, T20 Blast and SMAT) that the first published run used.

All 13 leagues (103 batters, 132 bowlers):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall | 0.22 | 0.10 | +0.12 [−0.02, +0.25] | 96% | 0.042 | 0.25 |
| Batters, scoring | 0.13 | 0.19 | −0.06 [−0.23, +0.11] | 22% | 0.78 | 1.00 |
| Batters, survival | 0.29 | 0.27 | +0.01 [−0.16, +0.18] | 56% | 0.44 | 1.00 |
| Bowlers, overall | 0.18 | 0.24 | −0.06 [−0.20, +0.09] | 20% | 0.80 | 1.00 |
| Bowlers, economy | 0.25 | 0.26 | −0.01 [−0.11, +0.10] | 44% | 0.56 | 1.00 |
| Bowlers, strike | 0.08 | 0.07 | +0.02 [−0.16, +0.20] | 58% | 0.42 | 1.00 |

The original five leagues (96 batters, 110 bowlers):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall | 0.25 | 0.09 | +0.16 [0.00, +0.33] | 98% | 0.025 | 0.15 |
| Batters, scoring | 0.11 | 0.18 | −0.07 [−0.26, +0.11] | 24% | 0.76 | 1.00 |
| Batters, survival | 0.31 | 0.23 | +0.08 [−0.10, +0.25] | 82% | 0.19 | 0.93 |
| Bowlers, overall | 0.18 | 0.22 | −0.04 [−0.20, +0.10] | 27% | 0.73 | 1.00 |
| Bowlers, economy | 0.21 | 0.20 | +0.01 [−0.11, +0.13] | 54% | 0.46 | 1.00 |
| Bowlers, strike | 0.21 | 0.13 | +0.08 [−0.10, +0.27] | 80% | 0.20 | 0.93 |

**Playing-time sensitivity (all 13 leagues, overall axis).** With a 30-ball bar the model leads for both
roles (batters 0.12 vs 0.05, n = 183; bowlers 0.16 vs 0.10, n = 187). With a 120-ball bar, batters flip
(−0.19 vs −0.12, n = 44) and bowlers lead slightly (0.24 vs 0.20, n = 70). Samples that small move a lot
either way.

**The honest read.** The first published headline, a survival edge for newcomer batters that held in 97%
of re-draws, **does not survive a fair, league-adjusted baseline**: that edge was mostly the league
discount itself. With the fixes, the model ranks newcomer batters better **overall** in both runs (ahead in
96–98% of re-draws), but no result is significant once you correct for running six tests (the best Holm
p is 0.15). Bowlers show no edge. For established players the ratings tie career averages for batters and
edge them for bowlers (0.12 vs 0.07), and the new model predicts held-out balls better in every season.
Single T20 seasons are mostly noise, so the newcomer-batter result is **a lean, not proof**.

**Not done yet.** There is no split-half noise ceiling, so we can't yet say how close any of these numbers
are to the best correlation a season this noisy allows (roadmap 37 and 27).

---

## 9. Limits

What the models can't see, and where they approximate. Most of these are on the
[roadmap](ROADMAP.md).

- **Fielding in NGI is a convention.** A catch or stumping earns the fielder a fixed 20% of the wicket's
  swing and a run out all of it, split between the fielders named; ball-by-ball data can't tell a sitter
  from a screamer, or show a dropped catch. Byes, leg-byes and penalty runs are credited to nobody.
- **NGI rewards opportunity.** Finishers and death bowlers face more balls that matter, so a high NGI is
  partly the role.
- **Fielding boards are counts.** Catches, stumpings and run-out involvements, not catch success rates,
  dropped catches or ground covered; ball-by-ball data doesn't record those.
- **Indian domestic data ends in December 2024.** Cricsheet's SMAT coverage currently stops at
  2024-12-15, so uncapped Indian prospects are rated on older form than everyone else. Ranji Trophy and
  Vijay Hazare have no ball-by-ball on Cricsheet and aren't covered.
- **Prices are invented from skill**, calibrated to recent auctions but not fitted to actual sale data.
- **A single season is noisy.** The backtest's correlations are low for every method, model or not. Treat
  any one-season ranking with care.
- **The ratings barely beat career averages for established players** (a tie for batters, a small edge for
  bowlers). For newcomers rated from other leagues they lean ahead for batters overall, but nothing is
  significant after correcting for six tests, and bowlers show no edge.
- **Each league is fitted on its own.** Cross-league comparison rests on one hand-set tier discount per
  league.
- **Context is adjusted, form isn't.** The rating model judges every ball against its season, phase,
  innings and ground, but each player has one skill set per league for his whole career.
- **Wicket Quality uses the dismissed batter's scoring skill only**, not his full value. (In a refresh the
  ratings are fitted before the metrics, so it always reads the current fit.)
- **Roles, bowling types and countries are AI-classified** and can be wrong; a player without a tag
  defaults to "batter" in the scout and auction.
- **Ages cover about a third of players** (those found on Wikidata), so the aging curves are indicative
  and skewed toward well-known players.
- **Men's cricket only, so far.** The ingester knows the women's collections, but none is built or checked
  yet.
- **Rain-reduced matches stay in** the win-probability model, scored against the revised DLS target and
  over count Cricsheet records (a database ingested before that field was read falls back to first-innings
  total + 1 over the scheduled overs until it is re-ingested).
