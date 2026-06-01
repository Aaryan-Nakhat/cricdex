# Shipping CricDex

CricDex ships as a **free static website** plus a **local-run toolkit**.
No package registry, no hosted server, no paid infra.

## The public face — GitHub Pages (live)

The web app is the ship: https://aaryan-nakhat.github.io/cricdex/

- `scripts/export_site.py` cooks every artifact (metrics, ratings, scout
  cohorts, profiles, records, venues, time-window leaderboards) into a
  static JSON tree under `site/public/data/`.
- `site/` is a React + Vite app that only *displays* those numbers — no
  backend, everything runs in the browser.
- **`deploy.yml`** builds `site/` and publishes to GitHub Pages on
  every push touching `site/**`.
- **`refresh-data.yml`** (manual "Run workflow") re-ingests Cricsheet,
  recomputes everything, re-cooks the snapshot, commits it, and triggers a
  redeploy — the only path that moves the site to the latest match date
  (browsers can't run JAX / XGBoost / Neo4j).

Cost: $0. GitHub Pages hosts the static site; GitHub Actions does the
periodic recompute.

## Running it yourself (local)

The CLI / TUI / Streamlit / FastAPI surfaces run locally over your own
`data/` (Cricsheet ball-by-ball, ~600 MB, gitignored).

```bash
git clone git@github.com:Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync --extra cli --extra graph --extra ui
uv run cricdex --help              # CLI / TUI
uv run streamlit run src/cricdex/dashboard/app.py   # dashboard
```

Or the full stack (incl. Neo4j + Qdrant) via Docker:

```bash
make docker-up                     # build + run locally
```

See [`RUNNING.md`](RUNNING.md) for the contributor quickstart and
[`DOCKER.md`](DOCKER.md) for the image / compose layout.

## Not in scope

No PyPI package and no GHCR image — CricDex isn't distributed as a
third-party install; the website is the public artifact and local dev is
clone + `uv`. (Both were considered and dropped: nobody needs to
`pip install` or `docker pull` a personal project that already has a live
demo, and a ~10 GB image built on every push was pure waste.)
