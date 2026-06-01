# CricDex — static web frontend

A React + Vite + Tailwind single-page app that displays the pre-cooked
CricDex data snapshot. **No backend**: everything is computed offline by
`scripts/export_site.py` and served as static JSON under
`public/data/`. The browser only ever renders numbers.

Live: https://aaryan-nakhat.github.io/cricdex/

## Develop

```bash
cd site
pnpm install
pnpm dev          # http://localhost:5173/cricdex/
```

The app reads `public/data/<collection>/…`. Regenerate that snapshot
from the repo root:

```bash
uv run python scripts/export_site.py            # all collections
uv run python scripts/export_site.py -c ipl     # one
```

## Build

```bash
pnpm build        # → dist/  (base path /cricdex/)
pnpm preview      # serve the build locally
```

## How it ships

- **`deploy-pages`** workflow builds `dist/` and publishes to GitHub
  Pages on every push to `site/**`.
- **`refresh-data`** workflow (nightly) re-ingests Cricsheet, recomputes
  metrics + Bayesian ratings + the scout graph, re-cooks
  `public/data/`, and commits it — which triggers a redeploy. That is
  the "refresh to the latest match date" mechanism; it can't run in the
  browser because the models need JAX / XGBoost / Neo4j.

## Features

Overview · Leaderboards (10 metrics) · Player profile (4 Bayesian skill
axes + uncertainty, career, metrics, dismissal fingerprint, twins) ·
Compare · Head-to-head P(A>B) · Scout graph · Auction room · Records ·
Venues · How it works.
