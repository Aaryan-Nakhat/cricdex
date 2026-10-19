# How the Auction room works (the math, in plain words)

> This describes the Auction room — a Monte-Carlo of a real IPL auction.
> The **same** logic runs on every surface: in the browser (TS,
> `site/src/lib/auction.ts`) and on the CLI / TUI / Streamlit (Python,
> `cricdex.web_parity`), from the **same** exported JSON and with a
> bit-exact seeded RNG, so a run reproduces everywhere trial-for-trial
> (locked by `test_scripts/test_web_parity.py`). It is driven from the CLI
> by `cricdex auction room`. The skill ratings it starts from, and every
> other model, are explained in [`METHODOLOGY.md`](METHODOLOGY.md).

The room answers one question a real franchise faces:

> **If all ten teams retain their core and then bid for everyone else,
> who likely lands which star — and for how much?**

But there's a wall first: the data only tells us how **good** a player is
(a skill rating). It never tells us what he **costs**. So step zero is
inventing a fair price from skill, calibrated to recent real auctions.

---

## Part 1 — Turn skill into a crore price

Think Zillow estimating a house price from its features. Our one feature
is the player's **skill score**, the Bayesian model's complete value, in
**runs per 100 balls above the league's average ball** (see
`scout/ratings/README.md` and [METHODOLOGY §4](METHODOLOGY.md)). For a
batter it is his extra scoring plus the runs his team doesn't lose because
he stays in, with a wicket priced at what it costs where he bats (about 14
runs early in the powerplay, 7–8 in the middle overs, 2–3 at the death);
for a bowler the runs he saves plus his extra wickets at the same price.
Average ≈ 0, the best IPL regulars sit around +20 to +25, weak players are
negative. The curve below is still hand-set, not fitted to sale data.

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
lots (a real auction lists far more, but most go unsold). They go up one
at a time, stars first. Each team
works out a **max bid**:

```
max bid = value × aggression × need × overseas-bias × luck × budget
```

- **value** — the player's projected worth (Part 1).
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

## The one honest caveat

Prices are **calibrated to recent real auctions** (the crore ceiling and
median are tuned to 2024–25), but they're still **invented from skill**, not
actual sale data. So the room faithfully **models** auction behaviour and
relative outcomes — it is **not** predicting the exact crore amounts of any
specific real auction.
