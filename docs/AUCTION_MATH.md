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
is the player's **skill score** — the Bayesian model's complete value, in
"typical spreads above average": average ≈ 0, stars ~+3, weak players
negative (see `scout/ratings/README.md`). Since the context-adjusted fit
(season, phase, innings and ground terms; a bowler's economy now counts his
wides and no-balls), the skill is judged against each player's own era and
role, on the same sd scale, so the price curve below is unchanged; it is
still hand-set, not fitted to sale data.

1. **Amplify exponentially.** `1.1 × e^(0.95 × skill)`, times a small role
   weight (all-rounders / keepers are rarer → weighted up). The `0.95`
   stretches the curve so the spread matches recent real money — the top
   names land in the 20s (27 cr, the 2025 ceiling, is the cap), the typical
   pool player around 1 cr — and the result is clamped to `[0.3, 27]`.
2. **Discount for IPL relevance.** A player who hasn't featured in the IPL
   lately is worth less to an IPL auction *now*. Each player gets an
   IPL-relevance weight between 0 and 1: about 1 for a current IPL regular
   (last IPL game within ~18 months; age barely matters while he's playing),
   fading with years since his last IPL game and with age past 32; 0.7 for an
   uncapped Indian who has never played the IPL; lower for an older overseas
   leaguer. Up to 2.7 is taken off the value at weight 0 (about −2.2 in
   practice, since the weight never drops below 0.2). This is what stops
   retired or league-only veterans topping the buys.
3. **Out come two numbers:**
   - **projected value** — what he's worth, in crore.
   - **base price** — his opening tag, snapped to real IPL bands:
     0.3 / 0.5 / 0.75 / 1.0 / 1.5 / 2.0 cr. Bidding pushes the final price
     up from there.

**Worked example — "Player X", skill +1.6, played last month:**

```
1.1 × e^(0.95 × 1.6)        ≈ 5.0 cr   ← projected value
(− recency penalty if stale)
opening tag                 = 0.75 cr  ← base price
```

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
  in the IPL, so cross-tier values are discounted before pricing (**BBL −0.45**,
  **SA20 −0.45**, **CPL −0.64**, **T20 Blast −0.64**, **SMAT −1.28**; IPL 0; the newer
  leagues borrow these values and are marked provisional).
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
never more than **27 cr** (the real record, Pant in 2025).

**Two passes so the pool is shared fairly.** Round 1 fills every team to a
**20-man minimum**; round 2 tops up toward the **25 cap**. A final safety
pass guarantees no team is left below 20.

**Worked example — bidding for Player X (worth 10):**

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
