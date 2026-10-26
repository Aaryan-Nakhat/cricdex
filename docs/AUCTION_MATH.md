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
  it and rounded. (The discounts and translation uncertainties were replaced
  on 2026-10-23 by translations fitted per league and role: Part 2 and
  METHODOLOGY §6d. The check that already showed they depended on role —
  SMAT +22 for batters / +7 for bowlers against one discount of 17 — is what
  the fit now does properly.)
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

- **IPL players under contract** — in the next competition's squads (the
  squads file with the 2026 auction, trades, retirements and releases
  applied); retainable, each carries his franchise.
- **Free agents** — everyone else: overseas talent via the **BBL** (Australia), **SA20**
  (South Africa), **CPL** (West Indies) and the **T20 Blast** (England), and
  uncapped Indians via the **SMAT** (Syed Mushtaq Ali Trophy).

With guardrails so it stays realistic:

- **Not retired** — an announced retirement (with its dated sources) in
  `data/curated/ipl_availability.json` keeps a player out (Bravo, Dinesh
  Karthik, Shikhar Dhawan, Amit Mishra, Rayudu, Pollard, Rahane, …). A
  player who only skipped an earlier auction (Warner, du Plessis in 2026)
  stays, priced by his P(plays).
- **Active only** — a T20 match in a pool league within 3 years. From the
  data: after 3 years without a match 1.9% of players (4.4% of former IPL
  players) played an IPL match again, after 2 years 3.6% (9.5%)
  (`scripts/inactivity_gap.py`, METHODOLOGY §7).
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
- **League translation** (since 2026-10-23, audit item 5) — a rating is relative to its own
  league, so each other league's rating is put on the IPL rating scale by a translation
  **fitted per league and per role** on every player seen in both (`IPL rating ≈ a + b ×
  league rating`, with its own translation sd; `config/league_translation.json`,
  METHODOLOGY §6d). What a +10 rating becomes in the IPL, batter / bowler: SMAT −9.1 / +0.8,
  BBL +8.8 / +9.1, SA20 +7.2 / +6.8, CPL +6.1 / +9.3, T20 Blast +1.5 / +7.0, PSL +11.1 / +8.1,
  ILT20 +5.0 / +8.4, The Hundred +12.1 / +7.8, MLC +1.6 / +9.0, BPL +2.7 / +8.5, LPL −2.3 / +8.3,
  Super Smash −3.0 / +7.5, CSA T20 +6.9 / +9.0. (Until then: one hand-set discount per league,
  both roles alike — SMAT −17, BBL / SA20 −6, CPL / Blast −8.5, eight leagues borrowing one.)
- **Several leagues, one value** — his IPL rating and every translated league are blended by
  precision (1 ÷ sd², the translation sd included): a long IPL record dominates because its sd is
  small, a thin one is filled in by the other leagues, with **no cut-off** (until 2026-10-23 a
  role record of 300+ IPL balls ignored every other league outright, a cliff added because the
  flat discount was "too harsh on stars"). A hot spell in a weaker league can't outrank a real IPL
  record because its translation is wide.
- **The market price keeps its own input** — the price recipe was fitted on the blend it replaced
  (one discount per league, the 300-ball switch), and a recipe on the translated value did not
  price the held-out auctions better (METHODOLOGY §6d), so `price_value` stays that blend until one
  does. Everything else — `value`, contributions, the pool's order, Bid plan's strength, the
  on-field worth — uses the translation.

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

