# metrics

Novel context-adjusted ratings. Skip commodity (avg/SR/eco) — only ship novel.

## Batter

- Pressure Runs — runs when required RPB > venue median for phase.
- Intent Curve — SR per ball-faced bucket.
- Recoverability Index — runs in next 6 balls after dot/partner-wicket.
- Crease Stickiness — balls before first boundary.
- Boundary Dependency Ratio — % runs from 4s/6s.
- Phase Dilation — actual balls faced vs expected given dismissal prob.
- Counter-Attack Coefficient — SR in 12 balls after partner wicket.
- Mismatch Exploit Rate — xRuns vs bowler with known weakness in batter's strong zone.
- Travel Penalty — home/away/neutral perf delta.
- Shot Risk Premium — per-shot xRuns minus xWicket cost.
- Spin Read Time — SR vs spin first 6 balls vs after.
- Setting Tax — SR before 20-ball mark deducted from career.

## Bowler

- Sequence Setup Score — Markov mining of delivery N-1 predicting wicket-ball N.
- Disguise Coefficient — outcome variance for same line/length (year-2, needs CV).
- Sticky Dot Pressure — wicket rate after 4+ dots.
- Phase Versatility — inverse-variance of economy across phases.
- LHB-RHB Asymmetry — perf gap.
- First-Up Wobble — 1st-over economy vs rest.
- Bounceback Rate — economy in over after being hit for 12+.
- Counter-Hitter Index — wickets of attacking batters vs defenders.
- Repeat Punishment — same length+line struck twice in over by same batter.

## Composite

- Net Game Impact (NGI) — leverage-weighted sum of runs + wickets + fielding.
- Replacement Delta — cricket WAR.
- Clutch Quotient — NGI in high-leverage / overall.
- Career Volatility — std dev of monthly NGI.
- Style Twin — k-NN in 25-dim metric space.

## Scout-specific

- Opposition-Adjusted Rating (OAR) — Bayesian with opponent-strength prior.
- Trajectory Slope — rating delta per match.
- Bridge Score — fraction of opponents that exist in pro tier.
- Wicket Quality — Σ(opponent OAR) of wickets taken / wickets taken.
- Punishment Selectivity — opponent strength when batter scores big.
