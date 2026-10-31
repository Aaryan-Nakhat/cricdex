# metrics

Novel, context-adjusted ratings — the commodity stats (avg / SR / econ)
are skipped on purpose. Twelve leaderboards ship today (ten context
metrics + wicketkeeping + fielding); each has a CLI subcommand in
`scripts/compute_metrics.py` (`compute_metrics.py all -c <collection>`
runs them all) and writes `data/metrics/<slug>_<collection>.json`, which
`scripts/export_site.py` cooks into the site snapshot every surface reads.
Formulas: [`docs/METRICS.md`](../../../docs/METRICS.md). Plain-English
explanations with worked examples: [`docs/METHODOLOGY.md` §2–3](../../../docs/METHODOLOGY.md#2-net-game-impact-ngi).

Run one collection: `uv run python scripts/compute_metrics.py all -c ipl`
(or `cricdesk data ingest metrics -c ipl`, which also re-exports the site
data). Wicket Quality reads `data/metrics/scout_ratings_<collection>.json`,
so fit the ratings first (`scripts/scout_rate.py`).

**Players are keyed by registry id.** Every query reads
`common/sql.py::keyed_balls` / `keyed_wickets` (the ball and wicket tables
with each player column swapped for the id from that match's registry) and
`relabel`s the result, so each row carries `cricsheet_id`, the scorecard name
and `display_name`, and two players who share a scorecard name are two rows.
Write new SQL against the `__BALLS__` / `__WICKETS__` placeholders and run it
with `keyed_query(con, collection, sql, ("batter",))`.

Other modules here: `matchups.py` (batter-vs-bowler + pace/spin splits),
`phase.py` (powerplay / middle / death boards), `dismissal_fingerprint.py`
(how a batter gets out, on the profile).

## Batting

- **Pressure Runs** (`pressure_runs`) — strike rate on chase balls where
  the required rate exceeds the venue/phase median by ≥1.5×. Output:
  `pressure_runs`, `pressure_balls`, `pressure_sr_per_100_balls`,
  `pct_balls_under_pressure`.
- **Intent Curve** (`intent_curve`) — strike rate per balls-faced bucket;
  the shape of how a batter accelerates through an innings.
- **Dot-Ball Recovery** (`dot_ball_recovery`) — runs off the bat in the
  next six deliveries on strike after a dot, per 6 balls. High = refuses to let dots compound.
- **Counter-Attack** (`counter_attack`) — strike rate of the surviving
  batter over the 12 balls after a partner is dismissed.
- **Boundary Dependency** (`boundary_dependency`) — share of runs from
  4s + 6s. Lower = better strike-rotator.
- **Crease Longevity** (`crease_longevity`) — balls survived per
  dismissal, indexed against the cohort (>1 = lasts longer than peers).
- **Slow-Start Cost** (`slow_start_cost`) — career SR minus SR over the
  first 20 balls of any innings; the hidden cost of cautious starts.

## Bowling

- **Pressure Conversion** (`pressure_conversion`) — wicket rate on the
  next ball after 4+ consecutive dots in the same over.
- **Wicket Quality** (`wicket_quality`) — the mean Bayesian batting
  skill of the batters a bowler dismissed.

## Fielding

- **Wicketkeeping** (`keeping`) — catches + stumpings + run-out
  involvements credited to a keeper (every wicket on a delivery; a keeper
  by the player master's role, by id, or any stumping).
- **Fielding** (`fielding`) — outfield catches + run-out involvements
  (caught-and-bowled excluded).

## Composite

- **NGI — Net Game Impact** (`ngi`) — per-ball change in win probability,
  split into play / wicket / extras and credited to the striker, the batter
  who is out, the bowler and the fielders (`ngi_batting`, `ngi_bowling`,
  `ngi_fielding`), averaged per appearance in the XI. T20 only; the
  win-probability model (monotone, beta-calibrated, era-relative features)
  sees only the pre-delivery state and scores every ball out of fold.
  `compute_metrics.py ngi-diagnostics` prints its checks.

Each metric also surfaces per-player on the Player Profile (CLI / TUI /
Streamlit / web) and feeds the Compare and Leaderboards views.