**Then the lots.** As many as real shortlists held for the open places: 4.6 per open squad place in a
mini auction, 3.0 in a mega (the 2018–2024 shortlists on Wikipedia's personnel pages), at most 35.7% of
them overseas (the shortlists' median). The most valuable unretained players make the list. They come up
in the real set order: the capped sets first (a mega auction's marquee sets are its best-known capped
players), then the uncapped, dearest first within each. Unsold lots come back once in an accelerated round.

**For each lot, every team decides** whether to bid at all and how high, by one demand model fitted on who
really bought whom, and for how much, at the 2019–2026 auctions (Part 3b). A team can bid only with a
squad place, an overseas place if he's overseas, and the purse for his base price after keeping the lowest
base price for each place it still needs to reach 18 (the IPL purse rule).

```
bids at all?   more likely when it's short in his role, for a dearer market price and base price,
               a little less likely with a bigger purse per place
its bid        = e^(level + its needs + heat + its own view), at most its spendable purse
  level        his market price (with a slope of its own above 2 cr) and base price, the last price
               he went for, the money per open place across the bidding teams, how far the auction
               has gone
  its needs    places short in his role, its open overseas places (overseas lots), its purse per
               open place against the others', how much he'd improve its best player in his role
  heat         how hot he is on the day, shared by every team (sd 0.55 in ln)
  own view     each team's own taste (Gumbel, scale 0.46 in ln)
```

**The highest bid wins, one ladder step above the second-highest** (5 lakh below 1 cr, 10 lakh to 2 cr,
20 lakh to 5 cr, 25 lakh above), or at the base price when nobody else reaches it. There is no price cap:
the purse rule is the only bound. A team still short of 18 after the accelerated round buys the cheapest
leftovers at base price.

**Worked example (made-up numbers).** A capped batter with a 2 cr base price, three teams with room:

```
Team A: short of batters, 40 cr for 8 places   → bids (P 0.45), view +0.6 → bid 14.0 cr
Team B: batters covered, 25 cr for 10 places    → bids (P 0.30), view −0.2 → bid  5.1 cr
Team C: no bid this time                        (P 0.30)
→ A wins at 5.25 cr: one ladder step (25 lakh above 5 cr) over B's 5.1, not its own 14.0.
```

That's **one** mock auction. We run it ~300 times, then average:

- each team's typical spend, squad size, value, and overseas count,
- for each star, the **% of runs each team won him** —
  "Bumrah → MI 62%, CSK 21%" is your real odds in a bidding war,
- one sample league you can browse.

The randomness comes from a seeded generator, so the same settings always
reproduce the same result.

---

## Part 3b — The bidding, fitted on real auctions

Until 2026-10-23 the bidding was hand-set (team personalities, need 1.5 / 0.7, a budget pressure clamped to
0.75–1.6, 200 lots with 36% overseas) with five knobs calibrated on top (a level per auction type, a curve,
a last-price weight, a demand shock, market tightness). It now comes from one model, fitted:

**The data.** Every sold lot of the 2019–2026 auctions, with each team's squad by role, overseas count, purse
and best contribution per role rebuilt lot by lot from the real retentions and the sold lots, in the order
the history lists them (the set order; inside a set the page's order). Each lot carries what was known
before that auction: his contribution and P(plays), his last price, and a market price from the price recipe
fitted on the other 2018–2024 auctions (2019–2024) or on the auctions before (2025, 2026).

**The likelihood** of each real sale is exact under the model: the winner's bid at least the price, the best
of the others' within the ladder step below it (below the base price for a sale at base), given that he sold
(the history lists no unsold lots), the lot's heat integrated out.

**Frozen protocol, in two rounds.** Round 1: nine candidates (market price only; + role and overseas need;
+ purse per place; + upgrade; + stage; + a mega level; + team effects; + needs in whether a team bids; + his own
contribution), chosen by leave-one-auction-out over 2019–2024, tested once on the 2025 mega and 2026 mini
auctions: the team's needs in both whether it bids and how high (D7). Team effects ("personalities" learned
from the data) lost out of time. D7 priced the 2025 stars at about a third of their real price (Pant 9.0 cr
against 27; the market price alone 21.5), so round 2 tested the causes, with a reality criterion on the 2019–2024
auctions declared first (METHODOLOGY §7 has every number): the auction likelihood already uses the order
statistics (winner's bid ≥ price, runner-up within a ladder step) and fits both spreads; a heavy-tailed heat
collapsed to one component; bidding in proportion to the market price, or dropping the base price from the
level, loses out of time; what the data show is that the 2019–2024 market price missed the mini-auction stars
(their real prices 2–8× it). A slope of its own for the market price above the top base price (2 cr) wins
round 2 and ships, refitted on 2019–2026.

**What it found.** A team short in a lot's role bids more often and a little higher; an overseas lot draws
more from a team with overseas places free; a team with more purse per open place than the others bids higher;
more money per place across the market lifts every bid; bids fall as the auction fills. The market price
lifts a bid weakly up to 2 cr and by +0.22 per ln above it.

**How low can a calibrated room price the dearest lots?** Take one simulated run as if it were the real
auction: its 10 dearest lots (picked by their outcome) land inside the other runs' 10–90% range 70% of the time,
at 2.3× the other runs' median. "The real top 10 at the simulated median" can't be asked of any room; "inside the
range about seven times in ten" can.

**Out of time** (all ten teams bid, 300 runs; the room before 2026-10-23 on the same inputs in brackets):

| | 2025 mega (test) | 2026 mini (test) |
|---|---|---|
| real price inside the simulated 10–90%, all sold lots (80% = calibrated) | **67%** (64%) | **70%** (56%) |
| the same, contested lots (market price ≥ 2× base) | **69%** (62%) | **85%** (50%) |
| median real ÷ simulated, contested | **1.45** (1.55) | **1.00** (1.00) |
| error, mean abs. ln, all sold lots | **0.65** (0.62) | **0.60** (0.64) |
| the 10 dearest simulated lots, simulated ÷ real | **1.06** (1.15) | **0.81** (0.78) |
| the real buyer is the simulation's most frequent buyer | **16%** (9%) | **19%** (16%) |
| the real top 10 inside their simulated range | **7 of 10** (D7: 6) | 5 of 10 (D7: 5) |

The spread and the buyer are better; the level of the 2025 mega auction is still about 1.45× above the
simulation on contested lots; the typical price of a star is still low (2025: Pant 10.6 cr median, range
3.2–32.3, real 27; Shreyas Iyer 11.5, 4.6–35.5, real 26.75). Read a star's price as its range. Players the market
prices at base that teams had scouted (Kartik Sharma, Prashant Veer, 14.2 cr each in 2026) stay outside any
bidding model.

**What the Auction room does now** (`scripts/auction_check.py`, scratch export of 2026-10-23, the 2025 mega
with the real retentions charged by the slab rule, 120 cr, 200 runs): 390 lots (of 555 unretained players: every
Indian in the pool, overseas up to the share), 340 sold; every team ends with 22–23 players and 1.4–5.8 cr
left (2.8 on average); the dearest by average price when sold: Vaibhav Suryavanshi 24.9, Noor Ahmad 22.9,
Cameron Green 17.3, Rishabh Pant 17.3, Jofra Archer 16.7, Arshdeep Singh 16.1, Shreyas Iyer 16.1 (PBKS, with
110.5 cr left after its two retentions, buys most of them); 19 lots average 10 cr+.

---

## Part 4 — Bid plan: the same simulator, turned into a bidding sheet

The room answers "where does each star go?". **Bid plan** answers "what should *my* team bid?"
(page *Bid plan*, `cricdex bidplan --team RCB`; full method and the replay of the 2025 and 2026
auctions: [METHODOLOGY §12](METHODOLOGY.md#12-bid-plan-beta)).

1. **Rivals only.** Your team steps out; the other nine (their Keep-or-release squads, each opening
   at least 8 places) run through this simulator 200 times. In each run, for each player, the
   **price to beat** = one ladder step above the winning rival's bid, or his base price if nobody bid.
2. **Strength.** Your best XI's expected runs a match above replacement (each player's batting at the balls
   he faces a match plus his bowling at the balls he bowls, × his P(plays), a lot's as a free agent,
   METHODOLOGY §6c; the XI's balls held to a side's 115 an innings; ≤ 4 overseas, a keeper, 5 bowling and 6
   batting options, a replacement player, 0, for any gap) + the bench filling the matches the XI misses:
   Σ (1 − P(plays)) over the XI, best bench contribution first, at most one appearance a match for a squad
   player and at most his P(plays) for an auction lot (since 2026-10-23: until then a 40-year-old free agent
   who plays 4% of the time filled a whole appearance a match at his career contribution and topped the
   lists). Role needs are reported, not scored. (Until 2026-10-23: + 0.25 × the next four − 0.63 per role
   need missed, both hand-set.)
   "Above replacement" means above the freely available player (a minimum-price buy) **at his own batting
   position and bowling load**: since 2026-10-26 a smooth curve in each, fitted on past minimum-price buys,
   not four position groups (a No. 7.5 lower-order hitter used to be measured against bowlers batting at
   9–11 and topped nine sheets; METHODOLOGY §6c).
3. **The rule.** Stars first, bid up to *(gain in strength − a squad place's worth) ÷ λ*, where λ is what
   a crore can still buy later in this auction: the lots still to come, ranked by gain ÷ expected price, filled
   within the money and places left; λ = the ratio of the first lot the money no longer covers. Money left
   after the auction buys nothing for the season, so when the places run out first λ is 0 (the purse is the
   limit) and a place is worth the gain of the lot it would push out. Chosen on the 2024 auction against what
   real teams spent (a median 0.76 of the purse at mini auctions, 0.99 at megas). Until 2026-10-26 one λ for
   the whole auction, chosen for the most strength, left 30–90% of the purse unspent.

```
Worked example (made-up numbers).
(Say λ = 0.2 at this lot: the later lots' marginal gain per crore.)
Spinner A adds 1.66 runs a match of strength → max bid 8.3 cr. Rivals' prices to beat
over 200 runs: median 1.2 cr, 100% of runs ≤ 8.3 → "P(≤ max) 100%".
If A goes above 8.3, spinner B (who now fills the gap A leaves) adds 1.7
→ fallback: "A up to 8.3 → if he goes above that: B up to 8.5".
```

A team never bids for its own releases: if one is worth more to the squad than his salary, the plan says
"reconsider keeping" instead. Read the max bid as "where the value runs out" (walk away above it), and
"usually enough" as what wins him 9 times in 10. How often "P(≤ max)" came true, by band, is in
METHODOLOGY §12.

---

## The one honest caveat

The market price is **fitted to real sale data** (Part 0), but it is
rough: a typical lot is off by a factor of about 1.9 out of time (mean
|ln error| 0.66; median 49%), the lots that sold for 10 cr+ come out at
about 0.36× their price (regression to the mean, Part 0), overseas players
lean about 1.2× high in median, and the retained stars price at about half
what their franchises pay to keep them (what a released player like them
fetches; Keep or release models the keeping).
The bidding is fitted on real auctions (Part 3b) and its spread holds out of time, but the market price
misses the mini-auction stars (their real prices 2–8× it), so a star's typical price comes out low, and no
model sees the scouting behind a surprise buy. So the room faithfully **models** auction behaviour and relative outcomes — it is **not**
predicting the exact crore amounts of any specific real auction.
