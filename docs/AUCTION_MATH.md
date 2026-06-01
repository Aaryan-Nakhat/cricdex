# How the Auction room works (the math, in plain words)

The Auction room answers two questions a real franchise faces:

1. **"What's the best squad I can buy?"** — on a fixed budget, with squad
   rules.
2. **"If all ten teams bid, who lands which star?"**

But there's a wall first: the data only tells us how **good** a player is
(a skill rating). It never tells us what he **costs**. So step zero is
inventing a fair price from skill.

---

## Part 1 — Turn skill into a price tag

Think Zillow estimating a house price from its features. Our one feature
is the player's **skill score** (a small number from the Bayesian model:
average ≈ 0, stars positive, weak players negative).

Three moves:

1. **Exponentiate — `e^skill`.** This makes the scale *multiplicative*: a
   star isn't "a bit" better, he's a multiple.
   - skill 0 → ×1.00
   - skill +0.3 → ×1.35
   - skill −0.3 → ×0.74
2. **Scale to crore.** Multiply by a role weight (all-rounders are rarer →
   weighted higher) and a constant, so the best players land around
   10–12 cr.
3. **Out come two numbers:**
   - **projected value** — what he's worth.
   - **base price** — his opening tag, snapped to real IPL bands:
     0.3 / 0.5 / 0.75 / 1.0 / 1.5 / 2.0 cr.

The number that matters most:

> **value per credit = projected value ÷ base price** — quality per rupee.
> A bargain has a high ratio.

**Worked example — "Player X", skill +0.25:**

```
e^0.25            = 1.28
× 0.5 (batter)    × 4   = 2.56 cr   ← projected value
opening tag             = 0.50 cr   ← base price
value per credit  = 2.56 / 0.50     = 5.1   (cheap and good)
```

---

## Part 2 — Build my squad (you, shopping smart)

This is the classic **"fill a cart on a budget"** problem (a knapsack),
plus extra rules: squad size, overseas cap, and a minimum number of
players per role.

Strategy — buy the best value-for-money, but cover requirements first:

- **Pass 1 — minimums.** For each role (bat / bowl / all-rounder / keeper),
  buy the highest value-per-credit players until that role's minimum is
  met. Skip anyone you can't afford or who'd break the overseas cap.
- **Pass 2 — spend the rest.** Fill the remaining slots with the best
  value-per-credit players left, regardless of role, until the squad is
  full or the money runs out.

**Why value-per-credit?** When cash is the bottleneck, "most quality per
rupee" is the correct greedy ranking. It's near-optimal and instant. (The
desktop tool solves the exact optimum as a mixed-integer program.)

So in the UI: lower the overseas cap → it swaps imports for the next-best
Indians; shrink the purse → it trades stars for value picks.

---

## Part 3 — Simulate the auction (the whole room, many times)

Now you're not shopping alone — ten franchises bid against each other,
each with a **temperament**. The auction runs player-by-player, stars
first. For each player, every team works out a **max bid**:

```
max bid = value × aggression × need × overseas-bias × luck
```

- **value** — the player's projected worth.
- **aggression** — the team's style (MarqueeChaser 1.35 splurges;
  ValueHunter 0.85 holds back).
- **need** — 1.5 if the team still needs that role, 0.7 once it's covered
  (so teams chase what they lack).
- **overseas-bias** — boosts the bid for imports if the team loves overseas
  talent; 1 for Indians.
- **luck** — a small random nudge sized by the team's risk appetite. This
  is what makes each run differ.

A team also can't bid past its remaining money, its squad size, or its
overseas cap.

**Highest max bid wins.** But — like a real auction — the winner pays just
**above the second-highest bid**, not his own max (you stop bidding the
moment everyone else drops out).

**Worked example — bidding for Player X (worth 10):**

```
MI  (MarqueeChaser, needs a batter): 10 × 1.35 × 1.5 × 1 = 20.3
CSK (Balanced, batters already full):10 × 1.00 × 0.7 × 1 =  7.0
→ MI wins, pays ≈ 7.1 cr (just over CSK) — NOT its full 20.3.
```

That's **one** mock auction. We run it ~300 times, reshuffling the order
slightly each time, then average:

- each team's typical spend, squad value, and overseas count,
- for each star, the **% of runs each team won him** —
  "Bumrah → MI 62%, CSK 21%" is your real odds in a bidding war,
- one sample league you can browse.

The randomness (the "luck" + slight reshuffles) comes from a fixed seeded
generator, so the same settings always reproduce the same result.

---

## The one honest caveat

Prices are **invented from skill**, not real auction data. So the room
faithfully **models** auction behaviour and relative outcomes — it is
**not** predicting the actual crore amounts of a real IPL auction.
