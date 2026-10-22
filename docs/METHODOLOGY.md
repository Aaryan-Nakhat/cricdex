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
| [10. Keep or release](#10-keep-or-release) | The retention calculator: price against salary, purse, role gaps |
| [11. Form forecast](#11-form-forecast) | A player's value over the next three seasons: aging, survivorship, ranges, backtest |
| [12. Bid plan (beta)](#12-bid-plan-beta) | The auction bidding plan: rival prices, squad strength, max bids, fallback chains, the 2025 and 2026 auctions replayed |

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

**One number per role: `value`, in runs.** Scoring is measured in log runs per ball and survival in
log-odds of getting out, so they can't just be added: the question is what a wicket is *worth* in runs.
That depends on when it falls. A wicket in the 2nd over with nobody out costs a side far more of its
future runs than one in the 19th, so a finisher who rarely gets out has saved his team much less than an
opener who rarely gets out. CricDex prices it from the ball-by-ball data
(`src/cricdex/scout/ratings/runs_value.py`):

1. **The run cost of a wicket.** From every first innings of a full-length, non-rain-affected match in the
   league, count the runs and wickets per ball in each state (over, wickets down), smoothed so a thin state
   borrows from its neighbours (an over level times a wickets-down factor per phase). A backward pass over
   the innings gives the expected runs still to come from each state, `V(ball, wickets down)`, and the
   cost of losing a wicket on a ball is `λ = V(next ball, w) − V(next ball, w + 1)`, the same
   dynamic-programming idea as Duckworth–Lewis resources and the "dismissal-adjusted runs" of
   Bandyopadhyay (2026, arXiv:2608.18020). On the IPL (par first-innings total 168):

   | | 0–1 down | 2–3 down | 4–5 down | 6+ down |
   |---|---|---|---|---|
   | Powerplay (overs 1–6) | 13–14 | 12–13 | 17–18 | 15–18 |
   | Middle (7–15) | 7–8 | 8 | 10–11 | 11–16 |
   | Death (16–20) | 2.5 | 2 | 2.5 | 3–8 |

   With 2 down it falls steadily from about 15 runs in the 1st over to 3 in the 16th and 0.3 in the 20th.
2. **Where the player plays.** Each player's wicket cost is the average of `λ` over the states he actually
   batted (or bowled) in, each ball weighted by the chance of a wicket there, kept per phase and innings.
   KL Rahul's is 9.6 runs; Dhoni's 4.7; Russell's 5.4.
3. **Runs per 100 balls.** With the league's runs per ball `r` and dismissal rate `q` in each phase and
   innings, his share of balls there `π`, his run-rate multiplier against the average ball `m` (from his
   scoring skill) and his survival skill against the average ball `Δs`:

   ```
   batting value = 100 × Σ π × [ r × (m − 1)  −  λ × (P(out | his survival) − q) ]
   bowling value = 100 × Σ π × [ R × (1 − m)  +  λ × (P(out | his strike) − q) ]
   ```

   (for a bowler `m` comes from his economy skill, `R` counts wides and no-balls). Both are re-centred so
   the league's balls average 0, and computed for every posterior draw, so the uncertainty carries
   through. So **`value` is runs per 100 balls above the league's average ball**: +10 is ten runs better
   every 100 balls. The best IPL regulars sit around +20 to +25. The rates and `λ` are pooled over the
   league's seasons, so a 2009 and a 2026 player are converted at the same rate (their skills are already
   judged against their own season).

*Worked example (current IPL fit).*

```
                  scoring part   staying-in part   wicket cost   value (runs / 100 balls)
KL Rahul             +8.9            +10.5            9.6          +19.4
V Kohli              +4.6             +9.0            9.3          +13.6
AD Russell          +24.7             −0.2            5.4          +24.5
MS Dhoni             −6.8             +7.9            4.7           +1.1
SP Narine (bat)     +31.8            −31.8           11.2           +0.1
```

Dhoni gets out far less than the average batter at the death, but a wicket there costs about 5 runs and
he scores below the death-overs rate, so he is about an average batter per ball (40th of 64 active IPL
batters with 600+ balls). Under the earlier value, which divided each axis by its spread and added the two
with equal weight, he was the **best** active IPL batter (3.32, ahead of KL Rahul 3.31 and Kohli 2.97):
staying in counted as much at the death as at the top. Narine opens and gets out often at the costliest
time, so his scoring and his wickets cancel. Among bowlers the order barely moves (Narine +24.0, Bumrah
+23.2, Rashid +20.3): a bowler's wicket-taking skill is shrunk hard (it is noisy), so his value is mostly
runs saved, Chahal's wickets adding +3.5 to his +6.6.

The top active IPL batters by value (600+ balls): Russell +24.5, Abhishek Sharma +22.9, Salt +22.6, Head
+20.7, Bairstow +20.4, Buttler +20.3, KL Rahul +19.4, Pooran +18.6, Klaasen +17.7, Gill +17.5. Young
hitters with short records rate higher still on the mean (Suryavanshi +60 ± 12 on 449 balls), with
uncertainty to match.

**Uncertainty.** Every skill and `value` carries a standard deviation from the fit. The Head-to-Head page
uses it directly: treating two players' values as bell curves, the chance that A is better than B is
`Φ((value_A − value_B) / √(sd_A² + sd_B²))` (`src/cricdex/scout/ratings/head_to_head.py`). Two players
with close values and wide uncertainty come out near 50/50, as they should.

**How it's fitted, and how we checked the shortcut.** The fit runs in NumPyro (JAX). The default is
**ADVI**, a fast approximation (12,000 optimisation steps, about 2–3 minutes for the IPL). The exact
method, **NUTS** (Hamiltonian Monte Carlo), is opt-in (`scripts/scout_rate.py --sampler nuts`). With the
context terms in, we ran both on the IPL again (2 chains × 500 + 500 NUTS draws, about two hours on a busy laptop; worst r-hat 1.02, smallest effective sample 187, no divergences). For players with 100+ balls, ADVI's uncertainties are 98% of NUTS's for batters (scoring and survival) and 92–95% for bowlers (strike and economy), the uncertainty of the earlier sd-sum `value` 101% (batters) and 96% (bowlers) (not yet re-run for the runs value, which is built from the same draws); the point estimates correlate 0.994 or better; and head-to-head probabilities differ by a median of 2–2.5 points (95th percentile 7). So the shortcut holds, a touch over-confident for bowlers.

**Does it fit better?** On every IPL season 2021–26, fitted only on the matches before it, the new model's
held-out log-likelihood per ball is higher than the old model's in **every season, for both runs and
dismissals**: −0.621 against −0.626 nats per ball for runs and −0.147 against −0.148 for dismissals
(averaged over the six seasons, ~100,000 balls). That's a proper scoring rule over every ball, so it's
a sharper test than a rank correlation of season totals: the context terms, the dispersion fix and the
role priors predict the next season's balls better. (`scripts/backtest_ratings.py --compare legacy`.)

**Limits.** Each league is fitted separately, so an IPL +20 and a BBL +20 aren't the same thing; the scout
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

**What it does.** CricDex prices a player two ways. His **market price** is what IPL franchises have
actually paid for players like him: a model fitted to the IPL auctions since 2018 (6b below). His
**on-field worth** is what his game alone would fetch on a hand-set skill→price curve (6a, the original
price). The market price is the price wherever a crore figure is shown (the Auction room's pool, Keep or
release, Scout's est. prices); the on-field worth is shown next to it. Code:
`src/cricdex/web_parity/pricing.py` ⇄ `site/src/lib/auction.ts` (the same features and coefficients on
both, locked by `test_scripts/test_web_parity.py`).

### 6a. On-field worth (the skill→price curve)

**How.**

1. **Tier discount.** A rating from a weaker league is lowered first, in runs per 100 balls: BBL −6.0,
   SA20 −6.0, CPL −8.5, T20 Blast −8.5, SMAT −17.0, IPL 0. A player in several leagues gets one value per
   role, his leagues blended by precision (and his IPL value alone when he has 300+ IPL balls in the
   role). The discounts live in `[tiers.*]` of `config/leagues.toml`; the leagues added later borrow one
   by analogy until fitted (PSL, ILT20 and The Hundred −6.0 like BBL / SA20; MLC, BPL, LPL, Super Smash
   and CSA T20 −8.5 like CPL / Blast) and are marked `calibrated = false`. They were set in the earlier
   sd units (1.28 / 0.45 / 0.64) and converted with one factor, 13.3 (the spread of the runs value over
   the spread of the old value, IPL players with 150+ balls); players with 300+ balls in both leagues show
   gaps of the same size (SMAT +22 runs for batters and +7 for bowlers, BBL +4 / +3, CPL +5 / +6, Blast
   +9 / +6).
2. **IPL relevance.** For the auction pool, a player who hasn't featured in the IPL lately loses up to
   36 runs per 100 balls from his value, scaled by an *IPL-relevance* weight between 0 and 1: about 1 for a current IPL
   regular (age barely matters while he's playing), fading with years since his last IPL game and with age
   past 32; 0.7 for an uncapped Indian who has never played the IPL. This is what stops a league-only
   veteran from topping an IPL auction.
3. **Cautious estimate.** The price is set from `value − 0.5 × value_sd`, not the central value
   (`PRICE_CAUTION_SD`, `pricing.py` ⇄ `auction.ts`): a proven star (sd ≈ 3 runs) gives up about 1.5
   runs, a 400-ball prodigy (sd ≈ 12) about 6. Displays and rankings keep the central value. The pool
   carries the blended value's sd (translation uncertainty included); Scout the league rating's sd with
   the tier's translation sd added.
4. **Exponential price curve.**

   ```
   projected price = 4.03 × e^(0.0743 × (value − 0.5 × value_sd)) × role weight     clamped to 0.3 – ceiling
   ceiling         = 27 × (0.5 + 0.5 × min(1, IPL balls in the role / 600))
   ```

   The ceiling rises with IPL evidence: no IPL balls → 13.5 cr at most, 449 (Suryavanshi) → 23.6 cr,
   600+ (about two full seasons) → 27 cr. The pool and Scout rows carry `target_balls` for it.

   All-rounders are weighted ×1.15 and keepers ×1.05, because they're scarcer. The top names land in the
   20s of crore; the typical pool player is around 1.2 crore; nobody passes 27 cr, the real record. When
   `value` moved to runs, the two constants were re-fitted so the 600-player pool keeps the same median
   price (1.18 cr) and the same number of 10 cr+ players (25) as before, on the cautious values
   ([AUCTION_MATH.md](AUCTION_MATH.md)). The top end now leans to batters (18 of the 25 are batters or
   keepers, against 14), because in runs a batter's scoring edge is worth more than a bowler's economy
   edge after the model's shrinkage.
5. **Base price.** Each player enters the auction at a real IPL base-price band chosen from his projected
   price: 0.3, 0.5, 0.75, 1.0, 1.5 or 2.0 cr.

*Worked example.* Kohli's IPL batting value is +13.6 ± 2.8 with full IPL relevance: priced value
13.6 − 1.4 = 12.2, `4.03 × e^(0.0743 × 12.2) ≈ 4.03 × 2.48 ≈ 10.0 cr` projected, entering at the 1.0 cr
band. Priyansh Arya's is higher (+27.7) but on 471 balls (± 12.4): priced at 21.5, about 20 cr instead
of the 27 cr cap. Suryavanshi (+59.7 ± 12.5 on 449 balls) would still reach 27 cr on the curve, but
his 449 IPL balls hold him to a 23.6 cr ceiling; Finn Allen (163 IPL balls) is held to 17.2.

**Limits.** This curve is **invented from skill**, calibrated to the level and spread of recent auctions
but not fitted to sale data. Out of time it predicts the 2025 and 2026 auction prices worse than the
market model (6b), so it is kept as the "on-field worth" column, not as the price.

### 6b. Market price (fitted to real IPL auctions)

**The data.** `scripts/ipl_auction_history.py` reads Wikipedia's per-season IPL personnel pages, 2008 to
2026 (CC BY-SA 4.0; each pinned to the revision read, cached raw in `data/curated/ipl_auction_pages/`),
into the hand-editable `data/curated/ipl_auction_history.json`: **1,647 sold lots** (player, country,
base price, final price, buying team, his previous team and set where the page has them, RTM) and
**1,046 retentions** with salaries (2008 icons, the 2011 / 2014 / 2018 / 2022 / 2025 mega retentions,
every mini year's retained list from 2019, the 2016 draft). Prices before 2014 were in US$ and are
converted at the Federal Reserve H.10 rupee rate on the auction day or the last business day before it
(₹40.11 per US$ in 2008, 48.61 in 2009, 45.84, 45.35, 48.65, 53.16 in 2013). Players are matched to a
Cricsheet id by Wikipedia title, then name, initial + surname or a close spelling among IPL players:
1,598 of the 1,647 sold lots (97%) and 1,033 of the 1,046 retentions (99%); the rest are uncapped
players with no ball-by-ball. The pages list sold players only: there is no unsold list.

**Features, as of each auction (no leakage).** For every auction the IPL is re-fitted on the matches
before that auction's date (18 fits, cached; `scripts/ipl_price_model.py fits`, about 45 minutes once),
and the other leagues come from the newcomer backtest's fits, using only those whose cut-off is on or
before the auction date (for a December auction that league data is up to a year old). The auction
pool's blend (section 7) then gives his **value** and its sd. The features (`market_features` ⇄
`marketFeatures`):

| feature | definition |
|---|---|
| `pv`, `pv_pos_sq` | cautious value `value − 0.5 × sd`, clamped to −40…60; max(pv, 0)² / 100 |
| `unrated` | no value at all (pv = 0) |
| `overseas`, `pv_x_overseas` | not Indian; pv × overseas |
| `caps`, `caps_x_indian` | ln(1 + men's T20I + ODI + Test matches before the auction); × Indian |
| `recent_caps`, `recent_caps_x_indian` | the same over the two years before the auction; × Indian (a current international) |
| `pv_x_capped_indian` | pv for a capped Indian (the "Indian star" interaction, from the data, no names) |
| `age`, `age_sq`, `age_missing` | age − 28 at the auction; its square / 10; no date of birth |
| `ipl_balls`, `ipl_seasons`, `never_ipl`, `ipl_gap` | ln(1 + IPL balls faced + bowled); IPL seasons (max 15); never played the IPL; years since his last IPL match (max 6) |
| `all_rounder`, `keeper`, `bowler` | role (batter is the base) |
| `mega` | a mega auction |
| `captain_ipl`, `captain_seasons`, `captain_intl` | regular captain of an IPL side the season before the auction; ln(1 + IPL seasons as captain before it); captained his country (men's Test / ODI / T20I) in the two calendar years before |

**Captaincy** comes from `data/curated/ipl_captains.json` (`scripts/ipl_captains.py`: each franchise
article's captains table, filled in from "List of Indian Premier League captains", and each Test
nation's list of national captains; Wikipedia, CC BY-SA; details in [IDENTITY.md](IDENTITY.md)). Only
seasons before the auction count; a stand-in (fewer than 4 matches a year) counts as a captaincy season
but never as "last season's captain". One small leak: whether a stint is a stand-in uses its total
matches, which can include games after the auction.

Base price is left out of the shipped model (a player picks it, and Keep or release prices players who
don't have one yet), and so is his previous IPL salary (it would make "worth his salary" partly
"because he's paid it"); both are reported as variants below.

**The model.** A hurdle:

1. **P(bought)**: logistic regression (L2, standardised). The risk set is every player who played the
   IPL in the two years before an auction and wasn't retained, in the seasons whose retained lists are
   complete (2018–2026): bought at that auction = 1, else 0. "Else" mixes unsold, unregistered and
   retired players (no unsold lists exist), so it's a proxy for "released, does a franchise buy him?".
   A player who has never played the IPL gets no P(bought).
2. **ln(price / purse | bought)**: a Huber (robust) regression on standardised features, folded back to
   raw units. Prices are a share of that year's purse (60 cr in 2014 … 125 cr in 2026), so purse growth
   and the US$ years drop out; a cycle's price is that share × its purse. The prediction is then
   calibrated at the top end (below).

**Retentions.** Mega-year retention prices (2018, 2022, 2025; 97 with a Cricsheet id) are slab-set (in
2025 a fixed purse deduction of 18 / 14 / 11 cr or more), so each is a floor on the player's worth to
his franchise rather than a bid. They are in the price fit as observed prices, because they are the only
sale-like data on the stars who never reach an auction (Kohli, Rohit, Bumrah), and including them
lowered the out-of-time error slightly (a `retained` indicator, tried too, absorbed their premium and
did worse). Mini-year retained salaries are old contracts and are left out.

**Training window.** Auctions 2018–2026 (the rupee era with complete retention lists); starting in 2009
or 2014 was within 0.01 out of time. Shipped: 1,020 price rows (923 lots + 97 retentions) and 1,226
P(bought) rows, in `config/price_model.json`.

**Top-end calibration, by group.** A regression on logs shrinks toward the middle, so before calibration
the lots that sold for 10 cr+ came out at about 0.45× their price. The linear predictor is therefore
passed through a monotone **calibration map** fitted on out-of-fold predictions (each season predicted
by a fit on the other seasons; for the test below, only seasons up to 2024): `quantile` maps the
predictions' quantiles onto the actual prices' (21 knots), so the predicted prices have the same spread
as real auctions. That map alone left overseas players about 1.9× what they fetched in 2025–26, so the
shipped calibration is **group-aware**: three groups (overseas, capped Indian, uncapped Indian, defined
as ranges on the features in `config/price_model.json` → `price.groups`) share the quantile map and
each gets its own shift, its mean out-of-fold residual (`quantile+group-offset`; shipped shifts:
overseas −0.19, capped Indian −0.28, uncapped Indian +0.31 in ln). The first group whose ranges hold
applies (`calibration_part` ⇄ `calibrationPart`, then `calibrate` ⇄ `calibrate`), identically in Python
and the browser, parity-tested.

Also tried and reported: an isotonic recalibration (E[price | prediction]), Duan's smearing (ln mean
e^residual, the median turned into a mean), the quantile map above the median only, a separate quantile
map per group (`group-quantile`), and group shifts from the last two auctions only (`-recent`). Smearing
lifts the 10 cr+ lots to 0.7–1.2× but overprices the typical lot by 2–2.5×; the recent-only shifts are
worse out of time (2023–24 overseas prices were high, 2025–26 low).

Two caveats. Selecting lots by their *actual* price always shows a model below them (regression to the
mean), even a perfectly calibrated one, so a 10 cr+ ratio of 1 means over-pricing everyone else.
And no shift fitted on 2018–2024 removes the 2025–26 overseas drop: before any calibration overseas
lots were already +0.28 too high out of time, and a shift fitted on 2025 and applied to 2026 overshoots
the other way (2026 overseas −0.35). The overseas level moves from auction to auction (mega vs mini,
the 18 cr overseas fee cap of the 2025–27 rules), so it stays the model's largest error.

**Out-of-time test.** Trained (and calibrated) on auctions up to 2024, scored on the 2025 mega and 2026
mini auctions (235 matched lots; errors on ln crore, prices clamped as shipped: 0.3 cr floor, IPL-evidence
ceiling). "10 cr+ ratio" = geometric-mean predicted / actual price of the lots that sold for 10 cr+:

| | MAE (ln) | median abs. error | within ±50% | rank corr. | bias (ln) | 10 cr+ ratio | 2025 MAE | 2026 MAE |
|---|---|---|---|---|---|---|---|---|
| **shipped: Huber + quantile map + group shifts** | **0.703** | **53%** | **49%** | **0.731** | **+0.15** | **0.50** | **0.675** | **0.783** |
| Huber + quantile map (one group) | 0.706 | 51% | 49% | 0.745 | +0.19 | 0.62 | 0.678 | 0.786 |
| Huber + a quantile map per group | 0.729 | 49% | 51% | 0.715 | +0.18 | 0.58 | 0.719 | 0.758 |
| Huber + quantile map + recent group shifts | 0.785 | 57% | 45% | 0.696 | +0.22 | 0.49 | 0.779 | 0.804 |
| Huber, no calibration | 0.674 | 56% | 45% | 0.741 | +0.05 | 0.45 | 0.650 | 0.741 |
| + isotonic calibration | 0.697 | 54% | 46% | 0.744 | +0.10 | 0.39 | 0.671 | 0.770 |
| + isotonic + smearing | 0.967 | 156% | 24% | 0.744 | +0.75 | 0.73 | 0.952 | 1.009 |
| + quantile + smearing | 1.138 | 129% | 14% | 0.738 | +0.93 | 1.15 | 1.127 | 1.167 |
| + quantile map above the median only | 0.706 | 56% | 46% | 0.740 | +0.19 | 0.58 | 0.685 | 0.766 |
| shipped, without the captaincy features | 0.697 | 52% | 48% | 0.735 | +0.14 | 0.49 | | |
| Huber, no calibration, without captaincy | 0.667 | 56% | 45% | 0.745 | +0.04 | 0.44 | | |
| ridge, no calibration | 0.703 | 63% | 43% | 0.739 | +0.12 | 0.45 | 0.682 | 0.763 |
| median (quantile) regression, no calibration | 0.681 | 55% | 45% | 0.730 | +0.04 | 0.46 | 0.651 | 0.764 |
| + previous IPL salary (not shipped, no calibration) | 0.668 | 52% | 47% | 0.745 | +0.05 | 0.46 | 0.649 | 0.722 |
| + base price (not shipped, no calibration) | 0.661 | 52% | 47% | 0.755 | −0.13 | 0.36 | 0.638 | 0.725 |
| old on-field curve (6a) | 0.776 | 59% | 43% | 0.631 | −0.04 | 0.35 | 0.734 | 0.891 |

By group (90 overseas, 52 capped Indian, 93 uncapped Indian lots):

| | overseas: MAE / bias / 10 cr+ | capped Indian: MAE / bias / 10 cr+ | uncapped Indian: MAE / bias |
|---|---|---|---|
| **shipped: quantile map + group shifts** | **0.72 / +0.37 / 0.71** | **0.70 / −0.06 / 0.54** | **0.70 / +0.04** |
| quantile map (one group) | 0.82 / +0.62 / 0.91 | 0.72 / +0.25 / 0.71 | 0.59 / −0.26 |
| a quantile map per group | 0.72 / +0.40 / 0.91 | 0.67 / −0.09 / 0.61 | 0.77 / +0.11 |
| no calibration | 0.65 / +0.28 / 0.59 | 0.73 / −0.06 / 0.51 | 0.67 / −0.11 |
| old on-field curve | 0.69 / −0.15 / 0.49 | 0.87 / −0.10 / 0.37 | 0.81 / +0.10 |

What the group shifts buy, against the single map: the capped and uncapped Indians' bias is about 0
(−0.06, +0.04) and the overseas lean falls from +0.62 to +0.37 (1.9× to 1.45×); the mean error is a
touch lower (0.703). What they cost: the 10 cr+ ratio falls from 0.62 to 0.50 (the overseas shift pulls
the top overseas lots down, the capped-Indian shift the stars) and the rank correlation from 0.745 to
0.731. Examples: Pant 27 predicted for 27 paid, Shreyas Iyer 19.6 for 26.75, Arshdeep 13.4 for 18,
Green 13.7 for 25.2, Buttler 10.9 for 15.75; Venkatesh Iyer 2.7 for 23.75 and Prashant Veer / Kartik
Sharma ~0.5 for 14.2 are beyond any feature.

**Captaincy, honestly.** A regular IPL captain the season before fetches about 22% more (`captain_ipl`
+0.20 in ln) and is likelier to be bought; seasons as captain add a little, a recent international
captaincy nothing once caps are in. Out of time the captaincy features don't improve the score (0.703
with, 0.697 without), so their effect rests on the 2018–2024 fit, not on a measured gain.

Refitted on everything, the model puts the mega retentions at a median 0.77× what they were paid (26% at
or above it). P(bought), out of time (352 players): log loss 0.571 against 0.692 for the base rate, AUC
0.77, Brier 0.20, calibrated within a few points in each band (predicted 0.19 → 12% bought, 0.38 → 35%,
0.62 → 61%, 0.81 → 79%).

**What the coefficients say.** The market pays for **reputation and experience** as much as for
measured on-field value. Value counts most at the top (cautious value 0 → 10 adds about 45%, 10 → 20
nearly doubles the price), while being a current Indian international (about ×3 for 30 caps in two
years, before the other caps terms), IPL experience, captaincy and youth move it as much; an overseas
player fetches about 1.8× an Indian with the same record; a mega auction pays about 17% more; bowlers
about 16% less. (Before the calibration map, which stretches the top.)

**The price.**

```
lin               = intercept + Σ coefficient × feature            (config/price_model.json)
ln(price / purse) = calibrate(lin)   (the quantile map: piecewise-linear knots, slope 1 beyond them,
                                       plus the shift of his group: overseas / capped / uncapped Indian)
market price      = purse × e^(that), clamped to 0.3 cr … the IPL-evidence ceiling (6a, step 4)
upper quartile    = purse × e^(that + 0.674 × residual sd)          (same clamps; sd 1.02, out of fold)
```

The cautious estimate stays inside the price (`pv`) and the IPL-evidence ceiling stays on top: with
fewer than 600 IPL balls the market price can't pass `27 × (0.5 + 0.5 × balls / 600)` either
(Suryavanshi: 23.6 cr), and nobody passes 27 cr. The purse and cycle default to the league's next
competition in `config/competitions.toml` (IPL 2027: mini, 125 cr). Scout prices a player from another
league with his value less the tier discount (6a step 1) as `pv`. An export from before the model (no
`price_value` in its rows), or no model file, falls back to the on-field curve.

*Examples (IPL 2027 mini, 125 cr; data to the 2026 final).* Market price, with on-field worth in
brackets: Kohli 10.3 cr (10.0), P(bought) 0.62; Rohit Sharma 7.5 (4.7); Bumrah 10.9 (20.5); Suryavanshi
23.6 (23.6, the ceiling); Pant 12.7 (10.3, captain LSG); Shubman Gill 21.7 (12.7, captain GT); Tilak Varma
17.8 (4.6); Abhishek Sharma 16.0 (19.6); Hardik Pandya 11.8 (3.5, captain MI); Shreyas Iyer 12.7 (6.4,
captain PBKS); the uncapped Priyansh Arya 9.3 (20.0) and Ayush Mhatre 9.7 (18.0): the market prices an
uncapped two-season player well below his on-field numbers.

**Limits.** The market model ranks lots better than the curve and the calibration gets the top end
closer, but a typical lot is still off by a factor of about 1.7, overseas players are over-priced
against the last two auctions, and bidding wars for individual names aren't predictable. It sees
captaincy now, but no injury, brand or loyalty, and P(bought)'s "not bought" includes players who didn't
register.

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

**The bidding.** The 200 most valuable unretained players are the lots, at most 36% of them overseas as on a
real shortlist (2024: 119 of 333; `AUCTION_OVERSEAS_SHARE`), stars first (the order is nudged
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

**Calibrated to real auctions** (since 2026-10-22). The value a team starts from is the market price through
a fitted level (0.86× in a mega auction, 1.04× in a mini), a concave curve (^0.75, so money spreads beyond the
stars as in real rooms), his last IPL price where known (weight 0.3), a demand shock per lot per run (sd 1.0 in
ln, shared by all teams: how hot he is on the day) and the market tightness (money left with teams that still
have places ÷ the market value of the best unsold players who'd fill them). Fitted on the 2022 mega and
2023–24 mini auctions, tested on 2025 and 2026: the simulated 10–90% range now holds 77% (2025) and 46% (2026)
of real prices, up from 28% and 12%, and the dearest simulated lots come out at 1.09× and 1.07× their real
price, down from 2.44× and 1.55×; the 2025 mega auction still ran about 1.5× above the simulation on contested
lots. Step by step and every number: [AUCTION_MATH.md Part 3b](AUCTION_MATH.md); `scripts/auction_calibrate.py`.

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
  rate), the overall axis in the same runs currency as `value` (runs per 100 balls above the league's
  average ball, each dismissal priced at the player's wicket cost) minus the same tier discount the model
  gets, pooled across leagues by balls. The first version compared the tier-discounted model with raw numbers
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
numbers before that season. The overall axis is scored in the currency `value` is built in: what the player
actually did that season in runs per 100 balls above the league's average ball, each dismissal above or below
the league's rate priced at his own wicket cost (`runs_value.observed_value`); the career baseline is the same
number from his raw career totals. The earlier yardstick (each axis as a z-score, summed) is kept as
"overall (z-sum)" so the change can be compared with what was published before (0.14 vs 0.15 for batters,
0.12 vs 0.07 for bowlers, with the earlier sd-sum value):

| | Model | Career average |
|---|---|---|
| Batters, overall (runs) | 0.19 | 0.15 |
| Batters, overall (z-sum) | 0.20 | 0.15 |
| Batters, scoring | 0.13 | 0.13 |
| Batters, survival (staying in) | 0.30 | 0.34 |
| Bowlers, overall (runs) | 0.15 | 0.11 |
| Bowlers, overall (z-sum) | 0.10 | 0.07 |
| Bowlers, economy | 0.31 | 0.30 |
| Bowlers, strike (wicket-taking) | 0.05 | 0.05 |

The runs value edges career averages for both roles overall (batters 0.19 against 0.15, bowlers 0.15 against
0.11; the three seeds agree to ±0.01), and it even predicts the old z-sum yardstick better than the old value
did for batters (0.20 against 0.14 published). The batter edge is largest in 2021 (0.36 against 0.22); in 2025
and 2026 model and career are level. The single axes are unchanged (the model is the same; only `value` moved). For players with a long IPL
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

The overall rows are scored in runs, like the established-player test: the IPL season's runs per 100 balls
above the league's average ball against the model's `value` and against the same number from the player's
league-adjusted raw numbers.

All 13 leagues (103 batters, 132 bowlers):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall (runs) | 0.08 | 0.10 | −0.02 [−0.15, +0.12] | 38% | 0.62 | 1.00 |
| Batters, scoring | 0.13 | 0.19 | −0.06 [−0.23, +0.11] | 22% | 0.78 | 1.00 |
| Batters, survival | 0.29 | 0.27 | +0.01 [−0.15, +0.17] | 55% | 0.45 | 1.00 |
| Bowlers, overall (runs) | 0.22 | 0.26 | −0.04 [−0.17, +0.10] | 32% | 0.68 | 1.00 |
| Bowlers, economy | 0.25 | 0.26 | −0.01 [−0.12, +0.10] | 42% | 0.58 | 1.00 |
| Bowlers, strike | 0.08 | 0.07 | +0.02 [−0.16, +0.19] | 57% | 0.43 | 1.00 |

The original five leagues (96 batters, 110 bowlers):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall (runs) | 0.11 | 0.06 | +0.05 [−0.08, +0.17] | 78% | 0.22 | 1.00 |
| Batters, scoring | 0.11 | 0.18 | −0.07 [−0.25, +0.12] | 23% | 0.77 | 1.00 |
| Batters, survival | 0.31 | 0.23 | +0.08 [−0.09, +0.25] | 83% | 0.17 | 1.00 |
| Bowlers, overall (runs) | 0.22 | 0.25 | −0.04 [−0.18, +0.09] | 27% | 0.73 | 1.00 |
| Bowlers, economy | 0.21 | 0.20 | +0.00 [−0.11, +0.12] | 53% | 0.47 | 1.00 |
| Bowlers, strike | 0.21 | 0.13 | +0.08 [−0.11, +0.27] | 79% | 0.21 | 1.00 |

Every Holm-adjusted p is 1.00: no test is significant.

**Playing-time sensitivity (all 13 leagues, overall in runs).** With a 30-ball bar the model is slightly
ahead for both roles (batters 0.06 vs 0.03, n = 183; bowlers 0.18 vs 0.16, n = 187). With a 120-ball bar
it is slightly behind for both (batters 0.05 vs 0.08, n = 44; bowlers 0.20 vs 0.24, n = 70). None of these
gaps is large, and samples that small move a lot either way.

**The honest read.** With the runs-currency `value`, the ratings **beat career averages for established IPL
players**, batters (0.19 vs 0.15) and bowlers (0.15 vs 0.11), and the new model predicts held-out balls
better in every season. For **IPL newcomers rated from other leagues they are no better than the players' own
league-adjusted numbers**: there is a lean for batters in the original five leagues only (ahead in 78% of
re-draws, not significant), and no test survives the correction for six comparisons. Two earlier newcomer
headlines are withdrawn: the first, a survival edge for newcomer batters "in 97% of re-draws", was mostly the
league discount and fell to the fair baseline; the second, an overall lean for newcomer batters (96–98% of
re-draws), came from the old sd-sum `value` and doesn't survive the switch to runs. Single T20 seasons are
mostly noise, for any method.

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
- **The ratings only modestly beat career averages for established players** (overall 0.19 vs 0.15 for
  batters, 0.15 vs 0.11 for bowlers), and **for newcomers rated from other leagues they are no better than
  the players' own league-adjusted numbers** (no test significant after correcting for six).
- **Each league is fitted on its own.** Cross-league comparison rests on one hand-set tier discount per
  league.
- **A wicket's price is a first-innings average.** The run cost of a wicket comes from first innings
  (over, wickets down) only and is applied to the chase too, where it really depends on the target; it
  is a league average, not the cost given the actual batters still to come.
- **Value is per ball, not per match.** A finisher who faces 10 balls a game and an opener who faces 25
  are compared per 100 balls; how many balls he gets is a team decision the value leaves out.
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

---

## 10. Keep or release

**What it does.** Before a retention deadline (IPL 2027: 15 November 2026, as reported), a franchise decides
which of its players to keep. For each player in its squad, CricDex sets what his game would fetch at auction
against what he is paid, makes a Keep / Release / Borderline call with a one-line reason, and shows the squad
that follows: purse left, open slots, role gaps and what filling them costs. Every assumption is editable on
the page (flip any player, change the purse or a role target) and on the CLI (`cricdex keep --team RCB
--release "Virat Kohli" --need spinner=4`). Code: `src/cricdex/web_parity/keep.py` ⇄ `site/src/lib/keep.ts`
(the same numbers and sentences, locked by `test_scripts/test_keep_parity.py`); the data is
`site/public/data/ipl/keep.json`, cooked by `scripts/export_site.py`.

**The rules are data.** A cycle's rules (purse, squad size, overseas cap, how many players may be kept, what a
kept player costs, RTM cards) live in `config/competitions.toml`, one entry per cycle, validated on load. Every
rule must cite a source or be listed as `assumed`, and the page marks the assumed ones. For IPL 2027 (a mini
auction): retentions due 15 Nov 2026 and the auction likely 16 Dec 2026 in Goa (press reports); any number of
players may be kept within 25 per squad and 8 overseas; a kept player costs his current salary out of the
purse; no right-to-match card; an overseas mini-auction buy is paid at most 18 cr. **No 2027 purse has been
published**, so the 2026 figure, 125 cr, is the editable default (the 2025-27 regulations set the total salary
cap at 146 / 151 / 157 cr, so about 131 cr is plausible, but nothing confirms it). The squad minimum (18), no
minimum-spend rule and season replacements being keepable are also assumptions. Sources are listed in the file
and on the page.

**The squads and salaries.** Each franchise's 2026 squad and every player's salary (the 2025 auction or
retention price carried into 2026, the 2026 auction price, a replacement's fee, a trade's price) come from
Wikipedia's "List of 2026 Indian Premier League personnel changes" (CC BY-SA), with the moves since the season
(Pant to DC at 15 cr for Kuldeep Yadav to LSG; Natarajan to SRH for Zeeshan Ansari; Rahane retired) from the 2027
page, by `scripts/ipl_squad_salaries.py` into the hand-editable `data/curated/ipl_squads_2026.json`. A player
released by his franchise (Mustafizur Rahman) or retired isn't on the list. A data check: 125 cr less the
retained salaries reproduces the published purse each team took into the 2026 auction exactly for six teams;
CSK (by 2.0 cr), DC (3.45), KKR (6.0) and RR (4.0) differ, so a salary on the source page differs from what the
team paid there. 252 of 274 squad players match a Cricsheet id (two by hand); the 22 who don't (uncapped players with no
ball-by-ball in our data) are listed and shown unrated.

**How each number is made.**

1. **Value** is the auction pool's value (section 7): his IPL value in runs per 100 balls, blended with his
   other leagues when his IPL record in the role is under 300 balls, with its uncertainty `sd`.
2. **Market price** is section 6b's price: what the IPL market has paid for players like him (on the
   cautious estimate, calibrated at the top end, under the IPL-evidence ceiling), with the chance he's
   bought if released. The **upper figure** is the upper quartile of that price on his central value
   (`price × e^(0.674 × 1.02)`, about 2×). His **on-field worth** (section 6a's curve) is a separate
   column, for comparison; it doesn't drive the call. A player who was an IPL side's regular **captain**
   last season carries a Captain badge, and the reason says the market pays captains a premium (about
   +22%, already in his market price). (An export from before the market model falls back to the curve,
   with the central price at `sd = 0` as the upper figure.)
3. **Surplus** = market price − salary. The **margin** is the larger of 0.5 cr and 15% of the salary.
4. **The call.** *Keep* when the surplus is at least the margin. *Release* when even the upper figure is
   at least a margin below the salary (so the call doesn't rest on the model's spread). *Borderline*
   otherwise: fairly paid (the salary sits inside the median-to-upper-quartile range), a close call (the
   upper figure clears the margin, the median doesn't), or a thin record (the same, with `sd` of 6+ runs).
   A player aged 35+ needs twice the margin to be a Keep. A player we can't rate is Borderline ("decide on
   scouting").
5. **Age** is at the auction date from the player master's date of birth; the outlook is a rule of thumb
   (under 24 improving, 24–29 prime, 30–32 holding, 33–34 slipping, 35+ declining). **Last season** is the
   raw 2026 strike rate or economy and wickets against that season's league figure (30+ balls), not the model.
6. **The squad.** Kept by default: every Keep and Borderline, **then made legal**: while the kept overseas
   players are over the overseas cap (8, or a retention limit on overseas players), the kept overseas
   Borderline players are released, lowest surplus per crore of salary first (an unrated player first, a
   Keep only once no Borderline is left); then the same over every kept player for the squad maximum (25,
   or a retention limit). Each one says "Released to fit the 8-overseas cap" / "the 25-player squad limit"
   in his reason, the CSV marks him (`auto_release`), and a player the user flipped is never moved; any
   call can still be flipped back. Purse left = purse − kept salaries. Slots open = 25 − kept (overseas:
   8 − kept overseas). Warnings flag a squad or overseas count over the cap (now only after a flip), a
   purse overrun, or too little purse to reach 18 players at 0.3 cr each. (`fit_to_rules` ⇄
   `fitToRules`.)
7. **Role gaps.** Tags: keeper (role), opener (batting position in the player master), death bowler (25%+ of
   his legal balls in overs 16–20, 60+ such balls, every auction-pool league), spinner (bowling type), overseas.
   Targets: 2 keepers, 3 openers, 3 death bowlers, 3 spinners, and the overseas players the squad has now (at
   most 8). Gaps are filled in that order from the **likely pool**: today's free agents in the auction pool
   plus the players our calls release from the other nine squads (at our price), cheapest first, among those
   at least as good as the best player the team released in that role (else an average player, value 0),
   within the open slots and overseas room. A pick counts for every tag he carries.

*Worked example (IPL 2027 defaults, data to the 2026 final).* RCB's Virat Kohli: value +13.6 ± 2.8 on 6,926
IPL balls, 555 international caps (24 in the last two years), 11 IPL seasons as captain but not last
season's, 37.9 at the auction. His market price is 10.3 cr (62% chance he's bought if released), the upper
figure 20.8; his on-field worth 10.0. Salary 21 cr, margin 3.15: the surplus (−10.7) isn't a Keep, and the
upper figure is only 0.2 under the salary, so **Borderline** ("Fairly paid: players like him fetch 10.3 to
20.8 cr (top quarter) against 21"). On the on-field curve alone (the earlier price) he was a Release.

The default calls (market price / upper figure vs salary, cr), legal after step 6:

- **RCB** (21 kept, 8 overseas): Keep Tim David, Bethell, Padikkal, Duffy, Suyash Sharma. Borderline
  Kohli (10.3 / 20.8 vs 21), Salt (12.2 / 26.3 vs 11.5), Hazlewood (6.4 / 13.4 vs 12.5), Jitesh Sharma,
  Krunal Pandya, Yash Dayal. Release captain Rajat Patidar (3.3 / 7.0 vs 11), Bhuvneshwar Kumar,
  Venkatesh Iyer, Rasikh Salam; released to fit the overseas cap: Richard Gleeson.
- **CSK** (25, 8): Keep Brevis, Short, Mhatre, Ellis, Hosein, Overton. Borderline captain Gaikwad (11.4 /
  23.4 vs 18), Samson (9.7 / 19.8 vs 18), Dube, Dhoni, Khaleel. Release Prashant Veer and Kartik Sharma
  (1.1 and 3.8 vs 14.2), Rahul Chahar; released to fit the overseas cap: Noor Ahmad (8.9 / 18.5 vs 10) and
  Dian Forrester.
- **MI** (25, 8): Keep Tilak Varma (17.6 / 27 vs 8), Rickelton, Jacks, Santner, de Kock. Borderline Bumrah
  (10.9 / 22.0 vs 18), captain Hardik Pandya (11.7 / 23.9 vs 16.35), Suryakumar Yadav (7.5 / 15.4 vs 16.35),
  Rohit Sharma (7.5 / 15.2 vs 16.3), Naman Dhir. Release Boult, Deepak Chahar; released to fit the squad
  limit: two unrated uncapped players (Mohammad Izhar, Ruchit Ahir).
- **KKR** (25, 8): Keep Harshit Rana, Finn Allen, Rachin Ravindra, Raghuvanshi. Borderline Green (13.8 /
  27 vs 25.2), Pathirana (8.0 / 16.9 vs 18), Rinku Singh, Narine, Varun Chakravarthy. Release Ramandeep
  Singh; released to fit the squad limit: Daksh Kamra (unrated).
- **SRH** (24, 8): Keep captain Ishan Kishan (13.7 / 27 vs 11.25), Nitish Kumar Reddy, Eshan Malinga.
  Borderline Abhishek Sharma (15.8 / 27 vs 14), Klaasen (9.8 / 20.5 vs 23), Head, Livingstone. Release
  captain Pat Cummins (6.9 / 14.2 vs 18), Harshal Patel, Natarajan, Jack Edwards; released to fit the
  overseas cap: David Payne.
- **GT** (24, 7): Keep captain Shubman Gill (21.4 / 27 vs 16.5), Sai Sudharsan, Washington Sundar.
  Borderline Buttler, Siraj, Rabada, Prasidh Krishna, Holder. Release Rashid Khan (6.9 / 14.1 vs 18),
  Tewatia, Shahrukh Khan.
- **PBKS** (21, 6): Keep Priyansh Arya, Connolly, Omarzai. Borderline captain Shreyas Iyer (12.6 / 25.6 vs
  26.75), Arshdeep Singh, Jansen, Stoinis. Release Chahal (1.8 / 3.6 vs 18), Shashank Singh, Dwarshuis,
  Mitchell Owen.

The market model sees no injury, form slump or loyalty, and Cummins and Rashid Khan are Releases on age
and the overseas level of the last two auctions; the toggles are how a franchise overrules a call.

**3-season outlook.** Each squad player also carries his Form forecast (section 11): the three medians for
2027–29, the shape (holds / improves / holds, then declines / declines) and the chance he is still a regular
in 2029, from his batting forecast (batters, keepers), bowling (bowlers) or the stronger of the two
(all-rounders). It is shown beside the call, sortable, and exported (`outlook_3y_avg`, `outlook_3y` in the CSV;
`cricdex keep --sort outlook`); it doesn't change the call, which prices one auction, not three seasons.

**Limits.** The price is section 6b's market price: better than the on-field curve out of time, but a
typical player is still off by a factor of about 1.7, overseas players lean high and single bidding wars
aren't predictable (section 6b), which is why the call only releases a player whose salary is above even
the upper figure. The comparison (who is paid well above or below the market for players like him) is the
useful part, not the exact crore. A franchise keeps players for reasons the data can't see (captaincy, fitness, local appeal,
the cost of buying a replacement in a thin market). The likely pool is our guess at what other teams release.
The overseas fee cap is shown but not modelled: Cameron Green's salary is the 25.2 cr KKR bid, assumed to be
the purse cost of keeping him. Twenty-two squad players aren't in the ball-by-ball data and can't be rated.

---

## 11. Form forecast

*Code: `src/cricdex/scout/forecast.py`, `scripts/form_forecast.py`; on the site: the player profile's
"Form forecast" section and Keep or release's "3-season outlook" column; in the terminal:
`cricdex forecast "<name>"` / `--team RCB` and `cricdex keep --sort outlook`.*

A retention or a mega-auction contract buys a player's **next three seasons**, not his career. Form
forecast projects his `value` (section 4: runs per 100 balls above the average ball, a wicket priced at its
run cost) for each of the next three IPL seasons, **starting from his current level**, with an 80% range,
and gives the chance he is still a regular (120+ balls faced or bowled in the season).

**What it learns from.** Two leakage-free histories. (1) What every player actually did in every IPL season
2008–2026, in the same currency (`runs_value.observed_value` on that season's own tables, so 2009 is judged
against 2009's scoring). (2) His career rating as it stood at the end of every season: the model refitted on
matches before each auction (everything through the season before, nothing after), the walk-forward fits the
price model already caches. A season value uses only that season; a rating at season t uses only matches up
to t.

### Step 1: his current level

The career rating (section 4) is one number for a whole career. A forecast should start from where he is
now, so each player gets a **current level** from a local-level Kalman filter over his seasons (the
standard state-space model for a quantity that drifts over time and is measured with noise):

```
true level, each year:   level(s) = level(s-1) + drift(age) + N(0, q)        debut level ~ N(mu0, tau2)
a season's value:        value(s) ~ N(level(s), c × 100 / balls)
drift(age) = d0 + d1 (age − 28) + d2 max(age − 32, 0)
```

All seven parameters are fitted by maximum likelihood per role, on the seasons up to the forecast's own
origin (so the backtest never sees later data). The filter weighs each season by how much it can be
trusted: a 450-ball season counts far more than a 60-ball cameo, recent seasons more than old ones (the
level drifts), and a season he missed adds a year's drift and uncertainty. For IPL batters: q = 8.0 (the
true level wanders by about ±2.8 a year), c = 940 (a 450-ball season still has a sampling sd of ~14), and
the drift is +2.5 a year at 20, 0 at about 28, −1.4 at 32 and −2.0 at 38. For bowlers q = 4.4; their drift
wanted to rise past 32 (the survivors again, see below), so it is held flat there, which leaves bowlers
with almost no age drift at all. The level model's own forecast k seasons on is the level plus k years of
drift (`f_k`), with sd √(level variance + k·q).

### Step 2: from the current level to a forecast

For each role, one weighted ridge regression of the value he goes on to post 1, 2 and 3 seasons later on a
blend of the level model's forecast and the career rating, `b = w × rating + (1 − w) × f_k`, with a slope and
a level per horizon, plus a residual age curve (a line with a bend at 32). The blend weight was **chosen on
validation origins 2014–2018** (targets up to 2021, before any test season), by rank correlation over
w = 0, 0.25, …, 1:

| Validation (origins 2014–18), mean of the three horizons | w = 0 (current level) | 0.25 | 0.5 | 0.75 | 1 (career rating) |
|---|---|---|---|---|---|
| Batters: ρ / MAE | 0.179 / 19.41 | **0.184** / 19.34 | 0.176 / 19.27 | 0.164 / 19.20 | 0.153 / 19.17 |
| Bowlers: ρ / MAE | 0.142 / 21.52 | 0.162 / 21.49 | 0.184 / 21.42 | 0.195 / 21.37 | **0.204** / 21.33 |

So **batters start from their current level** (w = 0.25: three-quarters the level model, a quarter the
career rating) and **bowlers from their career rating** (w = 1). That is the data, not a preference: a
bowler's career rating is already the best estimate of his current level (bowling ratings barely drift,
q = 4.4 against 8.0), and leaning on recent bowling seasons made the forecast worse at every weight. For
batters the current level ranks next season better; the career rating has a slightly lower error, so the
two are blended. Also tried on the same validation origins and left out: recent form as raw features (each
of the last two seasons, or the last three pooled, against the rating), last season's balls, career balls,
a finer age spline, and the rating and level side by side as separate regressors (their slopes split
unstably, one of them negative).

**Survivorship.** A season is only seen for players who play it, and the ones who decline are the ones who
get dropped: an aging curve fitted on survivors is too kind to age (Lichtman 2009, "How do baseball players
age?"; for cricket, Thorley on Test bowlers, and the 2024 ODI aging study, which both warn about it). The
level model's drift is fitted on the seasons that were played, so the regression's residual age curve is
where the correction happens: **inverse-probability weighting** (selection on observables; Hernán &
Robins, *Causal Inference: What If*, ch. 12). A logistic model gives every player-season the chance of being
seen (10+ balls) 1, 2 and 3 seasons later, from his rating, current level, age, recent form, balls last
season and in his career, and whether he missed last season. Each season that was seen counts 1 / that
chance (stabilised, capped at 10), so a 36-year-old who was kept stands in for the ones who weren't. The
residual curve, on top of the drift, with two bounds:

| Next-season value vs age 28, beyond the level model's drift | 25 | 32 | 35 | 38 |
|---|---|---|---|---|
| Batters, survivors only (no correction) | +0.8 | −1.0 | −2.1 | −3.2 |
| **Batters, corrected (used)** | +0.8 | −1.0 | −3.5 | −5.9 |
| Batters, phantom seasons (pessimistic bound) | +1.6 | −2.1 | −5.6 | −9.1 |
| Bowlers, survivors only | +0.7 | −0.9 | +1.3 | +3.6 |
| **Bowlers, corrected (used; held flat past 32)** | −0.2 | +0.2 | +0.2 | +0.2 |
| Bowlers, phantom seasons | +1.0 | −1.3 | −5.7 | −10.2 |

The corrected batting curve is steeper than the survivors-only one, as it should be. Bowlers are the honest
exception: the ones still picked in their mid-30s are the ones selectors trust for reasons the data doesn't
hold, so their curve *rises* past 32, more so after the weighting (which up-weights exactly those unlikely
survivors). Weighting can only correct for what is in the data. Within-player studies find no gain with age
once selection is modelled (Thorley), so a curve that rises past 32 is held **flat** there, in the level
model's drift and in the residual curve alike. The phantom bound (Lichtman's fix: every player who didn't
come back is given the value of a season that got a player dropped, the mean of the 10–59-ball seasons, −58
for batters and −43 for bowlers) is the other extreme and isn't used.

**Weights and noise.** Each season counts by 1 / its variance, `a_k + (slope × sd of the input)² + c × 100 /
balls` (the extra spread of true levels at horizon k, the input's own uncertainty carried forward, and one
season's sampling noise), fitted by maximum likelihood. Because the weights use the balls he actually got,
the median is his value **per ball of the balls he actually plays**. (Weighting by the balls he was
*expected* to get came out ~10 runs per 100 balls lower, with a bias of −11 in the backtest, and was
dropped.)

**The ranges.** Two 80% ranges per season: his **level** and **one season** at his usual workload (adds the
sampling noise for his average balls over his last three seasons). The one-season range is what the
backtest can check, and it is calibrated out of sample: for every earlier origin the model fitted only on
seasons up to then predicts the next three, and the range is widened by the factor that made 80% of those
past seasons land inside (walk-forward split-conformal; 1.02–1.05 for batters, 1.07–1.13 for bowlers).

**P(regular)** is a logistic model per horizon on the full feature set (rating, current level, age curve,
form, balls last season and in his career, a missed season): the chance he faces or bowls 120+ legal balls
that season. The medians are *if he plays*; P(regular) is the risk that he doesn't.

**The plain-English line** gives next season against his current level, then the shape (later seasons
against next season; within ±2 runs per 100 balls is "holding"). Flags: holds · improves · holds, then
declines · declines. When a current regular's P(regular) falls below 50% the line says so.

**Who gets a forecast.** Players with an IPL season in the last two (2025 or 2026) and, in that role, 60+
balls a season on average; not players the player master marks retired (Russell, Ashwin, Mohit Sharma).
194 players, 207 role rows.

### Backtest

Projections made with data through **2021, 2022 and 2023** (the level model, the regression and the
calibration all refitted on those seasons only), scored against what players actually did in 2022–2026, 1, 2
and 3 seasons ahead. Scored on players who played 60+ balls in the target season; ADVI seeds 42, 43 and 44
(the ratings refitted per seed; seed mean shown; the forecast's ρ moves by at most ±0.01 between seeds).

| Role, seasons ahead | n | MAE: forecast / rating now / current level / career numbers / age curve / last season | ρ: same order | One-season 80% range caught |
|---|---|---|---|---|
| Batters, 1 | 199 | **21.6** / 22.8 / 21.9 / 25.9 / 23.1 / 37.4 | 0.20 / 0.22 / 0.17 / 0.19 / **0.24** / 0.14 | 75% |
| Batters, 2 | 182 | **21.4** / 22.8 / 22.1 / 26.0 / 23.0 / 38.0 | 0.16 / 0.17 / 0.13 / 0.15 / **0.20** / 0.02 | 76% |
| Batters, 3 | 164 | **20.5** / 22.7 / 21.0 / 25.3 / 24.0 / 37.6 | 0.14 / 0.10 / 0.13 / 0.11 / **0.17** / 0.11 | 78% |
| Bowlers, 1 | 188 | **19.7** / **19.7** / 20.1 / 23.9 / 20.6 / 28.8 | 0.16 / **0.20** / 0.08 / 0.09 / 0.14 / −0.02 | 82% |
| Bowlers, 2 | 178 | 22.0 / **21.8** / 22.1 / 25.3 / 24.0 / 28.6 | 0.19 / **0.26** / 0.17 / 0.20 / 0.17 / 0.09 | 77% |
| Bowlers, 3 | 151 | 22.9 / **22.6** / 23.1 / 25.9 / 26.5 / 29.7 | 0.25 / **0.29** / 0.22 / 0.20 / 0.19 / 0.15 | 72% |

| P(regular), Brier score (lower = better) | 1 season ahead | 2 | 3 |
|---|---|---|---|
| Batters: forecast / rate by regular-now / base rate | **0.125** / 0.153 / 0.215 | **0.129** / 0.149 / 0.198 | **0.121** / 0.144 / 0.186 |
| Bowlers: forecast / rate by regular-now / base rate | **0.137** / 0.166 / 0.224 | **0.148** / 0.175 / 0.217 | **0.144** / 0.166 / 0.203 |

Baselines: **rating now** = his career rating for every future season (what CricDex showed before),
**current level** = the level model's estimate, unchanged, **career numbers** = his raw career totals in the
same currency, **age curve** = the rating plus the naive survivors-only average change by age (the classic
cross-sectional curve), **last season** = his value in the origin season. MAE in runs per 100 balls; ρ =
Spearman rank correlation, averaged over origins.

Read: **for batters the forecast has the lowest error at every horizon** (about 21 against 23 for the career
rating, 22 for the current level on its own, 26 for career numbers); on rank it is level with the rating
(0.20 vs 0.22 one season out, ahead three seasons out), and the naive age curve ranks best on these test
seasons, although it was no better than the rating on validation. **For bowlers it ties the career rating
on error and ranks a little lower**: bowling ratings are already well calibrated and age adds nothing, so
the bowling forecast is essentially the rating with honest ranges and P(regular). The previous version of
this forecast (the career rating plus age, no current level) scored batters' MAE 21.3 / 21.0 / 20.5 and ρ
0.24 / 0.22 / 0.14 on the same test: about the same error, a little better rank at one and two seasons; it
was replaced because it ignored how a player is doing now (Kohli at −1 after +31, +16, +30), which no test on
average error would catch. Single seasons are noisy enough that every method's error is ~20 runs per 100
balls and every rank correlation is 0.1–0.3. The one-season 80% ranges caught 72–82% of seasons.
P(regular) beats both baselines at every horizon.

Disclosure: a first version (separate models per horizon, form and sample-size features in the value
model) was scored on these test origins before the validation runs; it was worse for bowlers and isn't
shipped. Every later choice (the level model, the blend weights, the residual age curve) was made on the
validation origins, except the flat-past-32 bowler constraint, which comes from the literature.

### Reality check (as of the 2026 season)

Medians with the 80% range of his level; the one-season ranges are ~±20 wider. Russell is retired from the
IPL and gets no published forecast; his row shows what the model says anyway.

| Player (role, age) | Career rating | Current level | Last seasons: value (balls) | 2027 | 2028 | 2029 | P(regular) 2027 / 2029 |
|---|---|---|---|---|---|---|---|
| Virat Kohli (bat, 37) | +14 | +11 ± 6 | 2024 +31 (479), 2025 +16 (454), 2026 +30 (407) | +5 (−3 to +12) | +4 (−4 to +11) | +2 (−6 to +10) | 87% / 54% |
| Rohit Sharma (bat, 39) | +4 | −13 ± 7 | 2024 0 (278), 2025 −14 (280), 2026 +6 (180) | −14 (−22 to −7) | −15 (−23 to −7) | −16 (−24 to −8) | 42% / 20% |
| Jasprit Bumrah (bowl, 32) | +23 | +23 ± 6 | 2024 +58 (315), 2025 +62 (284), 2026 −6 (301) | +17 (+14 to +19) | +15 (+10 to +20) | +15 (+8 to +21) | 91% / 79% |
| Vaibhav Suryavanshi (bat, 15) | +60 | +38 ± 11 | 2025 +37 (122), 2026 +83 (327) | +45 (+33 to +56) | +50 (+38 to +61) | +51 (+39 to +63) | 99% / 100% |
| Sunil Narine (bat, 37) | 0 | −24 ± 10 | 2024 +34 (270), 2025 −28 (144), 2026 −81 (32) | −21 (−31 to −11) | −23 (−34 to −13) | −24 (−35 to −14) | 8% / 3% |
| Sunil Narine (bowl, 37) | +24 | +20 ± 6 | 2024 +40 (330), 2025 +21 (272), 2026 +42 (306) | +17 (+15 to +20) | +16 (+11 to +20) | +15 (+9 to +22) | 86% / 47% |
| Shubman Gill (bat, 27) | +18 | +21 ± 6 | 2024 +8 (289), 2025 +24 (417), 2026 +29 (449) | +20 (+13 to +27) | +21 (+14 to +29) | +21 (+13 to +29) | 97% / 94% |
| Abhishek Sharma (bat, 26) | +23 | +20 ± 8 | 2024 +32 (237), 2025 +30 (227), 2026 +39 (275) | +21 (+12 to +29) | +22 (+13 to +31) | +22 (+13 to +32) | 94% / 93% |
| MS Dhoni (bat, 45) | +1 | −13 ± 9 | 2024 +58 (73), 2025 −19 (145) | −15 (−24 to −6) | −16 (−25 to −7) | −17 (−26 to −7) | 8% / 4% |
| Heinrich Klaasen (bat, 35) | +18 | +17 ± 8 | 2024 +23 (280), 2025 +36 (282), 2026 +23 (390) | +12 (+4 to +21) | +12 (+3 to +21) | +10 (+1 to +19) | 87% / 58% |
| Travis Head (bat, 32) | +21 | +5 ± 10 | 2024 +49 (296), 2025 +1 (230), 2026 −12 (241) | +7 (−3 to +17) | +7 (−4 to +17) | +5 (−5 to +16) | 71% / 49% |
| Rashid Khan (bowl, 28) | +20 | +16 ± 6 | 2024 +3 (262), 2025 −15 (330), 2026 +23 (341) | +14 (+11 to +17) | +13 (+8 to +18) | +13 (+6 to +19) | 93% / 87% |
| Yuzvendra Chahal (bowl, 36) | +10 | +10 ± 6 | 2024 −1 (349), 2025 −3 (270), 2026 +4 (250) | +7 (+4 to +10) | +7 (+2 to +12) | +7 (0 to +13) | 71% / 34% |
| Andre Russell (bat, 38; retired) | +25 | +14 ± 9 | 2024 +30 (120), 2025 −7 (102) | +9 (−1 to +18) | +8 (−2 to +18) | +7 (−3 to +17) | 20% / 9% |
| Andre Russell (bowl, 38; retired) | −6 | 0 ± 8 | 2024 +30 (176), 2025 −7 (112) | −5 (−9 to −1) | −4 (−9 to +2) | −4 (−11 to +3) | 6% / 2% |

Where the forecast parts from recent form, and why:

- **Kohli** (+5 next season after +31, +16, +30). Three reasons, each from the data. His level (+11) still
  carries 2021–22 (−3, −14): seasons are noisy enough (sd ~14 even at 450 balls) that four good ones move it
  only part of the way. At 37–38 the level model drifts a batter down ~2 a year, and the survivorship-corrected
  residual takes another ~5 off at 38. And it is what happened to players like him: walk-forward, the 11
  batters aged 34+ whose last three seasons averaged +20 or better (mean +30; among them de Villiers, Gayle,
  Sehwag and Suryakumar) posted **+6 the next season on average (+13 balls-weighted)**, while the
  forecast had them at +15. If anything the model was too kind to that group, not too harsh. The 80% range
  (−3 to +12) and his 87% chance of playing on are the honest reading: he is more likely than not to stay a
  regular, at well above average, but not at his 2024–26 level.
- **Rohit** (−14 after 0, −14, +6): the level averages his seasons; at 39 the drift and residual age take
  his level of −13 a little lower. 42% to be a regular in 2027.
- **Bumrah** (+17 after +58, +62, −6): bowlers start from the career rating (+23), which already averages his
  history; the forecast pulls it toward average (slope 0.72 for bowlers). The bad 2026 isn't ignored but
  doesn't dominate: 301 balls is one season.
- **Suryavanshi** (+45 after +37, +83 at 15): two seasons (449 balls) are a small sample, so the level is
  pulled toward a debutant's prior (+38 ± 11), and the rating's +60 gets a quarter of the weight; age 15–17
  adds a little each year (the drift is positive at young ages), so the path rises to +51.
- **Narine as a batter** (−21 after +34, −28, −81): the −81 came from 32 balls and barely counts; the level
  (−24) follows his longer record as an opener who gets out often; 8% to bat as a regular.
- **Narine as a bowler** (+17 after +40, +21, +42): career rating +24 (bowlers lean on it), pulled toward
  average (the history puts a bowling rating's slope at about 0.7 a season ahead).
- **Gill, Abhishek** (+20, +21): in their prime and their level matches their form; the forecasts hold.
- **Dhoni** (−15 at 45): the 2024 +58 came from 73 balls; the level follows his 145-ball 2025 and his age.
  8% to be a regular.
- **Klaasen** (+12 after +23, +36, +23): level +17, then about −2 a year at 35+ and the residual age curve.
- **Head** (+7 after +49, +1, −12): the level has followed his last two seasons down to +5; a quarter weight on
  his +21 career rating lifts the forecast a little.
- **Rashid** (+14 after +3, −15, +23) and **Chahal** (+7 after −1, −3, +4): bowlers, so the career rating leads
  (+20 and +10) and is pulled toward average; their recent seasons count through the rating, not on top of it.
- **Russell** (retired): the model would say +9 as a batter at a 20% chance of being a regular.

**Limits.** One league: a thin IPL record gets a wide range, not help from other leagues. A season's value is
not opponent-adjusted (the career rating is); the level model works on season values. Selection the data
can't see (fitness, injury, captaincy, a franchise's plans) is outside the survivorship correction, which is
why the bowler curves are constrained. About 4% of players have no birth date and are taken as 23 at IPL
debut. The impact-player era (2023+) is in the training data only for the latest origins. Ranges are ~3
points narrow out of sample. The medians are conditional on playing: read them with P(regular).

Run: `uv run python scripts/form_forecast.py fits` (the walk-forward fits; cached), `backtest`, `build`,
`export` (`scripts/export_site.py` also writes `ipl/forecast.json` and the Keep or release outlook from
`data/metrics/forecast_ipl.json`).

---

## 12. Bid plan (beta)

> **Beta.** In honest replays of the 2025 mega and 2026 mini auctions the plan built a stronger squad
> than the real franchise for 4 and 2 of 10 teams — it is shipped as an exploration tool, not a verdict.

**What it does.** Before the auction (IPL 2027: likely 16 December 2026), a franchise needs a sheet: whom to
bid for, how high, and what to do when a target goes for more. Bid plan takes the squad and purse a team
brings in (Keep or release's plan, section 10, with the user's own keep / release calls carried in the
link), the competition's rules and the auction pool, and returns a priority list of targets, each with the
price rivals would likely pay, a bid that is usually enough, a **max bid** (the walk-away price) and the
chance of landing him under it, a **fallback chain** per role, and the squad that follows. Every assumption
is editable on the page and the CLI (`cricdex bidplan --team RCB --release "Rajat Patidar" --need spinner=4
--max "Rashid Khan=12"`). Code: `src/cricdex/web_parity/bidplan.py` ⇄ `site/src/lib/bidplan.ts` (the same
numbers on both, locked by `test_scripts/test_bidplan_parity.py` on synthetic leagues, all ten real teams and
the simulator with every calibration path switched on). It reads Keep or release's `keep.json` and the
auction pool; the only new export is an optional official auction list.

**1. The pool.** The free agents in the auction pool (section 7) plus every player the ten Keep-or-release
plans release, each at his market price (section 6b) with his value, role and tags (keeper, opener, death
bowler, spinner, overseas, as in section 10; *pace* = a bowler or all-rounder who isn't a spinner). A
released squad player also carries his 2026 salary as his **last price** (the rivals' reference price, step
2). Keep or release keeps every Borderline player, so its plans leave few places (19 across the league for
2027); real teams clear room before a mini auction. So each plan opens **at least 8 places** (the median
number of players a team bought at the 2023, 2024 and 2026 mini auctions), releasing its lowest-valued
players first (an unrated one first; a player the user decided on is never moved). The number is editable;
0 gives Keep or release's plans exactly. When the official auction list is published,
`data/curated/ipl_auction_register.json` (`[{"id": cricsheet id, "base_price": cr}]`) replaces this guess:
the export copies it to `auction_register.json`, and the page and the CLI use exactly those players at their
real base prices.

**2. What rivals would pay.** The other nine franchises, each with its own plan's squad and purse and the
Auction room's personality, bid in the Auction room's simulator 200 times. The simulator's bidding is
**calibrated to real auctions** (section 7 and [AUCTION_MATH Part 3b](AUCTION_MATH.md): a fitted level per
auction type, a concave curve on the market price, the last price where known, a demand shock per lot and
the market tightness). For each player sold in a run, the price **we would have to beat** is the winning
rival's maximum bid × 1.02 (the simulator's clearing step), within the 27 cr record and his price ceiling; a
player no rival bid for (or not among the simulator's lots) costs his base price. We are a price-taker: our
own buys don't change what the rivals do in a run.

**3. Squad strength**, in the runs-per-100-balls currency of section 4:

```
strength = best XI + 0.25 × depth − 3 × role places short
```

- **Best XI**: 11 players, at most 4 overseas, at least one keeper, five bowling options (bowlers and
  all-rounders) and six batting options (batters, keepers, all-rounders), their values added up. It is
  picked greedily: highest value first, skipping a player who would break the overseas limit or leave too
  few places for the keeper, bowling and batting minimums. A place the squad can't fill goes to a
  **replacement-level** player, −15 (about the median value of the pool's players priced at 2 cr or less); a
  player below that never plays, and an unrated player counts at that level.
- **Depth**: the next four players' edge over replacement level.
- **Role needs**: keepers (2), openers (3), death bowlers (3), spinners (3), pace bowlers (4), editable; each
  place short costs 3.

A player's **gain** is strength with him minus strength without him.

**4. The bidding rule and the exchange rate λ.** In each rival run the lots come up in pool order (stars
first). For each, bid up to **gain ÷ λ** (λ = runs of strength per crore) and buy him when that reaches the
price to beat, the purse allows (keeping 0.3 cr for each place still needed to reach the squad minimum) and
there is squad and overseas room. A user's max bid replaces gain ÷ λ for that player (0 = never bid). The
gain is measured on the squad so far **plus the likely buys still to come**, so an early lot isn't overpaid
while a cheaper fit comes later, and if a likely buy goes elsewhere his substitutes bid higher. "Likely buys"
are the players the rule lands in at least half the runs; the rule is re-run with them until they stop
changing (at most four rounds, usually two or three). λ is chosen from 25 rates (0.25 to 16, ×2^¼ apart) as
the one whose rule gives the **highest mean strength over the 200 runs** (a sample-average optimisation;
ties go to the higher rate). A low λ (a big purse for the places left) bids generously; a high one waits for
bargains. Unspent purse counts for nothing.

**No buying back your own releases.** A player the team releases goes into the auction, and the plan never
bids for him (unless the user sets a max bid). If he is worth that much to the squad, keeping him at his
salary is the cheaper and surer route. Instead the plan lists **"reconsider keeping"**: each release whose
worth to the likely squad (gain ÷ λ) is at least his salary. This is where Keep or release and Bid plan can
disagree on purpose: Keep or release asks "is he paid more than the market pays players like him?", Bid plan
asks "what is he worth to *this* squad?".

**5. The plan.**

- **Targets**: players the rule lands in at least 5% of the runs, or that the user gave a max bid.
- **Rivals pay** = the median price to beat over the runs (what to expect to pay); **usually enough** = the
  price that wins him in 9 runs of 10.
- **Max bid** = his worth to the squad: his gain to the likely squad (without him) ÷ λ, capped at 27 cr and at
  what the purse leaves after the other likely buys at their average prices (marked "purse"). In an open
  auction you keep bidding while the price is below your worth, so this is the walk-away price, not the
  expected price; when it is far above "rivals pay", the market undervalues him for this squad.
- **P(≤ max)** = the share of runs in which the max bid is enough; **in plan** = how often the rule actually
  lands him (purse and places run out).
- **Priority** = P(≤ max) × (gain − λ × his average price when the max bid is enough).
- **Fallback chain**, per role slot (keeper, opener, death bowler, spinner, pace, middle-order batter,
  all-rounder): the slot's targets in priority order, each with his max bid if every name before him has
  gone for more.
- **The squad**: strength now and expected (mean over the runs), best XI before and after, expected spend
  and squad size, the likely squad, the share of runs in which each need is met, what is still missing, and
  the releases to reconsider.

*Examples (IPL 2027 defaults: 125 cr assumed, 8 places opened, 200 runs; data to the 2026 final).* "Rivals"
= what rivals usually pay; "9 in 10" = usually enough; "max" = worth to the squad.

- **RCB** (17 kept, 41.1 cr left; Patidar, Bhuvneshwar Kumar, Venkatesh Iyer and Rasikh Salam released on
  Keep's calls, four unrated youngsters to open places; λ 0.84).
  1. *Rahul Singh*, uncapped batter, free agent: rivals 0.9, 9 in 10 3.6, max 17.6. His domestic record rates
     him +10 per 100 balls but the market prices him at 0.8 (uncapped, little IPL); after the middle-order
     releases he would add 14.8 to RCB's strength. Expect to pay about 1 cr; the high ceiling says don't lose
     him to a small bidding war.
  2. *Yuzvendra Chahal*, released by PBKS (last paid 18): rivals 3.3, 9 in 10 12.4, max 14.5. The one spinner
     who walks into RCB's XI; his old price keeps rivals interested, so the range is wide. If he goes above
     14.5: Rahul Chahar up to 13.2.
  3. *Sandeep Sharma* (RR, last 4): rivals 1.1, max 10.4: the fourth pace bowler RCB lacks.
  4. *Atharva Taide*, opener: rivals 4.1, max 11.4; fallback Mayank Agarwal ≤ 5.5. He fills the third opener
     (each missing role place costs 3 runs of strength).
  5. *Rahul Chahar* (CSK, last 5.2): rivals 3.1, max 10.3.

  **Reconsider keeping**: Patidar (paid 11, worth about 20 to RCB), Bhuvneshwar (10.75, about 19), Venkatesh
  Iyer (7, about 9). Keep or release releases them because players like them fetch less than their salary;
  Bid plan says RCB's thin squad would miss them more than that. Expected: strength 34 → 105 (best XI 36 → 92)
  for about 17 cr.
- **CSK** (17 kept, 51.9 cr; λ 0.42: plenty of purse for the places, so it bids generously): Rashid Khan (GT
  release, last 18: rivals 4.4, 9 in 10 19.6, max 19.5, purse-bound), the spinner the XI is built around;
  Bhuvneshwar (rivals 3.6, max 17.5) for the death overs; Jonny Bairstow, keeper-opener (rivals 4.8, max 18.9;
  fallback Devon Conway ≤ 13.9); Chahal (3.5, max 16.6). Reconsider keeping Noor Ahmad (paid 10, worth about
  12). Strength 87 → 176 for about 35 cr.
- **MI** (17 kept, 26.8 cr; λ 1.0): Bhuvneshwar ≤ 15.5 (purse-bound), Bairstow ≤ 16.3, Rashid ≤ 11.6 (the purse
  can't stretch further, so MI lands him in only a quarter of the runs; Chahal ≤ 12.3 is the fallback),
  Sandeep Sharma ≤ 8.9, Rahul Singh ≤ 8.6. Strength 86 → 162 for about 19 cr.
- **KKR** (17 kept, 26.8 cr; λ 1.19, so the purse binds hardest): Bhuvneshwar ≤ 8.5, Rahul Singh ≤ 6.1, Chahal
  ≤ 7.5, Sandeep ≤ 5.8, all cut to what the purse leaves after the likely buys; keeper chain Bairstow ≤ 4.5 →
  Conway ≤ 9.6 (Conway is the likelier buy). Still one death bowler short (2 of 3) after the likely buys.

The same few names top several lists (Bhuvneshwar, Chahal, Bairstow, Rahul Singh): released or free players
the rival model thinks will go cheaply for what they add. In a real room more than one team would chase them;
the price-taker plan can't see that, which is why "9 in 10" and the fallback chains matter.

**Validation 1: rival prices against real ones.** On the 2025 mega and 2026 mini auctions, out of time (the
inputs of `scripts/bidplan_backtest.py`, below), the median price to beat from a team's nine rivals for each
player that team really bought, against what it paid:

| | 2025, before → after calibration | 2026, before → after |
|---|---|---|
| lots | 173 | 62 |
| median real ÷ price to beat | 1.00 → 1.25 | 1.00 → 1.00 |
| error, mean abs. ln | 0.71 → **0.60** (market price alone 0.67) | 0.70 → **0.68** (0.80) |
| rank correlation | 0.80 → 0.80 | 0.56 → 0.50 |
| real price inside the rivals' 20–80% range (60% = calibrated) | 29% → **55%** | 40% → **52%** |

The simulator's own clearing prices against reality (all ten teams bidding) are in AUCTION_MATH Part 3b: the
spread and the top end now hold out of time; the 2025 mega auction still ran about 1.5× above the simulation
on contested lots.

*Reality check: well-known lots* (real price; the rivals' price to beat for the team that bought him, median
and 20–80% range; market price):

| auction | player | real | rivals' price to beat | market |
|---|---|---|---|---|
| 2025 | Rishabh Pant | 27.00 | 16.2 (7.3–27.0) | 27.0 |
| 2025 | Shreyas Iyer | 26.75 | 12.3 (5.3–27.0) | 19.6 |
| 2025 | Venkatesh Iyer | 23.75 | 2.7 (2.0–6.7) | 2.7 |
| 2025 | Arshdeep Singh | 18.00 | 7.1 (2.8–16.0) | 13.4 |
| 2025 | Yuzvendra Chahal | 18.00 | 5.8 (2.3–15.3) | 7.8 |
| 2025 | Jos Buttler | 15.75 | 7.8 (3.0–18.4) | 10.9 |
| 2025 | KL Rahul | 14.00 | 15.6 (7.1–27.0) | 23.0 |
| 2025 | Mitchell Starc | 11.75 | 7.5 (3.2–18.5) | 9.5 |
| 2025 | Ishan Kishan | 11.25 | 11.6 (5.3–27.0) | 14.6 |
| 2025 | Jitesh Sharma | 11.00 | 1.0 (1.0–1.4) | 4.1 |
| 2025 | Bhuvneshwar Kumar | 10.75 | 2.0 (2.0–2.3) | 2.3 |
| 2025 | Prasidh Krishna | 9.50 | 4.7 (2.0–10.3) | 5.5 |
| 2025 | Liam Livingstone | 8.75 | 6.2 (3.1–13.3) | 9.6 |
| 2026 | Cameron Green | 25.20 | 13.8 (5.3–21.9) | 12.8 |
| 2026 | Matheesha Pathirana | 18.00 | 3.8 (2.1–8.7) | 9.7 |
| 2026 | Liam Livingstone | 13.00 | 6.2 (2.9–13.2) | 7.1 |
| 2026 | Venkatesh Iyer | 7.00 | 4.1 (2.6–8.3) | 2.3 |
| 2026 | Kartik Sharma | 14.20 | 0.3 (0.3–0.5) | 0.5 |
| 2026 | Prashant Veer | 14.20 | 0.3 (0.3–0.5) | 0.5 |

Most stars land inside the range (Pant, Shreyas Iyer, Arshdeep, Chahal, Buttler, Rahul, Starc, Kishan,
Prasidh, Livingstone twice). The misses are the market model's blind spots, which no bidding model fixes:
players teams had scouted that the model barely rates (Kartik Sharma and Prashant Veer, 14.2 each), prices the
features don't explain (Venkatesh Iyer 23.75 in 2025, Pathirana 18 in 2026), and two whose old price misled
the anchor: Jitesh Sharma (his last price was an uncapped 0.2 cr) and Bhuvneshwar (priced on age, with a last
price of about 5 cr in 2025 terms; for 2027 his 10.75 salary is the anchor). The last-price anchor helps on
average (it is fitted) but drags down a player who has improved since his last auction.

**Validation 2: the plans, replayed** (`scripts/bidplan_backtest.py`, about 35 minutes). For each auction and
franchise, with only what was known before it: values from the IPL fitted on the matches before the auction
date, blended with the other leagues' fits whose cut-off is on or before it and discounted for IPL relevance
as the pool does; market prices from the shipped recipe re-fitted on the auctions before (2018–2024 for 2025,
2018–2025 for 2026); the real retentions and purses; the pool = every player sold at that auction with a
Cricsheet id at his real base price, **plus the unsold alternatives** (recent IPL players neither retained nor
bought: the P(bought) risk set, which the plan may target but is never credited with buying); rivals
calibrated as above, 200 runs. The plan is built with the team's real purse left and with a purse equal to
what it actually spent ("same spend"); its bidding rule is played against **the real prices** (a player is
ours if our bid reaches what he actually sold for, purse and room permitting). Squads are scored on **what the
players did in the IPL season the auction was for** (runs per 100 balls above that season's average,
`runs_value.observed_value`, 60+ balls in a role, else replacement level), with the same strength measure.

| | 2025 mega | 2026 mini |
|---|---|---|
| Same spend, next season: plan's squad stronger than the real one | **4 of 10 teams** (mean +2.1 strength, −0.4 best XI) | **2 of 10 teams** (mean −5.7, −8.8) |
| The same on our own pre-auction values (circular: the plan maximises exactly this) | 10 of 10 (+77) | 10 of 10 (+30) |
| The plan's top 10 targets that team really bought | 0.9 on average | 0.5 |
| Real price ÷ rivals' median, over the plan's targets that sold | 1.61 | 1.87 |
| P(≤ max bid) said 0.8–1.0: share sold at or under the max bid | 0.92 (said 0.93, n = 74) | 0.44 (said 0.88, n = 9) |
| P(≤ max bid) said 0.5–0.8 | 0.41 (said 0.63, n = 87) | 0.55 (said 0.63, n = 20) |

Per team, best XI next season, plan / real (same spend). 2025: CSK 16 / 26, DC 146 / 69, GT 113 / 157, KKR
133 / 39, LSG 99 / 72, MI 137 / 284, PBKS 138 / 178, RCB 139 / 166, RR 106 / 39, SRH 125 / 127. 2026: CSK 74 /
92, DC 52 / 63, GT 173 / 207, KKR 129 / 41, LSG 102 / 119, MI 153 / 153 (two buys against five), PBKS 153 / 132,
RCB 230 / 267, RR 105 / 166, SRH 102 / 118.

**The honest read.** With rivals that price like real rooms, the plan's squads are **level with the real ones in
2025** (ahead for DC, KKR, LSG and RR, behind for CSK, GT, MI, PBKS, RCB and SRH; mean +2 strength) and **worse
in 2026** (ahead only for KKR and PBKS). It often spends less than the team did (it walks away when the price
passes a player's worth, and some of its picks went unsold or unregistered in reality). An earlier version of
this replay, with uncalibrated (too cheap) rivals and a pool of only the players who sold (a hindsight the real
room didn't have), showed the plan ahead for 8 of 10 teams in 2025; that lead does not survive. Teams bought
about one of the plan's top 10: it doesn't read the room as franchises do, whose scouting sees what our
ratings can't. The targets' real prices ran 1.6–1.9× the rivals' median: they are chosen *because* the model
rates them above their price, so they are where it is most often wrong. So the plan is a structured starting
sheet (who fills which need, where the value runs out, what to do next, which release to rethink), not a
forecast and not, on this evidence, better than a franchise's own war room.

**Limits.** Rivals bid by hand-set personalities on a calibrated level, and don't react to our buys; a bidding
war for one name isn't predictable. Prices rest on the market model (a typical player off by about 1.7×), which
can't see scouting, injury or brand. Strength adds per-ball values across an XI (a bowler's per ball he bowls, a
batter's per ball he faces) and knows nothing of batting order, conditions or the impact-player rule beyond
five bowling and six batting options. Lot order is "stars first", not the real sets. Values are this season's
ratings, not a multi-year forecast: for a player bought for three seasons, section 11's forecast
(`forecast.json`) is the natural next input (gain over the next three seasons, weighted by P(regular)); not
wired in yet. Keep or release's salaries, squads and assumed purse carry over unchanged.
