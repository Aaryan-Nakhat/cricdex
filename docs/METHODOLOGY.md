# How CricDex works — every model, in plain English

CricDex turns Cricsheet's ball-by-ball records into numbers a scorecard can't give you: how much a player
moved the result, how good he is once you account for who he faced, who plays like him in another league,
and what he might fetch at an IPL auction. This page explains every one of those models: **what it does,
how it does it, a small worked example, and where it falls short**. It was checked against the code in
October 2026, and file names are given so you can trace any claim.

No maths background is assumed. Where a formula helps, it comes after the plain-words version.

**A note on the 2025–26 tests.** Each model's recipe is chosen on data up to 2024 and then scored on the
2025 and 2026 seasons, and the protocols below are written as "the test, once". That was true of each
protocol when it ran, but the same two seasons have since been looked at again and again across CricDex:
several price recipes were each scored on them (section 6b), and the Bid plan replays have seen them five
times (section 12; ROADMAP I17, I18). Choices made after a look are no longer blind to it, so read every
2025–26 figure on this page as **optimistic**, not as a clean out-of-time test. The clean test is the next
real event: the 2027 retention lists (15 Nov 2026) and auction.

**A key to the labels.** Wherever several versions of a model were compared, each candidate has a short
name, declared before any of its numbers: price recipes are letters (Z, then BA–BJ in October 2026, the one
shipped in bold), Keep models L1–L8, Bid plan money rules by a word ("auction", "opportunity"). They are the
record of what was tried, so they stay; the tables say what each one is. "Audit item N" and codes such as
B15 name findings of the October 2026 reviews of the models; each is explained where it is cited. ROADMAP
items (I17, I18) are in [ROADMAP.md](ROADMAP.md).

← back to the [README](../README.md) · the deeper technical tour: [STUDY_GUIDE.md](STUDY_GUIDE.md) ·
metric formulas in full: [METRICS.md](METRICS.md) · the auction step by step: [AUCTION_MATH.md](AUCTION_MATH.md)

