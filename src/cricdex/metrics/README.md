# metrics

Novel, context-adjusted ratings — the commodity stats (avg / SR / econ)
are skipped on purpose. Ten metrics ship today; each has a CLI subcommand
in `scripts/compute_metrics.py` (`compute_metrics.py all -c <collection>`
runs them all) and writes `data/metrics/<slug>_<collection>.json`.

## Batting

- **Pressure Runs** (`pressure_runs`) — strike rate on chase balls where
  the required rate exceeds the venue/phase median by ≥1.5×. Output:
  `pressure_runs`, `pressure_balls`, `pressure_sr_per_100_balls`,
  `pct_balls_under_pressure`.
- **Intent Curve** (`intent_curve`) — strike rate per balls-faced bucket;
  the shape of how a batter accelerates through an innings.
- **Dot-Ball Recovery** (`dot_ball_recovery`) — runs scored in the six
  balls after a dot. High = refuses to let dots compound.
- **Counter-Attack** (`counter_attack`) — strike rate on balls faced
  right after a partner is dismissed.
- **Boundary Dependency** (`boundary_dependency`) — share of runs from
  4s + 6s. Lower = better strike-rotator.
- **Crease Longevity** (`crease_longevity`) — balls survived per
  dismissal, indexed against the cohort (>1 = lasts longer than peers).
- **Slow-Start Cost** (`slow_start_cost`) — career SR minus setting
  (1st-innings) SR; the hidden cost of cautious starts.

## Bowling

- **Pressure Conversion** (`pressure_conversion`) — wicket rate on
  pressure balls (after a run of dots / tight overs).
- **Wicket Quality** (`wicket_quality`) — wickets weighted by the
  Bayesian batting value of the batter dismissed.

## Composite

- **NGI — Net Game Impact** (`ngi`) — leverage/win-probability-weighted
  runs added above replacement, batting + bowling, normalised per match.

Each metric also surfaces per-player on the Player Profile (CLI / TUI /
Streamlit / web) and feeds the Compare and Leaderboards views.
