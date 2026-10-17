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
| [3. The nine context metrics + fielding](#3-the-nine-context-metrics--fielding) | Pressure Runs, Intent Curve, Dot-Ball Recovery and the rest |
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
of winning?* It credits that change to the batter and the opposite to the bowler, then averages it per
match. A 30 not out that wins a tight chase scores more than a hundred in a lost cause, and a wicket at
200/3 chasing 220 counts for more than one at 50/3 chasing 250. Code: `src/cricdex/metrics/ngi.py`.

**How.**

1. **A win-probability model.** For every ball of every decided T20 match in a league, CricDex records the
   state *before* the ball: which innings, balls left (scheduled overs minus legal balls bowled), wickets
   left, the score, the target and runs still needed, the required rate, the current rate, and how the
   current rate compares with that ground's usual first-innings rate. A gradient-boosted tree model
   (XGBoost) learns how often the batting side went on to win from each kind of state. Ties and no-results
   are dropped; super overs are not used.
2. **Honest training.** Matches, not balls, are split 70 / 15 / 15. The model learns on the first 70%,
   stops early and is *calibrated* on the next 15% (isotonic regression, so "70%" really means the side
   wins about 70% of the time), and its accuracy is reported only on the last 15% it never saw. Splitting
   by match matters: if balls were split at random, the model would see ball 99 of a match in training
   and be "tested" on ball 100.
3. **Score every ball.** The model reads the state before the ball and the state after it (runs added,
   wicket fallen, one ball fewer). The difference is that ball's value, ΔWP. The last ball of the chase
   resolves to the actual result (1 or 0). The last ball of the first innings hands over to the chase's
   opening position, so nobody is credited with the other team's innings.
4. **Credit and average.** The striker gets +ΔWP, the bowler −ΔWP. Summed over a match, then over a
   career, and divided by matches played, that's **NGI per match**. The all-time board needs 25 matches
   (6 for the last-3-years board, 3 for the last year), because one great game shouldn't top a career
   table. Time-window boards reuse the whole league's model, since a single year is too few matches to
   train one.

**Worked example (illustrative numbers).** A side needs 12 off the last 6 balls with 5 wickets in hand;
the model gives them a 40% chance. The batter hits a six: now 6 off 5, and the model says 68%.

```
ΔWP = 0.68 − 0.40 = +0.28   →  batter +0.28, bowler −0.28
```

The same six in the second over of a first innings might move the needle from 50% to 52%: +0.02. Same
six, fourteen times the credit, because it mattered fourteen times as much.

**Reading it.** An NGI per match of +0.05 means the player adds, on average, five percentage points to his
side's chance of winning each game he plays.

**Limits.** Fielders get no credit yet (a stunning catch shows up as the bowler's wicket), and a run-out at
the non-striker's end is booked to the striker of that ball. Byes, leg-byes and wides move win probability
too, and that swing goes to the striker and bowler of the ball. NGI is T20-only.

**Rain-reduced chases.** Cricsheet does flag Duckworth-Lewis-Stern results (`outcome.method = "D/L"`) and
records the target each chase actually faced (`innings[].target`: runs and overs). Both are ingested
(`matches_<col>.outcome_method`, `innings_<col>.target_runs` / `target_overs`), so a rain-hit chase is
scored against its revised target with the shortened over count (overs × balls per over, so The Hundred's
five-ball overs count right). A database ingested before the `innings_<col>` table existed falls back to
first-innings total + 1 and the scheduled overs. Pressure Runs uses the same target.

---

## 3. The nine context metrics + fielding

Standard averages and strike rates are context-blind. Each of these nine isolates one skill a scorecard
hides. They're all on the Leaderboards page (all-time, last 3 years, last year), with the same
explanations as below. Exact formulas and column names: [METRICS.md](METRICS.md); code in
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

**Wicketkeeping and Fielding boards.** From each dismissal's list of fielders: a catch, a stumping, or a
run-out involvement (every fielder named in a run-out gets one). A player is a keeper if the taxonomy says
so or he has any stumping; keepers get their own board so their catches don't swamp the outfield list.
Caught-and-bowled is a bowling wicket and isn't counted. These are *counts* of dismissals, not a
success rate or diving range; ball-by-ball data can't see dropped catches.

---

## 4. Bayesian skill ratings

**What it does.** A raw average treats a fifty against a great attack and a fifty against a weak one as
the same fifty. The rating model learns a skill for every batter and every bowler *at the same time*, so
each run is judged against who it came off. It is **dismissal-aware**: each player gets two skills per
role, and every skill comes with a measure of how sure the model is. Code:
`src/cricdex/scout/ratings/bayesian.py`; model spec: [ratings README](../src/cricdex/scout/ratings/README.md).

| Role | Skill | Plain meaning (higher = better) |
|---|---|---|
| Batter | **scoring** (`skill`) | scores faster than an average batter would against the same bowlers |
| Batter | **survival** (`survival_skill`) | harder to get out |
| Bowler | **economy** (`skill`) | concedes less than an average bowler would to the same batters |
| Bowler | **strike** (`strike_skill`) | takes wickets more often |

**How.**

1. **Every matchup.** For each batter–bowler pair in a league, count the legal balls, the runs off the bat
   and the dismissals the bowler was credited with (bowled, caught, lbw, stumped, hit wicket; run-outs
   don't test the duel). Every pairing is kept, even a single ball.
2. **Two linked models on those matchups.** Expected runs per ball rise with the batter's scoring skill
   and fall with the bowler's economy skill (a Negative-Binomial count, which allows for cricket's lumpy
   scoring of dots and sixes). The chance of a dismissal on each ball rises with the bowler's strike skill
   and falls with the batter's survival skill (a Binomial on the balls, through a logistic link).
3. **Shrinkage.** Each skill is assumed to come from a population with a spread the model also learns.
   A player with 30 balls is pulled strongly toward average; one with 3,000 is barely moved. That's what
   stops a debutant who hit 35 off 10 from being rated the best batter in the league, and it's why no
   matchup needs to be thrown away.
4. **Opponent bridging.** Because each skill is learned from every opponent at once, a batter who scored
   freely off strong bowlers gains more than one who scored the same off part-timers. Strength flows
   through the whole network of matchups.

**One number per role: `value`.** Scoring is measured in log runs per ball and survival in log-odds of
getting out, so they can't just be added. Each is first divided by its population spread (the fitted
σ for that skill), then summed. So `value` is in **"typical spreads above average"**: 0 is an average
player, +1 is one typical player-to-player spread better, the best in the IPL sit near +3.

*Worked example (current IPL fit).* The scoring spread is about 0.21 and the survival spread about 0.30.

```
V Kohli     scoring +0.16 ÷ 0.21 ≈ +0.76    survival +0.575 ÷ 0.30 ≈ +1.92    value ≈ +2.68
SP Narine   scoring +0.30 ÷ 0.21 ≈ +1.44    survival −0.405 ÷ 0.30 ≈ −1.36    value ≈ +0.08
```

Narine (batting) scores faster than Kohli but gets out far more often, so his complete batting value is
about average. A runs-only model would have rated him the better batter. The same split separates
bowlers: Chahal's economy is ordinary but his strike skill is high; Ashwin is the reverse.

**Uncertainty.** Every skill and `value` carries a standard deviation from the fit. The Head-to-Head page
uses it directly: treating two players' values as bell curves, the chance that A is better than B is
`Φ((value_A − value_B) / √(sd_A² + sd_B²))` (`src/cricdex/scout/ratings/head_to_head.py`). Two players
with close values and wide uncertainty come out near 50/50, as they should.

**How it's fitted, and how we checked the shortcut.** The fit runs in NumPyro (JAX). The default is
**ADVI**, a fast approximation (12,000 optimisation steps, about 1.5–3 minutes for the IPL). The exact
method, **NUTS** (Hamiltonian Monte Carlo), takes about 15 minutes for the IPL and two to three hours for
all eight leagues, so it's opt-in (`scripts/scout_rate.py --sampler nuts`). We ran both on the IPL: ADVI's
uncertainties were 95–99% of NUTS's on every skill, `value` uncertainty about 99%, and head-to-head
probabilities differed by a median of 1–2 points. NUTS converged cleanly (worst r-hat 1.03, no
divergences).

**Limits.** Each league is fitted separately, so an IPL +2 and a BBL +2 aren't the same thing; the scout
and the auction correct for that with a tier discount (sections 5 and 6). Economy counts runs off the bat
only, so wides and no-ball extras don't count against a bowler here. There's one skill set per role for a
player's whole career in that league: no separate rating per venue, phase or era yet.

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
`auction_nationalities` / `auction_excluded_nationalities` lists in the registry). Priced as
in section 6; the top 600 by value make the pool.

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