| Section | What's in it |
|---|---|
| [1. Data and identity](#1-data-and-identity) | Where the balls come from, one id per player, merged venues, super overs, the one AI step |
| [2. Net Game Impact (NGI)](#2-net-game-impact-ngi) | Win probability added, ball by ball |
| [3. The twelve context metrics + fielding](#3-the-twelve-context-metrics--fielding) | Pressure Runs, Intent Curve, Dot-Ball Recovery and the rest; time windows and eras |
| [4. Bayesian skill ratings](#4-bayesian-skill-ratings) | Four skills per player, adjusted for the opposition, with honest uncertainty; moved to his age next season for the auction tools (4b) and calibrated against what players then did (4c) |
| [5. Scout look-alikes](#5-scout-look-alikes) | Who plays like X in another league, and what he'd cost; style twins on every profile (5a) |
| [6. From skill to crore](#6-from-skill-to-crore) | Turning a rating into an auction price; who plays and how much he adds a match (6c); how a rating from another league carries over to the IPL (6d) |
| [7. The auction room](#7-the-auction-room) | Retentions, lots as real shortlists, a demand model fitted on real auctions, ladder clearing |
| [8. Does it predict? The backtest](#8-does-it-predict-the-backtest) | Fitted before each season, scored on that season |
| [9. Limits](#9-limits) | What the models can't see, and what's approximate |
| [10. Keep or release](#10-keep-or-release) | The retention calculator: the chance a franchise keeps him (backtested on every real deadline), purse, role gaps |
| [11. Form forecast](#11-form-forecast) | A player's value over the next three seasons: aging, survivorship, ranges, backtest |
| [12. Bid plan (draft)](#12-bid-plan-draft) | The auction bidding plan: rival prices, squad strength, max bids, fallback chains, the 2025 and 2026 auctions replayed |
| [13. The reality gate](#13-the-reality-gate) | The standing check every model change must pass: the outputs against the real IPL |

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
from these files. Cricsheet's SMAT stops at 15 Dec 2024 (checked again 22 Oct 2026; the 2024-25 group stage
and all of 2025-26 are on its missing list), so every number that leans on SMAT is marked with how much of it
does (section 9).

**Afghanistan is withheld.** Since 14 November 2024 Cricsheet withholds every match featuring the
Afghanistan men's team, and the Afghanistan Premier League, as a protest at the treatment of Afghanistan's
women players ([Cricsheet's explanation](https://cricsheet.org/article/explanation-for-withholding-of-afghanistani-matches/)).
So the men's T20I, ODI and Test collections have no Afghanistan match at all (checked 22 Oct 2026: every
other Test nation and every associate with 50+ matches is present and current). Two consequences:

- *International caps* (the capped flag, and `intl_caps` / `intl_caps_2y` in the market price, 6b) are
  restored from two sourced records (`src/cricdex/scout/identity/withheld.py`, cached in
  `data/curated/withheld_internationals.json`): Cricsheet's own `all_json.zip` as archived by the Wayback
  Machine on 10 Mar 2023 (both XIs of every Afghanistan T20I / ODI / Test to 19 Feb 2023, real dates,
  Cricsheet identifiers), and after it the revision history of Wikipedia's Afghanistan T20I / ODI / Test
  cap lists (each increase in a player's count dated at the revision that published it, so a count as of
  an auction can lag the matches by the page's editing delay but never lead them; a count later reverted
  never counts). Each row's ESPNcricinfo link maps to a Cricsheet id through the People Register, checked
  by name. Checked against the archive's exact XIs where both exist (2016 to Feb 2023): T20I counts within
  0.9 appearances per player on average (a lag), ODI within 1.0 (no lean); for Tests the Wikipedia lists
  are the more complete record (the archive misses several Afghanistan Tests). Opponents' appearances in
  the matches after Feb 2023 aren't recovered (a few games per opponent). Rashid Khan goes from 1 cap (an
  ICC World XI game) to 239 before the 2027 auction; 31 Afghan players in the master become capped.
- *Ball-by-ball:* Afghanistan's T20Is can't be rebuilt, so Afghan players have no T20I rating and their
  opponents miss those balls. T20Is aren't an auction-pool league, so no IPL rating, pool value or price
  uses them; the IPL, BBL, SA20, ILT20 and other franchise leagues still have every Afghan player's balls.

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

## 3. The twelve context metrics + fielding

Standard averages and strike rates are context-blind. Each of these twelve isolates one skill a scorecard
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

**Four splits, and a reliability test (since 2026-10-29).** A metric is only worth a board if it measures
something stable about a player, not luck. The test, declared before any number: split each player's IPL
matches alternately in two, compute the metric on each half, and keep it when the two halves rank players
alike (Spearman r ≥ 0.30, p < 0.01, 40+ players). Six candidates were tested, with the shipped Boundary
Dependency as a yardstick (r 0.67) and Pressure Conversion as a control:

| Candidate | Split-half r | Kept |
|---|---|---|
| Dot-Ball Avoidance (batters) | 0.70 | yes |
| Pace vs Spin, the spin edge (batters) | 0.37 (scoring against spin alone 0.66) | yes |
| Finisher Index (batters) | 0.44 | yes |
| Left vs Right, the left edge (bowlers) | 0.30 | yes, the weakest |
| Wickets of set batters (20+ balls faced; bowlers) | −0.05 | no |
| Wickets with the new ball, overs 1–3 (bowlers) | −0.16 | no |
| Pressure Conversion (control, either definition) | −0.18 | no: retired |

Run-based skills hold up; wicket-based ones don't, because wickets are too rare for a split of a player's
matches to agree. Each kept metric is measured against the league on the same kind of ball (same phase;
the same over of a chase for the finisher), and pulled toward the league by how little the player's sample
says (empirical Bayes: the spread between players beyond ball-to-ball noise sets the prior strength; an
edge is shrunk as a difference, with the noise of both samples), so a short record doesn't top a board.

**Dot-Ball Avoidance** — *does he keep the score moving?* Dots avoided per 100 balls: the league's dot
rate in the phase of each ball he faced, less his. +5 = five fewer dot balls per 100 than the average
batter on the same balls. Needs 150 balls. IPL leaders: Sai Sudharsan, Shubman Gill, Heinrich Klaasen.

**Pace vs Spin** — *who to send in when the spinners come on?* Runs per 100 balls above the league
against spin and against pace (each against the league on that bowling type in the same phase), and the
spin edge, their difference. Needs 100 balls against each. Narine and Abhishek Sharma are far better
against spin; Dhoni and Gilchrist were better against pace.

**Finisher Index** — *who closes a chase?* Runs per 100 balls above the league in overs 17–20 of a chase,
with innings and not-out %. Needs 40 balls. Leaders: Rinku Singh, AB de Villiers, Tim David.

**Left vs Right** (bowlers) — *who to bowl at a left-hander?* Runs saved per 100 balls against left- and
right-handers (each against the league on that hand in the same phase), and the left edge. Needs 90 balls
against each hand. Off-spinners turning the ball into the left-hander lead (Moeen Ali, Washington
Sundar, Mohammad Nabi); leg-spinners and left-arm spinners sit at the right-hander end (Chahal, Axar).
The weakest signal of the four.

**Pressure Conversion, retired.** It counted wickets on the ball after four dots in a row inside one
bowler's over, so a season gave a bowler a handful of chances and the board sorted raw rates of 0 out of
9. Rebuilt from the batting side's drought (four balls with no run or wicket, across overs and bowlers)
and shrunk toward the league rate, the data still show no bowler differing from the league beyond chance
(the fitted spread between bowlers is zero, and its split-half r is −0.18). With nothing to rank, the
board was removed; `metrics/bowler.py` keeps the rebuilt computation for reference.

**Wicketkeeping and Fielding boards.** From each dismissal's list of fielders (every wicket on a delivery,
including the rare second one): a catch, a stumping, or a run-out involvement (every fielder named in a
run-out gets one). Scorecards don't say who kept wicket, so the keeper of each innings is read from the
fielding side's XI: whoever made a stumping in it, else the XI player the player master tags as a
wicket-keeper, else one who has stumped anyone in this league (ties to the most stumpings). Dismissals
made while keeping go on the Wicketkeeping board, with the matches kept; the rest, a keeper's on days he
fielded included, go on Fielding. (Until 2026-10-29 a player counted as a keeper for his whole career if
the tag or any stumping said so: a batter once tagged a keeper sat on the keeping board.)
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
and the auction correct for that with a league translation fitted per league and role (section 6d). There's one skill set per role
for a player's whole career in that league (the context is adjusted for, but a player's own form isn't
allowed to drift); what the auction tools read is moved to his age next season (section 4b). Batting slot
comes from the data, so a player who moved up the order is grouped by his median slot.

### 4b. Time-aware ratings: his level next season

**Why.** The rating above is one number for a whole career. Everything that values a player for the coming
season read it as his level now: the contribution per match (6c), and through it the auction pool's ranking,
P(plays), Bid plan and Keep or release, and the market price's input (6b). So a 37-year-old's number still
carried the seasons he played at 29. David Miller (37) was the first Bid plan target on six of ten sheets,
and with the buy model on (6c) David Warner (40), Mohammad Nabi (42) and Faf du Plessis (42) topped sheets
(ROADMAP I18, Tier D #34). Since 2026-10-27 each role's value is moved to the coming season before anything
reads it. Code: `src/cricdex/scout/ratings/drift.py`; fit, choice and test: `scripts/rating_drift_fit.py`;
model: `config/rating_drift.json`; every number below: `data/metrics/rating_drift_ipl.json`.

**What it does.**

```
value now = career value + A(his age next season) − Σ w_s × A(his age in season s)
```

`A` is the aging curve in runs per 100 balls, piecewise linear through knots every four years from 16 to 44
(flat beyond them), with A(28) = 0. `w_s` is the weight of season s in his career value: each league's seasons
by balls, times that league's share of his blend (6d). A batter whose evidence was gathered at 29 to 33 and
who will be 38 next season loses A(29–33) − A(38), about 5 runs per 100 balls; a 24-year-old whose evidence
starts at 19 gains a little. The value shown (`value`) stays the career rating; the pool rows carry the shift
as `time_shift_bat` / `time_shift_bowl`.

**The model the curve is fitted in.** A state-space model of every player's season values in every
auction-pool league (`runs_value.observed_value` per league and calendar year, 58,559 player-league-seasons;
on the IPL scale through the league translation, a + b × value), fitted by maximum likelihood per group:

```
level(y)    = level(y − 1) + A(age(y)) − A(age(y − 1)) [+ N(0, q): a random walk, in some candidates]
season value on the IPL scale ~ N(level(y), b² × c × 100 / balls [+ e in a league other than the IPL])
P(he plays in year y | level) = Φ(b0[y] + bL × level(y) + bA(age(y)))       the selection model
```

The curve is learned **within players**: each season is compared only with the same player's other seasons.
The **selection model** is the survivorship correction. A curve fitted on the seasons that were played is too
kind to age, because the players who decline are the ones who stop playing (Lichtman 2009; for cricket,
Thorley). Here a season a player was at risk of playing (a league he had played had matches that year, so
the end of Cricsheet's SMAT in 2024 doesn't count as him being dropped) and didn't is evidence that his level
fell: a shared-parameter model (Diggle & Kenward 1994), with a per-year intercept, a slope on the level and
its own age curve (players retire with age at any level). The probit updates are moment-matched (assumed
density filtering, Rasmussen & Williams §3.6); the Gaussian part is an exact Kalman filter, checked against
a brute-force conditioning in `tests/test_drift.py`. Without the selection model the fitted batting curve
is flat after 28 and the bowling curve rises to +8 at 40, the survivors' picture; with it, batting falls
after 32.

*Tried while building, before any validation number:* a constant offset per player and league (his
translated level there against his IPL-scale level, prior variance fitted). Maximum likelihood put its
variance at 3.6 (sd 1.9 runs per 100 balls) and the curves didn't move, so it was dropped.

**Candidates and the frozen protocol.** Declared on 2026-10-27 before any validation number. For every IPL
season 2019–2024 (walk-forward), each candidate is fitted on the season values known before that season's
auction and scored on what every player who then played did: his **contribution per match** (runs above
replacement a match he played, `bidplan_backtest._next_season_values`), predicted the way the export
predicts it (his as-of ratings per role blended across leagues, shifted by the candidate, at his expected
balls and that auction's replacement levels). Chosen on the pooled mean absolute error; then fitted on the
season values before the 2025 auction and scored **once** on 2025 and 2026.

| candidate | validation 2019–24 (764 player-seasons): MAE / RMSE / bias / rank corr. | aged 34+ (117): MAE / bias |
|---|---|---|
| C0 career rating (reference, shipped until now) | 4.036 / 5.112 / +0.38 / 0.297 | 4.34 / +1.18 |
| **C1 aging only (no random walk) (chosen)** | **4.019** / **5.088** / +0.35 / **0.298** | 4.23 / +0.65 |
| C2 random walk only (no aging curve) | 4.087 / 5.192 / +0.64 / 0.284 | 4.34 / +1.56 |
| C3 random walk + aging; one bowling curve | 4.065 / 5.146 / +0.14 / 0.276 | 4.20 / +0.10 |
| C4 C3 with pace and spin curves apart | 4.066 / 5.152 / +0.11 / 0.275 | 4.20 / +0.07 |
| C5 C3 with pace and spin partially pooled (empirical Bayes) | 4.067 / 5.147 / +0.10 / 0.277 | 4.22 / +0.06 |
| C6 C3 without the selection model | 4.066 / 5.160 / +0.78 / 0.304 | 4.37 / +1.62 |

| test, once | 2025 (142): MAE / rank corr. / bias | 2026 (140) | pooled (282): MAE / RMSE / bias / rank corr. | aged 34+, 2025 / 2026: bias |
|---|---|---|---|---|
| C0 career rating | 4.147 / 0.304 / +0.68 | 4.674 / 0.299 / +0.48 | 4.408 / 5.796 / +0.58 / 0.301 | +0.49 / +1.32 |
| **C1 aging only** | **4.136** / **0.315** / +0.77 | **4.667** / **0.302** / +0.59 | **4.400** / 5.803 / +0.68 / **0.309** | **+0.13** / **+1.04** |

(Contribution per match, runs above replacement; bias = mean predicted − real. The 34+ columns are a
reading, not a selection criterion.)

**Honest reading.** The aging curve helps a little, and the test agrees: mean error 4.400 against 4.408, rank
correlation 0.309 against 0.301; the root mean square error is a hair worse (5.803 against 5.796) and the
overall bias rises (the curve lifts the young). Where it matters is the veterans: the career rating
overrated players aged 34+ by 1.18 runs a match in the validation and by 0.49 and 1.32 in the test; the
aging curve takes that to 0.65, 0.13 and 1.04. **A drifting skill did not help.** Every random-walk
candidate predicted next season worse than the career rating itself (pooled MAE 4.065–4.087 against
4.036), as the form forecast found for bowlers (section 11): one season is too noisy (sd ~14 runs per 100
balls even at 450 balls) for the walk to separate form from luck at the horizon that matters here. Pace and
spin apart (C4) didn't beat one bowling curve, and the empirical-Bayes pooling (C5) estimated the spread
between them at zero, so the curves were fully pooled.

**The shipped curves** (refitted on every season before the 2027 auction; runs per 100 balls against age 28):

| age | 18 | 20 | 22 | 24 | 26 | 28 | 30 | 32 | 34 | 36 | 38 | 40 | 42 | 44 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batting | −10.0 | −6.7 | −3.5 | −0.2 | −0.1 | 0 | −0.2 | −0.5 | −2.4 | −4.3 | −6.8 | −9.4 | −18.4 | −27.4 |
| bowling | −1.6 | −0.9 | +0.2 | +1.3 | +0.6 | 0 | −0.1 | −0.3 | −0.7 | −1.2 | −1.9 | −2.7 | −1.0 | +0.7 |

Batters improve into their mid-20s, hold to about 32 and then decline, faster after 40 (few players there,
so the last knots are wide). Bowling barely changes with age. The fit on seasons up to 2024 (what the
protocol runs use, `model_le2024`) is similar: batting −2.8 at 36, −6.2 at 40. A player with no date of
birth is taken as the median age at a first season in the data, 23.9.

*Reality check, 2026-10-27* (pool, IPL 2027; shift in runs per 100 balls; contribution in runs a match
above replacement, before → after; the market price and Keep inputs moved with it):

| player | age | shift bat / bowl | contribution (bat + bowl) | P(plays) | season value | pool rank |
|---|---|---|---|---|---|---|
| David Miller | 37 | −5.3 / – | 2.8 → 1.8 | 0.60 → 0.66 | 23 → 16 | 59 → 78 |
| David Warner | 40 | −9.8 / −1.7 | 6.9 → 4.5 | 0.03 → 0.02 | 3 → 1 | 173 → 187 |
| Faf du Plessis | 42 | −17.1 / −0.4 | 4.7 → 0.8 | 0.01 → 0.01 | 1 → 0 | 211 → 533 |
| Mohammad Nabi | 42 | −15.2 / +0.4 | 6.5 (4.2 + 2.3) → 5.1 (2.7 + 2.4) | 0.01 → 0.01 | 1 → 0 | 223 → 231 |
| MS Dhoni | 45 | −23.0 / – | 2.7 → 0.4 | 0.36 → 0.28 | 14 → 2 | 95 → 184 |
| Rohit Sharma | 39 | −7.3 / −3.1 | 2.1 → 0.6 | 0.67 → 0.60 | 20 → 5 | 71 → 145 |
| Virat Kohli | 38 | −5.3 / −2.0 | 5.9 → 4.1 | 0.92 → 0.87 | 76 → 50 | 9 → 27 |
| Ravindra Jadeja | 38 | −4.7 / −1.9 | 3.4 (1.8 + 1.6) → 2.4 (1.1 + 1.3) | 0.84 → 0.82 | 40 → 27 | 38 → 46 |
| Sunil Narine | 38 | −5.7 / −2.0 | 7.4 (0.5 + 6.9) → 6.4 (0.0 + 6.4) | 0.88 → 0.86 | 91 → 78 | 2 → 5 |
| Andre Russell (retired; not in the pool) | 38 | −6.4 / −2.0 | value bat +22.1 → +15.7, bowl −6.9 → −8.9 | | | |
| Vaibhav Suryavanshi | 15 | +0.1 / – | 13.1 → 12.9 | 0.91 → 0.88 | 167 → 159 | 1 → 1 |
| Abhishek Sharma | 26 | +3.0 / +0.5 | 4.6 → 4.9 | 0.92 → 0.92 | 59 → 63 | 19 → 13 |
| Sai Sudharsan | 25 | +2.5 / – | 5.3 → 5.5 | 0.90 → 0.90 | 66 → 70 | 14 → 11 |
| Yashasvi Jaiswal | 25 | +3.9 / +1.8 | 4.3 → 4.8 | 0.91 → 0.92 | 54 → 61 | 24 → 14 |
| Jasprit Bumrah | 33 | −0.5 / −0.8 | 6.6 → 6.4 | 0.91 → 0.91 | 84 → 81 | 5 → 4 |
| Rashid Khan | 28 | +2.2 / −0.1 | 6.4 → 6.4 | 0.91 → 0.91 | 82 → 82 | 6 → 3 |
| Shubman Gill | 27 | +2.8 / – | 6.4 → 6.8 | 0.95 → 0.95 | 86 → 90 | 4 → 2 |

Read:

- **The veterans fall by their age, not by a rule**: du Plessis (−17 at 42) and Dhoni (−23 at 45) drop out of
  any useful range; Miller, Warner, Rohit, Kohli, Jadeja and Narine lose 1–2 runs a match. Rohit's season
  value goes from 20 to 5.
- **Kohli** falls to 27th. The curve is a population curve: it doesn't know that his last three seasons were
  +31, +16 and +30 (a random walk would, and lost on the validation). His form forecast (section 11) says
  much the same, +5 next season.
- **Young players gain** a few runs per 100 balls (Abhishek, Sai Sudharsan, Jaiswal, Gill: their evidence
  was gathered younger than they will be). **Suryavanshi** doesn't: the curve is flat below its first knot
  (16), and there are almost no seasons younger than that to fit it on.
- **Bowlers barely move** (Bumrah −0.8, Rashid −0.1): the bowling curve is nearly flat, so Nabi's bowling
  (2.4 a match) keeps him high once bought (section 12).

**Limits.** One curve per group: not per batting position or bowling style (pace and spin apart didn't help).
The shift doesn't see a player's own recent form; the random walk that would see it predicted worse. The
selection model can only correct for being dropped through what the level explains; injuries, international
calls and franchise plans are noise to it. Ages below 16 and above 44 are read at the ends of the curve. A
missing date of birth is imputed. The fits take about 1–3 minutes each (JAX gradients); the validation about
an hour and a half.

### 4c. How far a value is trusted

**Why.** After 4b, with the buy model on (6c), the 2027 sheets were led by players the market passes over:
Mohammad Nabi (42), Chirag Jani (37, never played the IPL; a SMAT all-rounder), Rahul Singh (SMAT) and
Jonny Bairstow (37). Each value the auction tools read is a posterior mean: within its league the
rating shrinks a thin record toward its slot's mean, and the league translation (6d) carries its own
uncertainty into the value's sd. But the contribution per match, P(plays) and Bid plan then used the
mean as if it were the player's IPL level: the sd went no further than a display (`contrib_sd`), and
nothing checked that a mean resting on a thin, old or other-league record predicts the IPL as well as one
earned there. Since 2026-10-27 each role's value is calibrated against what players then did in the IPL
before anything reads it. Code: `src/cricdex/scout/ratings/shrink.py`; fit, choice and test:
`scripts/value_shrink_fit.py`; model: `config/value_shrink.json`; numbers: `data/metrics/value_shrink_ipl.json`.

**The model** (the measurement-error form of empirical Bayes):

```
value used = mu + k × (value now − mu)
k = tau² / (tau² + s × sd² + w_o × (1 − IPL share of the blend) + w_r × years since his last season)
```

fitted per role by maximum likelihood on every player who played an IPL season 2012–2026 (3,663
player-role-seasons): his value as of that auction (blended, moved to his age by 4b's model to 2024)
against his value that season, with noise c × 100 / balls + psi.

**Candidates** (declared 2026-10-27 before any number; walk-forward 2019–2024, each fitted on the seasons
before; chosen by next season's contribution per match, as in 4b; "thin" = the IPL's share of his blend
below a half, a reading, not a criterion):

| candidate | validation 2019–24 (764): MAE / RMSE / bias / rank corr. | thin (133): MAE / bias |
|---|---|---|
| K0 none (reference) | 4.010 / 5.073 / +0.44 / 0.297 | 4.42 / +0.71 |
| **K1 one shrink factor per role, toward the role's mean (chosen)** | **3.935** / **4.988** / −0.12 / 0.296 | **4.35** / +0.27 |
| K2 shrink by the value's own posterior sd (its uncertainty carried through) | 3.966 / 5.038 / +0.01 / 0.285 | 4.45 / −0.09 |
| K3 K2 + the non-IPL share + years since his last season | 3.977 / 5.047 / +0.02 / 0.278 | 4.49 / 0.00 |

| test, once (282) | 2025: MAE / rank / bias | 2026 | pooled: MAE / RMSE / bias / rank | thin (40): MAE / bias |
|---|---|---|---|---|
| K0 | 4.117 / 0.308 / +0.74 | 4.657 / 0.284 / +0.58 | 4.385 / 5.784 / +0.66 / 0.296 | 4.61 / +0.62 |
| **K1** | **4.021 / 0.323 / +0.34** | **4.605 / 0.298 / +0.19** | **4.311 / 5.718 / +0.26 / 0.310** | **4.46 / +0.36** |

(K0 here is 4b's shipped values with the replacement levels refitted on them; 4.010 against 4.019 in 4b.)

**Shipped** (refitted on every season): batting mu −10.7, k 0.76; bowling mu −7.9, k 0.81 (fitted to 2024:
−9.1 / 0.74, −5.9 / 0.79). Every value is pulled about a quarter of the way to its role's mean; a
season-ahead rating regresses, as the form forecast found (section 11, slope about 0.7). The replacement
levels, refitted on the calibrated values of the minimum-price buys (6c), come in with them (No. 1 −6.9,
No. 7 −22.6, No. 8 −45.4, No. 11 −56.3; bowling −13.8 at 0 balls, −5.7 at 24).

**Honest reading.** The calibration fixes the level: the values were too high by 0.44 runs a match in
validation and 0.66 in the test, and too spread out; k < 1 corrects both, and the test agrees (MAE 4.311
against 4.385, rank 0.310 against 0.296). **What it doesn't do is trust thin evidence less.** Carrying the
posterior sd through (K2), and charging the non-IPL share and staleness (K3), predicted worse: among the
players who then played, a league-only or old record is not over-predicted more than an IPL one once every
value is shrunk (thin bias +0.27 in validation, +0.36 in the test). So the ranking hardly moves: Chirag
Jani 3.5 runs a match (from 4.6, rank 305), Nabi 4.0 (from 5.1), Rahul Singh 3.5 (4.6), Bairstow 2.9 (3.7),
everyone else by the same quarter.

*Does bowling age?* The other suspect for Nabi. On the same validation, the bowling part of the
contribution: 4b's flat bowling curve MAE 3.82 (33+: bias −0.82), the steeper curve of the random-walk
model (−7.7 at 36, −18 at 40) 3.89 (33+: −1.00), no aging 3.81 (33+: −0.47). Older bowlers who play are
**under**-predicted, not over: in the data, bowling doesn't fade for those who keep playing.

**So the buy-model sheets are a different problem** (section 12, *with the buy model on*). The outcome
data are the players who were bought and played; nobody buys a 37-year-old with no IPL record at 0.3 cr,
so a fitted calibration can't see what Jani would do, and the buy model's P(plays) for him rests on his
rank in a squad that would never pick him. The buy model stays off.

*Reality check, 2026-10-27* (contribution, runs a match above replacement; pool rank by season value):

| player | contribution before → after | season value | pool rank |
|---|---|---|---|
| Virat Kohli | 4.1 → 3.1 | 50 → 38 | 27 → 28 |
| Rohit Sharma | 0.6 → 0.4 | 5 → 3 | 145 → 145 |
| David Miller | 1.8 → 1.3 | 16 → 13 | 78 → 78 |
| David Warner | 4.5 → 3.4 | 1 → 1 | 187 → 186 |
| Mohammad Nabi | 5.1 → 4.0 | 0 → 0 | 231 → 227 |
| Chirag Jani | 4.6 → 3.5 | 0 → 0 | 304 → 305 |
| Rahul Singh | 4.6 → 3.5 | 1 → 1 | 191 → 191 |
| Jonny Bairstow | 3.7 → 2.9 | 2 → 2 | 175 → 175 |
| Sunil Narine | 6.4 → 5.2 | 78 → 65 | 5 → 5 |
| Vaibhav Suryavanshi | 12.9 → 9.8 | 159 → 123 | 1 → 1 |
| Shubman Gill | 6.8 → 5.2 | 90 → 69 | 2 → 2 |
| Jasprit Bumrah | 6.4 → 5.2 | 81 → 66 | 4 → 3 |
| Rashid Khan | 6.4 → 5.2 | 82 → 65 | 3 → 4 |
| Yashasvi Jaiswal | 4.8 → 3.6 | 61 → 46 | 14 → 14 |
| Abhishek Sharma | 4.9 → 3.7 | 63 → 48 | 13 → 13 |

In-form veterans aren't singled out: Kohli and Rohit keep their places. The market price's input is not
calibrated (6b prices what the market pays, on its own recipe).

*Thin records, checked again 2026-10-27* (an analyst's review: Vaibhav Suryavanshi, 449 IPL balls, at a
season value of 123 against Shubman Gill's 69; Finn Allen alike). Two more candidates, declared before
any of their numbers: **K4** = K1's flat factor times K2's evidence term, `k = k0 × 1 / (1 + s × sd²)`,
and **K5** = K4 with K3's terms (the non-IPL share and the years since). Both contain K1 (s = 0), and the
prior strength (s, and w_o, w_r in K5) is fitted, by maximum likelihood (empirical Bayes) on the seasons
before each validation season, not set by hand. The whole validation was rerun (the as-of values have
moved a little since the first run, with the player-master fixes of 2026-10-27):

| candidate | validation 2019–24 (764): MAE / RMSE / bias / rank corr. | thin (133): MAE / bias |
|---|---|---|
| K0 none | 3.984 / 5.045 / +0.35 / 0.278 | 4.37 / +0.60 |
| **K1 one factor per role (chosen again)** | **3.905** / **4.962** / −0.21 / **0.281** | **4.30** / +0.16 |
| K2 by the posterior sd | 3.936 / 5.008 / −0.09 / 0.274 | 4.40 / −0.20 |
| K3 K2 + non-IPL share + years | 3.947 / 5.017 / −0.07 / 0.266 | 4.44 / −0.10 |
| K4 K1 × K2's evidence term | 3.918 / 4.977 / −0.24 / 0.280 | 4.35 / −0.02 |
| K5 K1 × K3's evidence term | 3.919 / 4.980 / −0.24 / 0.273 | 4.37 / −0.02 |

Fitted on every row up to 2024, K4's evidence term is tiny: s = 0.0003 for batting (0.0002 for bowling),
so Suryavanshi's factor would be 0.725 against Gill's 0.755, where K1 gives both 0.738. Once every value
takes K1's flat factor, the data give no reason to shrink a thin record harder: the rating model has
already shrunk it, through population spreads it learns from the data (`sigma_b`, `sigma_k`,
`sigma_surv`, `sigma_strike` in `bayesian.py`, with wide half-normal priors), not spreads set by hand. K1
stays (`config/value_shrink.json` unchanged), so there was no test look. The honest limit is that the
validation can't speak to a record like Suryavanshi's: among the 2019–24 batters with a value of +20 or
more, one had a posterior sd of 8 or more (113 balls; predicted +13.7, did +7.7). His +60 is outside
anything the calibration was fitted on, and his number should be read with its range (± 12.5). (A
reading declared with K4 and K5, values with an sd of 8 or more, turned out to hold 501 of the 764 rows,
mostly bowlers' batting, so it says little about thin records and is not quoted.)

**Limits.** One factor per role: not by position, league or record length (the candidates that tried
were worse, K4 and K5 included). The calibration is fitted on players who played, so it says nothing
about players nobody picks.

**Which value is shown (since 2026-10-30).** The pages lead with this value for the coming season (the
career rating moved by §4b and shrunk here): Keep or release, the profile (IPL), the Bid plan targets and
their CSVs. The career rating stays beside it with the IPL balls it rests on. The reason is a test run on
2026-10-29 (seasons up to 2024 to choose, 2025–26 held out): as a guide to the next season the career
rating is far too spread (a calibration slope of 0.36 for batters: a player rated ten runs above another
did about three and a half better the next season), and it can't see a decline (Kohli 13.6 career, 8.3
for the coming season; Maxwell 14.0 and 7.9). Short IPL records were not the problem: the best-rated
batters with under 500 IPL balls did slightly *better* the next season than rated (−1.8 runs per 100).
A rating model that let each player's scoring and survival skills correlate (V3) was tested against the
shipped one under a rule declared first and lost (held-out log-likelihood −0.60419 against −0.60357, the
same calibration), so the shipped model stays.

**Why bowlers' wickets count for little.** A bowler's value splits into economy (runs saved) and wickets
(extra wickets at what a wicket is worth where he bowls); the profile shows both parts. Between one IPL
season and the next, a bowler's economy carries over (Spearman 0.31 for the model, 0.27 for his raw
career economy) and his wicket rate barely does (0.09 and 0.05). That is the data, not the model: a
Purple Cap season says little about the next one, so the model weighs wickets lightly and a high
wicket-taker can rate below a miserly bowler (Rabada 3.0, Arshdeep −0.2 for the coming season).

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
4. **Price and saving.** Each candidate is priced as the auction prices him (section 6), on his rating
   translated onto the IPL for his league and role (`ipl_value`, section 6d), and the saving is your
   pick's price minus his.
5. **Gem flag.** A prospect is a "gem" when his standing is high (z ≥ 0.6) on at most the median SMAT
   exposure: punching above a small sample.

*Worked example.* Your pick stands at z = +1.8 among IPL batters. A SMAT batter at z = +1.6 among SMAT
batters has similarity 1 − 0.2 ÷ 2.5 = 0.92, a strong match. One at z = +0.3 has 1 − 1.5 ÷ 2.5 = 0.40.

Separately, every Player Profile shows **style twins** (below) and a **co-faced cohort** (who faced the
most of the same bowlers, or bowled to the most of the same batters; `src/cricdex/scout/cohort.py`).

### 5a. Style twins: players who play like him

**What it does.** For each player, the players in the same league whose game looks most like his, the
way a fan would describe it: where he bats and how he scores, or what he bowls and when he is bowled. It
is about style, not quality: a twin can be better or worse. Code: `src/cricdex/scout/search/style_twin.py`.

**Batter axes** (weight in brackets), all from the ball-by-ball of the league:

| Axis | What it is | Weight |
|---|---|---|
| Slot | His batting position, weighted by balls faced (where he did most of his batting) | 3.0 |
| Powerplay share, death share | Share of his balls faced in overs 1–6 and 17–20 | 1.0 each |
| Tempo in the powerplay, middle, death | His runs ÷ par runs for those balls | 1.5 each |
| Boundaries, dots | Boundaries hit and dot balls ÷ par | 1.0 each |
| Rotation | Balls turned over for 1–3 ÷ par | 0.75 |
| Six share | Sixes ÷ boundaries (power against placement) | 0.75 |
| Spin against pace | log(tempo against spin ÷ tempo against pace) | 0.75 |
| Risk | log(balls per dismissal) | 1.0 |
| Batting hand | Left or right (player master) | 0.5 |

**Bowler axes:**

| Axis | What it is | Weight |
|---|---|---|
| Powerplay share, death share | Share of his balls bowled in overs 1–6 and 17–20 (when his captain uses him) | 1.5 each |
| Economy in the powerplay, middle, death | Runs conceded ÷ par for those balls | 1.0 each |
| Strike | log(balls per wicket) | 1.0 |
| Dots, boundaries conceded | ÷ par | 0.75 each |
| Bowled or lbw share, stumped share | Of his wickets | 0.5 each |
| Pace | Fast 1, fast-medium 0.5, medium 0 (seamers; player master) | 1.0 |
| Arm | Left or right (player master) | 1.0 |

**Why these weights.** They follow the order a fan describes a player in. A batter is first an opener,
a No. 3 or a finisher (slot 3.0), then a fast or slow scorer in each phase (1.5 each), then how the runs
come: boundaries, dots, risk (1.0), then the finer grain (0.75). A bowler is first defined by when he
bowls (1.5 each), then by what it costs and what it takes (1.0), then how he takes wickets (0.5).

**Par.** Every "÷ par" is against the whole league's rate in the same season and phase, so a 2010
opener and a 2024 opener are compared on how far each was above his own era (an index of 1.0 is exactly
par). Without it, every recent batter looks like every other recent batter.

**Thin samples.** Before scaling, each phase index is shrunk toward par with a prior of 60 balls in that
phase (an opener's 20 death balls say little); the six share toward the pool mean with a prior of 15
boundaries; wicket-type shares with a prior of 8 wickets; balls per dismissal and per wicket with a
prior of 4 events.

**Scaling.** Each axis is put on a robust z-scale (median and 1.4826 × MAD over the pool, clipped at
±3), so one outlier or one wide axis can't dominate. The categorical axes (hand, arm, pace) count a
difference as a fixed 2 SD gap (pace: 1 SD per step).

**Gates.** Applied before the distance, so the obvious always fits:

- *Evidence:* at least 120 balls faced (or bowled) and 6 innings in the role in that league.
- *Batters:* twins within 1.5 batting positions of his slot rank first (an opener's twins are openers).
- *Bowlers:* a seamer's twins are seamers and a spinner's are spinners, always. A wrist spinner's twins
  are wrist spinners first, then finger spinners (and the other way round). A bowler whose style the
  player master doesn't know is matched only with other unknowns and is never offered as the twin of a
  known one.

**Distance and "% alike".** D = √(Σ w·Δz² ÷ Σ w), the weighted root-mean-square gap in robust SDs per
axis. **% alike = 100 × (1 − D ÷ 2)**, floored at 0: identical players are 100%, an average gap of half an
SD per axis is 75%, one full SD is 50%. Two players picked at random from a league's pool sit around
35%; a top twin is usually 65–85%. A player with no one like him shows it: Andre Russell's closest
batting twin is 35%. The exported `distance` is 1 − alike, so every surface shows the same number. The
profile export keeps 25 twins so the country filter (same country / overseas / all) still has rows.

*Worked example.* Two openers differ by 0.4 SD in powerplay tempo, 0.2 in middle tempo and 0.3 in
boundaries, and match on the rest. Σ w·Δz² = 1.5 × 0.16 + 1.5 × 0.04 + 1.0 × 0.09 = 0.39; Σ w = 15.25
(all batter weights); D = √(0.39 ÷ 15.25) = 0.16; alike = 1 − 0.16 ÷ 2 = 92%.

**Checked by eye.** The IPL twins of 20 well-known players were read one by one (roadmap I12): Kohli →
du Plessis, KL Rahul, Amla; Jaiswal ↔ Head; Abhishek Sharma → Priyansh Arya, Phil Salt; Bumrah → Steyn,
Archer, Malinga; Kuldeep → Noor Ahmad, Brad Hogg; Arshdeep and Starc → left-arm quicks; Narine (bowling)
→ Muralitharan, Ashwin. Tests: `tests/test_style_twins.py`.

**Limits.** A whole-career average: a player who changed role (Narine from No. 9 to opener) is matched on
his blend. Style comes from one league's data, so a player with few games there falls under the evidence
bar and has no twins. Bowling type comes from the player master; where it is missing (many associate
players in T20Is) the player only meets other unknowns.

**Limits.** "Same standing in his league" is not "same quality": a SMAT z of +1.6 is impressive, but how a
league's rating carries over is a fitted average with a wide spread (a translation sd of 9–15 runs per 100
balls, section 6d). Roles come from the AI-classified taxonomy; a player without one is treated as
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

1. **League translation.** A rating from another league is first put on the IPL rating scale by the
   translation fitted for that league and role (section 6d: SMAT batters lose about 9 runs per 100 balls
   at +10, SMAT bowlers almost nothing, overseas bowlers almost nothing); a player in several leagues
   gets one value per role, his IPL rating and his translated leagues blended by precision, with no
   ball-count switch. (Until 2026-10-23: one hand-set discount per league, SMAT −17, BBL / SA20 −6,
   CPL / Blast −8.5, eight leagues borrowing one, and his IPL value alone at 300+ IPL balls.)
2. **No IPL-relevance penalty** (since 2026-10-22, audit item 4). Until then a player who hadn't featured
   in the IPL lately lost up to 36 runs per 100 balls from his value on a hand-set curve (age, years since
   his last IPL game, 0.7 for a never-IPL Indian), which also set the pool's order. Whether he will play is
   now a fitted chance, P(plays), and the pool is ranked by what he is expected to add over a season (6c).
   This curve prices his value as it is.
3. **Cautious estimate.** The price is set from `value − 0.5 × value_sd`, not the central value
   (`PRICE_CAUTION_SD`, `pricing.py` ⇄ `auction.ts`): a proven star (sd ≈ 3 runs) gives up about 1.5
   runs, a 400-ball prodigy (sd ≈ 12) about 6. Displays and rankings keep the central value. The pool
   carries the blended value's sd and Scout the translated rating's (`ipl_value_sd`), translation
   uncertainty included in both.
4. **Exponential price curve.**

   ```
   projected price = 4.03 × e^(0.0743 × (value − 0.5 × value_sd)) × role weight     clamped to 0.3 – ceiling
   ceiling         = 27 × (0.5 + 0.5 × min(1, IPL balls in the role / 600))
   ```

   The ceiling rises with IPL evidence: no IPL balls → 13.5 cr at most, 449 (Suryavanshi) → 23.6 cr,
   600+ (about two full seasons) → 27 cr. The pool and Scout rows carry `target_balls` for it.

   Until 2026-10-22 all-rounders were weighted ×1.15 and keepers ×1.05 "because they're scarcer", a
   hand-set premium standing in for an all-rounder's second discipline (audit item 6); it is gone: the
   second discipline counts in his contribution per match (6c), and the market model's fitted role terms
   are the price premium. The top names land in the
   20s of crore; the typical pool player is around 1.2 crore; nobody passes 27 cr, the real record. When
   `value` moved to runs, the two constants were re-fitted so the 600-player pool keeps the same median
   price (1.18 cr) and the same number of 10 cr+ players (25) as before, on the cautious values
   ([AUCTION_MATH.md](AUCTION_MATH.md)). The top end now leans to batters (18 of the 25 are batters or
   keepers, against 14), because in runs a batter's scoring edge is worth more than a bowler's economy
   edge after the model's shrinkage.
5. **Base price.** Each player enters the auction at a real IPL base-price band chosen from his projected
   price: 0.3, 0.5, 0.75, 1.0, 1.5 or 2.0 cr.

*Worked example.* Kohli's IPL batting value is +13.6 ± 2.8: priced value
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
Cricsheet id by Wikipedia title, then name, initial + surname (only when the first name doesn't
contradict it: "Mangesh Yadav" and "Ramesh Kumar" had been matched to Mayank Yadav and R Vinay Kumar
until 2026-10-22) or a close spelling among IPL players:
1,600 of the 1,647 sold lots (97%) and 1,033 of the 1,046 retentions (99%); the rest are uncapped
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
don't have one yet).

**The prior market price** (since 2026-10-22, the owner's request: "use what teams actually paid", as a
mechanism, not a floor). The best-known fact about a player at an auction is the market's last verdict
on him: the price a franchise last paid (his last auction price, a bid, or his mega-auction retention
salary; mini-year retained salaries are older contracts and don't count), as a share of that season's
purse (so 2014's 60 cr and 2026's 125 cr compare), with the seasons since it and whether it was a
retention (`pricing.market_verdicts` / `prior_verdict`, from `ipl_auction_history.json`):

| feature | definition |
|---|---|
| `prior`, `no_prior` | ln(last price share ÷ 2%), clamped to −4…3 (2% of the purse ≈ 2.5 cr in 2026); no earlier sale or mega retention |
| `prior_years`, `prior_x_years` | seasons since it (max 6); `prior` × that |
| `prior_retained` | the last verdict was a mega-auction retention |

It was tested as a feature of both parts of the model, under the protocol below. **It improves P(bought)**
(leave one auction out up to 2024, log loss 0.585 → 0.564) and ships there. **It does not improve the
price**, alone or with censored retentions (candidates C, D, F, J below): leaving one auction out up to
2024 its error is 0.801 against 0.787–0.791 without it, and it over-prices the top predictions (top 20
0.84 against 0.89). The reason is in the data: the players who reach an auction are mostly the ones their
franchise let go, and a released player with a high last price usually fetches much less (median ln(new ÷
last) −0.33 for last prices above 10% of the purse: Sam Curran 18.5 → 2.4, Ishan Kishan 15.25 → 11.25,
Deepak Chahar 14 → 9.25). For the lots the model is scored on, a high last price is as much a sign of
being overpaid as of being good. So the price ignores it, and stars are priced through the retentions
instead (next paragraph).

**Retentions are floors** (since 2026-10-22, audit item 2). A mega-auction retention (2018, 2022, 2025;
97 with a Cricsheet id) is the franchise paying at least that to keep him rather than buy him back, so it
says his worth is **at least** that, not that it is his price. The price is now fitted as a censored
(Tobit) regression: each auction lot is an exact ln price, each mega retention only says "ln price ≥
ln retention salary" (its likelihood term is the chance of that). Until 2026-10-22 the retentions were fitted
as exact prices, which pinned the stars who never reach an auction to their slab values. Mini-year
retained salaries were tried as floors too (candidate G) and made everything much worse (error 0.95):
keeping an older contract in a mini year is not a statement that the market would pay that much.

**Resale: the last auction price, a season on** (since 2026-10-29). As a feature of the whole model the
last price didn't help (above). As a second step it does, for one group: a player the market priced at
the last auction. The owner's reality check started it (Prashant Veer and Kartik Sharma, bought for
14.2 cr in Dec 2025, priced 0.8 and 1.7 cr), and the data agree that the model runs low there: the 2025–26
lots whose last price was 8 cr+ a season before fetched a median e^0.77 ≈ 2.2× the model's price (Starc
4.7 for 11.75, Pathirana 6.9 for 18, Livingstone 5.6 for 13), while the hyped uncapped buys did crash
(Sameer Rizvi 8.4 → 0.95, Kumar Kushagra 7.2 → 0.65). `scripts/ipl_price_model.py resale` prices every
lot 2019–2026 out of time (the shipped recipe fitted on the auctions before it) and tries, declared before
any number: R0 the model alone; R1 ln share = a + b ln(model share) + c ln(last share); R2 R1 + the seasons
since + a retention flag; R3 the last price times the median resale ratio; each for a last verdict 1, 2 or
3 seasons back. Leave one auction out on 2019–2024 (mean |ln error|): **R2 within 1 season wins (0.855
against the model's 0.873)**; 2 and 3 seasons gain nothing (0.864 against 0.866; 0.874 against 0.877).
Tested once on 2025–26 (48 lots): error level with the model (0.722 against 0.721), and the lots with a
last price of 8 cr+ are no longer priced low (median error −0.30 against −0.77). **That last figure rests on
11 lots and the median only: out of time the rule shows no measurable gain** (mean |ln error| on the 8 cr+
lots 0.720 against 0.722). It is kept because it doesn't hurt and the stars' resale prices read right,
not because it was shown to price better. Refitted on all 133
resold lots: ln share = −0.43 + 0.585 ln(model) + 0.224 ln(last) − 0.43 × seasons since − 0.08 if it
was a retention (`price.resale` in `config/price_model.json`; `pricing.market_price` ⇄ `marketPrice`,
parity-tested); the upper quartile moves by the same amount. It pulls a price toward the last one both
ways: Veer 0.8 → 1.7 cr, Kartik Sharma 1.7 → 2.6, Finn Allen (bought for 2) 9.9 → 4.8, Rachin Ravindra
5.1 → 3.2 (he sold for 2.0 in 2026). A price two auctions old isn't used: Chahal (18 cr at the 2025 mega
auction) stays 2.4. Keep or release's backtest refits the rule before each deadline on the earlier lots
only.

**The model.** A hurdle:

1. **P(bought)**: logistic regression (L2, standardised), with the prior market price. The risk set is
   every player who played the IPL in the two years before an auction and wasn't retained, in the
   seasons whose retained lists are complete (2018–2026): bought at that auction = 1, else 0. "Else"
   mixes unsold, unregistered and retired players (no unsold lists exist), so it's a proxy for
   "released, does a franchise buy him?". A player who has never played the IPL gets no P(bought).
2. **ln(price / purse | bought)**: a censored (Tobit) regression with normal errors and an L2 penalty
   (alpha by leaving one auction out), on standardised features folded back to raw units
   (`TobitRidge`). Prices are a share of that year's purse (60 cr in 2014 … 125 cr in 2026), so purse
   growth and the US$ years drop out; a cycle's price is that share × its purse. The prediction is then
   shifted to his group's median.

**Calibration: four groups, each at its median.** The linear prediction is shifted by the median
out-of-fold residual of the player's group (each season predicted by a fit on the other seasons; for the
tests, only the training seasons): overseas in a mega auction, overseas in a mini auction, capped Indian,
uncapped Indian (ranges on the features in `config/price_model.json` → `price.groups`; `calibration_part`
⇄ `calibrationPart`, parity-tested). Shipped shifts (ln): overseas mega −0.38, overseas mini +0.10,
capped Indian −0.18, uncapped Indian −0.40.

**How the recipe is chosen (since 2026-10-22).** Until then about twenty recipes were compared on the
2025–26 lots and the best one kept, which made the "out-of-time" score a best-of-twenty on the test set
(audit item 2). Now the candidates are declared in `scripts/ipl_price_model.py` (`CANDIDATES`), **chosen
on auctions up to 2024 only**, and the chosen one is scored on 2025–26 **once**:

- *Selection:* leave one auction out over 2019–2024 (each auction predicted by the recipe fitted on the
  other auctions up to 2024); **the lowest mean absolute ln error on the held-out lots wins**, the rule
  the protocol has always stated (`evaluation.protocol` in `config/price_model.json`). The held-out
  log-likelihood of lots and mega retentions together, and a validation split (fitted up to 2022, scored
  on the 2023 and 2024 minis), are reported beside it. *Correction (2026-10-22, top-end rework):* the code
  had been choosing by that log-likelihood instead of the stated rule. A retention enters it as "price at
  least what he was kept at", and a floor can't penalise a price far above it, so that score rewarded the
  recipes that priced the kept stars at several times their retention (Shubman Gill about 90 cr; below).
  It now follows the stated rule. In fairness to the protocol: this correction, and candidates U–W, came
  after the day's first run, which had chosen N by the log-likelihood and scored it once on 2025–26 (MAE
  0.668, top 20 0.75). T's test below is therefore the second look at the test set that day, not the first.
- Scoring a 2018–2024 auction clamps at that auction's floor (its lowest base price: 0.2 cr then, 0.3
  from 2025).

**The top end: what made Gill 90 cr, and the fix** (audit item 3, 2026-10-22). With the 2026-10-22
morning recipe (K below) the uncapped prediction for the IPL 2027 pool was Shubman Gill 76–90 cr, Axar
Patel 38, Abhishek Sharma 39, Ishan Kishan 32, Suryavanshi 809, held down only by the 27 cr / IPL-balls
ceiling. Taking the prediction apart:

- **Not the quadratic in value, except for Suryavanshi.** Gill's cautious value (15.4) is mid-range; his
  `pv_pos_sq` term adds 0.18 in ln. Suryavanshi's (53.5) is far outside anything the market has priced
  (the largest in the training rows is 31.8, Gayle in 2018), and there the quadratic does run away.
- **The stars' features add up without limit, pushed by the retentions.** Gill's ln price is the sum of
  being a current India international (`recent_caps_x_indian` +1.5), 3,200 IPL balls (+3.4), last
  season's GT captain (+0.8), caps (+0.8) and so on. Fitted on the auction lots alone, the same model
  prices him at 22 cr; adding the 97 mega retentions as floors lifts him to 104 (at a fixed penalty).
  A floor only says "at least": the likelihood gains when the kept stars (Kohli, Rohit, Bumrah at 16–21
  cr) are priced above their retention and loses nothing when they are priced far above it, so the
  coefficients they share with Gill grow until the released players' lots stop them. In sample the
  morning recipe priced KL Rahul's 2025 lot at 56 cr (sold for 14) and Pant's at 57 (27).
- **What the market does at the top, measured.** Out of fold (each auction predicted by a fit on the
  others), the lots in the top 5% of predictions sold for e^−0.62 ≈ 0.54× their prediction, and over the
  top fifth real prices rise only about half as fast as the prediction (slope 0.54 against 0.89 over all
  lots). The linear index over-separates the dearest players: the second-highest bidder's purse and
  every franchise's need to fill a squad from the same money flatten the top.

**The fix: price the top the way the market did.** The shipped recipe (T below) passes the linear
prediction through a **monotone calibration fitted out of fold**: an isotonic regression of the real ln
price on the out-of-fold prediction (21 knots at its quantiles), continued beyond the highest knot at the
slope real prices show over the top fifth of the lots (least squares, held to 0..1; fitted 0.51, `hi_slope`
in `config/price_model.json`) instead of slope 1; each group then shifted to its median as before. The
quadratic term is dropped, and the cautious value is held to its training support (`pv_max` = 31.8: a
value beyond the best the market has priced is priced as that). Nothing is clamped at the top: the IPL
2027 pool's dearest is Gill at 25.8 cr, then Suryavanshi 21.3, Axar Patel 18.2, Ishan Kishan 17.0,
Abhishek Sharma 16.2, Tilak Varma 14.9, Pant 14.6, Shreyas Iyer 14.2, and **no player passes 27 cr**.
**The 27 cr / IPL-balls ceiling is gone** from the market price, the Auction room and Bid plan. The only
bounds left are rules: the floor (the lowest base price) and, in the room and Bid plan, what a team's
purse can pay (its purse less 0.3 cr for every place it still has to fill). The old on-field curve (6a)
keeps its own ceiling: it is a hand-set curve shown for comparison only (audit item 10).

Also tried and declared before the test, and not chosen: the same recipe without the ceiling (L), with the
value held to its support (M), a **saturating budget limit** (N: the median ln share is ln S + ln σ(η),
saturating at a fitted share S of the purse, the most one franchise pays for one player; the likelihood
put S at the purse itself, S = 1.0, so the data alone don't identify a lower limit), and, declared after
the first run because the lots-only calibration priced the kept stars below their retentions, a top-end
**hinge** whose slope is fitted on lots and retentions together (U, V, W: knots at the top fifth, tenth
and twentieth; fitted slopes 0.93, 0.86, 0.77, so the retention floors hold the top up). The bounded
purse in its literal form (a price at most the second-richest team's spendable purse) never binds: in
2025 that is RCB's 83 cr less the reserve for its open places, about 79 cr.

Selection (auctions up to 2024; 688 lots and 51 retentions held out; lower MAE wins):

| candidate | lots: MAE (ln) | top 20 | log-lik. per obs. | lots | retentions | validation 2023–24: MAE |
|---|---|---|---|---|---|---|
| A previous: Huber, mega retentions as prices | 0.799 | 0.90 | −1.439 | −1.475 | −0.955 | 0.896 |
| B A without captaincy | 0.796 | 0.89 | −1.444 | −1.475 | −1.025 | 0.894 |
| C A + prior market price | 0.808 | 0.85 | −1.449 | −1.489 | −0.916 | 0.886 |
| D C without captaincy | 0.810 | 0.83 | −1.455 | −1.494 | −0.934 | 0.887 |
| E C as Tobit, retentions as prices | 0.800 | 0.93 | −1.446 | −1.471 | −1.107 | 0.886 |
| F C as Tobit, mega retentions as floors | 0.807 | 0.85 | −1.443 | −1.482 | −0.917 | 0.880 |
| G F + mini-year retentions as floors | 0.969 | 0.64 | −1.609 | −1.626 | −1.386 | 1.057 |
| H G without captaincy | 0.973 | 0.64 | −1.623 | −1.632 | −1.499 | 1.046 |
| I G without the prior | 0.959 | 0.71 | −1.616 | −1.622 | −1.533 | 1.092 |
| J F without captaincy | 0.810 | 0.84 | −1.453 | −1.490 | −0.951 | 0.875 |
| K F without the prior (shipped in the morning) | 0.795 | 0.91 | −1.434 | −1.474 | −0.902 | 0.890 |
| L K without the IPL-evidence ceiling | 0.795 | 0.91 | −1.432 | −1.474 | −0.867 | 0.890 |
| M L, value held to its support | 0.795 | 0.91 | −1.432 | −1.474 | −0.867 | 0.890 |
| N L with a saturating budget limit (S fitted) | 0.795 | 0.91 | −1.431 | −1.471 | −0.900 | 0.891 |
| R L, monotone calibration with a fitted top tail | 0.798 | 0.96 | −1.465 | −1.477 | −1.305 | 0.925 |
| S R, value held to its support | 0.798 | 0.96 | −1.465 | −1.477 | −1.305 | 0.925 |
| **T S without the quadratic value term (shipped)** | **0.792** | **0.98** | **−1.455** | **−1.473** | **−1.215** | **0.924** |
| U L, value held, top-end hinge on lots + retentions (top fifth) | 0.795 | 0.90 | −1.432 | −1.473 | −0.867 | 0.889 |
| V U, hinge at the top tenth | 0.795 | 0.91 | −1.431 | −1.469 | −0.917 | 0.889 |
| W U, hinge at the top twentieth | 0.795 | 0.91 | −1.437 | −1.467 | −1.039 | 0.890 |
| X T with the contribution per match as the value (declared later that evening, below) | 0.794 | 0.92 | −1.438 | −1.461 | −1.127 | 0.906 |

**Candidate X** (declared on the evening of 2026-10-22 with the playing-time model, 6c, before any of its
numbers): T with the value replaced by the contribution per match (both roles at their expected balls,
above replacement, as of each auction; `scripts/playing_time_fit.py asof-contrib`). Under the declared rule
T stays: its held-out lot error is 0.792 against 0.794 and its dearest predictions are better placed (0.98
against 0.92), though X fits the retention floors and the 2023–24 validation better (−1.438 against −1.455;
0.906 against 0.924). The market seems to price a player's headline rate more than his runs a match, so the
price keeps `value` (the better role's rate) as its input; an all-rounder's premium is its fitted role term.
X wasn't chosen, so it has no test score; T's below is unchanged.

**Candidate Z, and the recipe since 2026-10-27** (declared with the time-aware rating, section 4b, before any
of its numbers): T with its value input (the legacy blend) moved to the coming season by the aging curve,
the time-aware model fitted on seasons up to 2024 for every row. Rerun of the whole selection on the same
rows (X now on the time-aware contributions):

| candidate (rerun 2026-10-27) | lots: MAE (ln) ≤ 2024 | top 20 | log-lik. per obs. | validation 2023–24: MAE |
|---|---|---|---|---|
| T (shipped until then) | 0.793 | 0.97 | −1.456 | 0.917 |
| X T on the contribution per match | 0.794 | 1.03 | −1.475 | 0.901 |
| Y T on the fitted translation | 0.793 | 0.99 | −1.461 | 0.917 |
| **Z T on the time-aware value (chosen)** | **0.790** | 0.97 | −1.453 | 0.911 |

Z has the lowest held-out lot error, so under the declared rule it ships (`value_input: "time_aware"` in
`config/price_model.json`; the export hands the pool and the Scout rows the legacy blend moved the same way,
with the shipped time-aware model). **The test** (fitted to 2024, 237 lots of 2025–26; by now at least the
fifth recipe scored on these lots, after A, K, N and T, so optimistic): Z 0.659 MAE
(ln), rank corr. 0.739, bias −0.11, top 20 0.83, 2025 0.615, 2026 0.778, 2026 walking forward 0.784; T on
the same rows 0.661, 0.741, −0.10, 0.87, 0.617, 0.779, 0.773. A tie: Z is a shade better on the lots and a
shade worse at the top. Old stars move most: Rohit Sharma 6.1 → 4.3 cr, du Plessis 4.3 → 2.8, Warner 4.4 →
3.4, Kohli 8.5 → 7.6, Dhoni 1.4 → 0.5; Tilak Varma 13.9 → 15.0, Jaiswal 11.8 → 12.5, Gill 23.5 → 24.5.

**The brand: candidates AA and AB (2026-10-27, evening; chosen, then vetoed by the reality gate).** An analyst's review: the
market price had Kohli at 7.5 cr (P(bought) 0.64), Narine 4.9, Rohit Sharma 4.3 and Chahal 2.4, while
franchises retained Kohli at 21, Rohit at 16.3 and Narine at 12 in 2025, and Chahal was bought for 18.
Taking Kohli's index apart: a current India international (+1.32), 8,400 IPL balls (+3.73), 19 seasons
(−1.80, the term is capped at 15), age 38 (−0.37), and a value term of +0.16 (each run per 100 balls adds
only 0.023). Nothing in it separates him from the released Indian icons of 35+ who went cheap, because the
model had no measure of a player's following. The one dated, public, reproducible measure we could find is
how often people read his Wikipedia article: the **Wikimedia Pageviews API** (monthly views by human
readers since July 2015, CC0; `scripts/wiki_pageviews.py` → `data/curated/wiki_pageviews.json`, read by
`scout/identity/pageviews.py`). The feature is the mean monthly views of his English article over the 12
complete months before the auction month (so known on auction day; for the 2027 pool, the 12 months to
the data's last complete month), `brand = ln(1 + views / 1000)`, with `no_brand` for a player with no
article. Kohli read 579,000 times a month before the 2018 auction and 276,000 before 2027; Rohit Sharma
109,000; Gambhir 39,000 and Yuvraj Singh 108,000 before 2018 (both went for about 2–3 cr at 36, so the
data can push back); Narine 17,000; Chahal 23,000. Declared before any of their numbers:

- **AA**: Z + `brand`, `no_brand`;
- **AB**: AA + `brand_x_indian` (the Indian market paying for fame at its own rate);
- for P(bought), "+ prior market price + the brand".

| candidate (2026-10-27 evening run) | lots: MAE (ln) ≤ 2024, leave one auction out | top 20 | log-lik. per obs. | validation 2023–24: MAE |
|---|---|---|---|---|
| Z (shipped until then; rerun on the refreshed data) | 0.796 | 0.99 | −1.457 | 0.905 |
| AA Z + the brand | 0.801 | 0.93 | −1.430 | 0.864 |
| **AB AA + the brand for an Indian player (best; vetoed)** | **0.788** | 0.94 | **−1.417** | **0.861** |

AB has the lowest held-out lot error, so under the declared rule it was chosen. It also fits the retention
floors far better (retention log-likelihood −0.98 against −1.22; 41% of the held-out mega retentions priced
at or above what they were kept at, against 26%). P(bought): the brand wins leave-one-auction-out (log
loss 0.553 against 0.561 with the prior price alone). Fitted on 2018–2026: `brand` +0.28 per
ln unit and `brand_x_indian` +0.16 more for an Indian, so ten times the views is about ×1.9 on the index
for an overseas player and ×2.7 for an Indian, before the top-end calibration flattens it.

**The test, once (fitted to 2024; 237 lots of 2025–26, by now at least the sixth recipe scored on them,
so optimistic), against Z on the same rows** (Z's own number is a further look, reported only so the
comparison is honest; it played no part in the choice):

| | MAE (ln) | within ±50% | rank corr. | bias mean / median | 10 cr+ ratio | top 20 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| **AB** | 0.690 | 50% | 0.716 | +0.01 / +0.02 | **0.42** | 0.74 | 0.642 | 0.821 |
| Z | **0.660** | 50% | **0.740** | −0.10 / 0.00 | 0.36 | **0.88** | **0.613** | **0.787** |

P(bought) on the 2025–26 risk set: log loss 0.598 against 0.595 for the prior price alone, AUC 0.767
against 0.755, Brier 0.199 against 0.203. **Read honestly: the test does not confirm the gain.** The
brand prices the lots that sold for 10 cr+ closer to what they fetched (0.42 against 0.36), but the lot
error is worse (0.690 against 0.660) and the 20 dearest predictions of each auction fetched 0.74× their
price against 0.88×: fame lifts the famous more than the 2025–26 market paid for it (Rachin Ravindra, read 118,000 times a
month, priced 8.5 and sold for 4.0 in 2025 and 2.0 in 2026; Glenn Maxwell, 103,000, 7.4 for 4.2; Prithvi
Shaw 7.5 for 0.75 in 2026), while it helps where fame was paid for (Mohammed Shami 11.4 for 10, against
6.7; Chahal 9.3 for 18, against 7.3; Shreyas Iyer 17.4 for 26.75, against 14.7). **Why it is not shipped: the reality gate** (section 13, a standing rule that no
model change may make a check worse, declared before this work). On the IPL 2027 pool AB moved the gate's
star-price check from 0.3597 to 0.333 (Livingstone 0.34 of his 13 cr, Pathirana 0.33 of 18; Green 0.41)
and priced Suryavanshi at 31.6 cr, past the 27 cr record; and it lifted the Indian stars it was meant for
only a little: Kohli 7.6 → 9.0 cr (P(bought) 0.64 → 0.71), Rohit Sharma 4.3 → 4.3, Chahal 2.4 → 2.7,
Narine 4.9 → 6.4, Bumrah 11.1 → 13.0, Gill 24.5 → 26.5. So the brand is vetoed (`VETOED` and
`BOUGHT_VETOED` in `scripts/ipl_price_model.py`: still evaluated and reported by `fit`, never shipped),
and the shipped model is the one of the morning (Z, unchanged). The pageviews and the `brand` features
stay in the code and the export (the site and the Python mirror read `wiki_views`, inert while the model
has no brand coefficient), so the next real auction can be scored against them.

**IPL evidence, tried and not chosen** (2026-10-29). The owner's reality check: Chahal 2.4 cr against 18 at
the 2025 mega auction. His inputs show why: no international in the two years before (the recent-caps term
is worth about ×4.5 for a current Indian international), age 36.4, and a strong value (+9.6) that adds
little; Bhuvneshwar Kumar (+15.2) is 3.8, Mohammed Shami (+0.4, recent caps) 4.1. Declared before any
number: AC = Z + value × ln IPL balls / 8 (value backed by IPL evidence), AD = Z + value for a capped
Indian with no international in two years, AE = both (`pv_x_ipl_evidence`, `pv_x_indian_no_recent` in
`market_features` ⇄ `marketFeatures`, inert unless a model has them). Leave one auction out on 2018–2024:
Z 0.796, AD 0.798, AC 0.803, AE 0.804, so Z stays. Refitted on everything, AD and AE price Chahal 2.4 and
2.3: the released Indians of 35+ out of the India side went cheap (Chawla, Mishra, Harbhajan, Karn
Sharma), and the data can't tell Chahal from them. His last price (18 cr, two auctions back) is outside
the resale window (above), which 2 seasons didn't earn.

**An older last price, tried and not chosen** (2026-10-29, second round). The owner again: Chahal at 2.4
is too low. Declared before any number: R4 = R2 + ln(last share) × seasons since (the last price's weight
fades each season), and a score that counts the stars: the mean of the |ln error| over every resold lot
and over those whose last price was 8 cr+ (`STAR_LAST_CR`), so the few stars weigh as much as the many
cheap resales. Leave one auction out on 2019–2024 (score; all / 8 cr+): **R2 within 1 season still wins
(0.888; 0.855 / 0.920)**; within 2 seasons R1 0.913, R2 0.920, R4 0.928, the 8 cr+ lots worse at 0.963
or more; within 3, R1 0.905, R4 0.927. An older last price reads both ways: Sam Curran 23.4 → 2.4, Kyle
Jamieson 16.8 → 1.0, Jhye Richardson 15.7 → 1.5, Hasaranga 11.9 → 1.5, against Harshal Patel 11.9 →
11.75 and Chahal 8.7 → 18. The resale rule is unchanged (`f_last_years` 0 in `price.resale`; `pricing`
⇄ `marketPrice` carry the term, parity-tested). What the list does show: proven stars in a bidding war
fetch far above the model at mega auctions (Chahal 7.3 against 18, Starc 2.4 against 24.75 in 2024),
the gap the star-price check measures; it is open.

**What is left, the honest reading.** The market price is "what a released player like him fetches", and
the data's released icons of 35+ went cheap; no stars like Kohli or Rohit have been released, so the
data can't say what they would fetch. Their real 21 and 16.3 cr are retentions, a franchise paying to keep
a player, which Keep or release models directly (section 10: Kohli 93% Keep, Rohit 71% Keep since 2026-10-29,
Narine 89%, Chahal 82%). A routine refit of recipe Z on the refreshed data (same recipe, new rows) prices
Kohli at 6.8 and moves the star-price check to 0.317, so the shipped coefficients were left as they are.

(All on the international caps with Afghanistan restored, section 1.) T has the lowest held-out lot
error and the best top end (its 20 dearest predictions per auction fetched 0.98× them, against 0.91×).
The differences in lot error are small (0.792 against 0.795); what T changes is the top. Its price for the
retained stars is lower (retention log-likelihood −1.22 against −0.87): it prices them from what released
players like them fetched, not from the floors. Keep or release no longer uses the price as the call
(section 10), so that matters less than it did.

**The test of T** (fitted on auctions up to 2024, scored on the 2025 mega and 2026 mini, 237 matched
lots; prices clamped as shipped; "10 cr+ ratio" = geometric-mean predicted ÷ real of the lots that *sold*
for 10 cr+, chosen by the outcome, so well below 1 even for a perfect model; "top 20" = geometric-mean real
÷ predicted of each auction's 20 dearest *predictions*, chosen before the auction: 1 = right, below 1 =
over-priced; bias = mean / median predicted − real in ln):

| | MAE (ln) | median abs. error | within ±50% | rank corr. | bias: mean / median | 10 cr+ ratio | top 20 | 2025 MAE | 2026 MAE | 2026 walking forward (fit ≤2025) |
|---|---|---|---|---|---|---|---|---|---|---|
| **T (shipped until 2026-10-27; Z since, above: top 20 0.83)** | **0.661** | **49%** | **51%** | **0.741** | **−0.10 / 0.00** | **0.36** | **0.87** | **0.617** | **0.779** | **0.773** |
| previous recipe (A), same data and scoring | 0.660 | 52% | 49% | 0.730 | −0.09 / 0.00 | 0.39 | 0.79 | 0.621 | 0.765 | 0.774 |
| morning recipe (K), same data, with its ceiling | 0.661 | 50% | 50% | 0.734 | −0.11 / 0.00 | 0.41 | 0.76 | 0.624 | 0.762 | 0.765 |
| old on-field curve (6a), as reported before | 0.785 | 60% | 43% | 0.620 | −0.06 / 0.00 | 0.35 | | 0.734 | 0.919 | |

(K's row is the morning run's single test on the restored caps; N, the protocol's choice under the old
log-likelihood rule, scored 0.668 and 0.75 at the top.) By group (MAE / mean bias / median bias):
overseas 0.65 / +0.12 / +0.21 (2025 mega 0.63 / +0.15 / +0.27, 2026 mini 0.68 / +0.05 / +0.10); capped
Indian 0.69 / +0.05 / −0.01; uncapped Indian 0.66 / −0.39 / 0.00. **On the auction lots T is level with
the earlier recipes, and its dearest predictions are the best placed of the three** (0.87 against 0.79 and
0.76): the top-end fix is confirmed out of time. Overseas players lean high in median (+0.21 ln, about
1.2×), as before.

**The retained stars, out of time** (a revealed-preference check: a franchise that retains a player at P,
with buying him back open to it, expects the auction to cost more than P). Fitted without each auction
(2022: on the others up to 2024; 2025: on auctions up to 2024), the 79 mega retentions of 2022 and 2025:
T prices them at a median 0.51× what they were retained at, 16% at or above it (32% within 0.75×); the
morning recipe 0.60×, 30%. Gill 29.0 and Axar 22.9 for 16.5, Hardik Pandya 16.1 for 16.35; Bumrah 10.8
for 18, Kohli 6.9 for 21, Rohit Sharma 4.6 for 16.3, Klaasen 4.7 for 23, Rashid Khan 6.6 for 18. Franchises
keep these players for more than what a released player like them fetches; section 10 models that
directly instead of reading it into the price.

**The reality table** (out of time: fitted on auctions up to 2024; median and the 25–75% range, the
calibrated price of an index ±0.674 out-of-fold residual sd away, clamped like the site; ↑ / ↓ = real
price above / below the range; for the 2026 lots also the median refitted on 2018–2025):

| lot | real (cr) | T (shipped until 2026-10-27): median (25–75%) | morning (K): median (25–75%) | T, 2026 walking forward |
|---|---|---|---|---|
| Rishabh Pant 2025 | 27 | 21.5 (10.8–42.7) | 27.0 (27.0–27.0) | |
| Shreyas Iyer 2025 | 26.75 | 14.5 (7.3–28.8) | 27.0 (18.1–27.0) | |
| Venkatesh Iyer 2025 | 23.75 | 3.4 (1.7–6.8) ↑ | 2.5 (1.2–4.9) ↑ | |
| Arshdeep Singh 2025 | 18 | 9.5 (4.8–19.0) | 14.5 (7.2–27.0) | |
| Yuzvendra Chahal 2025 | 18 | 7.5 (3.8–15.0) ↑ | 8.6 (4.3–17.4) ↑ | |
| Jos Buttler 2025 | 15.75 | 5.8 (2.9–11.6) ↑ | 7.6 (3.8–15.3) ↑ | |
| KL Rahul 2025 | 14 | 19.8 (10.0–39.4) | 27.0 (27.0–27.0) ↓ | |
| Ishan Kishan 2025 | 11.25 | 10.4 (5.3–20.7) | 17.6 (8.8–27.0) | |
| Jitesh Sharma 2025 | 11 | 3.6 (1.8–7.1) ↑ | 3.5 (1.7–7.0) ↑ | |
| Bhuvneshwar Kumar 2025 | 10.75 | 3.1 (1.6–6.2) ↑ | 2.2 (1.1–4.5) ↑ | |
| Liam Livingstone 2025 | 8.75 | 4.8 (2.4–9.5) | 5.2 (2.6–10.5) | |
| Prasidh Krishna 2025 | 9.5 | 5.8 (2.9–11.5) | 4.7 (2.3–9.4) ↑ | |
| Trent Boult 2025 | 12.5 | 4.2 (2.1–8.4) ↑ | 3.5 (1.7–7.1) ↑ | |
| Kagiso Rabada 2025 | 10.75 | 5.4 (2.7–10.8) | 6.1 (3.0–12.3) | |
| Josh Hazlewood 2025 | 12.5 | 4.2 (2.1–8.4) ↑ | 3.4 (1.7–6.9) ↑ | |
| Phil Salt 2025 | 11.5 | 5.7 (2.9–11.3) ↑ | 7.1 (3.5–14.2) | |
| Mitchell Starc 2025 | 11.75 | 4.7 (2.3–9.2) ↑ | 4.9 (2.4–9.9) ↑ | |
| Cameron Green 2026 | 25.2 (bid; paid 18) | 7.4 (3.7–14.8) ↑ | 11.4 (5.7–22.9) ↑ | 10.2 |
| Matheesha Pathirana 2026 | 18 | 6.0 (3.0–11.9) ↑ | 7.8 (3.9–15.7) ↑ | 8.1 |
| Liam Livingstone 2026 | 13 | 5.3 (2.7–10.6) ↑ | 5.7 (2.8–11.4) ↑ | 6.4 |
| Kartik Sharma 2026 | 14.2 | 0.4 (0.3–0.8) ↑ | 0.5 (0.3–1.0) ↑ | 0.4 |
| Prashant Veer 2026 | 14.2 | 0.5 (0.3–0.9) ↑ | 0.5 (0.3–1.1) ↑ | 0.5 |
| *the other side:* Sam Curran 2025 | 2.4 | 10.2 (5.1–20.2) ↓ | 24.7 (12.3–27.0) ↓ | |
| Washington Sundar 2025 | 3.2 | 10.9 (5.5–21.7) ↓ | 19.5 (9.7–27.0) ↓ | |
| Faf du Plessis 2025 | 2 | 7.3 (3.7–14.6) ↓ | 11.9 (5.9–23.9) ↓ | |
| Quinton de Kock 2025 | 3.6 | 5.1 (2.6–10.2) | 5.6 (2.8–11.3) | |
| Glenn Maxwell 2025 | 4.2 | 4.3 (2.1–8.5) | 4.0 (2.0–8.0) | |
| Wanindu Hasaranga 2026 | 2 | 5.8 (2.9–11.4) ↓ | 7.4 (3.7–15.0) ↓ | 7.4 |
| Rachin Ravindra 2026 | 2 | 5.3 (2.7–10.6) ↓ | 6.5 (3.2–13.0) ↓ | 5.4 |
| David Miller 2026 | 2 | 3.0 (1.5–5.9) | 2.6 (1.3–5.2) | 3.4 |

Read honestly: T is the better price where the morning recipe ran away (KL Rahul 19.8 for 14 against
27, Sam Curran 10.2 for 2.4 against 24.7, Washington Sundar 10.9 against 19.5) and worse for the Indian
stars who did fetch the top (Shreyas Iyer 14.5 for 26.75, inside the range; Arshdeep 9.5 for 18).
Venkatesh Iyer, Jitesh Sharma, Bhuvneshwar, the 2025 overseas pacers, Green's bid and the 2026 uncapped
14.2 cr buys are beyond both. Cameron Green's 25.2 cr is a bid: under the 2025–27 rules an overseas
mini-auction buy is paid at most 18 cr (the lower of the top retention slab and the top 2025 mega price,
27) and the rest goes to the BCCI, but the franchise's purse is debited the full bid (ESPNcricinfo, 29 Sep
2024; Business Today, 16 Dec 2025), so the model prices the bid, which is what leaves the purse
(`overseas_fee_cap` in `config/competitions.toml`).

**What the coefficients say** (T, refitted on 2018–2026). The market pays for **reputation and
experience** as much as for measured on-field value. Being a current Indian international
(`recent_caps_x_indian` +0.41 per ln cap: about ×4.9 for 46 caps in two years), IPL experience
(`ipl_balls` +0.42 per ln ball) and youth move the price as much as value does; each 10 runs of cautious
value add about 27%; last season's IPL captain about ×2.4 (`captain_ipl` +0.88, through the retained
captains' floors); a mega auction pays about 11% more; bowlers about 18% less. All of it then passes
through the calibration, which at the top turns each extra ln unit of the index into about half a unit
of price. Group shifts: overseas mega −0.23, overseas mini +0.13, capped Indian −0.04, uncapped Indian
−0.41; out-of-fold residual sd 0.99.

**The price.**

```
η                 = intercept + Σ coefficient × feature            (config/price_model.json)
lin               = ln S + ln σ(η), S = 1 (the budget limit, fitted; recipe BH since 2026-10-30)
ln(price / purse) = calibration(lin) + the shift of his group (overseas in a mega / in a mini
                    auction, capped Indian in a mini / in a mega auction, uncapped Indian: the group's
                    median out-of-fold residual); calibration: a hinge, slope 1 up to the top fifth of
                    the out-of-fold predictions and its fitted slope (1.0) above
market price      = purse × e^(that), at least 0.3 cr (the lowest base price). No ceiling.
upper quartile    = purse × e^(that + max(0, 0.20 − 0.12 × that)): the 75th percentile of the
                    out-of-fold residuals at that prediction (pricing._upper); until 2026-10-30 the
                    same price for an index 0.674 residual sd higher
P(bought)         = logistic(intercept + Σ coefficient × feature, the prior market price included)
```

The cautious value is held to the training support (`pv_max`). The purse and cycle default to the
league's next competition in `config/competitions.toml` (IPL 2027: mini, 125 cr). Its value input
(`price_value`, with its own sd `price_value_sd`) is the blend the recipe was fitted on: one discount per
league and the 300-ball switch (`translation.legacy_blend`), for the pool and for Scout rows alike, because a
recipe on the fitted translation did not price held-out auctions better (6d); since 2026-10-27 moved to the
coming season by the aging curve (recipe Z above, section 4b; a Scout row by his seasons in that league); the value shown, the
contributions and the on-field worth use the translation. An export from before the
model (no `price_value` in its rows), or no model file, falls back to the on-field curve. Code:
`pricing.market_price` / `calibrate` / `link_share` ⇄ `marketPrice` / `calibrate` / `linkShare`
(`test_scripts/test_web_parity.py` checks the knots, the top tail and the link on fixed inputs).

*Examples with BH (2026-10-30 rebuild, market median):* Gill 23.1 cr, Axar Patel 18.9, Pant 17.6, Shreyas
Iyer 17.5, Abhishek Sharma 17.2, Hardik Pandya 13.6, Bumrah 13.4, Cummins 13.1, Jaiswal 12.7, Rashid Khan
12.5, Kohli 7.8. The Z examples below are history.

*Examples (IPL 2027 mini, 125 cr; data to the 2026 final; the shipped recipe Z, market median / upper
quartile; refreshed 2026-10-27 evening, Keep or release's squad rows).* Kohli 7.5 / 10.9 cr; Rohit Sharma
4.3 / 8.3; Bumrah 11.0 / 15.5; Gill 24.3 / 34.1; Suryavanshi 18.0 / 25.4 (his value held to `pv_max`,
27.9); Pant 14.7 / 20.7; Tilak Varma 15.2 / 21.4; Abhishek Sharma 15.9 / 22.4; Hardik Pandya 11.9 / 16.7;
Shreyas Iyer 14.2 / 20.0; Rashid Khan 9.4 / 13.4 (with his Afghanistan caps, section 1); Cameron Green
10.5 / 14.8; Narine 4.9 / 9.3; Chahal 2.4 / 3.9.

**The 2026-10-30 refit (recipe BH; it replaces Z).** Six reviewers found that Z's price was mostly an
IPL-experience counter that cut a player's price for every extra season (Kohli 16.2 cr at three seasons,
7.6 at fifteen, at the same balls and value), that six IPL balls priced a player 40% below none, that
one India cap doubled a price, that a two-year IPL absence raised the chance of being bought (the risk set
let in absent players only when bought), that the isotonic map was a staircase (50 pool players at exactly
1.0672 cr), and that the upper quartile was beaten 41-50% of the time at 4-12 cr, not 25%. Each became a
test in `tests/test_price_gates.py` before the refit, together with a sixth, prices that never fall as
value rises, and, from round 2, a seventh: no pool price above the 27 cr record.

The candidates were declared before any of their numbers, in three rounds, each
scored the same way: the lowest leave-one-auction-out mean |ln error| on lots up to 2024 among those
passing every gate, then the 2025-26 test once against Z with a paired bootstrap (lots resampled within
each auction).

| Round | Candidate | LOAO ≤ 2024 | Gates failed |
|---|---|---|---|
| — | Z (shipped until now) | 0.800 | five |
| 1 | BA: Z + recent IPL matches for the season count, no never-played step, a seam term, saturating recent caps by nationality, the smooth hinge calibration, capped Indians split by auction type | 0.789 | coverage |
| 1 | BB: BA without captaincy | 0.781 | coverage |
| 1 | BC: BA with Z's isotonic map | 0.769 | ties, coverage |
| 1 | BD: BA without the seam term | 0.785 | the record (Gill 29.2) |
| 1 | BE: BA with Z's log caps | 0.787 | coverage |
| 2 | BF: BD without captaincy | 0.786 | coverage, the record |
| 2 | BG: BD with one pooled captaincy term | 0.788 | coverage, the record |
| 3 | **BH: BD with the budget-limit link** | 0.787 | **none** |
| 3 | BI: BH without captaincy | 0.784 | the record (Abhishek Sharma 29.0) |

Rounds 2 and 3 were added because nothing in round 1 passed the record: the hinge fitted a top slope
of 1.0, so nothing flattened the top. BH takes the saturating link already in the code (candidate N,
2026-10-22): the median ln share is ln S + ln σ(η), S fitted (it came out at its bound, 1, the whole
purse), so the price bends as it nears what one team can pay. On the 2025-26 test (fitted ≤ 2024) BH's
mean |ln error| is 0.652 against Z's 0.654: BH − Z = −0.003, 95% interval [−0.040, +0.035], a tie. It
ships because it passes the tests Z fails, not because it is more accurate. The star check of the
reality gate (2026 lots sold for 10 cr+, median model ÷ real ≥ 0.36) now passes: 0.369 (Z 0.347).

What changed in the recipe: `ipl_seasons` → `ipl_recent` = ln(1 + IPL matches in the two seasons before
the auction) (+0.49); `never_ipl` dropped (IPL evidence enters only through ln(1 + balls)); recent caps
→ 1 − e^(−caps in two years / 10), for Indians (+1.41) and overseas players (−0.14) apart; the calibration
is a hinge (slope 1, with the knot at the top fifth of the out-of-fold predictions; fitted top slope 1.0)
plus each group's median shift, with capped Indians in a mini auction their own group (−0.41; capped
Indian mega −0.07, overseas mega −0.36, overseas mini +0.11, uncapped Indian −0.44); `high` adds the
75th percentile of the out-of-fold residuals as a + b × the calibrated prediction (0.20 − 0.12 ×
prediction, at least 0): on the 2025-26 lots it is beaten 18%, 17%, 21% and 20% of the time in the
bands under 1, 1-2, 2-4 and 4-7 cr (15 and 9 lots above 7 cr: 13% and 0%). P(bought), refitted on the
corrected risk set: years out of the IPL now lower it (`ipl_gap` −0.88; it was +0.35).

What it did not fix. The seam term (BA) didn't price held-out auctions better and was dropped by the
rule; seamers rise anyway (Bumrah 11.1 → 13.5 cr, Hazlewood 5.0 → 7.7, Boult 4.2 → 7.3) because the
season count no longer cuts their long careers. Captaincy is still learned from a handful of lots
(`captain_ipl` +1.07): every candidate without it, or with it pooled, priced a star past the record, so
it stays. Since the captain data counts a stand-in as no captain, Ishan Kishan (SRH's stand-in for about seven
matches in 2026) is 11.2 cr against his 11.25 cr salary (it was 19.2). Kartik Sharma and Prashant Veer
(14.2 cr each in 2026) are still priced near 2 cr: what they were bought on isn't in the data.

**Round 4: uncapped Indians in a mini auction (2026-10-30, declared before its numbers).** Walking forward
to the 2026 mini auction (fitted ≤ 2025), BH priced uncapped Indians a mean ln error of −0.70 below what
they sold for (26 lots: about half), and 2027 is a mini auction. Candidate BJ = BH with uncapped Indians
split by auction type (as round 1 split capped Indians), to replace BH only if its leave-one-auction-out
error on lots up to 2024 is lower and it passes every gate. **It isn't: 0.801 against BH's 0.787**, so BH
stays and BJ was never tested. The gap is real and open: an uncapped Indian's price in a mini auction is
low, and the pool's dearest uncapped Indian is 3.5 cr (Ayush Mhatre; Priyansh Arya 3.3), where 13% of such
lots in 2022-26 went for 3 cr or more.

**The test error, without what flatters it** (`fit` reports it as `test_honest` since 2026-10-30; BH,
fitted ≤ 2024, on the 2025-26 lots):

| Lots | n | mean \|ln error\| | mean ln error (model − real) |
|---|---|---|---|
| all matched sold lots (the headline) | 237 | 0.652 | |
| sold above their base price | 132 | 0.745 | |
| real price under 1 cr | 94 | 0.463 | +0.31 |
| 1-3 cr | 66 | 0.657 | +0.12 |
| 3-7 cr | 34 | 0.816 | −0.55 |
| 7-12 cr | 27 | 0.825 | −0.76 |
| 12 cr+ | 16 | 1.098 | −0.90 |

44% of the lots sold at their base price, where the price is clamped to the same floor, so the headline
0.652 is flattered: over the lots that sold above it the error is 0.745 (off by a factor of about 2.1).
Grouping by the real price exaggerates the tilt (a lot that sold dear is by selection one the model
didn't foresee), but the sign is the known one: the dearest lots are priced well under what they fetched.
The error counts only lots matched to a Cricsheet player: 7 of 180 sold lots in 2025 (2.35 cr) and 13 of
77 in 2026 (9.5 cr, Mangesh Yadav 5.2 of it) have no ball-by-ball record and aren't scored. Unsold
players aren't scored either (P(bought) is scored on its own). The paired bootstrap of any two recipes on
the same lots is `test_honest.paired` (`fit --ref`).

**The value a price uses is not always the value shown.** The price recipe is fitted on
its own value input, `price_value`: the legacy blend (one discount per league, the 300-ball switch) moved
to the coming season by the time-aware rating. The value shown is the fitted league translation, moved
and shrunk (§4b, §4c). The two correlate 0.91 over the pool and squads, and differ by more than 7 runs for
about one player in eight (Glenn Phillips shown −11.5, priced on −0.4). Pricing on the value shown was
tried (recipe Y, 2026-10-23) and did not price later auctions better, so the price keeps its input; since
2026-10-30 the Keep page shows the value each price was "priced on" under it, and the CSV carries
`priced_on_value`.

**Limits.** A typical lot is still off by a factor of about 1.9 (mean |ln error| 0.66 out of time), the
overseas level swings between auctions, and bidding wars for individual names aren't predictable: a
star's price is a median with a wide range. The old stars are low (Kohli 7.5, Rohit Sharma 4.3, Narine 4.9, Chahal 2.4 for the
2027 mini): every released Indian icon of 35+ in the data went cheap (Gambhir 2.8 cr at 36, Harbhajan
Singh and Yuvraj Singh 2 at 36–38, Sehwag 3.2 at 35), and the brand feature built to set Kohli apart from them (Wikipedia pageviews, above) was vetoed by the
reality gate. The retained stars as a group are priced at about half their
retention: what a released player like them fetches, not what their franchise pays to keep them (section
10 models the second). The prior market price helps the "is he bought" part, and since 2026-10-29 the price of a
player resold a season after his last auction (Resale, above), not the price in general. P(bought)'s
"not bought" includes players who didn't register. The caution (`value − 0.5 × sd`) is still a fixed
0.5, not estimated (audit item 2c).

### 6c. Playing time: who plays, and what he adds a match

**What it does.** A rating says how good a player is per ball. A franchise buys matches: whether he plays,
and how many balls he gets when he does. Since 2026-10-22 (audit items 4 and 6) CricDex values every player
as

```
expected season value  = P(plays a match) × contribution per match × 14 matches
contribution per match = (batting value − replacement for his batting slot)   × balls faced a match / 100
                       + (bowling value − replacement for his bowling group) × balls bowled a match / 100
```

in the runs currency of section 4; since 2026-10-27 the batting and bowling values are the time-aware ones
(section 4b: the career value moved to his age next season), calibrated toward their role's mean (section
4c). It replaces two hand-set patches: the IPL-relevance penalty (6a step 2),
which ranked the pool, and the all-rounder rule (his better role only, ×1.15), which dropped Narine's batting
entirely and made Bid plan add per-100-ball rates across an XI as if a No. 7 faced as many balls as an
opener. Code: `src/cricdex/scout/playing_time.py`, fitted by `scripts/playing_time_fit.py` into
`config/playing_time_model.json`; every number below is in `data/metrics/playing_time_ipl.json`. Each piece
follows the frozen protocol of 6b: candidates declared before any test number, fitted on seasons up to 2023,
chosen on 2024, the chosen one refitted to 2024 and scored **once** on 2025–26, then refitted on everything.

**The data: who actually played.** Cricsheet lists each match's XI (`match_players`; the impact player too
from 2023), so for every player and match: did he play, where he batted, his legal balls faced and bowled,
and his side's legal balls. Every auction-pool league is read the same way, so a newcomer's usage comes from
his own leagues.

**1. Balls a match.** His share of his side's balls in the matches he played, batting and bowling apart, as a
credibility (shrinkage) estimate: his past IPL matches (×d per season back), his other-league matches
discounted (×k_o: another side uses him differently) and his role's mean share with the weight of k0
matches; times the IPL's balls per innings (115.0, 2023–26). Mean absolute error in balls a match
(matches-weighted):

| candidate | 2024 (validation): faced / bowled | 2025–26 (test): faced / bowled |
|---|---|---|
| E0 his role's mean (reference) | 3.98 / 2.17 | 3.71 / 2.14 |
| E1 last IPL season's share, else role mean (reference) | 3.66 / 1.96 | 3.12 / 1.55 |
| E2 credibility, IPL history only | 3.21 / 1.53 | |
| E3 E2 + other leagues | 3.12 / 1.53 | |
| **E4 E3 with impact-era role means (shipped)** | **3.00 / 1.46** | **2.71 / 1.44** |

Shipped (refitted 2012–2026): batting d = 0.8, other leagues ×0.25, 8 matches toward the role's mean; bowling
d = 0.4, ×0.1, 2 matches. Position comes through his own history: Kohli faces 27 balls a match, Gill 26,
Abhishek Sharma 17 (an opener who scores fast faces fewer), Rinku Singh 14, Dhoni 10, Tewatia 8; Bumrah and
Narine bowl 23–24. **On whole XIs** the predictions run high: summed over each real XI of the test seasons
they come to 1.22× (2025) and 1.11× (2026) the side's real balls faced (1.18× / 1.10× bowled). A regular is
predicted well; a newcomer or fringe player is shrunk toward his role's mean, which the regulars set. So Bid
plan holds an XI's balls to a side's innings (section 12).

**2. Replacement level.** What a side gets from the next man up: the rating, at the auction, of the
players bought at that auction's lowest price (nobody bid more: freely available talent, the usual definition
of replacement level), auctions 2012–2026 (walk-forward in the validations), as a **curve in his usual batting
position** and a **curve in the balls he is expected to bowl a match** (since 2026-10-26, ROADMAP I17a). Every
player, batter, all-rounder or bowler, is measured on the same two curves: his batting against the level at
his own position, his bowling against the level at his own load.

Until then the levels were one number per slot group (positions 1–3, 4–5, 6–7, 8–11: top −8.8, middle −17.1,
lower middle −23.1, tail −61.6) and per bowling group (frontline, 15+ balls a match, −5.2; part-time −13.0).
The tail's level is set by bowlers batting at 9–11, so a lower-order hitter whose usual position is 7.5
(Ramandeep Singh, rated −37 runs per 100 balls) was measured against −61.6 while a No. 7 was measured against
−23.1: 38 runs per 100 balls apart at one position. That made him the first target on eight of ten Bid plans.

| candidate (declared 2026-10-26) | validation 2018–24, squared error: batting / bowling | test 2025: bat / bowl | test 2026: bat / bowl |
|---|---|---|---|
| R0 slot groups (the old levels, reference) | 177.9 / 38.6 | 172.0 / 26.9 | 205.7 / 77.9 |
| R1 linear | 230.9 / 33.1 | 287.9 / 23.9 | 235.5 / 66.1 |
| **R2 isotonic (monotone; batting shipped)** | **170.5** / 37.8 | **191.8** / 23.2 | **205.8** / 67.8 |
| **R3 kernel, bandwidth 1.5 positions / 6 balls (bowling shipped)** | 216.1 / **32.3** | 269.7 / **27.2** | 246.8 / **64.7** |

(Each candidate is fitted on the buys of the auctions before each of 2018–2024 and scored on that auction's
buys, pooled: 125 batting and 96 bowling values; the kernel's bandwidth is chosen from five on the same
validation. The best per discipline is refitted on 2012–2024 and scored once on 2025 (29 / 23 buys) and 2026
(6 / 8). `scripts/playing_time_fit.py repl`, every number in `data/metrics/playing_time_ipl.json`.) The batting
curve is a monotone (isotonic) fit, joined linearly between its steps' centres: a lower position never has a
better replacement batter. The bowling curve is a Gaussian-weighted mean in balls bowled. **Honest reading of
the test:** the curves predict a minimum-price buy's rating no better than the groups did (batting 191.8
against 172.0 in 2025, level in 2026; bowling a little better both years, on few buys). What they change is
the jump: a player is no longer worth 38 runs per 100 balls more for batting at 7.5 rather than 7.

The shipped curves (refitted on 2012–2026: 184 batting and 150 bowling values) in runs per 100 balls above the
average ball:

| batting position | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 7.5 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| replacement | −7.1 | −8.1 | −11.2 | −15.1 | −17.2 | −21.3 | −27.2 | −42.9 | −57.3 | −62.7 | −68.3 | −70.8 |

| balls bowled a match | 0 | 6 | 12 | 15 | 18 | 24 |
|---|---|---|---|---|---|---|
| replacement | −15.1 | −12.6 | −8.0 | −6.6 | −5.9 | −5.3 |

*Refitted 2026-10-27 on the time-aware values (section 4b), same protocol and candidates:* the same choices
(R2 for batting, the kernel at 1.5 / 6 for bowling); validation batting 174.1 (R0 181.0), bowling 32.5 (R0
39.0); test 2025 batting 191.2 (R0 163.3), bowling 27.5 (29.1); 2026 208.4 (201.1) and 54.5 (67.6). The
shipped batting curve now runs −5.7 at No. 1, −15.6 at No. 5, −26.3 at No. 7, −56.2 at No. 8 and −70.4 at
No. 11; the bowling curve moves by 0.2 at most. *Refitted again on the calibrated values (section 4c):* same
choices; validation batting 94.9, bowling 20.3 (the calibrated values sit closer together, so every error is
smaller); the curve now runs −6.9 at No. 1, −14.4 at No. 5, −22.6 at No. 7, −45.4 at No. 8, −56.3 at No. 11,
and bowling −13.8 at 0 balls to −5.7 at 24.

The fall between No. 7 and No. 8 is in the data, not a boundary: the freely available players who bat at 8 are
mostly bowlers. A player whose usual position the data can't place (no match in the window and no role
position) is read at No. 11. So an opener is measured against a replacement opener, a bowler's batting against
a tail-ender. Tried first and rejected: "fringe" players defined after the fact (under half their side's
matches), who are fringe because they failed (top order −28).

*Reality check, 2026-10-23 → 2026-10-26* (the curves, the refitted P(plays) and the corrected dates of birth of
ROADMAP I17; contribution = runs a match above replacement, batting + bowling; pool rank by season value):

| player | contribution | P(plays) | season value | pool rank |
|---|---|---|---|---|
| Ramandeep Singh (usual position 7.5) | 1.9 (2.2 − 0.2) → 0.5 (0.7 − 0.2) | 0.64 → 0.51 | 17 → 3 | 80 → 171 |
| Vaibhav Suryavanshi | 13.3 → 13.1 | 0.90 → 0.91 | 166 → 167 | 1 → 1 |
| Sunil Narine | 7.4 (0.5 + 6.9) → 7.4 | 0.89 → 0.88 | 93 → 91 | 2 → 2 |
| Shubman Gill | 6.6 → 6.4 | 0.95 → 0.95 | 88 → 86 | 4 → 4 |
| Jasprit Bumrah | 6.5 → 6.6 | 0.91 → 0.91 | 83 → 84 | 5 → 5 |
| Rashid Khan | 6.5 → 6.4 | 0.90 → 0.91 | 82 → 82 | 7 → 6 |
| Heinrich Klaasen | 6.7 → 6.7 | 0.88 → 0.87 | 82 → 82 | 6 → 7 |
| Virat Kohli | 6.1 → 5.9 | 0.93 → 0.92 | 79 → 76 | 9 → 9 |
| Axar Patel | 4.5 (1.2 + 3.3) → 4.4 (1.0 + 3.4) | 0.90 → 0.89 | 56 → 55 | 23 → 23 |
| Ravindra Jadeja | 4.6 (2.0 + 2.6) → 3.4 (1.8 + 1.6) | 0.85 → 0.84 | 54 → 40 | 27 → 38 |
| Hardik Pandya | 2.8 (2.0 + 0.8) → 1.7 (1.7 + 0.0) | 0.75 → 0.72 | 30 → 17 | 46 → 78 |
| Rinku Singh | 2.8 → 2.5 | 0.85 → 0.85 | 33 → 30 | 43 → 44 |
| MS Dhoni | 2.3 → 2.7 | 0.37 → 0.36 | 12 → 14 | 104 → 95 |
| Venkatesh Iyer (age 35.8 → 31.7) | 2.2 → 2.6 | 0.57 → 0.62 | 18 → 23 | 78 → 60 |
| Mukesh Choudhary (age 40.2 → 30.2) | −0.3 → −0.1 | 0.29 → 0.38 | −1 → −1 | 554 → 550 |

The stars don't move. Jadeja and Hardik lose bowling value from the bowling curve, not the batting one: they
bowl about 14–15 balls a match, just under the old 15-ball frontline line, so they were measured against the
part-time level (−13.0) and gained 1–1.5 runs a match from the jump; at their load the curve gives about −7.

A player with **no batting position** in the four seasons before (no match in that window, or none in which he
batted) takes his role's typical one: the median usual position of the players of his role (a batter in the
middle order, a bowler in the tail). His balls are his role's mean share, so his replacement level must be his role's
too. Until 2026-10-23 he fell to the tail's level (−61.6): Sarthak Ranjan (KKR, rated −9.1 as a batter on
47 SMAT balls from 2016–18, nothing since in the data) was credited with +8.2 runs a match, more than David
Warner, and topped three teams' Bid plans. Measured against a middle-order replacement (the batters' median
position falls at No. 4–5) he is +1.2, and his free-agent P(plays) is 0.01 (audit item 6, follow-up; the playing-time fit picks the
same rule up on its next run).

**3. P(plays): a squad player.** The share of his side's matches he plays: a fractional logistic regression
(a binomial on matches) on every squad of every season with a complete retained list (2018–2026, the retained
and bought players, 1,899 player-seasons), with inputs as of the auction (walk-forward ratings, usage and
replacement levels): where he ranks in his squad (his contribution, whether he makes its projected XI —
Bid plan's greedy XI: four overseas, a keeper, five bowling and six batting options — his distance to its
selection line, ln of his rank); overseas places (overseas, outside the four best overseas, places beyond);
experience and age (ln IPL matches, never played, age, age past 32); availability (his share of matches last
season, 0 when he was in a squad and didn't play; not in a squad last season); keeper, last season's
captain, the impact-player era.

| candidate | 2024: log loss / Brier / rank corr. | 2025–26: log loss / Brier / MAE / rank corr. |
|---|---|---|
| P0 base rate (reference) | 0.694 / 0.152 / – | 0.697 / 0.150 / 0.350 / – |
| P1 rank in the squad | 0.658 / 0.134 / 0.35 | 0.631 / 0.118 / 0.297 / 0.46 |
| P2 P1 + overseas places | 0.639 / 0.126 / 0.40 | |
| P3 P2 + experience and age | 0.596 / 0.106 / 0.54 | |
| P4 P3 + availability | 0.581 / 0.099 / 0.58 | |
| **P5 P4 + keeper, captain, era (shipped)** | **0.578 / 0.098 / 0.58** | **0.556 / 0.085 / 0.239 / 0.65** |

(Log loss per match; Brier and MAE on the share of matches. Refitted 2026-10-26 on the replacement curves of
item 2 and the corrected dates of birth (ROADMAP I17), same protocol and candidates, P5 chosen again: before,
0.580 / 0.099 / 0.58 in validation and 0.558 / 0.086 / 0.241 / 0.64 in the test; the first fit, on the old
discounts of 6d, tested at 0.562 / 0.087 / 0.246 / 0.63.) Calibration in the test, fifths of the prediction,
predicted / real share: 0.19 / 0.22, 0.29 / 0.30, 0.48 / 0.48, 0.71 / 0.67, 0.85 / 0.90.
Refitted again 2026-10-27 on the time-aware values (section 4b): P5 chosen again (0.574 in validation); test
0.558 / 0.086 / 0.240 / 0.64, so a hair worse than on the career values (0.556). The free-agent model
(F3 again) tests at 0.0855 (0.0853 before), the buy model (B3 again) at 0.575 (0.574). Refitted once more on
the calibrated values (section 4c): the same choices; tests 0.5585, 0.0855 and 0.5754.
Availability and experience carry the most: a player who sat out last season in a squad is much less likely
to play than his rank says.

**P(plays): a free agent** has no squad to rank in, and whether he plays also depends on whether anyone buys
him, which is what the relevance penalty tried to say by hand. A second model, fitted the same way on every
free agent of every past auction pool (active in a pool league in the three years before, a nationality the
auction admits, not retained: 1,025–1,421 a year, 33–146 of whom then played): his contribution and its
distance to the median squad's XI line, ln IPL matches, never played the IPL, years since his last IPL match,
age and age past 32, last season's share, overseas, keeper, captain, era. Candidates F0 (base rate), F1
(contribution and line), F2 (+ experience, years since, age), F3 (+ last season, overseas, keeper, captain,
era); F3 chosen on 2024 (log loss 0.074 against 0.100); test 2025–26: **0.085** against 0.157 for the base
rate and 0.153 for F1, rank corr. 0.39 (refitted 2026-10-26 with the replacement curves and corrected dates of
birth; before, 0.086 and F1 0.154; the first fit, on the old discounts: 0.085, F1 0.137); the top fifth of predictions averaged 0.18 and played 0.17 of a
side's matches. A known gap: no mega/mini term was declared, so a 2027 (mini) free agent's chance averages
both kinds of year, and in a mini year far fewer free agents play (33 in 2026 against 133 in 2025).

**P(plays): an auction buy, in the squad that bought him** (2026-10-27, ROADMAP I18; built, tested,
switched off). Bid plan values a lot at his free-agent P(plays): the chance players like him play an IPL
match at all, which is mostly the chance nobody buys him (0.02–0.2 for most lots). Once a team has bought
him, what matters is whether he makes its XI.

The buy model is fitted on the real buys of 2018–2024 (`scripts/playing_time_fit.py buy`). It uses the
squad model's inputs (his rank in the buying squad, overseas places, experience, age, last season's share,
keeper, captain) plus what he cost. Four candidates were declared first. Per-match log loss, chosen on the
2024 buys (55 with a free-agent row):

| candidate | 2024 (validation) | 2025–26 (test, 185 buys) |
|---|---|---|
| B0 the free-agent model (what Bid plan used) | 1.150 | 0.749 (rank corr. 0.48) |
| B1 the squad model, all squad players | 0.694 | |
| B2 the squad model's inputs, fitted on buys | 0.680 | |
| **B3 B2 + his price, ln(price ÷ purse)** | **0.668** | **0.574 (rank corr. 0.64)** |

The test is clear: a buy's chance of playing is the squad model's, not the free agent's. Teams play the
players they paid for (the price coefficient is +0.34 per unit of ln price share).

**Why it is switched off** (`export_site.BIDPLAN_BUY_MODEL = False`). With it, the 2027 sheets put these
players first:

- David Warner (40, last IPL match in 2024, unsold twice);
- Mohammad Nabi (42);
- Faf du Plessis (42);
- never-IPL domestic batters at 0.3 cr (Chirag Jani, 36; Rahul Singh).

Their contributions are career ratings, or thin ratings translated from SMAT. The ratings don't see a
veteran's decline (Tier D #34 in the ROADMAP), and only the free-agent P(plays) was keeping these players
off the lists.

*Rechecked 2026-10-27 with the time-aware values (section 4b).* du Plessis is gone (0.8 runs a match, from
4.7), Warner falls to 4.5 a match but is still in four teams' top fives, and the sheets are still led by
players the market passes over: Mohammad Nabi (42) first on four sheets (his bowling, 2.4 a match, has no
age decline in the data), Chirag Jani (37, never played the IPL; a −9 SMAT batter measured against a
lower-order replacement, +4.2 a match) first on four, Jonny Bairstow (37) and Rahul Singh (SMAT) on one
each. The reality gate's first-target check fails (Jani on four sheets against at most 3.4). So the buy
model stays off: aging was one root, but the other is the contribution of a thin or never-IPL record.

*Rechecked again 2026-10-27 after the calibration of section 4c.* Every value is now shrunk a quarter of the
way to its role's mean, but the evidence-dependent shrinkage (by the value's sd, the non-IPL share and
staleness) lost on validation, so the order of these players doesn't change: Jani first on six sheets,
Nabi on three, Bairstow on one; both first-target checks fail. The outcome data are players who were bought
and played, so no fitted calibration sees what a never-bought 37-year-old would do. Still off.

A calibration of a buy's expected value against what real buys then delivered was also declared and tested
(`value`: V0 none, V1 one shrink factor, V2 a shrink by age past 32, years away and no IPL at all). Fitted
on 2019–23 and chosen on 2024, it chose V0: no shrink beat none (squared error 7.12 against 7.17 and 7.69).
On 2025–26 the uncalibrated value was unbiased (mean error +0.26 and −0.05 runs a match). Real buys can't
calibrate the players nobody buys. The outcomes of a player the market passes over aren't observed, so
the data that would correct his number doesn't exist. The fix belongs in the ratings: a player's form
drifting over time (Tier D #34). The model stays in `config/playing_time_model.json` (`buy`); the code is in
`web_parity/bidplan.py` (`buy_p`, `lot_p`) ⇄ `site/src/lib/bidplan.ts` (`buyP`, `lotP`), parity-locked, and is
used when keep.json carries a `buy_model`.

**The impact-player era** (2026-10-27; an analyst's review). Since IPL 2023 each side may bring on an
impact player during the match, and the rule stays for the whole 2025–27 cycle (IPL Player Regulations
2025–27, item 8, iplt20.com, 28 Sep 2024; confirmed at the 2026 captains' meeting, PTI via Free Press
Journal, March 2026). Until now the playing-time model pooled 2012–2026 for the replacement level and
picked a side of 11. What the data say:

| | 2008–2022 | 2023–2026 |
|---|---|---|
| players a side a match (Cricsheet's `match_players`) | 11.0 | 11.95–11.97 |
| batters used a side a match | 7.2–7.8 | 7.7–8.0 |
| bowlers used a side a match | 5.8–6.2 | 5.8–6.1 |
| first-innings par (the value function's V(0, 0)) | 162 runs | 189 runs |
| runs off the bat a legal ball, powerplay / middle / death (setting) | 1.17 / 1.24 / 1.63 | 1.47 / 1.42 / 1.79 |
| wicket cost λ with 0–1 down, powerplay / middle / death | 12.6–14.1 / 7.4–8.1 / 2.9–3.4 | 14.7–16.0 / 6.1–7.9 / 2.2–3.0 |

So the twelfth player is real, the extra player goes mostly into batting depth, scoring is 10–26% higher
a ball (most in the powerplay), and the run cost of a wicket barely moved. Three changes were declared before any of
their numbers, each chosen on data up to 2024:

1. **The replacement level, era-weighted.** The chosen smoothers (isotonic in batting position, the
   kernel in balls bowled) were refitted with the minimum-price buys of auctions before 2023 weighted by
   1 (pooled, as before), 0.5, 0.25 or 0 (impact era only), each scored on the impact-era validation
   auctions (2023 and 2024: 28 batting and 26 bowling buys, fitted on the auctions before each).
   Batting: squared error 168.4 pooled, **147.5 at 0.5 (chosen)**, 147.8 at 0.25, 603.2 impact era
   alone (too few buys). Bowling: 24.3 pooled (kept), 24.3, 24.5, 43.4. The test, once (fitted to
   2024; 2025: 29 buys, 2026: 6): batting 102.0 and 101.5 at 0.5 against 104.3 and 113.7 pooled (pooled
   over both seasons, 101.9 against 105.9). The shipped batting curve (refitted on 2012–2026, pre-2023
   buys at half weight) against the pooled one: No. 1 −6.2 (−6.9), No. 3 −10.1 (−10.1), No. 5 −15.3
   (−14.4), No. 7 −24.4 (−22.6), No. 8 −46.5 (−45.4), No. 11 −57.6 (−56.3). The freely available
   opener of the impact era is a little better and the freely available middle-order batter a little
   worse; bowling unchanged. P(plays) (P5), the free-agent and buy models were refitted on it, with the
   same choices: tests 0.5566, 0.0848 and 0.5738 (were 0.5585, 0.0855, 0.5754).
2. **A side of 12 in P(plays)** (candidate P6: P5 with each squad's projected side 12 players from
   2023, `playing_time.xi_size`; the free agent's XI line likewise). Validation 2024: log loss 0.5697
   against P5's 0.5691. **Not chosen**: who makes the 11 already orders a squad as well as who makes the
   12. The code carries the switch (`xi_by_era` in each P(plays) model; false as shipped).
3. **A side of 12 in Bid plan's strength** (`bidplan.XI_SIZE`, section 12). This one is not a fitted
   choice but a fact of the rules every plan is for: 12 players take part in an impact-era match, and
   the side's balls stay held to one innings. Not validated by a replay (the 2025–26 replays have been
   seen five times already; the reality gate was run, section 13).

*The effect* (IPL 2027 pool and squads, before → after the era-weighted replacement level and the refitted
P(plays); contribution = runs a match above replacement; season value = P × contribution × 14; pool rank
by season value; the market price doesn't move, its inputs are the values, not the contributions):

| player | contribution | P(plays) | season value | pool rank |
|---|---|---|---|---|
| Virat Kohli | 3.1 → 2.9 | 0.87 → 0.88 | 38 → 36 | 27 → 28 |
| Rohit Sharma | 0.4 → 0.3 | 0.59 → 0.60 | 3 → 3 | 146 → 165 |
| Sunil Narine | 5.2 → 5.2 | 0.89 → 0.89 | 65 → 65 | 5 → 5 |
| Yuzvendra Chahal | 2.1 → 2.1 | 0.84 → 0.84 | 25 → 25 | 40 → 42 |
| Jasprit Bumrah | 5.2 → 5.2 | 0.92 → 0.92 | 66 → 67 | 3 → 3 |
| Shubman Gill | 5.2 → 5.0 | 0.94 → 0.93 | 69 → 65 | 2 → 4 |
| Vaibhav Suryavanshi | 9.8 → 9.7 | 0.89 → 0.91 | 123 → 124 | 1 → 1 |
| Finn Allen | 4.9 → 4.8 | 0.74 → 0.74 | 51 → 50 | 12 → 12 |
| Pat Cummins | 1.9 → 1.9 | 0.66 → 0.64 | 17 → 17 | 59 → 60 |
| Lhuan-dre Pretorius | 2.6 → 2.4 | 0.38 → 0.38 | 14 → 13 | 74 → 79 |
| Rashid Khan | 5.2 → 5.2 | 0.90 → 0.93 | 65 → 68 | 4 → 2 |
| Abhishek Sharma | 3.7 → 3.6 | 0.92 → 0.92 | 48 → 46 | 14 → 15 |
| MS Dhoni | 0.3 → 0.5 | 0.27 → 0.29 | 1 → 2 | 186 → 175 |
| Ravindra Jadeja | 1.9 → 2.0 | 0.83 → 0.83 | 22 → 24 | 46 → 43 |
| Hardik Pandya | 0.9 → 0.8 | 0.72 → 0.71 | 9 → 8 | 95 → 104 |
| Heinrich Klaasen | 4.5 → 4.7 | 0.88 → 0.88 | 56 → 58 | 8 → 7 |
| KL Rahul | 4.5 → 4.3 | 0.92 → 0.93 | 58 → 57 | 6 → 8 |
| Shreyas Iyer | 3.5 → 3.3 | 0.90 → 0.89 | 44 → 41 | 20 → 25 |

Openers lose a little (their replacement is better: Gill 5.2 → 5.0, KL Rahul, Shreyas Iyer), lower-order
batters gain a little (Dhoni 0.3 → 0.5, Jadeja, Klaasen), bowlers don't move. The stars stay where they
were: Suryavanshi 1st, Rashid Khan 2nd, Bumrah 3rd, Gill 4th, Narine 5th, Kohli 28th.

*Not changed: the value's runs currency.* The value converts skills into runs at the league's baselines
and wicket costs pooled over every season (section 4). On the impact era's tables a scoring or economy
edge would be worth about 10–26% more runs (by phase) and a wicket about the same, which would scale every
player's rate part, and the replacement levels with it, by much the same factor. Moving the currency
means refitting every IPL value as of every past auction (the price fits, the translation, the aging
curve, the calibration and the replacement levels all read it); it is left open in the ROADMAP rather
than half-done.

**Fielding** isn't in the contribution: Cricsheet records completed catches, run-outs and stumpings, not
chances, drops or runs saved, so a fielding value in runs can't be identified from it.

**Where it is used.** The pool is ranked by expected season value (section 7) and the Auction room's mini
retentions by the same; Bid plan's strength adds P(plays) × contribution per match at realistic balls (section 12); Keep
or release's role gaps compare contribution per match, and P(plays) and P × contribution were tried as inputs
of its retention model (section 10, not chosen); the market price was tried on the contribution instead of
the better role's rate (6b, candidate X, not chosen). `value` (the better role's rate) is still shown, and is
still the market price's input.

**Reality check** (IPL 2027 defaults, data to the 2026 final; values with the league translation of 6d,
recomputed 2026-10-23; P(plays) in his 2026 squad, for a free agent the free-agent model; contribution = runs above replacement a match he plays, batting + bowling at his balls
faced / bowled a match; season value = P × contribution × 14; pool rank before = by value less the relevance
penalty, after = by season value; the market price and the Keep call are unchanged by this: the price's input
and the retention model are the same). **A snapshot of 2026-10-23**: the market and Keep columns are those
days' models (price recipe Z, Keep model L4), since replaced; today's prices and calls for these players are in
section 10's reality table, generated from the site's data:

| player | team | value (better role) | P(plays) | contribution (bat + bowl; balls faced / bowled) | season value | pool rank before → after | market (cr) | Keep |
|---|---|---|---|---|---|---|---|---|
| Vaibhav Suryavanshi | RR | 59.7 | 0.90 | 13.3 (13.3 + 0.0; 19 / 0) | 166 | 1 → 1 | 21.5 | Keep (100%) |
| Sunil Narine | KKR | 24.7 | 0.85 | 7.4 (0.5 + 6.9; 7 / 23) | 89 | 5 → 3 | 5.1 | Keep (88%) |
| Jasprit Bumrah | MI | 23.1 | 0.91 | 6.5 (−0.2 + 6.7; 1 / 24) | 83 | 6 → 5 | 11.3 | Keep (97%) |
| Rashid Khan | GT | 21.1 | 0.90 | 6.5 (0.9 + 5.6; 3 / 21) | 82 | 13 → 7 | 9.0 | Keep (92%) |
| Shubman Gill | GT | 16.9 | 0.95 | 6.6 (6.6 + 0.0; 26 / 0) | 88 | 17 → 4 | 26.1 | Keep (99%) |
| Heinrich Klaasen | SRH | 17.0 | 0.88 | 6.7 (6.7 + 0.0; 20 / 0) | 82 | 16 → 6 | 7.7 | Keep (83%) |
| Ravindra Jadeja | RR | 4.2 | 0.85 | 4.6 (2.0 + 2.6; 13 / 15) | 54 | 74 → 27 | 7.5 | Keep (84%) |
| Axar Patel | DC | 12.2 | 0.90 | 4.5 (1.2 + 3.3; 12 / 19) | 56 | 34 → 23 | 18.3 | Keep (96%) |
| Cameron Green | KKR | 4.1 | 0.81 | 3.8 (3.2 + 0.6; 15 / 11) | 43 | 57 → 37 | 10.7 | Keep (81%) |
| Virat Kohli | RCB | 13.6 | 0.93 | 6.1 (6.1 + 0.0; 27 / 0) | 79 | 28 → 9 | 7.9 | Keep (93%) |
| Abhishek Sharma | SRH | 19.9 | 0.92 | 4.8 (4.9 + −0.1; 17 / 3) | 62 | 7 → 18 | 16.4 | Keep (98%) |
| Finn Allen | KKR | 30.5 | 0.72 | 6.7 (6.7 + 0.0; 17 / 0) | 68 | 3 → 15 | 10.3 | Keep (90%) |
| Krunal Pandya | RCB | 9.3 | 0.85 | 3.6 (1.1 + 2.5; 9 / 17) | 43 | 45 → 35 | 3.3 | Keep (85%) |
| Hardik Pandya | MI | −2.1 | 0.75 | 2.8 (2.0 + 0.8; 13 / 14) | 30 | 127 → 46 | 12.4 | Keep (89%) |
| Mitchell Marsh | LSG | 13.2 | 0.79 | 5.0 (4.9 + 0.0; 22 / 1) | 55 | 33 → 25 | 5.5 | Keep (78%) |
| Marcus Stoinis | PBKS | 4.2 | 0.71 | 2.2 (2.8 + −0.6; 13 / 7) | 22 | 71 → 66 | 4.4 | Toss-up (52%) |
| Rinku Singh | KKR | −3.8 | 0.84 | 2.8 (2.7 + 0.0; 14 / 0) | 32 | 184 → 43 | 5.0 | Keep (90%) |
| Liam Livingstone | SRH | 5.8 | 0.45 | 3.3 (3.4 + −0.2; 15 / 8) | 21 | 72 → 71 | 4.9 | Toss-up (40%) |
| Rohit Sharma | MI | 3.7 | 0.68 | 2.3 (2.3 + 0.0; 18 / 0) | 21 | 80 → 67 | 5.0 | Toss-up (60%) |
| Washington Sundar | GT | 6.4 | 0.79 | 0.7 (−0.3 + 1.0; 12 / 5) | 8 | 65 → 118 | 10.7 | Keep (84%) |
| MS Dhoni | CSK | 1.1 | 0.37 | 2.3 (2.3 + 0.0; 10 / 0) | 12 | 177 → 104 | 1.1 | Toss-up (62%) |
| Rahul Tewatia | GT | −1.2 | 0.78 | 0.8 (0.7 + 0.1; 8 / 1) | 8 | 105 → 115 | 0.6 | Toss-up (48%) |
| Andre Russell (retired) | — | 24.5 | 0.08 | 7.4 (4.9 + 2.5; 10 / 12) | 8 | out → out | 5.3 | — |
| Moeen Ali, 39 | free agent | 11.2 | 0.03 | 5.0 (2.1 + 2.9; 11 / 12) | 2 | 39 → 186 | 5.4 | — |
| Faf du Plessis, 42 | free agent | 14.0 | 0.01 | 4.9 (4.9 + 0.0; 21 / 0) | 1 | 56 → 212 | 4.0 | — |
| Imran Tahir, 47 | free agent | −18.1 | 0.00 | 4.1 (0 + 4.1; 1 / 22) | 0 | 449 → out | 2.4 | — |
| Rahul Singh (uncapped, SMAT) | free agent | 13.5 | 0.02 | 4.8 (4.8 + 0.0; 16 / 0) | 1 | 40 → 203 | 0.5 | — |
| Lewis Goldsworthy (never IPL; Blast, 26) | free agent | 0.8 | 0.02 | 5.4 (3.6 + 1.8; 9 / 13) | 2 | 385 → 195 | 1.5 | — |

(The "before" value of a free agent is his value less the relevance penalty, which is why it is low for
Imran Tahir and Goldsworthy; Russell and the retired are left out of the pool either way.)

Read player by player (2026-10-23 numbers, with the league translation; the 2026-10-22 run is in the
CHANGELOG):

- **The all-rounders count both disciplines.** Jadeja (batting 2.0 + bowling 2.6 runs a match) is 27th,
  Axar 23rd, Krunal 35th, Green 37th, Hardik 46th — far above where the better-rate-alone value put them (74th,
  34th, 45th, 57th, 127th), lower than on 2026-10-22: the replacement bowler is now about 6 runs per 100 balls
  better (6d), so every bowling contribution shrank by about 1.5 runs a match.
- **Narine's batting counts**: 7 balls a match at the top worth +0.5 against a replacement opener, on bowling
  worth 6.9: 3rd in the pool after Suryavanshi and Gill. Bumrah 6.5 (5th), Rashid 6.5 (7th), from 21–24 balls
  a match.
- **Batters at the death face few balls**: Rinku 14 a match, Dhoni 10, Tewatia 8. Rinku rises (his −3.8 per
  100 balls is a finisher's rate against the average ball; against a replacement lower-middle batter it is
  +2.8 a match); Tewatia (0.8) and Dhoni (2.3, a 37% chance of playing) fall.
- **Kohli** (6.1 a match from 27 balls, 93% to play, 9th) and **Rohit** (2.3, 68%) are where their recent
  seasons put them. **Abhishek Sharma** is 18th: a +19.9 rate on 17 balls a match is worth less a match than
  Kohli's +13.6 on 27.
- **Washington Sundar** is 118th: GT used him for 5 balls a match and his batting is below a replacement
  lower-middle batter's. That is how he was used, not a judgement of his ceiling.
- **Finn Allen** (+30.5 per 100 balls: a thin IPL record blended with strong overseas league batting) is 15th,
  on 17 balls a match and a 72% chance of playing in KKR's crowded overseas places.
- **Veterans out of the IPL**: Moeen Ali, Faf du Plessis and Imran Tahir still contribute per match in their
  leagues, but free agents of their age and years away rarely play an IPL match again (P ≤ 0.03): 186th,
  212th, and Imran Tahir out of the 600 — fitted, not penalised by hand. **Russell** (retired) stays out.
- **Newcomers** (an uncapped SMAT batter, an overseas league all-rounder) contribute 4.8–5.4 a match on their
  translated league numbers, but a never-IPL free agent plays rarely (2%), so they rank around 200; a
  franchise that buys one changes that (in a squad, the squad model applies).
- **Stoinis** and **Livingstone** are Toss-up on Keep, and P(plays) agrees: 0.71 and 0.45 (Livingstone
  played 2 of SRH's 15 matches in 2026).

**Limits.** The contribution uses the career rating moved by the fitted aging curve (section 4b) and shrunk
a quarter of the way to its role's mean (section 4c), not his own recent form: a random walk on the level was
tried and predicted worse. Its uncertainty (`contrib_sd`) is shown but not used: carrying it into a shrunk
mean was tried (4c, K2) and predicted worse. The free-agent model has no mega/mini term. A newcomer's balls are shrunk
toward his role's regular share (the XI check above). P(plays) is computed against the squad as listed; a
flipped Keep call doesn't recompute it. Fielding is missing. Balls a match don't depend on venue or
opposition.

### 6d. League translation: a rating from another league, on the IPL scale

**What it does.** Every rating is relative to its own league's average ball, so a +20 in SMAT is not a +20
in the IPL. Since 2026-10-23 (audit item 5) each league's rating is moved onto the IPL rating scale by a
translation **fitted per league and per role** on the players seen in both, and a player's sources (his IPL
rating and every translated league) are blended by precision with no cut-off. Code:
`src/cricdex/scout/translation.py` (`translate`, `blend`), fitted by `scripts/league_translation_fit.py`
into `config/league_translation.json`; the export applies it (the pool's `value`, Scout's `ipl_value`),
so the web app and `web_parity/pricing.py` only price values already on the IPL scale.

**What it replaced.** One hand-set discount per league for both roles (SMAT −17, BBL / SA20 −6, CPL / Blast
−8.5), eight leagues borrowing one of those, a guessed translation sd (6.5 or 10.5 runs) and a switch that
ignored every other league once a player had 300 IPL balls in a role, added because the flat discount was
"too harsh on stars". The old check already showed the gap depends on role (SMAT +22 runs for batters, +7
for bowlers, against one 17), and the level of a discount had never been tested (the newcomer backtest,
section 8, scores rank only).

**The mechanism.** For every IPL season S from 2015 to 2026, a player's **observed IPL value in S** (runs
per 100 balls above that season's average ball, from his n balls in the role) is modelled from what was
known before S:

```
y = α_k + β_k · x + e,     Var(e) = τ_k² + β_k² · sd_x² + κ / n
```

x (± sd_x) is his rating in source k fitted on matches before S: the IPL itself (his IPL rating as of the S
auction) or a league L (its rating as of 1 January of S, the newcomer backtest's cached fits). κ / n is a
season's ball-to-ball noise (one κ per role, fitted: a ball's sd is about 330–345 runs per 100 balls), τ_k²
what a rating in k doesn't know about his next IPL season. A league pair counts when he played L in the two
calendar years before S (**time-matched**), seasons with 20+ IPL balls in the role. Batting and bowling are
fitted separately.

- **Selection.** Players reach the IPL because their league numbers were good. A raw mean difference
  (IPL minus league) is inflated by that; a regression on the league *rating* (a posterior mean, already
  shrunk) is not, because the selection is on the regressor. Every season with 20+ balls counts, so a
  newcomer dropped after a bad month still counts. A re-weighting by the inverse chance of reaching the
  IPL given the rating (IPW) was a declared candidate (T5). What a regression can't fix is selection on
  what scouts see and the data doesn't: the fit describes players *who get games*, which is what the pool
  needs (its season value is P(plays) × the contribution when he plays, 6c).
- **Pooling.** Leagues are pooled hierarchically within their `[tiers.*] group` of `config/leagues.toml`
  (`india`: SMAT; `overseas_a`: BBL, SA20, PSL, ILT20, The Hundred; `overseas_b`: CPL, T20 Blast, MLC, BPL,
  LPL, Super Smash, CSA T20): α_L ~ N(μ_α[group], σ_α²), β_L ~ N(μ_β[group], σ_β²), log τ_L ~ N(m, s²), all
  fitted by NUTS (NumPyro). A league with few players in both (LPL 19 batters, SMAT 131) is pulled toward
  its group instead of copying a number; a league added later takes its group's typical league with the
  spread between leagues added to its uncertainty.
- **Onto the IPL rating scale.** The pool compares league players with IPL players on the IPL *rating*
  scale, and an IPL rating itself predicts the next season with a slope below 1 (batters 0.49, bowlers
  0.69: career ratings spread wider than next seasons do). So a league rating is translated to the IPL
  rating that predicts the same season: `a_L = (α_L − α_IPL) / β_IPL`, `b_L = β_L / β_IPL`, and the
  translation sd `√(τ_L² − τ_IPL²) / β_IPL` (what L knows less than the IPL does), per posterior draw; the
  posterior covariance of (a_L, b_L) is kept, so a thin league is less certain.
- **The blend** (replacing the 300-ball switch): each source a Gaussian on the IPL rating scale. His
  leagues first become one composite: each translated mean a_L + b_L·x weighted by 1 / (b_L²·sd_x² +
  parameter variance), the translation variance tsd² added **once** (weighted the same way), because the
  gap between a player's league numbers and his IPL level is his own and shared by all his leagues:
  playing six leagues mustn't shrink it six-fold. The composite and his IPL rating (value, sd) are then
  combined by precision; the chosen candidate (T2) also divides out the population prior that every
  source's posterior already holds (an exact product of Gaussian posteriors, prior N(−6.6, 25.2²) for
  batters and N(−1.1, 11.5²) for bowlers; never more than half the evidence's precision). A long IPL record
  dominates because its sd is small; nothing switches at a ball count.

**The fitted translation** (shipped: every season 2015–2026; on the IPL rating scale; "+10 →" = what a +10
league rating becomes; pairs = player-seasons, players in brackets; last column the old discount / sd):

| League | Bat a | Bat b | Bat tsd | +10 bat → | bat pairs | Bowl a | Bowl b | Bowl tsd | +10 bowl → | bowl pairs | old |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SMAT | −17.1 | 0.80 | 9.0 | −9.1 | 423 (131) | −3.8 | 0.46 | 9.2 | +0.8 | 406 (124) | −17.0 / 6.5 |
| BBL | +0.1 | 0.87 | 12.8 | +8.8 | 196 (74) | +0.9 | 0.81 | 10.5 | +9.1 | 186 (72) | −6.0 / 6.5 |
| SA20 | −1.2 | 0.84 | 11.4 | +7.2 | 60 (29) | −0.1 | 0.69 | 13.1 | +6.8 | 52 (31) | −6.0 / 6.5 |
| CPL | −2.1 | 0.82 | 12.1 | +6.1 | 168 (55) | 0.0 | 0.92 | 9.0 | +9.3 | 121 (54) | −8.5 / 6.5 |
| T20 Blast | −5.4 | 0.69 | 10.9 | +1.5 | 173 (71) | −1.8 | 0.88 | 12.1 | +7.0 | 156 (66) | −8.5 / 6.5 |
| PSL | +3.3 | 0.78 | 11.5 | +11.1 | 91 (45) | +1.0 | 0.71 | 11.6 | +8.1 | 63 (35) | −6.0 / 10.5 |
| ILT20 | −2.9 | 0.80 | 12.1 | +5.0 | 40 (26) | +1.1 | 0.73 | 15.0 | +8.4 | 46 (32) | −6.0 / 10.5 |
| The Hundred | +2.9 | 0.92 | 12.1 | +12.1 | 89 (39) | +0.6 | 0.72 | 11.9 | +7.8 | 79 (37) | −6.0 / 10.5 |
| MLC | −5.6 | 0.72 | 12.7 | +1.6 | 63 (36) | −0.4 | 0.94 | 14.0 | +9.0 | 51 (25) | −8.5 / 10.5 |
| BPL | −4.1 | 0.68 | 11.4 | +2.7 | 98 (42) | −0.7 | 0.92 | 9.8 | +8.5 | 84 (34) | −8.5 / 10.5 |
| LPL | −9.6 | 0.73 | 11.6 | −2.3 | 28 (19) | +0.3 | 0.80 | 10.4 | +8.3 | 34 (19) | −8.5 / 10.5 |
| Super Smash | −9.8 | 0.68 | 11.2 | −3.0 | 33 (19) | −1.2 | 0.88 | 9.9 | +7.5 | 48 (20) | −8.5 / 10.5 |
| CSA T20 | −1.2 | 0.81 | 11.0 | +6.9 | 75 (30) | +0.3 | 0.87 | 10.2 | +9.0 | 70 (35) | −8.5 / 10.5 |

Read across: a SMAT batter loses much more than a SMAT bowler (at a typical +19 batter, −1.9 in the IPL; at
a typical +5 bowler, −1.5); overseas bowling ratings carry over almost whole; slopes below 1 compress the
extremes (a +40 SMAT batter is +15, not +23). Every translation sd is larger than the old guess (9–15 runs
against 6.5 / 10.5), so league evidence counts less next to an IPL record than before.

**Frozen protocol** (declared 2026-10-23 before any test number; `league_translation_fit.py`). Five
candidates — T1 hierarchical with the registry groups and a precision blend; T2 T1 with the prior divided
out of the blend; T3 one pooling group; T4 T1 plus the phase mix of his league balls (death and powerplay
shares: "by phase if the data support it"); T5 T1 with IPW selection weights — compared by rolling-origin
validation (for V = 2022, 2023, 2024: fit on seasons before V, score V), chosen by the mean predictive log
score per player-season (both roles; every IPL player-season with 20+ balls and a league rating). The chosen
one is refitted on seasons up to 2024 and scored **once** on 2025–26, against the scheme it replaces and
"no translation" (league ratings taken as IPL ratings). The shipped fit uses every season to 2026.

*Validation* (mean log score, higher is better): T1 −4.9148, **T2 −4.9121 (chosen)**, T3 −4.9148, T4
−4.9155, T5 −4.9159; the old scheme −4.9127, no translation −4.9195. The phase mix and the IPW weights did
not help (the data don't support a phase split), nor did one pooling group; T2 edges the old discounts by
0.0006 a player-season, which is nothing.

*Disclosures.* (1) A trial run during development printed T1's 2025–26 table once before validation ran.
(2) The first full run blended each league separately, adding each league's translation sd as if
independent; the reality check then showed a player of many leagues gaining precision (and value) league
by league (Narine's pool value went from 24 to 34 on six leagues' bowling), which is wrong by construction,
so the blend was corrected to the composite above and the whole protocol re-run (validation, choice, test).
The fitted translation itself (the table) did not change. The first run's numbers, for the record: T2
chosen at −4.9138; test log score −4.960 / −5.022 (batters / bowlers); reality MAE 11.7. No candidate,
prior or setting was changed for the test.

*Test, once: 2025–26* (n player-seasons; bias = real − predicted IPL value per 100 balls, ball-weighted, the
prediction being the IPL line applied to the value; MAE over seasons with 60+ balls; slope = real on
predicted, 1 = calibrated; ρ = Spearman; log score per player-season):

| Players | Scheme | n | Bias | MAE (60+) | Slope | ρ | Log score |
|---|---|---|---|---|---|---|---|
| Newcomer batters | **fitted** | 33 | −9.1 | 29.4 | 0.82 | 0.18 | −5.287 |
| | old discounts + 300-ball switch | 33 | −9.3 | 28.7 | 1.18 | 0.25 | −5.262 |
| | no translation | 33 | −14.0 | 30.1 | 1.18 | 0.20 | −5.303 |
| Newcomer bowlers | **fitted** | 32 | +5.5 | 29.8 | −1.03 | −0.28 | −5.157 |
| | old | 32 | +13.7 | 31.6 | 0.14 | −0.06 | −5.200 |
| | no translation | 32 | +6.1 | 29.8 | −0.40 | −0.20 | −5.163 |
| Returning batters | **fitted** | 161 | −0.4 | 20.6 | 1.28 | 0.26 | −4.893 |
| | old | 161 | −0.3 | 20.6 | 1.31 | 0.27 | −4.889 |
| | no translation | 161 | −2.2 | 20.1 | 1.70 | 0.32 | −4.884 |
| Returning bowlers | **fitted** | 168 | +0.2 | 25.4 | 1.55 | 0.25 | −4.992 |
| | old | 168 | +0.8 | 25.2 | 1.56 | 0.27 | −4.984 |
| | no translation | 168 | −0.6 | 25.7 | 1.71 | 0.21 | −5.008 |
| All batters | **fitted** | 194 | −1.3 | 21.7 | 1.23 | 0.27 | −4.960 |
| | old | 194 | −1.2 | 21.6 | 1.34 | 0.29 | −4.952 |
| | no translation | 194 | −3.4 | 21.4 | 1.60 | 0.30 | −4.955 |
| All bowlers | **fitted** | 200 | +0.8 | 25.9 | 1.28 | 0.17 | −5.019 |
| | old | 200 | +2.0 | 26.0 | 1.02 | 0.21 | −5.018 |
| | no translation | 200 | +0.1 | 26.2 | 1.17 | 0.15 | −5.033 |

By fifth of the prediction (2025–26, predicted → real, ball-weighted). Batters: fitted −13.4 → −17.9,
−3.9 → −5.7, +0.9 → +3.2, +4.6 → +2.7, +9.1 → +7.1; old −14.5 → −26.1, −4.6 → −5.7, −0.3 → −1.3,
+3.9 → +4.6, +9.3 → +9.0. Bowlers: fitted −9.5 → −4.9, −3.7 → −7.9, −1.0 → −8.3, +1.6 → +6.5,
+7.9 → +12.5; old −14.7 → −9.3, −5.9 → −5.1, −2.9 → −11.0, +0.8 → +5.2, +7.9 → +12.8.

**The honest read.** Level: the fitted translation removes most of the old scheme's under-rating of league
bowlers (newcomer bowlers +5.5 against +13.7 runs per 100 balls; all bowlers +0.8 against +2.0), and its
batters' calibration slope is a little closer to 1 (1.23 against 1.34). On the proper score it is a
**tie**: 0.008 (batters) and 0.001 (bowlers) a player-season behind the old scheme in the test, 0.0006 ahead
in validation. Season numbers are mostly noise (MAE 20–30 runs per 100 balls for every scheme) and the
newcomers are 32–33 a role, so the old discounts and the fit can't be told apart on accuracy; "no
translation" is clearly worse for newcomer batters (−14.0 bias). It ships because it replaces four hand-set
parts (discounts, borrowed values, guessed sds, the 300-ball cliff) with fitted ones at no measured loss and
fixes the role gap the old check had found, not because it predicts better.

**Reality table** (`league_translation_fit.py reality`): each player's value from what was known before
his first IPL season with 20+ balls (the translation fitted on ≤ 2024, so entries before 2025 are
in-sample), against his IPL rating today on every IPL ball since (the same scale). Error = value − IPL
rating today.

| Player | Before | Leagues then | Fitted | Old | IPL today (balls) | Error | Old error |
|---|---|---|---|---|---|---|---|
| Priyansh Arya | IPL 2025 | SMAT +35.4 | +10.8 | +18.4 | +27.7 (471) | −16.9 | −9.4 |
| Ashutosh Sharma | IPL 2024 | SMAT +37.2 | +12.3 | +20.2 | −6.1 (334) | +18.4 | +26.2 |
| Shashank Singh | IPL 2022 | SMAT +6.3 | −14.3 | −10.7 | +0.2 (560) | −14.5 | −10.9 |
| Abhinav Manohar | IPL 2022 | SMAT +25.7 | +2.4 | +8.7 | −27.2 (235) | +29.6 | +35.9 |
| Sameer Rizvi | IPL 2024 | SMAT +14.1 | −7.6 | −2.9 | −6.4 (293) | −1.2 | +3.4 |
| Shahrukh Khan | IPL 2021 | SMAT +0.6 | −19.2 | −16.4 | −10.4 (524) | −8.8 | −6.0 |
| Angkrish Raghuvanshi | IPL 2024 | SMAT +0.7 | −19.2 | −16.3 | −1.2 (608) | −17.9 | −15.1 |
| Ashwani Kumar (bowl) | IPL 2025 | SMAT −3.8 | −5.0 | −20.8 | −8.8 (185) | +3.8 | −12.0 |
| Vipraj Nigam (bowl) | IPL 2025 | SMAT −24.8 | −13.7 | −41.8 | −2.9 (293) | −10.8 | −38.9 |
| Rahul Singh | no IPL go yet | SMAT +38.2 | +13.5 | +21.2 | — | — | — |
| Jake Fraser-McGurk | IPL 2024 | BBL −1.0 | +4.4 | −7.0 | +31.4 (193) | −27.0 | −38.4 |
| Will Jacks | IPL 2024 | SA20 +46.4, Blast +23.0, BPL +36.5 and 3 more | +15.3 | +14.1 | +6.8 (379) | +8.6 | +7.3 |
| Rachin Ravindra | IPL 2024 | Super Smash −0.7 | −4.5 | −9.2 | −1.3 (287) | −3.1 | −7.9 |
| Ryan Rickelton | IPL 2025 | SA20 +35.9, MLC +15.6, CSA +11.7 | +16.9 | +16.8 | +14.0 (497) | +2.9 | +2.8 |
| Tristan Stubbs | IPL 2023 | CSA +29.1, Hundred +3.1 | +1.3 | −2.1 | −4.9 (648) | +6.1 | +2.8 |
| Tim David | IPL 2022 | five leagues, −7.4 to +5.3 | +2.1 | −8.9 | +5.4 (650) | −3.3 | −14.2 |
| Gerald Coetzee (bowl) | IPL 2024 | SA20 +4.5, MLC +6.7, CSA −1.2 | +2.7 | −4.9 | −6.7 (274) | +9.4 | +1.8 |
| Spencer Johnson (bowl) | IPL 2024 | BBL +2.8, Hundred +4.5, MLC −1.5 | +5.8 | −3.9 | −6.7 (231) | +12.6 | +2.8 |
| Jos Buttler | IPL 2016 | BBL +12.3, Blast +18.2 | +11.8 | +8.2 | +20.3 (3,103) | −8.4 | −12.1 |
| Rashid Khan (bowl) | IPL 2017 | BPL +14.4 | +13.2 | +5.9 | +20.3 (3,530) | −7.1 | −14.4 |
| Nicholas Pooran | IPL 2019 | CPL +17.4, PSL −24.9, BPL −4.3 | +6.1 | −4.6 | +18.6 (1,540) | −12.6 | −23.2 |
| Liam Livingstone | IPL 2019 | Blast +10.8 | +5.8 | +2.3 | +4.4 (687) | +1.4 | −2.0 |
| Phil Salt | IPL 2023 | six leagues, Blast +24.6 | +12.9 | +6.6 | +22.6 (721) | −9.7 | −16.0 |
| Harry Brook | IPL 2023 | Blast +13.9, PSL +9.9, BBL −12.1, Hundred +6.0 | +9.0 | −1.6 | −13.5 (154) | +22.5 | +11.9 |
| Devon Conway | IPL 2022 | Super Smash +23.2 and 3 more | +6.5 | −1.1 | +13.9 (773) | −7.5 | −15.0 |
| Mitchell Starc (bowl) | IPL 2015 | BBL −0.1 | +8.4 | +7.0 | +3.8 (1,197) | +4.6 | +3.2 |

Mean absolute error over the 25 with an IPL record: **10.7 fitted against 13.3 old** (bias −1.2 against
−5.5). SMAT stars 13.5 against 17.5 (the old scheme sank the bowlers: Vipraj Nigam −41.8 against a real
−2.9, Ashwani Kumar −20.8 against −8.8; the fitted one rates SMAT batting stars lower, which was right for
Ashutosh Sharma and Abhinav Manohar and wrong for Priyansh Arya); overseas league stars new to the IPL 9.1
against 9.8; established internationals at their entry 9.2 against 12.2 (the old scheme rated every one of
them too low: Pooran, Salt, Conway and Tim David by 14–23). Single players are noisy (Ashutosh, Manohar,
Fraser-McGurk and Brook are far off for every scheme); the pattern across groups is the finding. The obvious
misses left: no scheme sees a breakout coming (Priyansh Arya, Fraser-McGurk), and the fitted one still
over-rates some overseas bowlers on league numbers (Spencer Johnson, Coetzee).

**Where it feeds.** The auction pool's `value` and both roles' values behind the contribution per match
(6c), so the pool's order, P(plays)'s inputs, the room's mini retentions and Bid plan's strength; Scout's
`ipl_value` (its prices, the uncapped and overseas pools, the gem board's prices; the gem flag and the
SMAT staleness labels are unchanged: they read the league's own standing and data date); the on-field
worth (6a). The playing-time model was refitted on the translated values under its own protocol (6c):
P(plays) squad test log loss 0.558 (was 0.562), free agents 0.0856 (was 0.0848); the replacement levels
moved (bowling frontline −11.3 → −5.2, part-time −27.4 → −13.0; batting within 2 runs), because the
minimum-price buys they average are mostly SMAT bowlers the old −17 discount had put far too low, so every
bowler's runs above replacement are about 6 per 100 balls smaller than before.

**Not where it feeds: the market price** (6b). The price recipe was fitted on the old blend. A recipe on
the translated value was declared (Y, 2026-10-23) and scored under the price model's own protocol: leave
one auction out ≤ 2024, mean absolute ln error **0.797 against 0.792** for the shipped recipe T (it also
priced retained stars lower: 20% of held-out retentions at or above their retention price against 24%), so
it was not chosen. The Keep backtest was re-run both ways: on T's prices with the translated playing-time
inputs, the chosen rule is again L4 with the same coefficients (selection F1 0.795; L5 with P(plays) 0.791),
so `config/keep_model.json` is unchanged; on Y's prices L5 would be chosen (selection F1 0.801, test 73.4%
F1 / 78.9% of calls against 72.4% / 78.1%), a small edge that can't ship on its own because Keep's price
must be the price the site shows, and Y lost its own protocol. So `price_value` (and Scout's market price
input) stays the old blend, computed by `translation.legacy_blend` for that input only, until a recipe on
the translated value wins; `config/price_model.json` is unchanged and the auction calibration wasn't re-run.

**Limits.** The fit describes players who got IPL games; for a free agent that is the right conditional
(it is multiplied by his P(plays)), but it is optimistic for the average player who never gets one. The
IPL line (slope 0.49 for batters) says career ratings themselves over-predict next seasons; the pool keeps
career ratings (audit items 3 and 9), so the translation is fitted to match them, not to correct them. The
product-of-posteriors blend divides out one population prior per role, while an IPL rating's own prior is
its batting slot's or bowling group's. Leagues as of 1 January of S use up to a year-old league data for a
December auction. One player can appear in several leagues in one season, so the effective sample is
smaller than the pair count.

---

## 7. The auction room

**What it does.** A Monte-Carlo of a real IPL auction: all ten teams keep their core, then bid for
everyone else under real rules, hundreds of times over. It answers *who probably lands which star, and
for roughly how much?* Code: `src/cricdex/web_parity/auction.py` ⇄ `site/src/lib/auction.ts`; the
step-by-step version is [AUCTION_MATH.md](AUCTION_MATH.md).

**The pool.** The active T20 world an IPL auction draws from: the players under contract (each carrying
his franchise, so he can be retained) plus free agents from every `auction_pool` league in the registry
(the overseas leagues and SMAT; men's T20Is are left out). Who is in it, for the next auction (IPL 2027;
since 2026-10-23):

- **Under contract** = in the next competition's squads (`competitions.squad_rows`: the squads file with
  the 2026 auction, the trades and the retirements and releases applied). Everyone else is a free agent.
  Until 2026-10-23 a player's franchise came from the player master, which can lag the squads file: Ajinkya
  Rahane (retired 30 July 2026) was still a KKR player in the pool.
- **Available**: not in `data/curated/ipl_availability.json` as retired (an announced retirement, with
  dated sources: Dwayne Bravo, Dinesh Karthik, Shikhar Dhawan, Amit Mishra, Ambati Rayudu, Kieron
  Pollard, Wriddhiman Saha, Piyush Chawla, Krishnappa Gowtham, Rishi Dhawan, Aaron Finch, Ravichandran
  Ashwin, Andre Russell, Mohit Sharma, Ajinkya Rahane) or as not registering for that auction. A player who
  only skipped an earlier auction (David Warner and Faf du Plessis, 2026) is recorded but stays: neither
  announced an IPL retirement, and his P(plays) as a free agent (0.04, 0.01) prices the rest.
- **Active**: a T20 match in one of those leagues in the last **three years**. The data rule: of every
  spell without a match in any covered league that began by September 2021, the share after which the
  player played an IPL match again (`scripts/inactivity_gap.py`):

  | years without a match | spells | IPL again (all) | former IPL players | IPL again |
  |---|---|---|---|---|
  | 1 | 4,409 | 12.1% | 937 | 33.8% |
  | 2 | 2,517 | 3.6% | 496 | 9.5% |
  | 3 | 2,009 | 1.9% | 410 | 4.4% |
  | 4 | 1,762 | 0.6% | 360 | 1.4% |

  Three years is the shortest gap after which fewer than one former IPL player in twenty came back; a
  shorter gap is priced by the free-agent P(plays) (its years-away term), not cut. (The SMAT data stops in
  December 2024, so an SMAT-only player stays in until December 2027.)
- Free agents must come from a nation whose players feature in IPL auctions (so not Pakistan or associate
  sides — the `auction_nationalities` / `auction_excluded_nationalities` lists in the registry).

When the official auction list is published it replaces this inferred pool in Bid plan (section 12). A player in several
leagues gets one value per role: his IPL rating and every other league's rating translated onto the IPL
scale (section 6d), blended by precision, so a long IPL record dominates by its small sd (no 300-ball
switch since 2026-10-23) and a hot spell in a weaker league can't outrank it. Both roles feed his contribution per match, and the
pool is ranked by **expected season value** (P(plays) × contribution per match × 14, section 6c; a squad
player's P(plays) in his squad, a free agent's from the free-agent model); the top 600 make the pool, a size
limit for the browser and the room's Monte-Carlo (the room auctions as many lots as real shortlists held for
the open places, below; Bid plan's free agents are this list), not a quality cut. His better role's rate is still shown as `value` and priced as in section
6. Until 2026-10-22 the order was the value less the IPL-relevance penalty (6a step 2) and players under 150
balls were dropped outright; the penalty is replaced by P(plays), the 150-ball cut by the ratings' own
shrinkage (a thin record sits near its slot's mean and, without IPL experience, plays little). The recency
rule stays, now with its evidence (above).

**Retentions.** Editable per team.
- **Mega auction**: each franchise keeps its real 2025 retention list (about five players), paid at the
  real retention price where known, else the IPL slabs (18 / 14 / 11 / 18 / 14 cr, then 4), out of a
  120 cr purse, charged by the real 2025 rule: the higher of the team's slab total and its salaries (KKR 69 cr,
  not its 57 of salaries; DC 47, not 43.75; every team's published 2025 purse reproduced).
- **Mini auction**: each team keeps its 18 players with the highest expected season value free (they were bought in earlier years)
  and tops up from a small purse (30 cr by default).

Retained overseas players count towards the overseas cap of 8.

**The franchises.** All ten bid by **one demand model fitted on real auctions** (since 2026-10-23, audit
item 7). What sets them apart at each lot is their own state: places left by role, overseas places, purse.
The hand-set personalities (MarqueeChaser 1.35, ValueHunter 0.85 …), the need multipliers 1.5 / 0.7, the
budget pressure clamped to 0.75–1.6, the 2% clearing step, MIN_SQUAD 20 and the five knobs calibrated on
top of them are gone. Team effects (personalities estimated from the data) were a candidate and lost out
of time (below).

**The lots.** As many as real shortlists held for the open squad places: the 2018–2024 shortlists
(Wikipedia's personnel pages) listed 4.6 players per open place in a mini auction (4.56, 4.63, 4.66, 4.32
in 2019, 2021, 2023, 2024) and 3.0 in a mega (3.18 in 2018, 2.76 in 2022); 35.7% of each list was
overseas (median of 0.377, 0.350, 0.428, 0.326, 0.357). Open places are the squad maximum less the
retained, over the ten teams (`LOTS_PER_PLACE`, `OVERSEAS_SHARE`; the mega room with the real 2025 lists
allows 3.0 × 205 = 615 and gets 390 of its 555 unretained players: every Indian in the 600 pool, and overseas
up to the share). The lots are the most valuable unretained players, at most that share overseas,
and come up in the real set order: the capped sets before the uncapped (the 2025 and 2026 pages; a mega
auction's marquee sets are its best-known capped players), dearest first within each (the role sets inside
a group aren't modelled). Unsold lots come back once in an accelerated round. Until 2026-10-23: 200 lots,
at most 36% overseas, stars first with a random ±5% nudge.

**The bidding.** For each lot, every team with a squad place, an overseas place if he's overseas, and the
purse for his base price (its purse less the lowest base price for each place it still needs to reach the
squad minimum of 18) decides whether it bids and how high:

```
bids at all with P = logistic(P0 + P1 ln market price + P2 ln base price
                              + I_need ln(1 + places short in his role) + I_os overseas share
                              + I_pps (its ln purse per open place − the mean) + I_up upgrade)
ln bid = mu + u + σ e,     e ~ Gumbel: the team's own view;   u ~ Normal(0, τ²): the lot's heat, shared
mu = A + C ln market price + HINGE max(0, ln(market price ÷ 2 cr)) + BASE ln base price
     + ANCHOR ln(last price ÷ market price)
     + MONEY × the bidding teams' mean ln(purse per open place) + STAGE × share of the open places filled
     + NEED ln(1 + places short in his role) + OS × (overseas lot) × open overseas places ÷ open places
     + PPS × (its ln purse per open place − the mean) + UP × (his expected contribution − its best in his role)
```

"Places short in his role" is against the usual make-up of a squad (the median end-of-auction count per role
in the real 2019–2024 squads: 6 batters, 11 bowlers, 4 all-rounders, 3 keepers); his expected contribution is
P(plays) × contribution per match (6c), held to ±15 runs a match. The bid is held to the team's spendable
purse. The highest bid wins at **the next step of the IPL ladder above the second-highest** (5 lakh below 1 cr,
10 lakh to 2 cr, 20 lakh to 5 cr, 25 lakh above: Business Today, 23 Nov 2024, gives 5 / 10 / 20 lakh for the
2025 auction and 20 lakh as the least step above 3 cr; most of the real 2020–2025 prices above 5 cr sit on
25-lakh steps), or at the base price when nobody else reaches it. A team still short of 18 after the
accelerated round buys the cheapest leftovers at base price (the squad minimum is a rule). There is no
price cap.

**How it was fitted** (`scripts/auction_demand_fit.py fit` and `round2` → `config/auction_demand.json`). Every sold lot of
the 2019–2026 auctions, each team's squad by role, overseas count, purse and best contribution per role
rebuilt lot by lot from the real retentions and the sold lots in the order the history lists them (the
auction's set order; inside a set the order is the page's, not necessarily the hammer's; the history has no
unsold lots, so the fit conditions on the lot selling). Each sale's likelihood is exact under the model: the
winner's bid at least the price, the best of the others' inside the ladder step below it (below the base price
for a sale at base), the heat integrated out by Gauss–Hermite quadrature. Inputs as of each auction:
walk-forward contributions and P(plays), and a market price from the price recipe fitted on the **other**
2018–2024 auctions for 2019–2024 (the walk-forward models of 2019–2021 had only three auctions behind them
and priced the top at 3–9 cr) and on the auctions before for the test. 2018 is left out (nothing earlier to
price it).

**Frozen protocol, round 1.** Candidates declared before any test number (D8 after the 2022–23 validation
replays, still before the test); chosen by leave-one-auction-out log-likelihood per lot over 2019–2024; the
chosen one fitted on 2019–2024 and scored **once** on the 2025 mega and 2026 mini auctions. Mean
log-likelihood per sold lot (higher is better):

| candidate | 2019–2024, leave one out | 2025 (test) | 2026 (test) |
|---|---|---|---|
| D0 market price only (symmetric bidders) | −4.488 | −5.405 | −4.666 |
| D1 + places short in his role, overseas places | −4.470 | −5.382 | −4.636 |
| D2 + purse per open place (the team's and the market's) | −4.439 | −5.175 | −4.503 |
| D3 + upgrade on the team's best in his role | −4.439 | −5.169 | −4.496 |
| D4 + the auction's stage | −4.449 | −5.178 | −4.504 |
| D5 D4 + a mega-auction level | −4.450 | −5.180 | −4.505 |
| D6 D4 + team effects (personalities estimated, ridge sd 0.3) | −4.464 | −5.184 | −4.522 |
| **D7 D4 + the team's needs in whether it bids at all (chosen in round 1)** | **−4.402** | **−5.136** | **−4.464** |
| D8 D7 + his own expected contribution | −4.418 | −5.136 | −4.464 |

2026 is over 63 of its 64 lots: one, Jack Edwards (3.0 cr to SRH), is impossible under the rebuilt order (no
other team could bid when he came up, yet he sold above base) and costs every candidate the same; with it
every 2026 mean is 10.7 lower. Team effects lose out of time: what makes a franchise bid is its squad and purse
at that lot, not a fixed style; a separate mega level adds nothing once the money per open place is in.

**Round 2: why D7 priced the stars low.** D7's 2025 replay put Pant's typical price at 9.0 cr (real 27, the
market price alone 21.5) and Shreyas Iyer's at 9.5 (26.75). The causes tested, on the validation auctions only:

- *Price formation (the order statistics)*: the likelihood is already the English-auction one (the winner's bid
  at least the price, the best other bid inside the ladder step below it), and both spreads are fitted (each
  team's view σ 0.47, the lot's heat τ 0.68 in ln). A heavy-tailed heat (quiet lots and bidding wars, a
  two-component mixture) was fitted and collapsed to one component: no evidence of a heavier tail.
- *The bid level and the market price*: the level rises only 0.08 per ln of market price. Forcing a bid in
  proportion to it (C = 1) or taking the base price, 0.87-correlated with it, out of the level both lose
  likelihood out of time and leave the validation stars no better (below). Within the top base band (1–2 cr) the
  2019–2024 prices followed the market price with slope 0.38 (correlation 0.26), and the market's own 10 dearest
  lots of each auction sold at 0.5–1.5× their market price. The money per open place and the stage don't soak
  it up: dropping both with C = 1 changes nothing.
- *What the stars were*: each auction's 10 dearest real lots sold at 2.3–8× their market price in 2019–2024
  (Starc 24.75 cr at a market price of 2.7, Cummins 20.5 at 3.6), and 2.4× in 2025. The market price's blind
  spot for the mini-auction stars is what no bidding model can see.
- *How low is too low*: a perfectly calibrated room can't put an auction's dearest lots, picked by their
  outcome, inside its 10–90% range 80% of the time, or price them at their real level. Taking each simulated run
  as the "real" auction, the room's own 10 dearest lots land inside the other runs' range **70%** of the time
  at a median **2.3×** the other runs' median (validation auctions). The real top 10: 43% inside at 4.3× under
  D7, a genuine shortfall in the mini auctions (2019–21, 2023–24: 20–50%); the 2022 mega auction sits at the
  benchmark (60% against 54%; 2.5× against 2.7×). The selection and the in-set order (cause a) can't be tested
  without unsold lots or hammer times; the mega auctions, where they would matter most, are not where it fails.

Round-2 candidates and the reality criterion were declared before any round-2 test number (the round-1 test
tables had been seen: this is a second look at 2025–26, disclosed): R0 = D7; R1 a bid in proportion to the
market price (C = 1); R2 R1 without the base price in the level; R3 D7 with a heavy-tailed heat; R4 D7 + its own
slope on the market price above the top base price (ln(market price ÷ 2 cr), where the base price says nothing).
Criterion on 2019–2024 (each candidate fitted on it, 150 runs): (i) the real top 10 inside the simulated range
at least as often as the candidate's own benchmark less 0.15, (ii) their median real ÷ simulated within 1.5× of
the benchmark, (iii) the market's own top 10 (picked by the prediction) at a median real ÷ simulated of
0.8–1.25; the best leave-one-out likelihood among those passing. Ship only if the 2025 real top 10 mostly land
inside their simulated range and the calibration doesn't regress.

| | leave one out | real top 10 inside (benchmark) | real top 10, real ÷ sim (benchmark) | market's top 10, real ÷ sim | 2025 / 2026 log-lik | 2025 real top 10 inside | inside 10–90%, 2025 / 2026 (contested) |
|---|---|---|---|---|---|---|---|
| R0 D7 | −4.402 | 43% (70%) | 4.3 (2.3) | 1.21 | −5.136 / −4.464 | 6 | 69% / 69% (70% / 81%) |
| R1 C = 1 | −4.429 | 40% (72%) | 5.4 (2.3) | 1.07 | −5.184 / −4.486 | 7 | 64% / 69% (66% / 81%) |
| R2 C = 1, no base | −4.500 | 48% (70%) | 5.8 (2.8) | 1.00 | −5.283 / −4.563 | 7 | 62% / 72% (64% / 85%) |
| R3 heavy heat | −4.402 | 43% (70%) | 4.4 (2.3) | 1.21 | −5.136 / −4.464 | 6 | 68% / 69% (70% / 81%) |
| **R4 + market price above 2 cr (shipped)** | **−4.399** | 45% (70%) | 4.6 (2.2) | **1.09** | **−5.137 / −4.453** | **7** | **67% / 70% (69% / 85%)** |

No candidate passes (i)–(ii): the shortfall is in the market price, not the bidding. All pass (iii); R4 has the
best likelihood and is chosen. On the test it puts 7 of the 2025 real top 10 inside their range (D7: 6) with the
calibration level (2025 slightly lower, 2026 higher) and ships, refitted on 2019–2026. Bidding in proportion to
the market price (R1) would price Pant at 21.6 cr (range 2.0–53.9) but loses out of time and widens the 2025
contested lots (simulated ÷ real of the dearest simulated lots 1.44); it is not shipped.

The fit (R4, 2019–2024; the shipped refit on 2019–2026 in brackets): a team short in a lot's role bids at all
more often (+0.35 on the logit per ln place [+0.39]) and a little higher (+0.15 [+0.18]); an overseas lot draws
higher bids from a team with more of its open places free for overseas players (+1.60 [+1.12] × that share); a
team with more purse per open place than the others bids higher (+0.95 [+1.11] per ln) though a little less often
(−0.31 [−0.32]); more money per place across the market lifts every bid (+0.51 [+0.66] per ln); bids fall as the
auction fills (−1.23 [−0.77] from first lot to last). The market price lifts a bid by −0.01 [+0.11] per ln up to
2 cr and by a further +0.23 [+0.22] above it, and the chance of bidding by +0.18 [+0.26]. Each team's own view
spreads σ = 0.46 [0.46] and the lot's heat τ = 0.68 [0.55] (ln).

**Checked as a simulator** (`scripts/auction_calibrate.py`: all ten teams bid, 300 runs, R4's 2019–2024 fit,
every sold lot scored; "contested" = the market price at least 2× base, chosen by the prediction; the room
before 2026-10-23 replayed on the same inputs alongside):

| | 2019–2024 (fitted on) | **2025 mega (test)** | **2026 mini (test)** |
|---|---|---|---|
| real price inside the simulated 10–90%, all sold lots (80% = calibrated) | 66–80% (before: 51–67%) | **67%** (before 64%) | **70%** (before 56%) |
| the same, contested lots | 67–81% (before 38–65%) | **69%** (62%) | **85%** (50%) |
| median real ÷ simulated, contested | 1.00–1.57 (0.98–1.16) | **1.45** (1.55) | **1.00** (1.00) |
| error, mean abs. ln, all sold lots | 0.49–0.98 (0.53–0.97) | **0.65** (0.62) | **0.60** (0.64) |
| the 10 dearest simulated lots, simulated ÷ real | 0.68–1.40 (1.13–2.25) | **1.06** (1.15) | **0.81** (0.78) |
| the real buyer is the simulation's most frequent buyer | 13–27% (4–24%) | **16%** (9%) | **19%** (16%) |

Real price inside the simulated 10–90% by real price band, test (2025 / 2026; before in brackets): under
1 cr 81% / 85% (84% / 70%), 1–3 cr 52% / 80% (50% / 65%), 3–8 cr 53% / 22% (43% / 22%), 8 cr+ 73% / 50% (63% /
25%). The typical (median) price runs low from 3 cr up: real ÷ simulated median 2.5 / 4.4 at 3–8 cr and 1.8 /
2.6 at 8 cr+.

**Reality check, 2025 mega** (the replay: real retentions and purses; simulated median and 10–90% range):

| player | real (cr) | simulated median (10–90%) | the room before |
|---|---|---|---|
| Rishabh Pant | 27.00 | 10.6 (3.2–32.3) | 20.6 |
| Shreyas Iyer | 26.75 | 11.5 (4.6–35.5) | 14.7 |
| Venkatesh Iyer | 23.75 | 2.0 (2.0–6.0) | 4.3 |
| Arshdeep Singh | 18.00 | 9.4 (3.0–28.3) | 6.6 |
| Yuzvendra Chahal | 18.00 | 8.3 (3.0–22.6) | 8.4 |
| Jos Buttler | 15.75 | 8.3 (2.0–25.5) | 6.5 |
| KL Rahul | 14.00 | 10.8 (2.6–27.1) | 20.0 |
| Jofra Archer | 12.50 | 10.5 (2.6–25.3) | 6.4 |
| Trent Boult | 12.50 | 3.7 (2.0–10.4) | 3.5 |
| Josh Hazlewood | 12.50 | 3.5 (2.0–10.0) | 3.3 |

Seven of the real top 10 land inside their simulated range (not Venkatesh Iyer, at the market price's 3.4 cr,
nor the two overseas pacers just above it); five are in the simulation's own top 10. The **typical** price of a
star is still about 10 cr where the real ones went for 14–27: the outcome-picked top lots sit high in any
calibrated room (2.3× its median, above), and here 2.3× the room's. The simulation's own top 10 (median): Sam
Curran 14.6 (real 2.4), Faf du Plessis 12.8 (2.0), Shreyas Iyer 11.5, Siraj 11.4 (12.25), KL Rahul 10.8, Pant
10.6, Archer 10.5, Rabada 9.6 (10.75), Noor Ahmad 9.5 (10.0), Arshdeep 9.4. **2026 mini**, real top 5 against
the simulation: Cameron Green 25.2 → 11.9 (2.0–23.0; before 21.9), Matheesha Pathirana 18.0 → 8.5 (2.0–22.3;
7.4), Prashant Veer and Kartik Sharma 14.2 → 0.3 (the market prices them at base; 0.3), Liam Livingstone 13.0 →
6.3 (2.0–18.1; 8.4). **Purse and squads**: 2025, purse left 0.9–5.5 cr a team (real 0.0–2.0), squads 21–23
(real 20–25); 2026, 0.5–17.0 cr (real 0.3–5.5; KKR, with the most money, keeps 17 of its 64), squads 24–25
(real 25).

**Many runs, one answer.** That's one mock auction. The room runs it **300 times** and reports each team's
typical spend, squad size and overseas count, each star's odds of landing at each team ("MI 62%, CSK
21%"), the average price per player, and one sample auction to browse. The randomness comes from a small
seeded generator (a linear congruential generator, run `t` seeded `1000 + 7919·t`), so the same settings
always give the same result, and the browser (TypeScript) and the CLI / TUI / Streamlit (Python) produce
**the same numbers trial for trial**. `test_scripts/test_web_parity.py` and `test_bidplan_parity.py` run
both and fail CI if they ever differ.

**Limits.** The lot order inside a set is the page's, so a team's state at a lot is approximate; the
history lists no unsold lots, so the fit conditions on a sale. The market price misses the stars of the mini
auctions (their real prices 2–8× it), so the room's typical price for a star is low and its range wide; a bid in
proportion to the market price would fix Pant and break the rest (R1). No right-to-match card, no withdrawals,
no injury news, no capped / uncapped base-price rule; the room's mini default (each team keeps its 18 most
valuable) is a default, not the real lists.

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
  average ball, each dismissal priced at the player's wicket cost) through the same league translation the
  model gets (until 2026-10-23 the tier discount), pooled across leagues by balls. The first version compared
  the discounted model with raw numbers that had no league adjustment at all, so part of the "model edge" was
  just the discount.
- **One number per player, pooled by precision.** A newcomer with several leagues gets one value per axis:
  each league's value translated onto the IPL scale and weighted by 1 / its translated variance, the same
  rule the auction pool uses. (This backtest scores rank; the level of the translation is tested in 6d.) The first version took a player's *best* league, which is biased
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

All 13 leagues (103 batters, 132 bowlers; the overall rows re-run 2026-10-23 with the fitted league
translation of 6d on both the model and the baseline — on the old discounts they were batters 0.08 vs 0.10,
bowlers 0.22 vs 0.26; the skill rows don't use a translation):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall (runs) | 0.12 | 0.08 | +0.03 [−0.09, +0.15] | 70% | 0.30 | 1.00 |
| Batters, scoring | 0.13 | 0.19 | −0.06 [−0.23, +0.11] | 22% | 0.78 | 1.00 |
| Batters, survival | 0.29 | 0.27 | +0.01 [−0.15, +0.17] | 55% | 0.45 | 1.00 |
| Bowlers, overall (runs) | 0.25 | 0.26 | −0.01 [−0.14, +0.13] | 44% | 0.56 | 1.00 |
| Bowlers, economy | 0.25 | 0.26 | −0.01 [−0.12, +0.10] | 42% | 0.58 | 1.00 |
| Bowlers, strike | 0.08 | 0.07 | +0.02 [−0.16, +0.19] | 57% | 0.43 | 1.00 |

The original five leagues (96 batters, 110 bowlers; not re-run with the translation):

| | Model | Baseline | Gap, 95% range | Model ahead in | p | Holm p |
|---|---|---|---|---|---|---|
| Batters, overall (runs) | 0.11 | 0.06 | +0.05 [−0.08, +0.17] | 78% | 0.22 | 1.00 |
| Batters, scoring | 0.11 | 0.18 | −0.07 [−0.25, +0.12] | 23% | 0.77 | 1.00 |
| Batters, survival | 0.31 | 0.23 | +0.08 [−0.09, +0.25] | 83% | 0.17 | 1.00 |
| Bowlers, overall (runs) | 0.22 | 0.25 | −0.04 [−0.18, +0.09] | 27% | 0.73 | 1.00 |
| Bowlers, economy | 0.21 | 0.20 | +0.00 [−0.11, +0.12] | 53% | 0.47 | 1.00 |
| Bowlers, strike | 0.21 | 0.13 | +0.08 [−0.11, +0.27] | 79% | 0.21 | 1.00 |

Every Holm-adjusted p is 1.00: no test is significant.

**Playing-time sensitivity (all 13 leagues, overall in runs, with the translation).** With a 30-ball bar the
model is slightly ahead for both roles (batters 0.07 vs 0.04, n = 183; bowlers 0.22 vs 0.16, n = 187). With a
120-ball bar it is level (batters 0.04 vs 0.04, n = 44; bowlers 0.21 vs 0.22, n = 70). None of these
gaps is large, and samples that small move a lot either way.

**The honest read.** With the runs-currency `value`, the ratings **beat career averages for established IPL
players**, batters (0.19 vs 0.15) and bowlers (0.15 vs 0.11), and the new model predicts held-out balls
better in every season. For **IPL newcomers rated from other leagues they are no better than the players' own
league-adjusted numbers**: a lean for batters (0.12 vs 0.08 with the league translation, ahead in 70% of
re-draws; in the original five leagues on the old discounts 78%), not significant, and no test survives the
correction for six comparisons. Two earlier newcomer
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
  2024-12-15 and is thin before that (44 matches in 2022, 39 in 2023, only the 8 knockout games of 2024-25),
  so uncapped Indian prospects are rated on older form than everyone else. Checked again on 22 Oct 2026:
  Cricsheet's [missing-matches page](https://cricsheet.org/missing/) lists the SMAT 2024-25 group stage (23
  Nov-9 Dec 2024) and all of SMAT 2025-26 (26 Nov-18 Dec 2025) as missing, and no other open-licence
  ball-by-ball source exists (BCCI, ESPNcricinfo, FanCode and iplt20 forbid scraping). Ranji Trophy and
  Vijay Hazare have no ball-by-ball on Cricsheet and aren't covered. So every SMAT-based number says so: the
  Scout SMAT pool and the gem board carry "data to 15 Dec 2024 · stale"; each auction-pool and Keep-or-release
  row carries `stale_share`, the share of the evidence behind his value (his blend weights, section 7) that
  comes from a stale league, and `stale_note` ("SMAT data to Dec 2024"), shown as a badge on the Auction and
  Bid plan pages and in the Keep-or-release reason once it is 10% or more. Form forecast is IPL-only, so SMAT
  doesn't enter it.
- **Prices are a market model**, fitted to real IPL auction prices (6b), but it can't see scouting, injury
  or brand, and a typical player is off by about 1.7×.
- **A single season is noisy.** The backtest's correlations are low for every method, model or not. Treat
  any one-season ranking with care.
- **The ratings only modestly beat career averages for established players** (overall 0.19 vs 0.15 for
  batters, 0.15 vs 0.11 for bowlers), and **for newcomers rated from other leagues they are no better than
  the players' own league-adjusted numbers** (no test significant after correcting for six).
- **Each league is fitted on its own.** Cross-league comparison rests on a fitted translation per league
  and role (6d), which predicts IPL seasons no better than the hand-set discounts it replaced; its spread
  (9–15 runs per 100 balls) is the honest size of that uncertainty.
- **A wicket's price is a first-innings average.** The run cost of a wicket comes from first innings
  (over, wickets down) only and is applied to the chase too, where it really depends on the target; it
  is a league average, not the cost given the actual batters still to come.
- **Value is per ball, not per match.** A finisher who faces 10 balls a game and an opener who faces 25
  are compared per 100 balls; how many balls he gets is a team decision the value leaves out (the auction
  tools' contribution per match, 6c, adds it back).
- **Context is adjusted, form isn't.** The rating model judges every ball against its season, phase,
  innings and ground, but each player has one skill set per league for his whole career. The auction tools
  move it to his age next season (4b), but not to his recent form: a random walk on the level predicted the
  next season worse.
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
which of its players to keep. For each player in its squad, CricDex sets what he would fetch at auction
against what keeping him costs the purse (his salary, or for a 2025 retention the retention slabs), gives
the chance a franchise keeps a player like him (a model of what franchises actually did at every deadline
since 2018, backtested), makes a Keep / Release / Toss-up call with a one-line reason, and shows the squad
that follows: purse left, open slots, role gaps and what filling them costs. Every assumption is editable on
the page (flip any player, change the purse or a role target) and on the CLI (`cricdex keep --team RCB
--release "Virat Kohli" --need spinner=4`). Code: `src/cricdex/web_parity/keep.py` ⇄ `site/src/lib/keep.ts`
(the same numbers and sentences, locked by `test_scripts/test_keep_parity.py`); the data is
`site/public/data/ipl/keep.json`, cooked by `scripts/export_site.py`.

**The rules are data.** A cycle's rules (purse, squad size, overseas cap, how many players may be kept, what a
kept player costs, RTM cards) live in `config/competitions.toml`, one entry per cycle, validated on load. Every
rule must cite a source or be listed as `assumed`, and the page marks the assumed ones. For IPL 2027 (a mini
auction, the last of the 2025–27 cycle): retentions due 15 Nov 2026 and the auction likely 16 Dec 2026 in Goa
(press reports); any number of players may be kept within 25 per squad and 8 overseas; a kept player costs his
current salary out of the purse, **except a player his franchise retained at the 2025 mega auction, who is
charged by the 2025 retention slabs** (below); no right-to-match card; an overseas mini-auction buy is paid at
most 18 cr (his fee: the franchise's purse still pays the whole bid). **No 2027 purse has been
published** (checked again 22 Oct 2026: reports of 18-19 Oct repeat only the 157 cr salary cap and the 2026
figure), so the 2026 figure, 125 cr, is the editable default (the 2025-27 regulations set the total salary
cap at 146 / 151 / 157 cr, so about 131 cr is plausible, but nothing confirms it). The auction date (16 Dec,
ITC Grand Goa, franchise briefing 15 Dec) is still "reported", not announced. The squad minimum (18), no
minimum-spend rule, season replacements being keepable and the 2025 slabs carrying into 2027 (the owner's
call, 22 Oct 2026: "assumed: 2025 mega-auction slabs until BCCI announces 2027 rules") are also assumptions.
Sources are listed in the file and on the page.

**The 2025–27 player rules, checked (22 Oct 2026).** From the IPL's release of 28 Sep 2024 (iplt20.com) and
ESPNcricinfo's reading of the regulations document (28–29 Sep 2024), each cited in `config/competitions.toml`:

| rule | source | in the code |
|---|---|---|
| Overseas fee cap in a mini auction: the lower of the top retention slab (18 cr) and the top mega-auction price (27, Pant): 18 cr; the excess goes to the BCCI for player welfare. It caps the **fee, not the bid**: bidding goes on and the purse is debited the full bid (Green: bid 25.2, paid 18, KKR's purse −25.2) | ESPNcricinfo 29 Sep 2024; Business Today / IANS 16 Dec 2025 | Prices model the bid (what leaves the purse); the squads file keeps Green's 25.2 as what KKR's purse paid; the cap is shown on the page. Unchanged and correct. The Auction room bids in bids too. |
| An overseas player must register for the mega auction, or "he will be ineligible to register in the following year's player auction" (the 2026 mini only, so it doesn't bind in 2027); "any player who registers in the player auction and after getting picked at the auction, makes himself unavailable before the start of the season, will get banned from participating in the tournament and player auction for 2 seasons" | iplt20 28 Sep 2024 (official, items 5 and 6) | The registration half isn't modelled: the pool has no registration list, and for 2027 it doesn't bind. Bid plan takes the official 2027 list when published (`ipl_auction_register.json`). **The ban is modelled since 2026-10-27**: `status: "banned"` with its seasons in `data/curated/ipl_availability.json` takes a player out of the pool and off his squad (`competitions.unavailable`, `squad_rows`). Harry Brook (bought 2025, pulled out; the BCCI told him and the ECB of a two-season ban, EWN / India TV, 13–14 Mar 2025): out for 2026 and 2027. Ben Duckett (bought by DC for 2 cr in 2026, withdrew before the season to play for England, Gulf News / Outlook, 24 Mar 2026): the rule applied to the confirmed withdrawal, out for 2027 and 2028; no formal BCCI announcement was found, so the record says so and goes if the BCCI makes an exception. |
| A capped Indian player becomes uncapped "if the player has in the last five calendar years preceding the year in which the relevant Season is held, not played in the starting XI in International Cricket (Test match, ODI, Twenty20 International) or does not have a Central Contract with BCCI"; Indian players only | iplt20 28 Sep 2024 (official, item 7) | **Modelled since 2026-10-27** (`competitions.ipl_capped`): an Indian whose last international XI (the player master's `last_international`, from Cricsheet's men's Test, ODI and T20I XIs) is before 1 January of the season less five is uncapped for that season. The data have no central-contract list; a player with no international for five years is taken to have none. It sets the set a pool player comes up in (capped first, then uncapped). For 2027 it makes 13 squad or pool players uncapped: MS Dhoni (last international 2019), Krunal Pandya, Manish Pandey, Prithvi Shaw, Rahul Chahar, Navdeep Saini, Nitish Rana, Ishant Sharma, T Natarajan, Chetan Sakariya (all 2021), Mayank Markande (2019), Sandeep Sharma (2015), Karn Sharma (2014). The market price keeps his international caps as a feature (what the market saw), not this status. |
| Retentions at the 2025 mega auction: at most 6 (retentions + RTMs), at most 5 capped and 2 uncapped; slabs 18 / 14 / 11 cr for the first three capped, 18 / 14 for the 4th and 5th, 4 cr uncapped; the purse is charged the higher of the slab total and the salaries | iplt20 (counts); ESPNcricinfo 28 Sep 2024 (slabs); explainers on KKR's 69 cr (the "higher of") | Now modelled for 2027 (below). The rule is checked on data: it reproduces every team's published 2025 purse and, charging the 2025 retentions still on each squad, every team's 2026 purse. The Auction room's mega replay charges the same rule since 2026-10-22 (KKR 69 cr of purse, DC 47; it had charged the salaries, 57 / 43.75). |
| RTM at the 2025 mega auction: 6 minus the retentions; after an RTM call the top bidder may raise once | iplt20; ESPNcricinfo | Not used: 2027 is a mini auction, no RTM. |
| Purse 120 cr (2025), 125 (2026); total salary cap 146 / 151 / 157 cr for 2025 / 26 / 27 incl. performance pay and match fees (7.5 lakh a game, impact player included, paid on top of the contract) | iplt20 (official); iplt20 2026 retentions | 125 cr assumed for 2027 (no figure published). Match fees are outside the auction purse and aren't modelled. |
| 2027: the last mini auction of the cycle; keep anyone at his contract salary; 25 per squad, 8 overseas; no RTM; trade window shut a week either side of the auction | press, Oct 2026 (Sporting News, Cricbuzz via The Cricket News) | As modelled; no 2028 mega-auction rule is announced. |

**The squads and salaries.** Each franchise's 2026 squad and every player's salary (the 2025 auction or
retention price carried into 2026, the 2026 auction price, a replacement's fee, a trade's price) come from
Wikipedia's "List of 2026 Indian Premier League personnel changes" (CC BY-SA), with the moves since the season
(Pant to DC at 15 cr for Kuldeep Yadav to LSG; Natarajan to SRH for Zeeshan Ansari; Rahane retired) from the 2027
page, by `scripts/ipl_squad_salaries.py` into the hand-editable `data/curated/ipl_squads_2026.json`. A player
released by his franchise (Mustafizur Rahman) or retired isn't on the list. **A data check, exact for all ten
teams:** 125 cr less the retained salaries less the *retention-slab charge* reproduces the purse each team took
into the 2026 auction (IPLT20 / ESPNcricinfo, 15 Nov 2025), and that purse less our 2026 auction prices
reproduces the purse left after the auction (CSK 2.4, DC 0.35, KKR 0.45, RR 2.65 cr; Business Standard). The
slab: at the 2025 mega auction a retained player was charged to the purse at a fixed slab (capped 18 / 14 / 11
/ 18 / 14 cr for the 1st-5th, uncapped 4) "regardless of the final retention value" (DNA India, 3 Nov 2024:
KKR paid 57 cr of salaries and lost 69 cr of purse). The published 2026 purses are exactly what you get when
each 2025 retention still on the squad is charged at his slab: KKR +6 cr (Rinku, Varun, Narine at 18 / 14 / 11
against 13 / 12 / 12), DC +3.25, CSK +2, RR +4 (Samson's slab was 14, not his 18). The team totals are exact;
the per-player split for CSK and RR isn't published. One salary was wrong on Wikipedia: Vipraj Nigam was
bought for 50 lakh in 2025, not 30 (Delhi Capitals; corrected by hand, `salary_note`). Whether the slab still
counts in 2027 isn't published: it is assumed to (the owner's call), with the 2025 rule as above. 253 of 272 squad
players match a Cricsheet id: Mukul Choudhary, Tejasvi Singh (Dahiya) and Sahil Parakh ("Parekh" on Wikipedia)
played IPL 2026 under scorecard names "MD Choudhary", "T Dahiya", "SU Parakh" and were matched on 22 Oct 2026
through the People Register's ESPNcricinfo key (`data/curated/player_overrides.json`; the name check had
wrongly called MD Choudhary "Mukesh Choudhary", CSK's bowler). The 19 who don't match have no ball-by-ball
record anywhere on Cricsheet (no IPL match, nor any SMAT match up to Dec 2024; Cricsheet lists the SMAT 2024-25
group stage and all of SMAT 2025-26 as missing) and are priced from the market (step 4).

**How each number is made.**

1. **Value** is the auction pool's value (section 7): his IPL value in runs per 100 balls, blended by
   precision with his other leagues translated onto the IPL (6d), with its uncertainty `sd`.
2. **Market price** is section 6b's price: what the IPL market has paid for players like him (on the
   cautious estimate, at the median for his kind of player, with the top end as the market really priced
   it), with the chance he's bought if released. The **upper figure** is the upper quartile of what
   players like him fetch, on his central value. His **on-field worth** (section 6a's curve) is a separate
   column, for comparison. A player who was an IPL side's regular **captain** last season carries a
   Captain badge. (An export from before the market model falls back to the curve.)
3. **Cost** = what keeping him takes from the purse. For most players his salary. For a player his
   franchise retained at the 2025 mega auction and still holds (`slab_holder`, from the squads file's
   `mega_retentions_2025`, capped or uncapped *at retention*; a player who has since been traded costs his
   salary at his new team): the team's slab holders together cost max(the first n capped slabs + 4 cr per
   uncapped one, their salaries), the 2025 rule, and **one player's cost is what releasing him alone would
   free** (the team's charge with every holder kept, less the charge without him). The slabs are counted
   in order (keeping 1–5 capped retentions costs 18, 32, 43, 61, 75 cr, as the rules publish them), so the
   order a team retained them in doesn't change its charge, and releasing any capped holder frees the last
   slab in use, or his salary when the salaries are what the purse counts. Examples: RCB (Kohli 21, Patidar
   11, Dayal 5): 18 + 14 + 4 = 36 of slabs against 37 of salary, so 37; without Kohli, 22 (slabs) → his cost
   15. MI's five (75 of slabs = 75 of salary): any of Bumrah, Rohit, Suryakumar, Hardik costs 14, Tilak
   Varma 8 (his salary). RR's four capped (61 of slabs + 4): Jurel and Parag cost 18 each, more than their
   14 salaries. `retention_costs` ⇄ `retentionCosts`, `slab_charge` ⇄ `slabCharge`.
4. **The chance a franchise keeps him** (since 2026-10-22, audit item 1). Not a margin set by hand: a
   logistic model of what franchises actually did at every retention deadline 2018–2026 (the backtest
   below), from (`keep_features` ⇄ `keepFeatures`):
   - his **market price against what keeping him costs** (ln of the ratio), and ln of the cost;
   - his **3-season Form forecast** (section 11): the three-season average and the chance he is still a
     regular in its third season (a flag when he has none);
   - his **ties to the franchise**: its regular captain last season, the IPL seasons he has played for it
     (ln), whether it was his first IPL side ("home-grown");
   - his **status**: capped Indian, overseas, age ((age − 28) / 5 and the years past 33), ln IPL balls, a
     buy at the last auction;
   - in a mega year, a mega flag and its interaction with the price ratio (zero for IPL 2027, a mini).

   - in a mini year, whether this franchise **retained him at the cycle's mega auction** (since
     2026-10-29, candidate L7; the page and the CLI read it from `slab_holder`);
   - his **IPL matches last season** (since 2026-10-30, candidate L8): matches / 14, at most 1, and a flag
     for none (`matches_last` in keep.json).

   Fitted on 1,910 squad decisions 2018–2026 (`config/keep_model.json`, by `scripts/keep_backtest.py`).
   The largest effects: matches last season (+2.28 from none to a full season of 14; the played-none
   flag adds +0.46 back, so a player who missed the season sits about where one who played three
   matches does: an injured regular is often kept), the forecast's chance he stays a regular (+1.20
   from 0 to 1), being overseas (−0.79 in log-odds), retained at the mega auction (+0.70), the forecast
   average (+0.72 per 10 runs), home-grown (+0.21). **The price against the cost counts little in a mini
   year (+0.12 per ln unit) and somewhat more in a mega year (+0.47): in a mini year this is a model of
   what franchises do, not a cost-benefit tool** (that is the *Should they?* column, 5b).

   **The mega retention (L7, 2026-10-29).** The owner's reality check: Rohit Sharma, retained by MI at the
   2025 mega auction and kept for 2026, was a 59% Toss-up. Franchises kept 104 of the 111 players they
   had retained at the cycle's mega auction at the mini deadlines up to 2024 (94%, against about 60% of the
   rest; 41 of 44 in 2026), and the previous model (L4) put them at 0.90 on average. L7 = L4 + that flag,
   declared before its numbers. On the selection (leave one deadline out, 2018–2024) it tied L4 on F1
   (0.798) and had the lower log loss (0.5770 against 0.5780), so the selection rule now breaks a tie on
   F1 (to 3 places) by the held-out log loss, written into the code before the test was read. Tested once
   on 2025–26: accuracy 78.3% (stars 82.8%), F1 0.727 against L4's 0.717; its 2026 retainees average 0.93
   against 0.93 kept (L4: 0.90). Rohit Sharma 59% → 71% (Keep), Dhoni 59% → 73%.

   **What a toss-up means.** On the 2026 deadline (fitted 2018–2024), franchises kept 49% of the players
   the model put at 35–50% and 56% of those at 50–65%, against 88% at 65%+: a Toss-up call is close to
   a coin flip, which is why it isn't forced either way.
5. **The call.** *Keep* at a 65%+ chance, *Release* below 35%, *Toss-up* in between (a close call
   either way); the default plan keeps him from 50% (the backtest's rule). The reason gives the price
   against the cost, his ties and the chance: "Worth about 7.8 cr at auction against 15 to keep
   (home-grown, 19 seasons with RCB): franchises kept 93% of players like him at their retention deadlines
   (2018-2026)." The 35+ rule and the 0.5 cr / 15% margins are gone. **A player with no match data** (no
   Cricsheet match at all) gets no value; his value column says "no match data — priced from the market",
   his price is the market model's prior for a player like him (uncapped Indian, unrated, no IPL record, his
   age when known), and the call comes from the same model; when his auction price was well above the top
   quarter (Mangesh Yadav, 5.2 cr) the reason says franchises saw something our data can't. A player we
   can't price at all (no market inputs, an old export) is Toss-up: scout him. **A rating that rests on
   stale data says so** ("85% of his rating rests on SMAT data to Dec 2024 (stale).").
5b. **Should they?** (since 2026-10-27). The call is what franchises *will likely do*, and in a mini year
   the fitted model hardly weighs the cost: ln(price / cost) at +0.141 and ln(cost) at +0.139 nearly
   cancel (together about +0.14 ln price − 0.002 ln cost), so a dear retention looks as likely as a cheap
   one (Kartik Sharma: 94% at a 14.2 cr cost against a 2.6 cr market price). The cost terms were not
   re-specified for this (the 2025–26 seasons are spent). Instead a second, cost-aware column reads
   the market price (6b) against the cost (step 3): **Yes** when the median market price is at least the
   cost (a player like him would cost at least as much to buy at the auction); **No** when even the upper
   figure, the upper quartile of what players like him fetch, is below the cost; **Close** in between,
   which is about the price's typical error (a factor of about 2); nothing when he has no price. It never
   changes the call, the default plan or the purse. It inherits the price's blind spots: no brand or
   captaincy plans, star prices that run low (AUCTION_MATH Part 0). `should_of` ⇄ `shouldOf`,
   parity-tested; the CSV column `should_keep`.
   **Domestic form not in our data** (since 2026-10-29). The auction comes straight after a domestic
   season our data doesn't have (SMAT on Cricsheet ends Dec 2024; the state T20 leagues were never
   there; no source publishes the 2025–26 season as data, and scraping scorecard sites is not done
   here). An uncapped Indian bought at the last auction (a sale, not a retention) for more than the upper
   quartile of players like him was bought on that form: the reason says so, and **Should they?** reads
   *Can't tell* instead of No (`form_unseen` ⇄ `formUnseen`, parity-tested). On the 2027 squads: Prashant
   Veer and Kartik Sharma (CSK, 14.2 cr), Tejasvi Singh (KKR, 3), Mukul Choudhary (LSG, 2.6), Akshat
   Raghuwanshi (LSG, 2.2), Ravi Singh (RR, 0.95). A player capped since (Auqib Nabi, 8.4 cr, one India
   cap) is outside it. The call is unchanged: it is what franchises do.
6. **Age** is at the auction date from the player master's date of birth, shown with the shape of his Form
   forecast (holds, improves, declines). **Last season** is the raw 2026 strike rate or economy and wickets
   against that season's league figure (30+ balls), not the model.
7. **The squad.** Kept by default: every player with a 50%+ chance, **then made legal**: while the kept
   overseas players are over the overseas cap (8, or a retention limit on overseas players), the kept
   overseas Toss-up players are released, lowest chance first (a Keep only once no Toss-up is left);
   then the same over every kept player for the squad maximum (25, or a retention limit). Each one says
   "Released to fit the 8-overseas cap" / "the 25-player squad limit" in his reason, the CSV marks him
   (`auto_release`), and a player the user flipped is never moved. Purse left = purse − what the kept
   players cost (`purse_charged`). Slots open = 25 − kept (overseas: 8 − kept overseas). Warnings flag a
   squad or overseas count over the cap (only after a flip), a purse overrun, or too little purse to reach
   18 players at 0.3 cr each. (`fit_to_rules` ⇄ `fitToRules`.)
8. **Role gaps.** Tags: keeper (role), opener (batting position in the player master), death bowler (25%+ of
   his legal balls in overs 16–20, 60+ such balls, every auction-pool league), spinner (bowling type), overseas.
   All of them read the **last 3 years**, not the career (since 2026-10-27): the keeper needs recent
   stumpings, the opener opened in at least half his last 30 T20 innings, pooled or in any one league
   with 8+ of them (so Narine, who opens for KKR, counts; a bowler gets the tag when the ball data says
   he opens; docs/IDENTITY.md), the death
   bowler's balls are counted from 3 years before the pool's newest match, and a spinner with 5+ recent T20
   matches must still bowl 0.6 overs a match. The career window had kept Duckett and Glenn Phillips as
   keepers, Padikkal and Ishan Kishan as openers, Shivam Mavi (24 balls in 3 years) as a death bowler and
   Rahul Tewatia (no overs) as a spinner, and missed Kohli, Samson, Marsh, Markram and Prabhsimran Singh as
   openers.
   Targets: 2 keepers, 3 openers, 3 death bowlers, 3 spinners, and the overseas players the squad has now (at
   most 8). Gaps are filled in that order from the **likely pool**: today's free agents in the auction pool
   plus the players our default plan releases from the other nine squads (at our price), cheapest first,
   among those at least as good as the best player the team released in that role, by contribution per match
   (runs above replacement, batting and bowling at his balls, section 6c; until 2026-10-22 by the better
   role's rate per 100 balls; a replacement-level player, 0, when the team released none), within the open
   slots and overseas room. A pick counts for every tag he carries.

**The 2026-10-30 refit (L8; protocol declared that morning, before any of its numbers).** Six reviewers
found that the backtest flattered the model: a mega-year player past the last retention slab got
P(keep) = 0 (16 of 2025's 46 real retentions, Rohit and Head among them), selection let a deadline be
predicted from later ones, the 78% headline pooled a mega year (where "release everyone" already scores
82%) with a mini year (where "keep everyone" scores 69%), and the 2025–26 "test" had been read at least
six times. The rows were also rebuilt on the corrected inputs (first IPL side from seasons before the
deadline only, every input as of the retention deadline, not the auction, retirements filtered by the
right key, every published retention matched to a row or listed with its reason). What changed:

- **No forced zeros.** In a mega year a player past the last slab costs the cycle's dearest slab and stays
  eligible; the per-team limits cap the calls (highest chance first), never the chance.
- **Forward-chaining folds.** Each deadline 2020–2024 is predicted by the model fitted on the deadlines
  before it only.
- **The rule: lowest pooled held-out log loss** (a proper score of the chance itself; F1 no longer picks).
- **Reported per cycle**, against that cycle's majority call and a constant rate, both from the training
  deadlines, with 95% intervals by resampling team-deadlines, and the release precision / recall.
- **One new candidate**, L8 = L7 + matches last season (Dhoni, Yash Dayal and Pathirana missed 2026).
- **A Platt recalibration per cycle**, fitted on the earlier deadlines' out-of-fold chances, to be kept
  only if it lowered the held-out log loss.

Selection (2020–2024 held out forward; each candidate at its best penalty; the majority call is "release
everyone" in a mega year, "keep everyone" in a mini year):

| candidate | log loss | accuracy | mega 2022: accuracy (release all 0.870) | mini 2020-21, 23-24: accuracy (keep all 0.659) | mini log loss (constant 0.646) | mini releases: precision / recall |
|---|---|---|---|---|---|---|
| B0 keep everyone the rules allow | | 0.693 | 0.832 | 0.659 | | – |
| C0 the rule before 2026-10-22 | | 0.653 | 0.832 | 0.610 | | 0.26 / 0.08 |
| L1 price vs cost | 0.588 | 0.699 | 0.865 | 0.659 | 0.645 | – |
| L2 + 3-season forecast | 0.493 | 0.728 | 0.861 | 0.696 | 0.535 | 0.55 / 0.66 |
| L3 + ties to the franchise | 0.493 | 0.734 | 0.870 | 0.701 | 0.536 | 0.55 / 0.67 |
| L4 + status | 0.488 | 0.755 | 0.841 | 0.735 | 0.525 | 0.60 / 0.65 |
| L5 L4 + playing time | 0.478 | 0.743 | 0.846 | 0.718 | 0.514 | 0.58 / 0.61 |
| L6 L5 without the Form forecast | 0.484 | 0.754 | 0.861 | 0.728 | 0.521 | 0.60 / 0.59 |
| L7 L4 + retained at the mega auction (shipped until now) | 0.487 | 0.753 | 0.846 | 0.730 | 0.524 | 0.59 / 0.66 |
| **L8 L7 + matches last season** | **0.4775** | 0.742 | 0.856 | 0.715 | 0.515 | 0.57 / 0.65 |

L8 wins (C = 0.1), L5 a close second (0.4780). No model beats "release everyone" on the one mega deadline
held out (2022), and none is more accurate than L4 on the mini ones: the gain is in the chance, not the
calls. The Platt recalibration made the held-out log loss worse (0.605 against 0.4775: the early
deadlines' out-of-fold chances are too few and too noisy to recalibrate on), so it is not applied. Held
out, the mini chances are close to right (franchises kept 47% of the players put at 35–50%, 58% at
50–65%, 80% at 65–80%, 92% at 80–90%, all at 90%+).

Validation (fitted on 2018–2024, scored once on 2025 and 2026; not an untouched test, since earlier models
were read on these deadlines):

| deadline | n (kept) | L8 accuracy | majority call | L8 − majority (95% interval) | log loss (constant) | L8 − constant (95% interval) | releases: precision / recall | stars' accuracy |
|---|---|---|---|---|---|---|---|---|
| 2025 mega | 252 (18%) | 0.841 | 0.817 release all | +0.024 (−0.004, +0.055) | 0.307 (0.494) | −0.187 (−0.223, −0.149) | 0.85 / 0.98 | 0.82 |
| 2026 mini | 229 (69%) | 0.707 | 0.686 keep all | +0.022 (−0.039, +0.091) | 0.509 (0.625) | −0.116 (−0.174, −0.064) | 0.53 / 0.61 | 0.88 |

The rule before 2026-10-22 (C0) scores 0.813 and 0.616 (7 points *below* keeping everyone in 2026). So:
the chance is much better than a flat rate in both kinds of year, and the model ranks who stays within a
squad; **in a mini year its keep / release calls are level with keeping everyone** (the interval spans
zero), and it found 61% of 2026's releases (L7: 51%). It still keeps the four stars franchises released in
2026 (Pathirana 96%, Bishnoi 97%, Russell 90%, Venkatesh Iyer 81%): all played most of 2026 and nothing in
the data says they were going. The model actually shipped is L8 refitted on every deadline 2018–2026. The
first true test is the 2027 deadline (15 Nov 2026): the calls were written on 2026-10-30 to
`data/predictions/ipl_keep_2027.json` / `.csv` (`scripts/keep_predictions.py`: every squad player's
chance and default call, 175 kept and 96 released of 271, with the git commit and a SHA-256 of every
input), committed before the deadline and scored once the retained lists are out.

The tables below are the history (the 2026-10-22 run, with the defects above).

**The backtest: does the call do what franchises do?** (`scripts/keep_backtest.py`; audit item 1.) Every
deadline with a complete published retained list is replayed with only what was known before it: the 2018,
2022 and 2025 mega auctions and the 2019, 2020, 2021, 2023, 2024 and 2026 mini auctions.

- **The squad before the deadline:** everyone who played for the franchise the season before (Cricsheet;
  2015 for CSK and RR, back in 2018), plus its retained and bought players of that season (the auction
  history). A player another franchise lists as retained was traded and is left out (except a pick of
  2022's two new sides, who was released by his old one); 2026's published retirements are left out.
- **What he was worth then:** his market price from the price recipe fitted on the earlier auctions only
  (`fit_price_part`; for 2018–19, on auctions from 2011), his value, caps, captaincy and age as of the
  auction, and his Form forecast built from the seasons up to the deadline (the walk-forward ratings).
- **What keeping him cost:** his contract salary in a mini year (the latest price paid for him); in a mega
  year the cycle's slab for his place, the team's players taken in market-price order (2018: 15 / 11 / 7 cr
  capped, 3 cr uncapped, at most 3; 2022: 16 / 12 / 8 / 6, 4 cr, at most 4; 2025: 18 / 14 / 11 / 18 / 14,
  4 cr, at most 6 with 5 capped and 2 uncapped; IPL Governing Council 2017, retention rules 2021, Player
  Regulations 2025-27), and the mega limits applied to the calls (the highest chances first); in 2026 the
  2025 slab holders at the slab their release frees.
- **The label** is the published retained list: 1,445 decisions up to 2024 (732 kept; 247 stars, 190
  kept) and 484 in the test (2025: 254, 46 kept; 2026: 230, 157 kept).

The candidates, declared before any test number: the shipped rule (C0, price against salary with the 0.5
cr / 15% margins and the age-35 rule); a fitted threshold on the market price against the cost (C1); the
same with the price on the three-season forecast (C2: what a buyer buys over a contract); and logistic
models adding, in turn, the forecast (L2), the ties to the franchise (L3) and the status terms (L4); and, as
a reference, keeping everyone the rules allow (B0). Chosen by leave one deadline out over 2018–2024 (each
deadline predicted by the rule fitted on the others), highest F1 for "kept" on the pooled held-out calls
(L's penalty chosen the same way). "Star" = what is at stake (his cost or his market price) is at least 8%
of the purse (10 cr at 125); regular 2–8%; depth below.

Selection (deadlines up to 2024, held out one at a time; precision / recall for "kept"; BA = balanced
accuracy, the mean of the share kept that we keep and the share released that we release):

| rule | precision | recall | F1 | BA | stars: precision / recall / F1 / BA | regulars F1 | depth F1 | log loss |
|---|---|---|---|---|---|---|---|---|
| B0 keep everyone the rules allow (reference) | 0.64 | 0.98 | 0.773 | 0.71 | 0.77 / 0.99 / 0.87 / 0.50 | 0.77 | 0.71 | |
| C0 shipped rule (margins, age 35) | 0.63 | 0.75 | 0.684 | 0.65 | 0.81 / 0.46 / 0.58 / 0.55 | 0.70 | 0.71 | |
| C1 market price vs cost, threshold | 0.65 | 0.96 | 0.772 | 0.71 | 0.80 / 0.93 / 0.86 / 0.57 | 0.77 | 0.71 | |
| C2 forecast market price vs cost | 0.65 | 0.96 | 0.771 | 0.71 | 0.80 / 0.93 / 0.86 / 0.58 | 0.77 | 0.71 | |
| L1 logistic: price vs cost | 0.65 | 0.95 | 0.773 | 0.71 | 0.83 / 0.91 / 0.87 / 0.65 | 0.77 | 0.71 | 0.653 |
| L2 + 3-season forecast | 0.75 | 0.74 | 0.745 | 0.74 | 0.82 / 0.91 / 0.86 / 0.63 | 0.78 | 0.52 | 0.573 |
| L3 + ties to the franchise | 0.74 | 0.82 | 0.774 | 0.76 | 0.83 / 0.93 / 0.88 / 0.64 | 0.79 | 0.65 | 0.566 |
| **L4 + status (shipped)** | **0.77** | **0.82** | **0.795** | **0.79** | **0.84 / 0.92 / 0.87 / 0.66** | **0.78** | **0.74** | **0.554** |
| L5 L4 + playing time (P(plays) in his squad, P × contribution) | 0.77 | 0.80 | 0.786 | 0.78 | 0.85 / 0.92 / 0.88 / 0.68 | 0.77 | 0.72 | 0.546 |
| L6 L5 without the Form forecast | 0.77 | 0.82 | 0.794 | 0.78 | 0.85 / 0.93 / 0.88 / 0.68 | 0.77 | 0.74 | 0.552 |

L4 is best on F1 and on balanced accuracy, and every step from L1 adds something: the price against the
cost alone does no better than keeping everyone; the forecast tells who stops playing (and so who goes); the
ties and the status terms tell the rest.

**Playing time as an input** (L5, L6; declared on the evening of 2026-10-22 with section 6c, before any of
their numbers; rows rebuilt with each player's contribution per match as of the deadline and his P(plays) in
the squad his franchise held before it, from the squad model fitted out of fold: on the other seasons up to
2024 for a training deadline, on 2018–2024 for 2025–26). Both fit the decisions better in likelihood (log loss
0.546 and 0.552 against 0.554; at a weaker penalty 0.543 against 0.548) and tell the stars apart better (stars'
F1 0.88 against 0.87, balanced accuracy 0.68 against 0.66), but neither beats L4 on the declared rule, F1 for
"kept" (0.786 and 0.794 against 0.795), so L4 stays and has the only test. What a franchise does at a deadline
is already carried by the Form forecast's chance he stays a regular, which overlaps P(plays). The C0 rows
were recomputed that evening on the shipped price recipe (T, 6b); the first run had priced C0 with the
afternoon's recipe (F1 0.729 in selection, 0.683 in the test); every other row is unchanged.

The test (fitted on 2018–2024, scored on 2025 and 2026). This model was scored on them once, but those
seasons had already shaped other choices (the price input, section 6b) and have been looked at up to five
times since, so read it as optimistic:

| rule | precision | recall | F1 | BA | accuracy | stars: precision / recall / F1 / BA (accuracy) | 2025 mega: F1 / BA | 2026 mini: F1 / BA |
|---|---|---|---|---|---|---|---|---|
| **L4 (shipped)** | **0.77** | **0.69** | **0.724** | **0.77** | **0.78** | **0.88 / 0.88 / 0.88 / 0.79 (82%)** | **0.48 / 0.66** | **0.78 / 0.64** |
| C0 shipped rule before | 0.64 | 0.66 | 0.646 | 0.69 | 0.70 | 0.82 / 0.63 / 0.71 / 0.65 (64%) | 0.42 / 0.64 | 0.69 / 0.42 |
| B0 keep everyone the rules allow | 0.64 | 0.92 | 0.755 | 0.77 | 0.75 | 0.73 / 1.00 / 0.85 / 0.57 (75%) | 0.55 / 0.74 | 0.81 / 0.50 |

Read honestly:

- **Against the rule it replaces** the model is better on every measure: it makes the franchise's own call
  for 78% of the players (70%) and 82% of the stars (64%), and it tells which stars go (balanced accuracy on
  stars 0.79 against 0.65).
- **Against keeping everyone**, it is level overall (balanced accuracy 0.77 / 0.77, F1 0.72 / 0.76): most of
  a squad is kept in a mini year (157 of 230 in 2026), so keeping everyone is a strong default. What the
  model adds is telling which of the expensive players go (stars 0.79 against 0.57).
- **The 2025 mega auction is under-kept** (recall 0.35: 21 called keeps where franchises kept 46). Its
  mega terms were learned from 2018 and 2022, when 3 and 4 retentions were allowed; 2025 allowed 6. The
  number of retentions a cycle allows isn't a feature (with two mega years to learn from, it can't be), so
  a mega-year call should be read as a ranking within the team. Its log loss on the test (0.81) is worse
  than the base rate for the same reason. 2027 is a mini auction.
- **The 2026 stars franchises let go, the model kept**: Venkatesh Iyer (KKR, 23.75 cr against a 2.6 cr
  market price, but home-grown and a regular), Pathirana, Bishnoi, Russell (who then retired). In a mini
  year the price against the cost counts little in the model (+0.14), because across 2019–2024 franchises
  mostly kept their dear players whatever the market said. Venkatesh's release says they don't always.
  The other way: Stoinis (36, 11 cr) was called a release and PBKS kept him.
- **The 2025 stars franchises kept, the model released**: Jadeja (14 cr slab, 36), Rinku Singh, Rashid
  Khan, Varun Chakravarthy, Cummins, Pooran, Patidar, Dube; and kept-by-model, released by the franchise:
  Pant, KL Rahul, Shreyas Iyer, Ishan Kishan, Arshdeep. In 2025 the stars who left were mostly captains
  and stars who chose to go (or whose franchise expected to buy them back cheaper with an RTM card), which
  no sourced field records.
- **Thin-evidence recent buys** (bought at the last auction, under 60 IPL balls): franchises kept 54% of
  those bought for 1 cr+ in 2019–2024 (28 players) and 86% in 2026 (7), 41% / 55% of the cheaper ones. The
  model's "bought at the last auction" term is near zero (−0.01): it treats them through their price, cost
  and forecast like anyone else, and they come out near the line (Tejasvi Singh, KKR, 3 cr on 15 balls:
  59%, Toss-up, kept by default). No special rule.

<!-- keep-example:start -->
*Worked example (IPL 2027 defaults, data to the 2026 final).* RCB's Virat Kohli: value +3.8 for the coming season (career +13.6), 38 at the auction, 16 IPL matches last season; market price 7.84 cr (13.69 in the top quarter). A 2025 retention, so keeping him costs what releasing him alone would free under the slab rule: 15 cr, against a 21 cr salary. His price is under his cost; he is home-grown and has played 19 seasons for RCB, and the forecast gives him a 55% chance of being a regular in its third season: franchises kept **97%** of players like him, so **Keep**.
<!-- keep-example:end -->

**The reality table: 25 marquee players** (2027 defaults; market median / upper quartile, cr; cost = what
keeping him takes from the purse; P = the chance a franchise keeps a player like him):

<!-- keep-reality:start -->
| player | team | salary | cost | market | P | call | what the franchise did |
|---|---|---|---|---|---|---|---|
| Virat Kohli | RCB | 21 | 15 (slab) | 7.84 / 13.69 | 97% | Keep | Retained 2025 (21 cr), kept for 2026 |
| Rohit Sharma | MI | 16.3 | 14 (slab) | 4.98 / 9.36 | 68% | Keep | Retained 2025, kept for 2026 |
| Suryakumar Yadav | MI | 16.35 | 14 (slab) | 9.17 / 15.65 | 96% | Keep | Retained 2025, kept for 2026 |
| Jasprit Bumrah | MI | 18 | 14 (slab) | 13.42 / 21.22 | 99% | Keep | Retained 2025, kept for 2026 |
| Shubman Gill | GT | 16.5 | 11 (slab) | 23.09 / 33.22 | 100% | Keep | Retained 2025, kept for 2026 (captain) |
| Rishabh Pant | DC | 15 | 15 | 17.61 / 27.1 | 98% | Keep | Bought 27 by LSG (2025); traded back to DC at 15 (June 2026) |
| Ravindra Jadeja | RR | 14 | 14 | 8.68 / 14.82 | 91% | Keep | Retained by CSK 2025; traded to RR for 2026 |
| MS Dhoni | CSK | 4 | 4 | 0.78 / 1.93 | 48% | Toss-up (released) | Retained 2025 (uncapped, 4 cr), kept for 2026; did not play in 2026 |
| Rinku Singh | KKR | 13 | 11 (slab) | 6.54 / 11.89 | 96% | Keep | Retained 2025, kept for 2026 |
| Tejasvi Singh | KKR | 3 | 3 | 0.65 / 1.76 | 47% | Toss-up (released) | Bought 3 cr at the 2026 auction; 15 IPL balls |
| Hardik Pandya | MI | 16.35 | 14 (slab) | 13.56 / 21.63 | 89% | Keep | Retained 2025, kept for 2026 (captain) |
| Tilak Varma | MI | 8 | 8 | 11.86 / 19 | 99% | Keep | Retained 2025, kept for 2026 |
| Abhishek Sharma | SRH | 14 | 14 | 17.22 / 26.59 | 100% | Keep | Retained 2025, kept for 2026 |
| Yashasvi Jaiswal | RR | 18 | 18 | 12.74 / 20.9 | 99% | Keep | Retained 2025, kept for 2026 |
| Shreyas Iyer | PBKS | 26.75 | 26.75 | 17.53 / 26.98 | 96% | Keep | Bought 26.75 (2025), kept for 2026 (captain) |
| KL Rahul | DC | 14 | 14 | 10.05 / 16.68 | 96% | Keep | Bought 14 (2025), kept for 2026 |
| Axar Patel | DC | 16.5 | 14 (slab) | 18.9 / 28.06 | 98% | Keep | Retained 2025, kept for 2026 (captain) |
| Sanju Samson | CSK | 18 | 18 | 9.13 / 15.66 | 94% | Keep | Retained by RR 2025; traded to CSK for 2026 |
| Ruturaj Gaikwad | CSK | 18 | 14 (slab) | 10.18 / 17.24 | 98% | Keep | Retained 2025, kept for 2026 (captain) |
| Rashid Khan | GT | 18 | 11 (slab) | 12.5 / 19.93 | 98% | Keep | Retained 2025, kept for 2026 |
| Pat Cummins | SRH | 18 | 14 (slab) | 13.12 / 20.82 | 75% | Keep | Retained 2025, kept for 2026 (captain) |
| Heinrich Klaasen | SRH | 23 | 14 (slab) | 10.66 / 17.94 | 95% | Keep | Retained 2025 (23 cr), kept for 2026 |
| Cameron Green | KKR | 25.2 | 25.2 | 9.21 / 15.91 | 88% | Keep | Bought 25.2 at the 2026 auction (paid 18) |
| Vaibhav Suryavanshi | RR | 1.1 | 1.1 | 9.92 / 14.77 | 100% | Keep | Bought 1.1 (2025), kept for 2026 |
| Arshdeep Singh | PBKS | 18 | 18 | 10.75 / 17.86 | 94% | Keep | Bought back 18 with an RTM (2025), kept for 2026 |

23 of the 25 are kept by default: not kept, MS Dhoni (48%, 0 IPL matches last season); Tejasvi Singh (47%, 2 IPL matches last season).
<!-- keep-reality:end -->

The old stars are kept through what the model sees (a 2025 retention, the home side, many seasons, a full
last season) rather than their price, which is a fraction of their cost. What it can't see (a following, a
place in the leadership) would push them further up; a season missed pushes a player down, which is why a
star who didn't play in 2026 can fall to a toss-up. A player the data has barely seen stays near the line,
the honest reading for a buy it can't judge.

The default calls (P = the chance kept; the default plan releases below 50%), legal after step 7:

<!-- keep-calls:start -->
- **CSK** (17 kept, 13.65 cr left): release Matthew Short (12%), Matt Henry, Spencer Johnson, Dian Forrester, Nathan Ellis, Zak Foulkes, Shreyas Gopal, Kuldip Yadav, Aman Khan, Akash Madhwal, Ramakrishna Ghosh, MS Dhoni, Macneil Noronha (49%). Toss-up, kept: Akeal Hosein, Rahul Chahar, Jamie Overton.
- **DC** (18 kept, 24.3 cr left): release Kyle Jamieson (19%), Dushmantha Chameera, Karun Nair, Rehan Ahmed, Ajay Mandal, Mitchell Starc, Tripurana Vijay (48%). Toss-up, kept: David Miller, Prithvi Shaw, Auqib Nabi, Zeeshan Ansari, Madhav Tiwari.
- **GT** (16 kept, 10.75 cr left): release Luke Wood (24%), Tom Banton, Connor Esterhuizen, Kulwant Khejroliya, Glenn Phillips, Jayant Yadav, Ishant Sharma, Y Prithvi Raj, Gurnoor Brar, Anuj Rawat, Kumar Kushagra (46%). Toss-up, kept: R Sai Kishore, Arshad Khan, Jason Holder, Manav Suthar.
- **KKR** (14 kept, 39.95 cr left): release Tim Seifert (28%), Blessing Muzarabani, Rachin Ravindra, Navdeep Saini, Rahul Tripathi, Matheesha Pathirana, Rovman Powell, Akash Deep, Sarthak Ranjan, Umran Malik, Luvnith Sisodia, Tejasvi Singh, Prashant Solanki (48%). Toss-up, kept: Daksh Kamra, Manish Pandey.
- **LSG** (19 kept, 25.8 cr left): release Anrich Nortje (21%), Shahbaz Ahmed, George Linde, Matthew Breetzke, Arjun Tendulkar, Wanindu Hasaranga, Himmat Singh (49%). Toss-up, kept: Naman Tiwari, Akash Singh, Akshat Raghuwanshi, Arshin Kulkarni, Aiden Markram.
- **MI** (21 kept, 14.65 cr left): release Keshav Maharaj (24%), Quinton de Kock, Trent Boult, Mahipal Lomror, Mohammad Izhar, Mayank Rawat, Ruchit Ahir, Atharva Ankolekar (50%). Toss-up, kept: Corbin Bosch, Robin Minz, Mitchell Santner, Sherfane Rutherford, Raj Bawa, Danish Malewar, Mayank Markande, Ashwani Kumar, Shardul Thakur, Krish Bhagat, Will Jacks.
- **PBKS** (17 kept, 18.45 cr left): release Ben Dwarshuis (18%), Lockie Ferguson, Vishnu Vinod, Yash Thakur, Mitchell Owen, Praveen Dubey, Azmatullah Omarzai, Pyla Avinash (47%). Toss-up, kept: Harnoor Pannu, Vishal Nishad, Marcus Stoinis, Xavier Bartlett, Musheer Khan.
- **RCB** (17 kept, 12.4 cr left): release Richard Gleeson (23%), Nuwan Thushara, Jordan Cox, Swapnil Singh, Jacob Duffy, Romario Shepherd, Mangesh Yadav, Satvik Deswal, Abhinandan Singh (49%). Toss-up, kept: Vicky Ostwal, Jacob Bethell, Kanishk Chouhan, Vihaan Malhotra.
- **RR** (17 kept, 12.2 cr left): release Adam Milne (17%), Sam Curran, Dasun Shanaka, Kwena Maphaka, Vignesh Puthur, Yudhvir Singh, Ravi Singh, Kuldeep Sen, Lhuan-dre Pretorius, Sushant Mishra (50%). Toss-up, kept: Tushar Deshpande, Emanjot Chahal, Aman Rao, Shubham Dubey.
- **SRH** (19 kept, 20.2 cr left): release Liam Livingstone (19%), Brydon Carse, David Payne, Jack Edwards, Kamindu Mendis, Dilshan Madushanka, Gerald Coetzee, Shivam Mavi, Amit Kumar, Jaydev Unadkat (48%). Toss-up, kept: Harshal Patel, Onkar Tarmale, Krains Fuletra, RS Ambrish.

175 of the 271 are kept by default (65%; franchises kept 69% in 2026). The releases are what franchises release in a mini year: overseas squad players, the young uncapped who didn't play, the old who stopped playing.
<!-- keep-calls:end -->

**Limits.** The model says what franchises do, not what is optimal: it inherits their habits (the
overseas discount, loyalty to their own players), and a franchise that wants to beat the others needs the
value-per-crore view of Bid plan as well. It sees no fitness, no brand or following, no captaincy plans for
next season, no player's wish to leave; 2025's departed captains (Pant, KL Rahul, Shreyas Iyer) are its
misses. Mega-year calls are a ranking (the limits on how many may be kept change by cycle). The market
price behind it is still off by a factor of about 1.9 on a typical player (section 6b). The likely pool is
our guess at what other teams release. The 2025 retention slabs are assumed to carry into 2027. Nineteen
squad players aren't in the ball-by-ball data and can't be rated: their price is a market prior for a
typical uncapped Indian, not a judgement of the player.

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

## 12. Bid plan (draft)

> **Draft: where it stands (2026-10-30).** Replayed with only what was known before each auction, the plan
> spends what real teams spend (spend error 0.075 of the purse at the 2024 auction) and its max bids now mean
> something (the opportunity money rule, step 4 below). Its squads beat the real franchises' on the next
> season for 7 of 10 teams at the 2024 auction (full purse, the year the rule was checked on), but only 2 of 10
> in 2025 and 1 of 10 in 2026 at the real team's spend; those two seasons have been looked at many times while
> building it. The rule that leaves money unspent ("none") builds stronger squads in 2025 (6 of 10) but misses
> what teams spend by two to three times as much; the plan follows the rule that spends like a franchise, and
> the replay tables below are the evidence. Two known gaps: a few cheap batters with a thin IPL record are
> overrated (B15), and each sheet is planned as if the other nine weren't chasing the same names (rival plans
> don't settle, step 4). It is an exploration tool, not a verdict. The earlier re-runs are kept below as
> history.

**What it does.** Before the auction (IPL 2027: likely 16 December 2026), a franchise needs a sheet: whom to
bid for, how high, and what to do when a target goes for more. Bid plan takes the squad and purse a team
brings in (Keep or release's plan, section 10, with the user's own keep / release calls carried in the
link; its purse left is the purse less what the kept players cost, 2025 retentions by the slabs, since
2026-10-22), the competition's rules and the auction pool, and returns a priority list of targets, each with the
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
2). Keep or release keeps every Toss-up player, so its plans leave few places (19 across the league for
2027); real teams clear room before a mini auction. So each plan opens **at least 8 places** (the median
number of players a team bought at the 2023, 2024 and 2026 mini auctions), releasing its lowest-valued
players first (an unrated one first; a player the user decided on is never moved). The number is editable;
0 gives Keep or release's plans exactly. When the official auction list is published,
`data/curated/ipl_auction_register.json` (`[{"id": cricsheet id, "base_price": cr}]`) replaces this guess:
the export copies it to `auction_register.json`, and the page and the CLI use exactly those players at their
real base prices.

**2. What rivals would pay.** The other nine franchises, each with its own plan's squad and purse, bid in the
Auction room's simulator 200 times, by its **demand model fitted on real auctions** (section 7: whether a team
bids at all and how high, from its places short in his role, its overseas places, its purse per place, the
upgrade he'd be, the money across the market, the stage, his market, base and last price, the heat of the
day; since 2026-10-23, replacing the personalities and the calibrated level, curve, anchor, shock and
tightness). The lots are as many as real shortlists hold for the open places (section 7). For each player sold
in a run, the price **we would have to beat** is one IPL ladder step above the winning rival's bid (a rival
bids at most what his purse allows; until 2026-10-23, his bid × 1.02); a player no rival bid for (or not among
the simulator's lots) costs his base price. We are a price-taker: our own buys don't change what the rivals
do in a run.

**3. Squad strength**, in runs a match above replacement (since 2026-10-22, audit items 6 and 8; section 6c;
the depth and needs since 2026-10-23):

```
strength = best XI + bench
best XI  = s_bat × Σ P × batting contribution + s_bowl × Σ P × bowling contribution
s_bat    = min(1, 115 ÷ the XI's expected balls faced a match),  s_bowl the same for balls bowled
P        = his P(plays) (6c): in his squad for a kept player; as a free agent for the auction's lots
bench    = the XI's missed appearances, Σ over the XI of (1 − P), filled by the bench in order of the
           contribution a match each makes when he plays: at most one appearance a match for a squad
           player, at most his P(plays) for an auction lot
```

- **Best XI**: 12 players since 2026-10-27 (11 before): the XI and the impact player, who has taken part
  in every IPL match since 2023 (11.95–11.97 players a side a match in Cricsheet's lists for 2023–26,
  11.0 in every season before; section 6c, *the impact-player era*). Every plan, the 2025 and 2026
  replays included, is an impact-era season. At most 4 overseas (the impact player must be Indian when
  the XI has four), at least one keeper, five bowling options (bowlers and all-rounders) and six batting
  options (batters, keepers, all-rounders); the side's balls stay held to an innings, so the twelfth man
  adds what he does in his share of them, not a 12th set of balls. Each counts his **expected
  contribution per match**: his batting value less a replacement batter's for his slot, at the balls he faces
  a match, plus his bowling value less a replacement bowler's, at the balls he bowls (6c), × his P(plays).
  For a lot (a free agent, or a player another plan releases) P is the free-agent model's: the chance players
  like him play an IPL match at all. That is what keeps long-gone veterans (Nabi, Warner, whose career
  contributions are 7–8 runs a match) off the target lists: the ratings are career-long and don't see a
  player's decline or absence; P(plays) carries the evidence that franchises stopped picking players like
  them. (Announced retirements are not left to P(plays): they are out of the pool, section 7.) It is picked
  greedily: highest expected contribution first, skipping a player who would break the overseas limit or leave too few places for the
  keeper, bowling and batting minimums. **Realistic balls**: an XI can't face or bowl more than a side's
  innings (115 legal balls, the IPL 2023–26 mean), so when its players' expected balls add up to more, every
  member's batting (bowling) part is scaled down alike; eight openers can't each face 25 balls. A place the
  squad can't fill goes to a **replacement-level** player, 0 by construction; a player at or below it never
  plays, and an unrated player counts at that level.
- **Depth**: an XI member plays P of his side's matches (the playing-time model), so the side misses him in
  1 − P of them; the bench fills those appearances, best first. The depth weight is the fitted P(plays), not
  a hand-set 0.25 on the next four (until 2026-10-23). A squad player on the bench can fill a whole
  appearance a match (his P(plays) is the chance he's picked ahead of the others, so he plays when one is
  missing); an **auction lot fills at most his P(plays)** of one (since 2026-10-23, audit item 8, follow-up): his
  free-agent P is how often players like him play at all, on the bench as in the XI. Before, every bench
  player gave a whole appearance at his full contribution, so a free agent with P 0.04 and a career
  contribution of 7 runs a match (David Warner, 40) added about 4–5 runs a match from the bench alone and
  sat near the top of the lists with max bids of 16–19 cr (Sarthak Ranjan, the same way plus the
  missing-position slip of 6c, was CSK's, DC's and RCB's first target); with the cap Warner adds about 0.2
  and is at most a low fallback.
- **Role needs**: keepers (2), openers (3), death bowlers (3), spinners (3), pace bowlers (4), editable; the
  plan reports how often each is met and what's missing, but a place short no longer costs strength (the
  hand-set 0.63 runs a match a place is gone, audit item 8): the XI's rules (a keeper, five bowling and six
  batting options, four overseas) carry the balance that matters to the score.
- **What filling a role still short costs** (since 2026-10-30). A franchise expects the sheet
  to act on its gaps; rather than put a hand-set penalty back, the sheet prices each one (`gap_costs` ⇄
  `gapCosts`, parity-tested). For each role the likely buys leave short, up to three of its targets who fill
  it (priority order, not already a likely buy or overridden) are each taken as bought at his usual price
  (the median price to beat over the runs): he joins the squad, the price leaves the purse, and the plan is
  rebuilt around him with the same runs. The one leaving the most strength is shown with his usual price,
  the price that lands him in 9 runs of 10, how often the role is then met, and the strength the rebuilt plan
  gives up (or gains) against the plan as it stands. On the 2027 sheets the gaps are cheap at the usual
  price (RCB's third spinner: Mujeeb Ur Rahman, usually 4 cr, the plan around him 0.25 runs a match
  stronger; GT's second keeper: Ben Cliff at 0.3 cr, 0.04 weaker), and dear to be sure of (Mujeeb 13.8 cr
  in 9 runs of 10): the gap is a price risk more than a strength cost. On the page it runs on request (each
  try rebuilds the plan); the CLI prints it whenever a role is short.

Until 2026-10-22 strength added the XI's per-100-ball values, as if a No. 7 faced as many balls as an
opener and a four-over bowler counted like a 25-ball batter, with a −15 replacement level and the better
role only for an all-rounder. λ's grid moved with the unit (0.05 … 3.2 runs a match per crore, the old
0.25 … 16 at the same 0.209), so the crore figures are on the same scale.

A player's **gain** is strength with him minus strength without him.

**4. The bidding rule and the exchange rate λ.** In each rival run the lots come up in pool order (stars
first). For each, bid up to **gain ÷ λ** (λ = runs of strength per crore) and buy him when that reaches the
price to beat, the purse allows (keeping 0.3 cr for each place still needed to reach the squad minimum) and
there is squad and overseas room. A user's max bid replaces gain ÷ λ for that player (0 = never bid). The
gain is measured on the squad so far **plus the likely buys still to come**, so an early lot isn't overpaid
while a cheaper fit comes later, and if a likely buy goes elsewhere his substitutes bid higher. "Likely buys"
are the players the rule lands in at least half the runs; the rule is re-run with them until they stop
changing (at most four rounds, usually two or three). λ is chosen from 25 rates (0.05 to 3.2 runs a match per crore, ×2^¼ apart) as
the one whose rule gives the **highest mean strength over the 200 runs** (rules "none" and "market" below; the
shipped rule "auction" replaces the single λ with a crore's worth at each lot) (a sample-average optimisation;
ties go to the higher rate). A low λ (a big purse for the places left) bids generously; a high one waits for
bargains.

**What an unspent crore is worth** (since 2026-10-27, ROADMAP I17b). Money left after an IPL auction
buys nothing for the season being planned. A replacement player's fee can't exceed the fee of the player he
replaces, and it sits outside the salary cap
([CricTracker, IPL 2025 replacement rules](https://www.crictracker.com/cricket-news/ipl-2025-bcci-new-replacement-rules-special-clause-wicketkeepers/)).
**This is an assumption**: one press article is the only source found; the 2025–27 regulations as
published on iplt20.com don't state it (checked 2026-10-29). The money rules below rest on it.
Unspent purse carries into the next auction only through the cap: a team's purse is the cap less its
contracts, which reproduces every published 2026 purse (KKR 64.3, CSK 43.4, MI 2.75 cr;
[Wisden](https://wisden.com/series/ipl-2026/cricket-news/ipl-2026-auction-all-you-need-to-know-start-time-rules-squads-purses-slots-and-more)).
It does so only within a cycle, and the next cycle's format is not yet announced. So a crore is worth only
what it can still buy **later in the same auction**.

At each lot the plan ranks the lots still to come by gain ÷ expected price. Each lot's gain is measured on
the likely squad, which gives diminishing returns; his expected price is the rivals' median price to beat,
from the fitted demand model. The money and the squad places left are then filled down that ranking:

- If the money runs out first, a crore is worth λ, the ratio of the first lot the money no longer covers,
  and a place costs nothing.
- If the places run out first, a crore is worth 0, and a place is worth the smallest gain among the lots
  that would fill them.
- If neither runs out (always so at the last lot), both are worth 0.

A lot is bought up to (gain − the place's worth) ÷ λ, or up to what the purse allows when λ = 0. There is no
single λ for the whole auction any more, and no grid. The page shows λ at the first lot (`_MoneyValue`,
`web_parity/bidplan.py` ⇄ `MoneyValue`, `site/src/lib/bidplan.ts`).

*How the rule was chosen* (declared 2026-10-27 before any number). The calibration target was the share of its
purse each real team spent (`ipl_auction_history.json`, the same purse arithmetic as above):

- Mini auctions 2018–2026 (54 team-auctions): median 0.76, 10–90% 0.41–0.98. By year: 2023 0.76, 2024 0.90,
  2026 0.84.
- Mega auctions (28): median 0.99.
- The share hardly depends on the purse left or the open places (rank correlation 0.11 and −0.07 in the
  minis). Teams buy about as many players as they have places (median bought ÷ open 1.0).

Three rules were replayed on the 2024 auction (validation), each team's plan built with its real purse:

| rule | plan's expected spend ÷ purse: median (mean abs. error per team vs real) | at the real prices | next season vs the real squad, full purse |
|---|---|---|---|
| none: one λ, an unspent crore worth nothing (until 2026-10-26) | 0.38 (0.46) | 0.12 (0.72) | −1.5 runs a match, ahead for 5 of 10 |
| market: one λ, a crore worth the rivals' runs per crore (2026-10-26) | 0.09 (0.72) | 0.08 (0.78) | −4.6, 2 of 10 |
| **auction: what a crore can still buy later in the auction (chosen)** | **0.97 (0.11)** | 0.55 (0.35) | **+3.1, 8 of 10** |
| real teams | 0.90 | | |

*The test, run once on 2025 and 2026 with the chosen rule*:

| | 2025 mega | 2026 mini |
|---|---|---|
| spend ÷ purse, real / plan's expected (MAE) | 1.00 / 0.99 (0.010) | 0.84 / 0.98 (0.109) |
| for reference, rule "none" | 0.84 (0.168) | 0.72 (0.149) |
| next season, same spend: plan's squad stronger than the real one | **2 of 10 (−5.1 runs a match)** | **0 of 10 (−3.2)** |
| for reference, rule "none" | 7 of 10 (+4.3) | 5 of 10 (+0.4) |

The rule matches what real teams spend. The squads it builds were weaker the next season, in both test
years, than the old rule's.

*After the test, one logic fix, so the numbers below are **seen twice***. The first version valued money
but not squad places. When places ran out before money, a crore was worth 0 and any lot with a positive gain
could be bought up to the purse, even if it pushed a better later lot out of the squad. The place's worth
(the gain of the lot it would push out) was added. This is a missing term in the rule, not a tuned number,
and nothing else changed. On 2024 it gave spend 0.95 (MAE 0.10) and +2.1 runs a match (8 of 10). On
2025–26, **seen twice**:

- spend 0.99 (MAE 0.012) and 0.97 (MAE 0.085);
- next season at the same spend, 2 of 10 (−4.7) and 0 of 10 (−3.5).

So the place term didn't change the outcome. **Reading.** On the calibration target the chosen rule matches
the real franchises: it spends what they spend, where the old rules left 30–90% of the purse unspent. On next
season's output it loses to them and to the old rule. With money worth nothing at the end, the plan spends
on whatever adds anything, and the strength model sees little between the players a mini auction sells (a
lot's contribution carries his free-agent P(plays), mostly 0.02–0.2). Both rules stay in the code
(`plan(money=...)`, `bidplan_backtest.py --money`). Which one ships is a product call, and the replay numbers
above are the evidence for it.

*Correction, 2026-10-27 (I18).* The replays had scored the "auction" rule wrongly.
`follow_plan`, which plays a finished plan against the real prices, replayed it with the plan's λ alone.
Under this rule λ is 0, so it bought every lot with a positive gain at any real price. The fixed replay
gives the rule the same money value the plan used. These numbers are **seen three times**:

| | 2024 | 2025 | 2026 |
|---|---|---|---|
| expected spend error | 0.104 | 0.012 | 0.085 |
| next season at the same spend: stronger than the real squad | 6 of 10 (+1.4) | 3 of 10 (−3.9) | 0 of 10 (−3.1) |

(2024 is at full purse.) The conclusion doesn't change: the rule spends like the franchises and builds
weaker squads than they do.

*Re-run with the time-aware values (section 4b), 2026-10-27.* Replay inputs rebuilt (`auction_demand_fit.py
inputs` / `mk` on the new as-of contributions and the price recipe Z), both rules, 200 runs. 2024 is the
validation (full purse); **2025–26 have now been seen four times**, so they are no longer a clean test:

| rule | 2024: spend error; stronger than the real squad | 2025: spend error; same spend, stronger | 2026 |
|---|---|---|---|
| "auction" (shipped), time-aware + calibrated values (4c; 2025–26 seen five times) | 0.103; 5 of 10 (−0.5) | 0.013; 1 of 10 (−6.3) | 0.091; 0 of 10 (−2.7) |
| "auction", time-aware values | 0.102; 5 of 10 (+0.2) | 0.011; 1 of 10 (−4.1) | 0.093; 0 of 10 (−2.7) |
| "auction", career values (the corrected replay above) | 0.104; 6 of 10 (+1.4) | 0.012; 3 of 10 (−3.9) | 0.085; 0 of 10 (−3.1) |
| "none", time-aware + calibrated values | 0.230; 7 of 10 (+0.7) | 0.173; 6 of 10 (+2.0) | 0.208; 5 of 10 (−0.7) |
| "none", time-aware values | 0.308; 7 of 10 (+0.9) | 0.174; 8 of 10 (+4.2) | 0.213; 5 of 10 (+0.3) |
| "none", career values (before the replacement curves) | 0.456; 5 of 10 (−1.5) | 7 of 10 (+4.3) | 5 of 10 (+0.4) |

(Spend error: mean absolute difference between the plan's expected spend and the real spend, as shares of
the purse, full-purse plans. Next season: runs a match above replacement, plan against the real squad.)
**The ranking of the two rules doesn't change**: "auction" spends like the franchises (error 0.01–0.10
against 0.17–0.31), "none" builds the stronger next-season squads (now ahead in 2024 too). The time-aware
values moved neither rule much: "auction" a little worse in 2024–25 and a little better in 2026, "none" a
little better in 2024. Which rule ships stays a product call. With the calibration of 4c (whose refitted
replacement levels also move the next-season scoring) the ranking holds again: "auction" 0.01–0.10 spend
error, 1 and 0 of 10; "none" 0.17–0.23, 6 and 5 of 10.

*The opportunity rule ships (2026-10-30; rule declared before the replays).* A review
of the 2027 sheets found that "auction" fails on its own terms: when the places run out before the money a
crore is worth 0, every max bid becomes the purse left (CSK 4.34 cr on every row), and the replay buys
players far above their own max bid (LSG: Gurbaz at 13.49 cr against a max bid of 0). "opportunity" values a
lot at what it adds minus what paying for it gives up: the later lots its money *and* its place (overseas
places counted) would have bought, so a max bid is finite. Declared: it ships if on the 2027 plans no likely
buy is paid above his max bid and the max bids differ, and if on 2024 its spend error is at most "none"'s and
its next season no more than 2 runs a match behind "auction"'s. Replay inputs rebuilt on today's data (price
recipe BH), 200 runs:

| rule | 2024: spend error; next season vs the real squad | 2025 (seen): same spend, next season | 2026 (seen) |
|---|---|---|---|
| **opportunity (shipped)** | **0.075; +6.1, 7 of 10** | −6.6, 2 of 10 | −3.0, 1 of 10 |
| auction (until now) | 0.106; +3.8, 6 of 10 | −3.3, 4 of 10 | −2.5, 2 of 10 |
| none | 0.261; +5.4, 7 of 10 | +4.8, 6 of 10 | −2.5, 1 of 10 |

On the 2027 plans: no likely buy above his max bid, 20-26 different max bids a sheet, squads of 24-25,
every plan converged. Both parts pass, and `MONEY` is "opportunity" (Python ⇄ TS). On the seen years it
still builds weaker squads than the real teams, like "auction"; "none" stays the strongest-squad rule, at a
spend error two to three times larger.

**What it exposed (B15, open).** Under it a cheap player who is sure to be landed ranks by his gain, and
Mayank Rawat (base price, rated −14.3) is first on 7 of 10 sheets, failing the reality gate's minimum-price
check (now marked open). The cause: his usual batting position is the median of his one 2026 IPL match (he
came in at No. 8 and faced no ball), while his expected balls come mostly from a batter's mean (14 a
match), so he is credited top-order balls against a No. 8's replacement level (−46.5): +2.45 runs a match.
27 of the 600 pool players are rated below −10 with a contribution above +0.5 (Sanvir Singh, Himmat Singh,
Atharva Taide are likely buys on 9-10 sheets). Declared fix, tried and **rejected**: the position blended
exactly as the balls are (the balls model's own weights, nothing fitted), the whole playing-time refit run
both ways. On the declared check, what 2024's buys added against their expected contribution, it was worse
(squared error 6.44 against 6.23, n 55; the bar was 1%); on 2025 and 2026 it was better (7.24 / 4.90
against 7.34 / 5.34), which was not the rule. The shipped playing-time model is unchanged
(`playing_time.POSITION` keeps the option, off).

*Rival plans tried again under the opportunity rule (2026-10-30; declared: on if the rival table converges
in its 3 rounds and every plan check passes).* They don't: after 3 rounds the table is still moving, GT's
plan doesn't converge, and with the plans chasing each other the top max bids climb back to the purse left
(CSK's for Mitchell Santner is all of its 13.7 cr). One check did improve: no player was a likely buy on more
than 3 sheets (without them Atharva Taide and Sanvir Singh are on all 10). They stay off.

*I2, the plans seeing each other (2026-10-27, built and switched off).* Each franchise's default plan is
built against the latest plans of the others (`rival_plan_bids`, in team order, repeated). In each rival
run, a rival chases each of its own targets up to its max bid, in the share of runs its plan lands him
(`_apply_rival_plans`, Python ⇄ TS, parity-locked; the export's `bidplan_rivals.json`). It does not work
with this money rule. Most max bids are the purse left (λ = 0), so the plans bid each other's targets up to
10–15 cr: Fraser-McGurk's price to beat reached 13–15 cr and Manish Pandey's 11. Three passes didn't
converge. The sheets still share the same names, now at those prices. The rival plans need max bids that
measure value. It is switched off (`export_site.BIDPLAN_RIVAL_PLANS = False`).

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
- **Max bid** = his worth to the squad: his gain to the likely squad (without him) ÷ λ, capped at what the
  purse leaves after the other likely buys at their average prices (marked "purse"; the 27 cr record cap
  was dropped on 2026-10-22). In an open
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

*The 2027 sheets (defaults: 125 cr assumed, 8 places opened, 200 runs, the opportunity money rule; data
to the 2026 final). Generated from the exported data by `scripts/bidplan_sheets.py`; the reality gate fails
when this table and the site differ.* Top five targets, each with his age, as what rivals usually pay → max
bid (cr); "rel." = released by that team's default plan:

<!-- bidplan-sheets:start -->
| team (kept, purse left, expected spend = share) | top five targets | still short of |
|---|---|---|
| CSK (17, 13.65, 12.91 = 95%) | Mayank Rawat (MI rel.), 27 0.3 → 0.95; Himmat Singh (LSG rel.), 30 0.3 → 1.05; Lhuan-dre Pretorius (RR rel.), 20 9.8 → 11.25; Jake Fraser-McGurk, 24 8 → 3.8; Atharva Taide, 26 0.3 → 1 | nothing |
| DC (17, 26.3, 25.47 = 97%) | Matheesha Pathirana (KKR rel.), 23 18.4 → 25.4; Mayank Rawat (MI rel.), 27 0.3 → 0.85; Jake Fraser-McGurk, 24 8.2 → 4; Lhuan-dre Pretorius (RR rel.), 20 9.6 → 8.5; Atharva Taide, 26 0.3 → 0.8 | nothing |
| GT (16, 10.75, 10.15 = 94%) | Mayank Rawat (MI rel.), 27 0.3 → 0.9; Jake Fraser-McGurk, 24 8.2 → 4.25; Lhuan-dre Pretorius (RR rel.), 20 10.2 → 9.05; Himmat Singh (LSG rel.), 30 0.3 → 1.05; Atharva Taide, 26 0.3 → 0.85 | Wicketkeepers |
| KKR (14, 39.95, 38.72 = 97%) | Mayank Rawat (MI rel.), 27 0.3 → 1.05; Lhuan-dre Pretorius (RR rel.), 20 10 → 18.95; Jake Fraser-McGurk, 24 7.8 → 5.35; Himmat Singh (LSG rel.), 30 0.3 → 1.35; Atharva Taide, 26 0.3 → 1.3 | Wicketkeepers |
| LSG (17, 27.1, 25.87 = 95%) | Mayank Rawat (MI rel.), 27 0.3 → 1.25; Matheesha Pathirana (KKR rel.), 23 18.6 → 25.7; Jake Fraser-McGurk, 24 8.4 → 4.5; Atharva Taide, 26 0.3 → 1.35; Mitchell Santner (MI rel.), 34 12.4 → 5.7 | nothing |
| MI (17, 20.65, 19.92 = 96%) | Lhuan-dre Pretorius (RR rel.), 20 9.8 → 9.1; Matheesha Pathirana (KKR rel.), 23 18.6 → 20; Atharva Taide, 26 0.3 → 0.85; Himmat Singh (LSG rel.), 30 0.35 → 0.85; Jake Fraser-McGurk, 24 8.4 → 5 | nothing |
| PBKS (17, 18.45, 17.81 = 97%) | Mayank Rawat (MI rel.), 27 0.3 → 0.85; Jake Fraser-McGurk, 24 8 → 3.55; Himmat Singh (LSG rel.), 30 0.3 → 0.8; Atharva Taide, 26 0.3 → 0.85; Matheesha Pathirana (KKR rel.), 23 20.4 → 17.05 | Wicketkeepers |
| RCB (17, 12.4, 11.8 = 95%) | Mayank Rawat (MI rel.), 27 0.3 → 0.85; Jake Fraser-McGurk, 24 9 → 3.5; Mitchell Santner (MI rel.), 34 13.8 → 5; Lhuan-dre Pretorius (RR rel.), 20 10.8 → 10; Atharva Taide, 26 0.3 → 0.85 | Spinners |
| RR (17, 12.2, 11.52 = 94%) | Jake Fraser-McGurk, 24 9 → 4.6; Mayank Rawat (MI rel.), 27 0.3 → 1.15; Mitchell Santner (MI rel.), 34 13.8 → 7.2; Himmat Singh (LSG rel.), 30 0.4 → 0.9; Atharva Taide, 26 0.3 → 0.9 | nothing |
| SRH (17, 28.5, 27.58 = 97%) | Mayank Rawat (MI rel.), 27 0.3 → 0.95; Matheesha Pathirana (KKR rel.), 23 18.6 → 26.6; Jake Fraser-McGurk, 24 6.8 → 3; Atharva Taide, 26 0.3 → 0.95; Himmat Singh (LSG rel.), 30 0.3 → 0.85 | Spinners |
<!-- bidplan-sheets:end -->

The max bids now differ down a list (with "auction" they were the purse left on every row) and the plans
spend 94–97% of their purse left, inside the real range. What the sheets get wrong is B15 above: a few cheap
batters with a thin IPL record (Mayank Rawat, Himmat Singh, Atharva Taide) lead or fill most sheets at
the base price, and the gate's minimum-price check is marked open. Matheesha Pathirana (KKR's release) is
the dearest target, with max bids of 25–27 cr on DC's, LSG's and SRH's sheets, nearly all their purse left:
each sheet is planned without the others' (rival plans off, above). **Mustafizur Rahman** is in the pool, flagged on the
page: whether Bangladesh players may be bought for 2027 is unreported (the BCCI had KKR release him in
January 2026; no statement on 2027 found by 2026-10-26).

*With the buy model on* (6c, `BIDPLAN_BUY_MODEL`, checked again after 4c and left off): Chirag Jani (37, never
played the IPL) is first on six sheets, Mohammad Nabi (42) on three, Jonny Bairstow on one; Warner, Rahul Singh,
Pallav Kumar Das and Ben Cliff fill the top fives. Both first-target checks fail (Jani on six against at most
3.4, and a minimum-price player first on most). Under rule "none" Nabi is first on six. The calibration
shrinks every value by the same quarter, so it doesn't change who leads; section 4c explains why a fitted
calibration can't see these players.

Before 2026-10-27 (`git show d76eb88a0:docs/METHODOLOGY.md`), David Miller (DC rel.) was the first target
on six of ten sheets. Before 2026-10-26 (`git show 553cfc428:docs/METHODOLOGY.md`), Ramandeep Singh (KKR rel.) was the first
target on 9 of 10 sheets, rated −37 runs per 100 balls at a usual position of 7.5 and measured against the
8–11 group's −61.6. On the position curve his contribution is 0.5 runs a match and he is in no top five.
Before the fixes of 2026-10-23, these sheets put Sarthak Ranjan first for CSK, DC and RCB at 8–17 cr and
David Warner (40) at 16–19 cr; the pool still held Bravo, Dinesh Karthik, Amit Mishra, Shikhar Dhawan and
Rayudu, all retired.

**Validation 1: rival prices against real ones.** On the 2025 mega and 2026 mini auctions, out of time (the
inputs of `scripts/bidplan_backtest.py`, below), the median price to beat from a team's nine rivals for each
player that team really bought, against what it paid (the hand-set rivals with the calibration of 2026-10-22 →
the fitted demand model, round 2, of 2026-10-23):

| | 2025 | 2026 |
|---|---|---|
| lots | 173 | 64 |
| median real ÷ price to beat | 1.11 → **1.00** | 1.00 → **1.00** |
| error, mean abs. ln | 0.61 → **0.63** (market price alone 0.62) | 0.69 → **0.68** (0.77) |
| rank correlation | 0.79 → **0.80** | 0.47 → **0.52** |
| real price inside the rivals' 20–80% range (60% = calibrated) | 49% → **65%** | 53% → **64%** |

The simulator's own clearing prices against reality (all ten teams bidding) are in section 7.

*Reality check: well-known lots* (real price; the rivals' price to beat for the team that bought him, median
and 20–80% range; market price):

| auction | player | real | rivals' price to beat | market |
|---|---|---|---|---|
| 2025 | Rishabh Pant | 27.00 | 18.0 (8.5–35.4) | 21.5 |
| 2025 | Shreyas Iyer | 26.75 | 16.0 (8.2–38.0) | 14.5 |
| 2025 | Venkatesh Iyer | 23.75 | 4.0 (2.0–8.8) | 3.4 |
| 2025 | Arshdeep Singh | 18.00 | 17.4 (7.0–40.3) | 9.5 |
| 2025 | Yuzvendra Chahal | 18.00 | 13.1 (7.5–26.3) | 7.5 |
| 2025 | Jos Buttler | 15.75 | 15.5 (6.0–31.6) | 5.8 |
| 2025 | KL Rahul | 14.00 | 17.3 (8.0–32.8) | 19.8 |
| 2025 | Mitchell Starc | 11.75 | 12.5 (5.4–25.9) | 4.7 |
| 2025 | Ishan Kishan | 11.25 | 14.0 (6.0–29.8) | 10.4 |
| 2025 | Jitesh Sharma | 11.00 | 2.0 (1.0–4.8) | 3.6 |
| 2025 | Bhuvneshwar Kumar | 10.75 | 4.0 (2.0–8.6) | 3.1 |
| 2025 | Mohammed Shami | 10.00 | 13.5 (6.5–30.2) | 6.6 |
| 2025 | Prasidh Krishna | 9.50 | 11.0 (5.0–26.9) | 5.8 |
| 2025 | Liam Livingstone | 8.75 | 10.0 (4.6–23.6) | 4.8 |
| 2026 | Cameron Green | 25.20 | 22.3 (11.3–25.0) | 10.2 |
| 2026 | Matheesha Pathirana | 18.00 | 13.0 (7.5–21.4) | 8.1 |
| 2026 | Liam Livingstone | 13.00 | 13.0 (5.5–24.3) | 6.4 |
| 2026 | Ravi Bishnoi | 7.20 | 13.0 (6.0–23.0) | 9.8 |
| 2026 | Venkatesh Iyer | 7.00 | 3.4 (2.0–8.3) | 2.6 |
| 2026 | Kartik Sharma | 14.20 | 0.3 (0.3–1.5) | 0.4 |
| 2026 | Prashant Veer | 14.20 | 0.3 (0.3–2.2) | 0.5 |

(Market prices: the walk-forward recipe of each replay.) The rivals' price to beat for a star is higher than
the room's typical price (section 7) because it is the best of nine rivals' bids, not the second. Most stars
land inside the 20–80% range (Pant, Shreyas Iyer, Arshdeep, Chahal, Buttler, Rahul, Starc, Kishan, Shami,
Prasidh, Livingstone twice, Pathirana, Bishnoi, Venkatesh Iyer in 2026; Green just above it). The misses are the
market model's blind spots, which no bidding model fixes: players teams had scouted that the model barely rates
(Kartik Sharma and Prashant Veer, 14.2 each), and prices the features don't explain (Venkatesh Iyer 23.75 in
2025, Jitesh Sharma, Bhuvneshwar).

**Validation 2: the plans, replayed** (`scripts/bidplan_backtest.py --inputs <the demand fit's inputs>`, about
35–45 minutes as a scheduled task; re-run 2026-10-23 with the round-2 rivals and the P(plays) bench, and again
that evening with the bench capped at a lot's P(plays)). The season inputs were built before the
missing-position fix of 6c (it changes almost no sold lot: they all have recent matches). For each auction and franchise,
with only what was known before it: each player's contribution per match as of the auction (6c: the IPL
fitted on the matches before the auction date, blended with the other leagues' fits whose cut-off is on or
before it, his usage before it, the walk-forward balls models and replacement levels) and his P(plays) from
the squad and free-agent models fitted on the seasons before (a kept player's in his squad, a lot's as a free
agent; the squad rows' rank features are computed against the squad after that auction, a small look-ahead);
market prices from the price recipe re-fitted on the auctions before (2018–2024 for 2025, 2018–2025 for 2026);
the real retentions and purses; the pool = every player sold at that auction with a Cricsheet id at his real
base price, **plus the unsold alternatives** (recent IPL players neither retained nor bought: the P(bought)
risk set, which the plan may target but is never credited with buying); rivals bidding by the demand model
**fitted on 2019–2024** (section 7, R4), 200 runs. The plan is built with the team's real purse left and with a
purse equal to what it actually spent ("same spend"); its bidding rule is played against **the real prices** (a
player is ours if our bid reaches what he actually sold for, purse and room permitting). Squads are scored on
**what the players did in the IPL season the auction was for**, in the same measure: per role with 60+ balls,
his season value (runs per 100 balls above that season's average, `runs_value.observed_value`) less the
replacement level at the position and bowling load he actually had (the curves of 6c; until 2026-10-26 his slot or group), at the balls he got a match, × the share of
his side's matches he actually played (a role under 60 balls, or a player who didn't play, at replacement
level). The 2019–2024 auctions are replayed the same way (full purse only, market prices from the other
2018–2024 auctions) to check P(≤ max bid) before the test.

| | 2025 mega | 2026 mini |
|---|---|---|
| Same spend, next season: plan's squad stronger than the real one | **7 of 10 teams** (mean +6.5 runs a match, +5.5 best XI) | **2 of 10 teams** (mean −2.4, −2.6) |
| (the bench uncapped, round-2 rivals) | 6 of 10 (+2.5, +2.8) | 3 of 10 (−0.2, −1.6) |
| (round 1, D7 rivals) | 6 of 10 (+3.1, +3.5) | 4 of 10 (+0.1, −1.0) |
| (the replay of 2026-10-22: hand-set rivals, 0.25 depth and 0.63 needs) | 8 of 10 (+8.5, +7.8) | 0 of 10 (−4.4, −4.8) |
| The same on our own pre-auction values (circular: the plan maximises exactly this) | 10 of 10 (+12.2) | 7 of 10 (+1.4) |
| The plan's top 10 targets that team really bought | 1.0 on average | 0.8 |
| Real price ÷ rivals' median, over the plan's targets that sold | 0.88 | 0.98 |

Per team, next season (expected runs a match above replacement, realised; best XI + bench), plan / real (same
spend). 2025: CSK 25.5 / 23.7, DC 45.9 / 33.6, GT 44.7 / 52.4, KKR 40.7 / 27.1, LSG 55.5 / 33.6, MI 54.8 / 56.1,
PBKS 39.2 / 35.3, RCB 37.7 / 42.9, RR 38.4 / 27.5, SRH 51.8 / 37.1. 2026: CSK 30.3 / 32.0, DC 22.8 / 27.1, GT 53.6 /
59.9, KKR 34.7 / 30.5, LSG 33.1 / 37.2, MI 42.4 / 42.4, PBKS 33.6 / 39.1, RCB 59.7 / 64.3, RR 46.5 / 49.9, SRH
44.1 / 42.5. In 2025 the plan spent about what each team spent but bought fewer players (13–19 against
14–23): it stops when the next player's gain per crore falls below the purse's best use. In the 2026 mini it
spent much less than the real teams at the same purse (CSK 13 of 41 cr, RR 3 of 13): with the bench capped
the free agents add little, so the rule keeps its money, and an unspent crore counts for nothing.

**Is "P(≤ max bid)" calibrated?** For every target of each team's full-purse plan that sold, the plan's
P(the rivals' price to beat ≤ the max bid) against whether the real price was at or under the max bid. The
real price is the second-best bid of all ten teams, never above the best rival's, so this check can only
flatter the plan; on the lots a team bought itself the real price *is* its rivals' best (exact, but few). The
room's own P(price ≤ max bid), all ten teams bidding by the same model, is the like-for-like check of the
price distribution. Predicted / came true (n):

| P band | validation 2019–2024: plan | room | **2025 (test): plan** | **room** | **2026 (test): plan** | **room** |
|---|---|---|---|---|---|---|
| 0.0–0.2 | 0.06 / 0.16 (314) | 0.02 / 0.04 (138) | **0.06 / 0.10 (145)** | 0.07 / 0.05 (75) | **0.12 / 0.04 (23)** | 0.00 / 0.00 (6) |
| 0.2–0.4 | 0.29 / 0.57 (168) | 0.29 / 0.38 (119) | **0.29 / 0.32 (56)** | 0.30 / 0.13 (54) | **0.30 / 0.35 (17)** | 0.34 / 0.14 (7) |
| 0.4–0.6 | 0.49 / 0.66 (141) | 0.50 / 0.45 (116) | **0.50 / 0.58 (71)** | 0.49 / 0.45 (47) | **0.50 / 0.58 (24)** | 0.47 / 0.14 (7) |
| 0.6–0.8 | 0.70 / 0.80 (123) | 0.70 / 0.65 (82) | **0.69 / 0.64 (45)** | 0.71 / 0.64 (66) | **0.69 / 0.78 (23)** | 0.69 / 0.71 (7) |
| 0.8–1.0 | 0.89 / 0.67 (79) | 0.94 / 0.92 (274) | **0.89 / 0.76 (58)** | 0.93 / 0.80 (101) | **0.91 / 1.00 (13)** | 0.93 / 0.97 (33) |
| all (Brier) | 0.35 / 0.47 (0.206) | 0.56 / 0.56 (0.134) | **0.38 / 0.39 (0.170)** | 0.54 / 0.45 (0.160) | **0.48 / 0.52 (0.148)** | 0.69 / 0.65 (0.085) |
| lots the team bought itself (exact; the uncapped-bench run) | 0.43 / 0.57 (75) | | **0.35 / 0.35 (34)** | | **0.49 / 0.71 (7)** | |

(The room's columns don't depend on the plan and were not re-run.)

Before (the replay of 2026-10-22, hand-set rivals), the plan said 0.95 and 0.75 came true in 2025's top band,
and 0.88 / 0.44 is the 2026 figure the audit recorded: over-confident. With the bench capped the targets
change (more cheap players, fewer veterans), and the top band is over-confident again in the validation (0.89 /
0.67) and 2025 (0.89 / 0.76), right in 2026 (0.91 / 1.00, 13 targets); overall the plan is about right in
both test years (0.38 / 0.39, 0.48 / 0.52) and says less than came true in the validation's middle bands.
(Before the cap: top band 0.92 / 0.89 in 2025, and right on the exact check, 0.35 / 0.35.) The room's like-for-like check is calibrated in the validation (0.56 /
0.56) and in 2026 (0.69 / 0.65), over-confident on the 2025 mega (0.54 / 0.45: that auction ran above the
simulation, section 7). No recalibration map is applied: a map fitted on the validation would raise every
probability, and the validation's event (real price ≤ max bid) can only flatter the plan. (This decision was
taken after seeing the round-1 test tables.)

**The honest read** (of the 2026-10-23 replay; the re-runs since, with the shipped money rule and the
time-aware values, give 1 of 10 and 0 of 10: the box at the top of this section and step 4). With the fitted rivals and the P(plays) bench capped at a lot's P(plays) the plan's squads
are **ahead in the mega auction and behind in the mini**: ahead for 7 of 10 teams in 2025 (+6.5 runs a match on
average) and 2 of 10 in 2026 (−2.4; −2.6 on the best XI, where it also spent far less). Before the cap: 6 of
10 (+2.5) and 3 of 10 (−0.2). The 2026-10-22 replay's 8 / 0 split (+8.5 / −4.4) is gone in both
directions: the fitted rivals pay more for stars in a mega auction and less in a mini, and the bench no longer
rewards the next four players whether or not they play. It does not beat the real franchises clearly in either
auction type, so **Bid plan stays a draft**. What remains: the plan is a price-taker (rivals don't react to its
targets, issue I2); the market price can't see the scouting behind the 2026 uncapped buys; the strength measure
is runs a match, not wins; values are each player's level next season (section 4b), not the three-season
forecast a multi-year buy needs.

**Limits.** Rivals bid by the room's fitted demand model and don't react to our buys; a bidding war for one name
isn't predictable. Prices rest on the market model (a typical player off by about 1.7×), which can't see
scouting, injury or brand. Strength adds expected contributions at each player's usual balls (6c), held to a
side's innings, with the bench filling the XI's missed matches, but knows nothing of batting order within the
XI, conditions or the impact-player rule beyond five bowling and six batting options. Values are his level
next season (4b, calibrated in 4c), not a multi-year forecast: for a player bought for three seasons, section 11's forecast
(`forecast.json`) is the natural next input (gain over the next three seasons, weighted by P(regular)); not
wired in yet. Keep or release's salaries, squads and assumed purse carry over unchanged.

---

## 13. The reality gate

**Why it exists.** The same kind of fault kept coming back after each fix:

- a 40-year-old free agent drawing max bids of 16–19 cr (I16);
- a No. 8 hitter first on nine Bid plan sheets (I17a);
- max bids set by where a grid ends (I17b);
- a 30-year-old shown as 40 (I17e).

Each was obvious to anyone who follows the IPL, and none was caught by a test. The unit and parity tests
check that the code does what it says. Nothing checked that what it says is true of cricket.

**What it is.** `tests/test_reality_gate.py` runs on the real outputs the site serves
(`site/public/data/ipl/`: keep.json, auction_pool.json, and all ten 2027 Bid plans built from them) and on the
real auction record. It fails the test suite when a check trips. **Every model change must pass it.** That
includes a new fit, a new rule, a re-export and a data refresh.

**Thresholds.** Every threshold comes from real data or a cited record, written next to the check. A
threshold is never set by looking at what the current outputs need. When the gate trips, the output is
fixed, or the failure is recorded as a known open issue in the ROADMAP. The threshold is not loosened.

| check | threshold and its source | 2026-10-27, before the time-aware values | after (section 4b) | after 4c | after the impact era, the bans and the 5-year rule (evening) |
|---|---|---|---|---|---|
| Each plan's expected spend ÷ purse left | within the range real teams spent at mini auctions (2023, 2024, 2026) with a purse left within a factor 2 of its own (`ipl_auction_history.json`, purse = cap − contracts as in step 4 of section 12) | **pass** (0.87–0.99) | **pass** (0.85–0.98) | **pass** (0.85–0.99) | **pass** |
| No player first on more sheets than franchises would bid for him | 10 × the mean fitted chance a franchise bids for him at all (the demand model, fitted on the 2019–2026 auctions) + 2 binomial sd | **fail**: David Miller first on 6, at most 4.4 | **pass**: Fraser-McGurk and Atharva Taide first on 3 each, Kusal Mendis 2, Mitchell Owen and Akeal Hosein 1 | **pass**: Mendis 4, Fraser-McGurk 3, Taide 2, Hosein 1 (later the same day **fail**: Lhuan-dre Pretorius 5, at most 4.4) | **fail**: Rahul Tewatia first on 4, at most 3.7 (with a side of 11: Fraser-McGurk 5, at most 4.9) |
| A minimum-price player (rivals don't bid above his base) doesn't top most sheets | at most half of the ten | **fail**: Miller, 6 | **pass** (Mendis, 4 of 10) | **pass** | **pass** (Tewatia, 4 of 10) |
| Known stars rank high | the players retained at the first capped slab (18 cr+, IPL Player Regulations 2025–27) inside the top N of the pool by season value; N = the number of squad players paid at least the lowest capped slab (11 cr): 47 | **fail**: Pat Cummins 57th (Ruturaj Gaikwad 25th, Jaiswal 24th, the rest top 10) | **fail**: Cummins 59th (Kohli 27th, Gaikwad 24th, Jaiswal 14th, the rest top 10) | **fail**: Cummins 59th (Kohli 28th, Gaikwad 27th, Jaiswal 14th, the rest top 10) | **fail**: Cummins 60th (Kohli 28th, Gaikwad 27th, Jaiswal 16th, the rest top 10) |
| Every IPL player's age is plausible | no younger at his first IPL match than the youngest IPL player (Vaibhav Suryavanshi, 14 years 23 days, 2025), no older at his last than the oldest (Brad Hogg, 45 years 92 days, 2016, ESPNcricinfo) | **pass** | **pass** | **pass** | **pass** |
| Keep calls the obvious retentions Keep | every player paid 18 cr+ (the first capped slab) kept by Keep or release's default | **pass** (14 of 14) | **pass** (14 of 14) | **pass** (14 of 14) | **pass** (14 of 14) |
| The star market price isn't below real prices by more than the documented error | for the lots sold for 10 cr+ at the last auction (2026), median market ÷ real ≥ 0.36 (AUCTION_MATH Part 0) | **fail**: 0.34 on 5 lots (Kartik Sharma and Prashant Veer, the scouted uncapped buys at 14.2 cr, at 0.06 and 0.12) | **fail**: 0.3597 (the same two lots) | **fail**: 0.3597 (price input unchanged) | **fail**: 0.3597 (price model unchanged: the brand was chosen on 2018–24 and vetoed here, section 6b, at 0.333) |

**The failures, read.** *(2026-10-27, after the time-aware values of section 4b: the two first-target checks
pass on the shipped sheets, the buy model off; their strict `xfail` marks were removed. With the buy model
on they fail again: section 6c.)*

- **The two "first target" checks** were the price-taker problem (ROADMAP I2). Every plan sees the same cheap
  regular and none sees the others chasing him. Every money rule tried hits it: rule "none" puts
  Fraser-McGurk first on six sheets. Two fixes were built on 2026-10-27, the buy model (6c) and the rival
  plans (section 12, step 4). Both made the sheets worse and are switched off. With the time-aware values
  (section 4b) Miller is worth 1.8 runs a match (from 2.8) and the shipped sheets' first targets spread
  over five players; the price-taker problem itself is still there (rule "none" now puts Fraser-McGurk
  first on nine sheets).
- **Cummins: a real signal, not a model error** (investigated 2026-10-27).
  - He played 8 of SRH's 15 matches in 2026, which is why his P(plays) is 0.64.
  - His IPL bowling was about the league average: economy 9.28, 9.06 and 9.59 in 2024, 2025 and 2026,
    against the league's 9.42, 9.51 and 9.77; a wicket every 20.3, 18.6 and 24.0 balls, against about 20.
  - His contribution, 2.74 runs a match (1.42 batting, 1.32 bowling), is right for that record.
  - Overseas places don't hold him back: he is SRH's 4th overseas player by contribution, inside the four.
  - The captain feature in P(plays) is small (+0.10), and the season value prices no captaincy.
  - His 18 cr retention pays for leading SRH, which the model doesn't value. That is a limit of the
    model's scope, documented here, not a number to fix.
- **The price check.** Kartik Sharma and Prashant Veer were bought at 14.2 cr each for CSK
  ([ESPNcricinfo](https://africa.espn.com/cricket/story/_/id/47323390/csk-bids-prashant-veer-kartik-sharma-smash-records-ipl-2026-auction)).
  - Veer: on UP T20 League form (320 runs at a strike rate of 155 and eight wickets) and an SMAT and U-23
    run that won him CSK trials. CSK also needed a replacement for Jadeja.
  - Sharma: on 12 T20s (334 runs, strike rate 164) and the 2025–26 SMAT.
  - None of this is in the data. Cricsheet's SMAT ends in December 2024, and the UP T20 League and the trial
    camps aren't covered.
  - No sourced, fitted feature explains them, so nothing was changed. It is the market model's documented
    blind spot for scouted uncapped players.

- **First on too many sheets, again (2026-10-27, after the player-master fixes).** Lhuan-dre Pretorius's
  sourced age is 20, not the 28 assumed while his date of birth was missing; the aging curve raises his
  value and he is first on 5 sheets against a bound of 4.4. The age is right, so the model is not tuned
  to pass: it is the price-taker problem above (every sheet planned alone), open in ROADMAP I18. *That
  evening*, with the impact-era replacement level (6c) and the side of 12 (section 12), Rahul Tewatia is
  first on 4 sheets against a bound of 3.7 (a lower-middle finisher measured against the impact era's
  weaker replacement at No. 7). With a side of 11 the same data put Fraser-McGurk first on 5 against 4.9.
  Same root, about the same margin; still marked.
- **The brand veto (2026-10-27, evening; section 6b).** The price recipe with Wikipedia pageviews (AB) won
  the selection on 2018–24, but on the 2027 pool it moved this check from 0.3597 to 0.333 (Livingstone
  and Pathirana down) and priced Suryavanshi at 31.6 cr, past the 27 cr record, so it was not shipped.
  The shipped price model is unchanged; a routine refit of it on today's data would also move the check
  the wrong way (0.317), so it was not refitted either.

The three still failing (Cummins, the star price, and the first-target bound) are open in the ROADMAP (I18)
and marked as known failures (`xfail`, strict); the two first-target checks lost their marks on 2026-10-27
when they passed, and the first of them got its mark back the same day (Pretorius, above). They show as
expected failures, not passes. When a fix makes one pass, the strict mark fails the suite until the mark is
removed, so a fixed check can't quietly stay marked. Any new failure fails the build.
The checks run in about 30 seconds.
