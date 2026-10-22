# How the Auction room works (the math, in plain words)

> This describes the Auction room — a Monte-Carlo of a real IPL auction.
> The **same** logic runs on every surface: in the browser (TS,
> `site/src/lib/auction.ts`) and on the CLI / TUI / Streamlit (Python,
> `cricdex.web_parity`), from the **same** exported JSON and with a
> bit-exact seeded RNG, so a run reproduces everywhere trial-for-trial
> (locked by `test_scripts/test_web_parity.py`). It is driven from the CLI
> by `cricdex auction room`. The skill ratings it starts from, and every
> other model, are explained in [`METHODOLOGY.md`](METHODOLOGY.md).
>
> Before an auction comes the retention deadline: **Keep or release**
> (`cricdex keep`, the site's Keep or release page) uses the same market
> price (Part 0) to set each squad player's worth against his salary, with
> his on-field worth (Part 1) alongside, and the
> same pool as the likely replacement market. How it decides:
> [METHODOLOGY §10](METHODOLOGY.md#10-keep-or-release). The cycle's real
> rules (purse, squad limits, deadline) are in `config/competitions.toml`;
> the room below still uses its own IPL defaults (wiring it to that file
> is roadmap #12).

The room answers one question a real franchise faces:

> **If all ten teams retain their core and then bid for everyone else,
> who likely lands which star — and for how much?**

But there's a wall first: the data only tells us how **good** a player is
(a skill rating). It never tells us what he **costs**. So step zero is a
price, and there are two:

- **Market price** (Part 0, the price the room uses): what IPL franchises
  have actually paid for players like him, fitted to every auction since
  2018.
- **On-field worth** (Part 1): what his game alone would fetch on a
  hand-set skill→price curve. Shown next to the market price.

---

## Part 0 — The market price (fitted to real auctions)

`scripts/ipl_auction_history.py` turns Wikipedia's personnel pages
(2008–2026, CC BY-SA) into `data/curated/ipl_auction_history.json`:
1,647 sold lots and 1,046 retentions, 97% / 99% matched to a Cricsheet
id, US$ prices before 2014 converted at the auction day's Federal Reserve
rate. `scripts/ipl_price_model.py` rebuilds each player **as he looked on
the day of that auction** (the IPL re-fitted on the matches before it,
his caps, age and IPL seasons then) and fits a **hurdle model**:

1. **Is he bought at all?** A logistic regression on IPL players who were
   neither retained nor (yet) bought: 48% of them are bought in the
   2025–26 test, and the model's 20% / 40% / 60% / 80% bands come true
   12% / 35% / 61% / 79% of the time.
2. **For how much?** `ln(price / purse)` from his cautious value, caps
   (all and in the last two years), Indian or overseas, age, IPL balls,
   seasons and time since his last IPL game, **captaincy** (regular IPL
   captain last season, seasons as captain, recent national captain;
   `data/curated/ipl_captains.json`, from Wikipedia), role and mega / mini,
   by a robust (Huber) regression. Mega-year retention prices are in too:
   the only "sale" data on the stars no franchise lets go.
3. **Top-end calibration, by group.** A regression on logs shrinks
   toward the middle, so its predictions go through a monotone map fitted
   on out-of-fold predictions (their quantiles onto the real prices', so
   the predicted prices spread like real auctions), plus a shift for each
   group (overseas, capped Indian, uncapped Indian: groups and shifts in
   `config/price_model.json`) so no group leans high or low in the fit.

```
market price   = purse × e^(calibrate(intercept + Σ coefficient × feature))   (config/price_model.json)
upper quartile = market price × e^(0.674 × 1.02) ≈ 2 × market price
both clamped to 0.3 cr … the IPL-evidence ceiling (Part 1, step 3)
```

**How good is it?** Trained on auctions up to 2024 and scored on the 2025
mega and 2026 mini auctions (235 lots): half the lots land within ±50%
of their price (43% for the Part 1 curve), the median lot is off by 53%
(59%), and it orders the lots better (rank correlation 0.73 against
0.63). The lots that went for 10 cr+ come out at 0.50× their price on
average (0.45× uncalibrated, 0.62× with one map for everyone, 0.35× on
the curve): Pant 27 for 27, Shreyas Iyer 19.6 for 26.75, Green 13.7 for
25.2. Capped and uncapped Indians come out with no lean (bias −0.06 and
+0.04 in ln); overseas players still come out about 1.45× what they
fetched in 2025–26 (1.9× with one map): the overseas level moves from one
auction to the next and no shift fitted on earlier years catches it. Mean
|ln error| 0.70 (0.67 uncalibrated, 0.78 curve).
Full table: [METHODOLOGY §6b](METHODOLOGY.md#6b-market-price-fitted-to-real-ipl-auctions).

The room prices the pool for the league's next cycle (IPL 2027: a mini
auction, 125 cr purse, from `config/competitions.toml`); `projected
value` is the market price and `onfield_value` the curve's.

---

## Part 1 — Turn skill into a crore price (on-field worth)

Think Zillow estimating a house price from its features. Our one feature
is the player's **skill score**, the Bayesian model's complete value, in
**runs per 100 balls above the league's average ball** (see
`scout/ratings/README.md` and [METHODOLOGY §4](METHODOLOGY.md)). For a
batter it is his extra scoring plus the runs his team doesn't lose because
he stays in, with a wicket priced at what it costs where he bats (about 14
runs early in the powerplay, 7–8 in the middle overs, 2–3 at the death);
for a bowler the runs he saves plus his extra wickets at the same price.
Average ≈ 0, the best IPL regulars sit around +20 to +25, weak players are
negative. The curve below is hand-set, not fitted to sale data: it is the
"on-field worth" shown next to the market price (Part 0), which the room
now prices with.

1. **Price the cautious estimate.** Every value comes with its uncertainty
   (`value_sd`), and the price is set from `value − 0.5 × value_sd`
   (`PRICE_CAUTION_SD` in `web_parity/pricing.py` ⇄ `auction.ts`), not from
   the central estimate. A proven star (sd ≈ 3 runs) loses about 1.5 runs; a
   400-ball prodigy (sd ≈ 12) loses about 6, so "promising but unproven" is
   priced below a proven player of the same central value. The displayed
   value and every ranking stay on the central estimate. In the pool the sd
   is the blended value's (`1 / √Σw`, translation uncertainty included), or
   the IPL rating's own when that stands alone; in Scout it is the league
   rating's sd with the tier's translation sd added, so both price a player
   the same way.
2. **Amplify exponentially.** `4.03 × e^(0.0743 × priced value)`, times a
   small role weight (all-rounders / keepers are rarer → weighted up). The
   `0.0743` stretches the curve so the spread matches recent real money —
   the top names land in the 20s (27 cr, the 2025 ceiling, is the cap,
   reached at a priced value of about +25.6), the typical pool player around
   1.2 cr — and the result is clamped to `[0.3, ceiling]`.
3. **A ceiling that rises with IPL evidence.** The most a player can be
   priced at grows with his IPL balls in the role being priced:
   `27 × (0.5 + 0.5 × min(1, IPL balls / 600))` (`CEILING_FULL_BALLS = 600`,
   about two full seasons; `CEILING_FLOOR_SHARE = 0.5`). No IPL balls →
   13.5 cr at most, 163 → ~17 cr, 449 → ~23.6 cr, 600+ → the full 27 cr. The
   exported pool and Scout rows carry `target_balls` (IPL balls in the role
   priced; missing counts as 0), so the web and Python apply it the same way.
4. **Discount for IPL relevance.** A player who hasn't featured in the IPL
   lately is worth less to an IPL auction *now*. Each player gets an
   IPL-relevance weight between 0 and 1: about 1 for a current IPL regular
   (last IPL game within ~18 months; age barely matters while he's playing),
   fading with years since his last IPL game and with age past 32; 0.7 for an
   uncapped Indian who has never played the IPL; lower for an older overseas
   leaguer. Up to 36 runs per 100 balls is taken off the value at weight 0
   (about −29 in practice, since the weight never drops below 0.2). This is
   what stops retired or league-only veterans topping the buys.
5. **Out come two numbers:**
   - **projected value** — what he's worth, in crore.
   - **base price** — his opening tag, snapped to real IPL bands:
     0.3 / 0.5 / 0.75 / 1.0 / 1.5 / 2.0 cr. Bidding pushes the final price
     up from there.

**Worked example — "Player X", value +10 ± 3 runs per 100 balls, played last month:**

```
priced value = 10 − 0.5 × 3 = 8.5
4.03 × e^(0.0743 × 8.5)     ≈ 7.6 cr   ← projected value
(− recency penalty if stale)
opening tag                 = 0.75 cr  ← base price
```

**How the curve was re-fitted when the value moved to runs (October 2026).**
The value used to be counted in "typical player-to-player spreads above
average" (scoring and survival each divided by its spread and added, so the
two counted equally; the curve was `1.1 × e^(0.95 × value)`). Moving to runs
changed the unit, so everything in value units was converted and the curve
re-fitted:

- **One conversion factor, 13.3** = the spread of the runs value over the
  spread of the old value, IPL players with 150+ balls (batters 20.3,
  bowlers 7.5: in runs, batters' values spread more than bowlers'). Every
  league discount, the default translation uncertainties (0.5 → 6.5,
  0.8 → 10.5) and the IPL-relevance penalty (2.7 → 36) were multiplied by
  it and rounded. A check from players with 300+ balls in both leagues
  (their runs value there minus in the IPL) gives gaps of the same size:
  SMAT +22 for batters / +7 for bowlers (discount 17), BBL +4 / +3 (6),
  CPL +5 / +6 and Blast +9 / +6 (8.5).
- **Two constants, two targets.** With the converted pool, `PV_BASE` and
  `PV_SCALE` were solved so the 600-player pool keeps the same **median
  price (1.17 cr against 1.18)** and the same **number of 10 cr+ players
  (25)** as the old curve on the old values, then rounded (3.15, 0.079);
  after the cautious price went in, re-fitted the same way on the cautious
  values (4.03, 0.0743: median 1.18 cr, 25 players at 10 cr+).
  The calibration ran on the IPL fit and the other leagues' values
  recomputed from their saved skills (posterior means, which agree with a
  full refit to within half a run).
- **What moved.** The top end now leans to batters, because a batter's
  scoring edge is worth more runs than a bowler's economy edge after the
  model's shrinkage: of the 25 players at 10 cr+, 18 are batters or keepers
  (14 before), 4 bowlers (7 before). Explosive openers rise (Abhishek
  Sharma, Salt, Head), and finishers who rarely get out but score at or
  below the death-overs rate fall (Dhoni, Miller).
- **The cautious price** (owner's call, October 2026). On the central
  estimate, young hitters with short IPL records reached the 27 cr cap.
  Priced at `value − 0.5 × sd`, with the curve re-fitted, the pool's top
  prices move as below (central value ± sd, runs per 100 balls):

  | Player | Value | Before | After |
  |---|---|---|---|
  | Suryavanshi (449 IPL balls) | +59.7 ± 12.5 | 27 | 27 |
  | Finn Allen (blend of 7 leagues) | +27.4 ± 4.9 | 27 | 27 |
  | Narine | +24.0 ± 2.5 | 21.0 | 21.9 |
  | Bumrah | +23.2 ± 2.7 | 19.7 | 20.5 |
  | Priyansh Arya | +27.7 ± 12.4 | 27 | 20.0 |
  | Abhishek Sharma | +22.9 ± 7.1 | 22.2 | 19.6 |
  | Ayush Mhatre | +25.9 ± 11.5 | 24.3 | 18.0 |
  | Rashid Khan | +20.3 ± 2.9 | 15.6 | 16.3 |
  | Buttler | +20.3 ± 4.3 | 16.4 | 16.3 |
  | Salt | +22.6 ± 9.4 | 19.7 | 16.0 |
  | KL Rahul | +19.4 ± 3.5 | 15.3 | 15.7 |
  | Inglis | +22.0 ± 11.7 | 18.8 | 14.0 |
  | Kohli | +13.6 ± 2.8 | 9.3 | 10.0 |

  Proven players move up slightly, thin records down. The caution alone
  left Suryavanshi at the cap (even two sds below his value, +35, is past
  the +25.6 that reaches 27 cr) and Finn Allen near it (his value blends
  seven leagues, so its sd is small). The **IPL-evidence ceiling** (step 3)
  settles both: Suryavanshi (449 IPL balls) 27 → 23.6 cr, Finn Allen (163)
  27 → 17.2. Nobody else in the top 25 is held by it, and the pool's median
  (1.18 cr) and 10 cr+ count (25) didn't move, so the curve wasn't re-fitted.

---

## Part 2 — Who's in the pool

A real IPL auction draws from the whole **active T20 world**, not just past
IPL squads. So the pool is **cross-collection**:

- **IPL players** — retainable; each carries his current franchise.
- **Free agents** — overseas talent via the **BBL** (Australia), **SA20**
  (South Africa), **CPL** (West Indies) and the **T20 Blast** (England), and
  uncapped Indians via the **SMAT** (Syed Mushtaq Ali Trophy).

With guardrails so it stays realistic:

- **Active only** — last match within ~3 years.
- **≥150 balls** of evidence — cuts tiny-sample flukes (no more a 30-ball
  domestic unknown outranking Kohli).
- **Excludes** men's-T20I associate noise and non-IPL nations (e.g. PAK).
- **Tier penalty** — runs against weaker attacks aren't worth as much as runs
  in the IPL, so cross-tier values are discounted before pricing, in runs per 100
  balls (**BBL −6.0**, **SA20 −6.0**, **CPL −8.5**, **T20 Blast −8.5**, **SMAT −17.0**;
  IPL 0; the newer leagues borrow these values and are marked provisional).
- **Several leagues, one value** — 300+ balls in the IPL in that role and the IPL rating stands
  on its own; otherwise the leagues are blended, weighted by how much evidence each has and how
  sure its translation is (`translation_sd` in `config/leagues.toml`), so a hot spell in a
  weaker league can't outrank a real IPL record.

---

## Part 3 — Retentions, then the auction (many times)

**First, retentions** — editable per team in the UI:

- **Mega auction** — each franchise keeps the **real 2025 retention list**
  (~5 players), paid out of the **120 cr** purse at the real retention price
  where known, else the IPL slabs (18 / 14 / 11 / 18 / 14 cr, then 4 cr).
- **Mini auction** — teams keep **most** of their squad (by default their 18
  most valuable players, already paid for in prior years), so retentions are
  free and they bid only a small leftover purse (30 cr by default) to top up.

Retained players leave the pool and count toward the **overseas cap (8)**.
Everyone else goes under the hammer.

**Then the bidding.** The 200 most valuable unretained players are the
lots (a real auction lists far more, but most go unsold), at most 36% of
them overseas, as on a real shortlist (2024: 119 overseas of 333;
`AUCTION_OVERSEAS_SHARE`). Without that cap the market price, which
values overseas players higher, made two-thirds of the lots overseas and
the eight-per-squad cap left squads short of 20. They go up one
at a time, stars first. Each team
works out a **max bid**:

```
max bid = value × aggression × need × overseas-bias × luck × budget
```

- **value** — the player's lot value: his market price (Part 0) through the calibration of Part 3b
  (level, curve, last price, demand shock), times the market tightness.
- **aggression** — the team's style (MarqueeChaser 1.35 splurges;
  ValueHunter 0.85 holds back).
- **need** — higher if the team still needs that role, lower once it's
  covered (so teams chase what they lack).
- **overseas-bias** — boosts the bid for imports if the team loves overseas
  talent; 1 for Indians.
- **luck** — a small seeded random nudge; this is what makes each run differ.
- **budget** — money left per open squad slot, compared with the league
  average (square root, kept between 0.75 and 1.6). A team that retained
  little and sits on a big purse bids harder; a stretched one bids softer.
  Without it a rich team fills its squad with cheap players and finishes
  with half its purse unspent.

A team can't bid past its remaining money (keeping 0.3 cr for every other
slot it still has to fill), the 25-man cap, or the overseas cap. **Highest max bid wins**, but — like a real auction — the winner pays
just **above the second-highest bid** (2% over it), not his own max, and
never more than **27 cr** (the real record, Pant in 2025) — and never more than his own price ceiling
(27 × (0.5 + 0.5 × min(1, IPL balls ÷ 600))), so a player with a thin IPL record can't be bid up to the
record either.

**Two passes so the pool is shared fairly.** Round 1 fills every team to a
**20-man minimum**; round 2 tops up toward the **25 cap**. A final safety
pass guarantees no team is left below 20.

**Worked example — bidding for Player X (worth 10 cr):**

```
MI  (MarqueeChaser, needs a batter): 10 × 1.35 × 1.5 × 1 = 20.3
CSK (Balanced, batters already full):10 × 1.00 × 0.7 × 1 =  7.0
(luck and budget left at 1 here)
→ MI wins, pays ≈ 7.1 cr (just over CSK) — NOT its full 20.3.
```

That's **one** mock auction. We run it ~300 times, reshuffling the order
slightly each time, then average:

- each team's typical spend, squad size, value, and overseas count,
- for each star, the **% of runs each team won him** —
  "Bumrah → MI 62%, CSK 21%" is your real odds in a bidding war,
- one sample league you can browse.

The randomness comes from a seeded generator, so the same settings always
reproduce the same result.

---

## Part 3b — The bidding, calibrated to real auctions

The bidding above was hand-set. Replayed against real auctions it got the **shape** wrong: teams
blew their purses on the first stars (the dearest lots came out 1.5–3× too high) while everyone
else went at base, and every run looked the same (real prices land inside the simulated 10–90% band
only 10–40% of the time, where 80% is right). So the value a team starts its bid from is now:

```
lot value = level × (market price)^0.75                      (level: 0.86 mega, 1.04 mini; crore, pivot 1 cr)
          ^0.7 × (level × his last IPL price)^0.3             (only when his last price is known)
          × e^(1.0 × z)                                        (z: a demand shock per lot per run, shared)
max bid   = lot value × market tightness × aggression × need × overseas-bias × luck × budget
tightness = money left with the teams that still have places
            ÷ market value of the best unsold players who'd fill those places   (kept 0.2–10)
```

- **level and curve.** A curve under 1 spreads money the way real rooms do: the 15th-best player
  gets closer to the star than the market model's ratio says.
- **last price** (a reference price): bidders remember what he went for. In a replay it's his
  previous IPL price scaled to that year's purse; for IPL 2027, a released player's 2026 salary.
  Free agents with no IPL price carry none.
- **demand shock.** How hot a player is on the day (form, a hype run, two teams that both need a
  keeper) isn't in any model: real prices scatter about ×2.7 around the market price. The shock
  gives each run its own version, so the spread of outcomes is honest.
- **tightness.** Lots of money chasing few places (a mini auction) lifts every bid; plenty of value
  still to come holds early bids back. It is recomputed before every lot.

**How it was fitted** (`scripts/auction_calibrate.py`). Each real auction is replayed with only
what was known before it: values fitted on the matches before it, a market model fitted on the
earlier auctions, the real retentions and purses; the pool is every player sold plus the recent IPL
players who weren't bought (as unsold alternatives). All ten teams bid, 40 runs each. Fitted on
the **2022 mega and 2023 / 2024 mini** auctions by grid search (level per auction type; curve 0.6–1;
shock 0.6–1.2; last-price weight 0–0.6), scored on the lots the market model itself expects to be
contested (sold, market price ≥ 2× base: chosen by the prediction, never by the real price, which
would flatter any model) plus the 10 lots the simulation prices highest. Then **tested out of time on
2025 and 2026**, which the fit never saw:

| | 2022 mega | 2023 mini | 2024 mini | **2025 mega (test)** | **2026 mini (test)** |
|---|---|---|---|---|---|
| contested lots | 150 | 24 | 22 | 110 | 24 |
| median real ÷ simulated, before → after | 1.00 → 1.04 | 1.00 → 0.99 | 0.93 → 0.76 | 1.20 → **1.53** | 0.90 → **0.99** |
| error, mean abs. ln, before → after | 0.87 → 0.71 | 0.61 → 0.53 | 0.98 → 0.90 | 0.85 → **0.71** | 0.80 → **0.77** |
| rank correlation, before → after | 0.71 → 0.70 | 0.75 → 0.77 | 0.46 → 0.63 | 0.71 → **0.74** | 0.54 → **0.48** |
| real price inside the simulated 10–90%, before → after (80% = calibrated) | 16% → 71% | 25% → 58% | 9% → 46% | 28% → **77%** | 12% → **46%** |
| the 10 dearest simulated lots, simulated ÷ real, before → after (all sold lots) | 3.06 → 0.99 | 1.14 → 0.79 | 0.68 → 0.85 | 2.44 → **1.09** | 1.55 → **1.07** |

Read honestly: the spread and the top end are much better and hold out of time; lot-by-lot error
improves a little; the **2025 mega auction still ran about 1.5× above the simulation on contested
lots** (the mega level was fitted on one auction, 2022, with a 90 cr purse), and the 2026 ranking is
no better. The market model's per-player misses (Starc 2024: 3.4 predicted, 24.75 paid) stay misses:
calibration can widen the range around them, not fix them. Players it prices at base (uncapped
youngsters) that real teams had scouted (Rizvi 8.4 cr in 2024) are outside any bidding model.

**What the Auction room does now.** With the 2025 retentions and a 120 cr purse: every team reaches
20–24 players, about 5 cr of purse left on average, 200 lots sold. Averaged over runs a star sits
nearer 12–15 cr (who gets the bidding war varies), but a single run's dearest three are typically
24–27 cr, as in 2025 (27, 26.75, 23.75). The neutral setting (level 1, curve 1, no shock, no
tightness, no last price) is the old room: `opts["calib"]` overrides any of them.

---

## Part 4 — Bid plan: the same simulator, turned into a bidding sheet

The room answers "where does each star go?". **Bid plan** answers "what should *my* team bid?"
(page *Bid plan*, `cricdex bidplan --team RCB`; full method and the replay of the 2025 and 2026
auctions: [METHODOLOGY §12](METHODOLOGY.md#12-bid-plan-beta)).

1. **Rivals only.** Your team steps out; the other nine (their Keep-or-release squads, each opening
   at least 8 places) run through this simulator 200 times. In each run, for each player, the
   **price to beat** = the winning rival's max bid × 1.02, or his base price if nobody bid.
2. **Strength.** Your best XI's values added up (≤ 4 overseas, a keeper, 5 bowling and 6 batting
   options, a −15 replacement player for any gap) + 0.25 × the next four + −3 per role need missed.
3. **The rule.** Stars first, bid up to *gain in strength ÷ λ*; λ (runs per crore) is the rate that
   gives the highest average strength across the 200 runs.

```
Worked example (made-up numbers). λ = 1.0 runs per crore.
Spinner A adds 8.3 runs of strength → max bid 8.3 cr. Rivals' prices to beat
over 200 runs: median 1.2 cr, 100% of runs ≤ 8.3 → "P(≤ max) 100%".
If A goes above 8.3, spinner B (who now fills the gap A leaves) adds 8.5
→ fallback: "A up to 8.3 → if he goes above that: B up to 8.5".
```

The rivals bid with the calibration of Part 3b, so "rivals pay" sits near real prices on average
(2025: the real price inside the rivals' 20–80% range for 55% of lots, 2026: 52%). A team never
bids for its own releases: if one is worth more to the squad than his salary, the plan says
"reconsider keeping" instead. Read the max bid as "where the value runs out" (walk away above
it), and "usually enough" as what wins him 9 times in 10.

---

## The one honest caveat

The market price is **fitted to real sale data** (Part 0), but it is
rough: a typical lot is off by a factor of about 1.7 out of time, the
10 cr+ lots come out at about half their price on average, and overseas
players lean high (about 1.45× in 2025–26).
The bidding is now calibrated to real auctions as a whole (level, spread, top end:
Part 3b), but the personalities are still hand-set and no model sees the scouting
behind a surprise buy. So the room faithfully **models** auction behaviour and
relative outcomes — it is **not** predicting the exact crore amounts of any
specific real auction.
