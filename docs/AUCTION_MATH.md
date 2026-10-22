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
> price (Part 0) against what keeping each squad player costs, and calls
> the chance a franchise keeps a player like him (a model of every real
> retention deadline since 2018), with the same pool as the likely
> replacement market. How it decides:
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
   neither retained nor (yet) bought, which also weighs **the price he
   last fetched** (his last auction price or mega-auction retention, as a
   share of that year's purse, and the seasons since): 48% of them are
   bought in the 2025–26 test (log loss 0.572 against 0.692 for the base
   rate, AUC 0.77).
2. **For how much?** `ln(price / purse)` from his cautious value, caps
   (all and in the last two years), Indian or overseas, age, IPL balls,
   seasons and time since his last IPL game, **captaincy** (regular IPL
   captain last season, seasons as captain, recent national captain;
   `data/curated/ipl_captains.json`, from Wikipedia), role and mega / mini.
   Fitted as a **censored (Tobit) regression**: every auction lot is a
   price, every mega-auction retention (2018, 2022, 2025) a **floor** (the
   franchise paid at least that to keep him, so he is worth at least
   that). The stars who never reach an auction enter only that way.
3. **The top end as the market priced it.** The prediction goes
   through a monotone map fitted out of fold (each auction predicted by
   a fit on the others): for most players it is close to the prediction
   itself, but the dearest predictions sold for about half of what a
   straight line says (the second-highest bidder's purse, and every team's
   need to fill a squad from the same money, flatten the top), so above
   the dearest lot the price rises half as fast as the prediction
   (`hi_slope` 0.51). His value is held to the range the market has
   priced (at most 31.8, the best ever sold).
4. **Each kind of player at its median.** Then shifted by its group's
   median out-of-fold error, for four groups: overseas in a mega auction,
   overseas in a mini auction, capped Indian, uncapped Indian (groups,
   shifts and the map in `config/price_model.json`).

```
market price   = purse × e^(map(intercept + Σ coefficient × feature) + his group's shift)
upper quartile = the same for a prediction 0.674 × 0.99 higher (narrower at the top, where the map flattens)
at least 0.3 cr; no ceiling
```

**How it was chosen.** Twenty candidate recipes (with and without the
last price, captaincy, retentions as floors, mini-year retentions as
floors, the old ceiling, a saturating budget limit, top-end maps and
hinges) were compared on auctions up to 2024 only, leaving one auction
out; the lowest error on the held-out lots won, and the winner was then
scored once on the 2025 mega and 2026 mini auctions. The last
price helps "is he bought" but not the price (the players who reach an
auction are mostly the ones their franchise let go, and a high last price
then means overpaid as often as good). Full tables: [METHODOLOGY
§6b](METHODOLOGY.md#6b-market-price-fitted-to-real-ipl-auctions).

**How good is it?** On the 2025–26 lots (237): half land within ±50% of
their price (43% for the Part 1 curve), the median lot is off by 49%
(60%), rank correlation 0.74 (0.62), mean |ln error| 0.66, level with
the earlier recipes. Overseas players come out about 1.2× what they
fetched in median, Indians with no lean in median. The retained stars
are priced from what released players like them fetched: the 2022 and
2025 retentions at about half what they were kept at (Gill and Axar
Patel above, Bumrah, Kohli, Rohit Sharma, Klaasen well below); what
their franchises pay to keep them is Keep or release's model, not the
price.

**The top end, honestly.** Until 2026-10-22 the prediction for the
IPL 2027 pool ran to Gill 90 cr, Axar Patel 38 and seven more past 27,
held only by a 27 cr / IPL-balls ceiling. The cause was not a squared
term (except for Suryavanshi, whose value is far beyond anything ever
priced) but the stars' features adding up without limit, pushed up by
the retained stars (a floor says "at least", so it never objects to a
price far above it). Fitted on the lots alone the same model priced
Gill at 22. The fix above prices the top as the market did; the
ceiling is gone, and the pool's dearest is Gill at 25.8 cr. Out of time,
the 20 dearest predictions of each auction fetched 0.87× their predicted
price (0.76× before the fix). The lots that *sold* for 10 cr+ come out
at 0.36× their price, but lots picked by their real price always sit
above any model (bidding wars; a model right on average would show
about 0.30×). Pant 21.5 predicted for 27 paid, Shreyas Iyer 14.5 for
26.75, KL Rahul 19.8 for 14, Sam Curran 10.2 for 2.4, Green 7.4 for a
25.2 bid; Venkatesh Iyer (3.4 for 23.75), Bhuvneshwar and the 2026
uncapped buys at 14.2 cr are beyond any pre-auction fact.

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
2. **Amplify exponentially.** `4.03 × e^(0.0743 × priced value)`. (Until
   2026-10-22 it was also multiplied by a hand-set role weight, all-rounders
   ×1.15 and keepers ×1.05; removed with audit item 6: an all-rounder's second
   discipline now counts in his contribution per match, METHODOLOGY §6c, and
   the market price has fitted role terms.) The `0.0743` stretches the curve so the spread matches recent real money —
   the top names land in the 20s (27 cr, the 2025 ceiling, is the cap,
   reached at a priced value of about +25.6), the typical pool player around
   1.2 cr — and the result is clamped to `[0.3, ceiling]`.
3. **A ceiling that rises with IPL evidence** (this curve only; the market price of Part 0 has none). The most a player can be
   priced at grows with his IPL balls in the role being priced:
   `27 × (0.5 + 0.5 × min(1, IPL balls / 600))` (`CEILING_FULL_BALLS = 600`,
   about two full seasons; `CEILING_FLOOR_SHARE = 0.5`). No IPL balls →
   13.5 cr at most, 163 → ~17 cr, 449 → ~23.6 cr, 600+ → the full 27 cr. The
   exported pool and Scout rows carry `target_balls` (IPL balls in the role
   priced; missing counts as 0), so the web and Python apply it the same way.
4. **No IPL-relevance discount any more** (removed 2026-10-22, audit item 4).
   Until then a hand-set weight (1 for a current IPL regular, fading with
   years since his last IPL game and age past 32, 0.7 for a never-IPL Indian)
   took up to 36 runs per 100 balls off the value, and that discounted value
   ordered the pool. Whether a player will play is now a chance fitted on real
   IPL XIs, P(plays), and the pool is ordered by his expected season value
   (P(plays) × runs above replacement a match × 14; METHODOLOGY §6c). That is
   what keeps league-only veterans out of the top now (Imran Tahir's P(plays)
   as a 47-year-old free agent is under 1%).
5. **Out come two numbers:**
   - **projected value** — what he's worth, in crore.
   - **base price** — his opening tag, snapped to real IPL bands:
     0.3 / 0.5 / 0.75 / 1.0 / 1.5 / 2.0 cr. Bidding pushes the final price
     up from there.

**Worked example — "Player X", value +10 ± 3 runs per 100 balls, played last month:**

```
priced value = 10 − 0.5 × 3 = 8.5
4.03 × e^(0.0743 × 8.5)     ≈ 7.6 cr   ← projected value
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
  0.8 → 10.5) and the IPL-relevance penalty (2.7 → 36, removed since) were multiplied by
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

- **Active only** — last match within ~3 years (a player idle for three
  seasons has no usage or form to project).
- **Ranked by expected season value** (since 2026-10-22): P(plays a match)
  × his runs above a replacement a match, batting and bowling at the balls
  he actually gets, × 14 (METHODOLOGY §6c). A squad player's P(plays) comes
  from where he ranks in his squad, his overseas place, experience, age and
  last season; a free agent's also from whether franchises buy players like
  him at all (fitted on every past auction pool). The top 600 are kept: a
  size limit for the browser and the simulation, not a quality cut. (Until
  then: the value less the IPL-relevance discount, and a ≥150-ball cut; a
  thin record is now handled by the ratings' shrinkage and a low P(plays).)
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
  (~5 players), charged to the **120 cr** purse by the 2025 rule: the team's
  retentions together cost the higher of the slab total (18 / 14 / 11 / 18 / 14
  cr for the 1st–5th capped, 4 cr uncapped, capped or uncapped at retention) and
  their salaries (KKR 69 cr, not its 57 of salaries; DC 47, not 43.75), including
  the real retentions too new to rate (Ramandeep Singh, Pathirana, Mayank Yadav,
  Prabhsimran Singh), who stay out of the pool but still cost the purse. A
  retention you add costs the slab for its place. Each player's figure is what
  releasing him alone would free (`retention_spend` ⇄ `retentionSpend`, the same
  charge as Keep or release).
- **Mini auction** — teams keep **most** of their squad (by default their 18
  players with the highest expected season value, METHODOLOGY §6c, already
  paid for in prior years), so retentions are
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
just **above the second-highest bid** (2% over it), not his own max. There is no price cap (the 27 cr
record and the IPL-balls ceiling were dropped on 2026-10-22): the purse rule above is the only bound.

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
lot value = level × (market price)^0.75                      (level: 0.72 mega, 1.49 mini; crore, pivot 1 cr)
          ^0.4 × (level × his last IPL price)^0.6             (only when his last price is known)
          × e^(0.8 × z)                                        (z: a demand shock per lot per run, shared)
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

Refitted again on 2026-10-22 (evening) for the top-end market price (Part 0: the calibrated top, no
ceiling), the room without its 27 cr cap, and the replays' retentions charged by the 2025 slab rule; same
grid and protocol (`scripts/auction_calibrate.py`, now resumable). The morning's fit → this fit (the
contested sets differ because the market price picks them):

| | 2022 mega | 2023 mini | 2024 mini | **2025 mega (test)** | **2026 mini (test)** |
|---|---|---|---|---|---|
| contested lots (morning / this fit) | 116 / 135 | 29 / 32 | 24 / 23 | 86 / 104 | 25 / 26 |
| median real ÷ simulated | 1.05 → 1.00 | 1.00 → 1.00 | 0.73 → 0.98 | 1.51 → **1.62** | 1.00 → **1.00** |
| error, mean abs. ln | 0.83 → 0.84 | 0.62 → 0.58 | 1.02 → 0.75 | 0.80 → **0.78** | 0.66 → **0.57** |
| rank correlation | 0.62 → 0.62 | 0.56 → 0.58 | 0.44 → 0.65 | 0.71 → **0.69** | 0.56 → **0.55** |
| real price inside the simulated 10–90% (80% = calibrated) | 58% → 63% | 48% → 53% | 29% → 44% | 65% → **62%** | 40% → **46%** |
| the 10 dearest simulated lots, simulated ÷ real (all sold lots) | 1.52 → 1.48 | 0.82 → 1.02 | 1.36 → 1.39 | 1.41 → **1.36** | 0.66 → **0.87** |

Chosen: level 0.72 mega / 1.493 mini, curve 0.75, shock sd 0.8, last-price weight 0.6, tightness on (the
morning's: 0.864 / 1.244, 0.6, 0.8, 0.3, on). Against the morning's fit the room is better on the
calibration auctions and on 2026 (lot error 0.57, the dearest simulated lots 0.87× real instead of 0.66×)
and about level on 2025, whose contested lots still ran about 1.6× above the simulation (the mega level
rests on one auction, 2022; the new market price's lower top asks more of it). The uncalibrated room for
reference: 2025 lot error 0.83 and 29% inside the range; 2026 0.60 and 23%.

Read honestly (previous fit): the spread and the top end were much better than the hand-set room and held out of time; lot-by-lot error
improved a little; the **2025 mega auction still ran about 1.5× above the simulation on contested
lots** (the mega level was fitted on one auction, 2022, with a 90 cr purse), and the 2026 ranking is
no better. The market model's per-player misses (Starc 2024: 3.4 predicted, 24.75 paid) stay misses:
calibration can widen the range around them, not fix them. Players it prices at base (uncapped
youngsters) that real teams had scouted (Rizvi 8.4 cr in 2024) are outside any bidding model.

**What the Auction room does now** (`scripts/auction_check.py`, 2026-10-22 evening export). With the
2025 retentions charged by the slab rule (KKR 69, DC 47, CSK 65 … all ten as published) and a 120 cr
purse: every team reaches 20–25 players, about 6 cr of purse left on average (PBKS, with the most money,
about 23), 200 lots sold. With no cap, averaged over runs the dearest player sits near 20 cr and ten lots
average 10 cr+. The neutral setting (level 1, curve 1, no shock, no
tightness, no last price) is the old room: `opts["calib"]` overrides any of them.

---

## Part 4 — Bid plan: the same simulator, turned into a bidding sheet

The room answers "where does each star go?". **Bid plan** answers "what should *my* team bid?"
(page *Bid plan*, `cricdex bidplan --team RCB`; full method and the replay of the 2025 and 2026
auctions: [METHODOLOGY §12](METHODOLOGY.md#12-bid-plan-beta)).

1. **Rivals only.** Your team steps out; the other nine (their Keep-or-release squads, each opening
   at least 8 places) run through this simulator 200 times. In each run, for each player, the
   **price to beat** = the winning rival's max bid × 1.02, or his base price if nobody bid.
2. **Strength.** Your best XI's expected runs a match above replacement (since 2026-10-22: each player's
   batting at the balls he faces a match plus his bowling at the balls he bowls, × his P(plays), a lot's as
   a free agent, METHODOLOGY §6c; the XI's balls
   held to a side's 115 an innings; ≤ 4 overseas, a keeper, 5 bowling and 6 batting options, a
   replacement player, 0, for any gap) + 0.25 × the next four − 0.63 per role need missed. (Until then
   the XI's per-100-ball values were added up as if every player got the same balls, with a −15
   replacement and −3 a need.)
3. **The rule.** Stars first, bid up to *gain in strength ÷ λ*; λ (runs per crore) is the rate that
   gives the highest average strength across the 200 runs.

```
Worked example (made-up numbers). λ = 0.2 runs a match per crore.
Spinner A adds 1.66 runs a match of strength → max bid 8.3 cr. Rivals' prices to beat
over 200 runs: median 1.2 cr, 100% of runs ≤ 8.3 → "P(≤ max) 100%".
If A goes above 8.3, spinner B (who now fills the gap A leaves) adds 1.7
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
rough: a typical lot is off by a factor of about 1.9 out of time (mean
|ln error| 0.66; median 49%), the lots that sold for 10 cr+ come out at
about 0.36× their price (regression to the mean, Part 0), overseas players
lean about 1.2× high in median, and the retained stars price at about half
what their franchises pay to keep them (what a released player like them
fetches; Keep or release models the keeping).
The bidding is now calibrated to real auctions as a whole (level, spread, top end:
Part 3b), but the personalities are still hand-set and no model sees the scouting
behind a surprise buy. So the room faithfully **models** auction behaviour and
relative outcomes — it is **not** predicting the exact crore amounts of any
specific real auction.
