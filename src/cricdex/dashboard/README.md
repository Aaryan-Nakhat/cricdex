# dashboard

Streamlit app surfacing every CricDex feature. Multi-page (Streamlit
auto-discovers `pages/`); the home module (`app.py`) is the landing
explainer. Every row carries the Cricsheet people-register bridge
(cricsheet_id + cross-source identifiers) for deeper linking.

## Pages

- **Leaderboards** — 12 metrics (10 novel batting/bowling + Wicketkeeping &
  Fielding dismissal boards), one tab each, with a time-window
  switcher (all-time / last 3 yrs / last 1 yr), the full filter bar (role /
  activity / bowling / position / country / min matches), inline magnitude bars
  and the Intent-Curve sparkline.
- **Player Profile** — per-player dossier: Bayesian skills (with ±σ band),
  metrics, dismissal fingerprint, style twins, the graph cohort, Wikidata identity.
- **Compare** — 2–4 players side by side (radar + table).
- **Head-to-Head** — P(A better than B) from the Bayesian posteriors, with a gauge.
- **Matchups** — batter-vs-bowler head-to-heads (as batter / as bowler) + a
  batter's pace-vs-spin split with a "weaker vs" read.
- **Phase** — powerplay / middle / death specialist boards (best SR, tightest econ).
- **Form** — a metric recomputed over the recent window vs career, heating-up /
  cooling-down (direction-corrected form Δ).
- **Partnerships** — batter-pair stands: a player's most productive partners + the
  all-time best partnerships.
- **Aging** — performance-vs-age curves (batting / bowling) with an optional
  per-player trajectory overlay (Plotly).
- **Records** — record books (year-range filterable).
- **Venues** — ground conditions (phase run-rate chart).
- **Scout** — cross-competition look-alikes (6 tiers) + a "next big things" gems
  board + draft to Auction.
- **Auction** — real-rules IPL auction Monte-Carlo (retain → bid), web-identical.
- **Update Data** — in-app buttons to re-run the ingest/compute pipeline.

The metrics: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery,
Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality,
Crease Longevity, Slow-Start Cost, Wicketkeeping, Fielding.

Sidebar picks the ingested collection — every `data/metrics/*_<collection>.json`
is auto-discovered.

## Run

```bash
make docker-dashboard-up      # serves on http://localhost:8511
make docker-dashboard-down    # stop it
```

Local without Docker:

```bash
uv sync --extra ui
uv run streamlit run src/cricdex/dashboard/app.py
```

## Refresh data

The app reads JSON snapshots, not the database directly:

```bash
make docker-metrics-all COLLECTION=ipl  # regenerate JSONs
# then rerun the page — Streamlit re-reads on rerun
```

## Add a new metric

1. Implement it in `cricdex.metrics.*` and wire a CLI subcommand in
   `scripts/compute_metrics.py`.
2. Append a `MetricDef` to the shared catalog `cricdex.common.metrics.METRICS`
   (slug, name, what/how copy, `name_col`, `higher_is_better`, and the column
   layout with one `primary=True` column).

That one catalog drives the Streamlit + TUI leaderboards and the `cricdex
leaderboard` CLI generically — no per-surface edits needed.