**Established IPL players (2021–26).** Ratings fitted before each season versus each player's raw career
numbers before that season:

| | Model | Career average |
|---|---|---|
| Batters, overall | 0.14 | 0.15 |
| Bowlers, overall | 0.09 | 0.07 |

A tie. For players with a long IPL record, the opponent adjustment adds nothing a career average doesn't
already know. We also tried weighting recent seasons more (half-lives of 1, 2 and 4 years); none helped,
so recency weighting is **off by default** (`fit(half_life=...)` is there to experiment with). Correlations
this low are the honest state of things: a single T20 season is mostly noise, for any method.

**IPL newcomers (2014–26).** The harder and more useful test: players new to the IPL, rated **only** from
the BBL, SA20, CPL, T20 Blast and SMAT (with the auction's tier discount), versus their raw numbers from
those same leagues, scored on their first real IPL season.

| | Model | Raw numbers | Players |
|---|---|---|---|
| Batters, overall | 0.18 | 0.12 | 96 |
| Batters, survival (staying in) | 0.34 | 0.22 | 96 |
| Bowlers, overall | 0.20 | 0.25 | 110 |

How sure is that? Re-drawing the players 2,000 times (a bootstrap):

- **Batter survival:** the model did better in **97%** of re-draws (95% range of the gap −0.00 to +0.26).
  This is the one solid result: opponent-adjusted ratings from other leagues tell you how long a new
  batter will last in the IPL better than his raw numbers do.
- **Batter overall:** model better in 79% of re-draws. A lean, not proof.
- **Bowlers overall:** model better in only 28%. No edge; if anything, raw numbers did slightly better.

---

## 9. Limits

What the models can't see, and where they approximate. Most of these are on the
[roadmap](ROADMAP.md).

- **No fielding in NGI.** Win-probability credit goes to the striker and the bowler only. A great catch
  is the bowler's wicket; a run-out at the non-striker's end is booked to the striker. Byes, leg-byes and
  wides swing win probability and that swing lands on the striker and bowler too.
- **Fielding boards are counts.** Catches, stumpings and run-out involvements, not catch success rates,
  dropped catches or ground covered; ball-by-ball data doesn't record those.
- **Indian domestic data ends in December 2024.** Cricsheet's SMAT coverage currently stops at
  2024-12-15, so uncapped Indian prospects are rated on older form than everyone else. Ranji Trophy and
  Vijay Hazare have no ball-by-ball on Cricsheet and aren't covered.
- **Prices are invented from skill**, calibrated to recent auctions but not fitted to actual sale data.
- **A single season is noisy.** The backtest's correlations are low for every method, model or not. Treat
  any one-season ranking with care.
- **The ratings don't beat career averages for established players.** Their edge is in rating players from
  other leagues, and even there only batter survival is clear.
- **Each league is fitted on its own.** Cross-league comparison rests on one hand-set tier discount per
  league.
- **Economy ignores extras.** The rating model counts runs off the bat; wides and no-ball runs aren't held
  against the bowler there (the bowling figures in records and phase boards do count them).
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
