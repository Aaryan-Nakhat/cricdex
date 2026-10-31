# dashboard

Streamlit app surfacing every CricDesk feature. Multi-page (Streamlit
auto-discovers `pages/`): the home module (`app.py`) is the landing
explainer, plus 14 pages (`1_Leaderboards` … `16_Aging`). Shared widgets in
`_widgets.py`: `player_select`, `player_multiselect`, `collection_picker`,
`provenance_banner`. Every row carries the Cricsheet people-register bridge
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
- **Head-to-Head** — P(A better than B) from the Bayesian posteriors, with a gauge
  (reads the local `data/metrics/scout_ratings_<col>.json`, not the snapshot).
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
- **Update Data** — in-app buttons to re-run the ingest → compute → export pipeline.

The metrics: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery,
Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality,
Crease Longevity, Slow-Start Cost, Wicketkeeping, Fielding.

Every page except Head-to-Head and Update Data reads the exported JSON snapshot
(`site/public/data/`, the same files the web app reads). The Leaderboards page
lists the collections found there; the other pages' `collection_picker` lists the
`balls_*` tables in the local DuckDB (falling back to `ipl` when there is none).

## Run

```bash
make docker-dashboard-up      # serves on http://localhost:8511
make docker-dashboard-down    # stop it
```

Local without Docker (from the repo root):

```bash
uv sync --extra ui
uv run cricdesk dashboard     # free local port, prints the URL; --port pins one
```

## Refresh data

The app reads the exported snapshot, so a refresh has to re-export it:

```bash
make refresh COLLECTION=ipl   # download → ratings → metrics → export
# or use the Update Data page; then rerun the page — Streamlit re-reads on rerun
```

## Add a new metric

1. Implement it in `cricdesk.metrics.*` and wire a CLI subcommand in
   `scripts/compute_metrics.py`.
2. Append a `MetricDef` to the shared catalog `cricdesk.common.metrics.METRICS`
   (slug, name, what/how copy, `name_col`, `higher_is_better`, and the column
   layout with one `primary=True` column), and mirror it in
   `site/src/lib/metrics.ts` for the web.
3. Add the slug to `METRIC_SLUGS` in `scripts/export_site.py` and re-run it so
   the leaderboard JSON lands in the snapshot.

That one catalog drives the Streamlit + TUI leaderboards and the `cricdesk
leaderboard` CLI generically — no per-surface edits needed.
