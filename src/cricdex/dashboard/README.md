# dashboard

Public-facing Streamlit app that surfaces every novel metric as a sortable
leaderboard with bar charts and the Cricsheet people-register bridge
(so every row carries Cricsheet + ESPNcricinfo identifiers for deeper
linking later).

## Layout

One tab per metric:

- Pressure Runs
- Recoverability
- Counter-Attack
- Boundary Dependency
- Intent Curve
- Sticky Dot Pressure (bowler)

Sidebar lets the user pick which ingested collection to slice by — every
JSON under `data/metrics/*_<collection>.json` is auto-discovered.

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

The app reads JSON snapshots, not the database directly, so the typical
flow is:

```bash
make docker-metrics-all COLLECTION=ipl  # regenerate JSONs
# refresh the dashboard tab — Streamlit re-reads on rerun
```

## Add a new metric

1. Implement it in `cricdex.metrics.*` and wire a CLI subcommand in
   `scripts/compute_metrics.py`.
2. Append a config block to `METRICS` in `app.py` with the slug, sort
   column, bar column, description, and (for bowler metrics)
   `primary_key="bowler"`.

That's it — the tab and chart are wired generically.
