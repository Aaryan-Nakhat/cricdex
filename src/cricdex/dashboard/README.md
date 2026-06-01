# dashboard

Streamlit app surfacing every CricDex feature. Multi-page (Streamlit
auto-discovers `pages/`); the home module (`app.py`) is the landing
explainer. Every row carries the Cricsheet people-register bridge
(cricsheet_id + cross-source identifiers) for deeper linking.

## Pages

- **Leaderboards** — the 10 novel metrics, one tab each, sortable + bar charts.
- **Player Profile** — per-player dossier: Bayesian skills, metrics,
  dismissal fingerprint, style twins, Wikidata identity.
- **Compare** — 2–5 players side by side.
- **Records** — record books.
- **Venues** — ground conditions.
- **Auction** — squad optimiser + franchise simulation.
- **Update Data** — in-app buttons to re-run the ingest/compute pipeline.

The 10 metrics: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery,
Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality,
Crease Longevity, Slow-Start Cost.

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
2. Append a config block to `METRICS` in `pages/1_Leaderboards.py` with
   the slug, sort column, bar column, description, and (for bowler
   metrics) `primary_key="bowler"`.

The tab and chart are wired generically.
