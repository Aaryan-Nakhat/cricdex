# Running CricDex

Two supported paths: **Docker (recommended for first-time users)** and **local uv**.

## A. Docker — anyone, one command

### Prerequisites

- Docker Engine 24+
- Docker Compose v2 (`docker compose` subcommand)
- ~4 GB free disk for the image + Cricsheet cache

### Boot the stack

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
cp .env.example .env   # optional — only for the LLM taxonomy (LLM_MODEL + the provider's key)
make docker-up
```

This brings up one service (the Streamlit `dashboard` service is behind a
compose profile, see below):

| Service | Container name | Port | Purpose |
|---|---|---|---|
| `cricdex` | `cricdex-app` | 8080 | FastAPI app (`/health` for liveness) |

### Run the data pipelines (one-shot)

```bash
make docker-ingest-cricsheet COLLECTION=ipl  # download a Cricsheet collection → Parquet + DuckDB
make docker-ingest-people                    # Cricsheet People Register (cross-IDs)
make docker-metrics-all COLLECTION=ipl       # quick metrics pass → data/metrics/ (top 100 per board by default)
make docker-export COLLECTION=ipl            # re-cook site/public/data so the dashboard sees it
```

For a full refresh of one collection (download → ratings → all metrics →
site data) use `make refresh COLLECTION=ipl` from a local uv setup (B below).

### Browse the leaderboards

```bash
make docker-dashboard-up   # Streamlit on http://localhost:8511
make docker-dashboard-down # stop it
```

### Scout look-alikes

Cross-competition look-alike finder (IPL / SMAT / BBL / SA20 / CPL /
Blast), shared with the web via `cricdex.web_parity`.

```bash
cricdex scout look-alikes "V Kohli"
```

UI: dashboard page **Scout** (web-identical).

### Auction room

Real-rules IPL auction Monte-Carlo, shared with the web via
`cricdex.web_parity`.

```bash
cricdex auction room --mode mega
```

UI: dashboard page **Auction** (web-identical). After a run, look up any
player (retained / sold / unsold) via the post-sim search. See
[`AUCTION_MATH.md`](AUCTION_MATH.md).

### Other useful targets

```bash
make docker-logs    # tail app logs
make docker-shell   # interactive shell inside the app container
make docker-test    # run pytest inside the container
make docker-down    # stop everything
```

### Volume layout

- `./data` (bind mount) — Cricsheet downloads, DuckDB, metrics / ratings
  JSON, curated JSON. Editable from the host.
- `./site/public/data` (bind mount) — the exported JSON snapshot the API,
  CLI and dashboard read.
- `./src`, `./scripts` (bind mount) — code is hot-reloaded into the container
  so iteration is fast. Comment those mounts out in `docker-compose.yml`
  for a frozen image.

## B. Local uv (faster inner loop, single Python process)

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) 0.5+

### Setup

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync --group dev --extra ui
cp .env.example .env
# Set LLM_MODEL (+ the provider's key) for the taxonomy
# enrichment — optional.
```

### Run pipelines

```bash
make refresh COLLECTION=ipl   # download → ratings → metrics → site data, one collection
make refresh-all              # every exported league, one export at the end (hours)

# or step by step:
uv run python scripts/ingest_cricsheet.py list               # the league registry
uv run python scripts/ingest_cricsheet.py ingest --collection ipl --force
uv run python scripts/ingest_cricsheet.py ingest --collection indian_domestic_male  # SMAT (sma_json.zip)
uv run python scripts/scout_rate.py --collection ipl         # ratings first: Wicket Quality reads them
uv run python scripts/compute_metrics.py all --collection ipl
uv run python scripts/export_site.py -c ipl
```

Which collections exist, which Cricsheet zip each comes from and which ones are
exported is set in [`config/leagues.toml`](../config/leagues.toml)
(`uv run python -m cricdex.leagues list --exported`; how to add one:
[LEAGUES.md](LEAGUES.md)). The Auction pool and Scout read every league's
ratings at once, so after re-ingesting several leagues refit all of them
before the final `export_site.py`.

`CRICDEX_LEAGUES=/path/to/leagues.toml` points every command at a different
registry (a franchise's own league list, say) without editing the repo copy.

### Run the API

```bash
make api      # uvicorn on :8080 with --reload
```

### Run the test + lint suite

```bash
make check    # ruff lint + format check
make test     # pytest
```

## Environment variables

All settings are loaded from `.env` (see `.env.example` for the canonical
list). The most important ones:

| Variable | Required? | Notes |
|---|---|---|
| `LLM_MODEL` | for the taxonomy enrichment | Any LiteLLM model string, `<provider>/<model>`. The provider's key goes in the variable LiteLLM documents for that provider. |
| `LLM_API_KEY` / `LLM_API_BASE` | optional | Override the key / endpoint (a self-hosted or custom server). |
| `CRICDEX_HOME` | optional | Where config lives (default `~/.cricdex`). |
| `CRICDEX_DATA_DIR` | optional | Override the data folder (default: the repo's `data/` in a clone). |
| `CRICDEX_LEAGUES` | optional | Path to a league registry TOML (default: `config/leagues.toml`; see [LEAGUES.md](LEAGUES.md)). |

### Persistence

`data/` is `.gitignore`d except the curated player facts
(`data/curated/player_taxonomy.json`, `data/curated/wikidata_enrichment.json`),
which are committed. The Cricsheet DuckDB, computed metrics and Bayes ratings
can always be rebuilt from Cricsheet (`make refresh`), and the exported
snapshot in `site/public/data` is committed.

## Troubleshooting

- **Cricsheet download failures**: large collections (`all`, `tests_male`,
  `t20s_male`) can be hundreds of MB. The downloader caches by zip name
  so re-running resumes from the cached zip.

- **Docker build slow first time**: the deps layer installs the locked
  wheels (jax for the Bayesian ratings is the largest). Subsequent builds
  reuse that layer and finish in seconds.
