# Running CricDesk

Two supported paths: **Docker (recommended for first-time users)** and **local uv**.

## A. Docker — anyone, one command

### Prerequisites

- Docker Engine 24+
- Docker Compose v2 (`docker compose` subcommand)
- ~4 GB free disk for the image + Cricsheet cache

### Boot the stack

```bash
git clone https://github.com/Aaryan-Nakhat/cricdesk.git
cd cricdesk
cp .env.example .env   # optional — only for the LLM taxonomy (LLM_MODEL + the provider's key)
make docker-up
```

This brings up one service (the Streamlit `dashboard` service is behind a
compose profile, see below):

| Service | Container name | Port | Purpose |
|---|---|---|---|
| `cricdesk` | `cricdesk-app` | 8080 | FastAPI app (`/health` for liveness) |

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
Blast), shared with the web via `cricdesk.web_parity`.

```bash
cricdesk scout look-alikes "V Kohli"
```

UI: dashboard page **Scout** (web-identical).

### Auction room

Real-rules IPL auction Monte-Carlo, shared with the web via
`cricdesk.web_parity`.

```bash
cricdesk auction room --mode mega
```

UI: dashboard page **Auction** (web-identical). After a run, look up any
player (retained / sold / unsold) via the post-sim search. See
[`AUCTION_MATH.md`](AUCTION_MATH.md).

### Keep or release (retentions)

The retention calculator for one franchise, shared with the web page
**Keep or release** via `cricdesk.web_parity.keep`:

```bash
cricdesk keep --team RCB
cricdesk keep --team CSK --release "MS Dhoni" --keep "Shivam Dube" --need spinner=4 --csv csk.csv
```

It reads `site/public/data/ipl/keep.json`, which `scripts/export_site.py` writes with the IPL
collection (`-c ipl`). The inputs it is built from:

- the cycle's rules: `config/competitions.toml` (`uv run python -m cricdesk.competitions check`);
- the squads and salaries: `data/curated/ipl_squads_2026.json`, refreshed from Wikipedia by
  `uv run python scripts/ipl_squad_salaries.py` (hand edits are kept unless `--force`);
- captaincy: `data/curated/ipl_captains.json`, from Wikipedia by `uv run python scripts/ipl_captains.py
  [--fetch]` (hand edits with `"edited": true` are kept);
- the market-price model: `config/price_model.json`, fitted to `data/curated/ipl_auction_history.json`
  (`uv run python scripts/ipl_auction_history.py [--fetch]`) by `uv run python scripts/ipl_price_model.py
  fits` (the IPL re-fitted before every auction: ~45 min the first time, cached and resumable; run it as
  a scheduled task on a laptop that sleeps) and then `... ipl_price_model.py fit` (seconds to minutes).

After editing either, re-export the IPL collection:

```bash
uv run python scripts/export_site.py -c ipl --skip-prep
```

### Bid plan (the auction bidding sheet)

Built on Keep or release's data (no extra export): the page **Bid plan**, or

```bash
cricdesk bidplan --team RCB
cricdesk bidplan --team CSK --release "Prashant Veer" --need spinner=4 --max "Rashid Khan=12" --csv csk.csv
```

When the official auction list is published (after the 15 November retentions), write it to
`data/curated/ipl_auction_register.json` as `[{"id": "<cricsheet id>", "base_price": 2.0}, …]` (also update
`data/curated/ipl_squads_2026.json` with the real retentions) and re-export the IPL
(`scripts/export_site.py -c ipl --skip-prep`): the page and the CLI then plan on exactly those players.
The replay of the 2025 and 2026 auctions (about 12 minutes; resumable per team):

```bash
uv run python scripts/bidplan_backtest.py --work /tmp/bidplan --out bidplan_report.json
```

It needs the walk-forward fits of `scripts/ipl_price_model.py fits` (cached).

### Form forecast (next three seasons)

Each IPL player's value projected over the next three seasons (profile section, `cricdesk forecast
"<name>"`, `cricdesk forecast --team RCB`; method: [METHODOLOGY §11](METHODOLOGY.md#11-form-forecast)):

```bash
uv run python scripts/form_forecast.py fits --seeds 42      # the ratings at every season end (shares
                                                            # ipl_price_model.py's cache; ~1 h if empty)
uv run python scripts/form_forecast.py build                # → data/metrics/forecast_ipl.json (~1 min)
uv run python scripts/form_forecast.py export               # → site/public/data/ipl/forecast.json
uv run python scripts/form_forecast.py fits --seeds 43,44 --last 2024   # only for the 3-seed backtest
uv run python scripts/form_forecast.py backtest             # → data/metrics/forecast_backtest_ipl.json
```

`build` reads the current ratings (`data/metrics/scout_ratings_ipl.json`), so run it after the IPL is
refit, then `export` (or re-export the IPL with `scripts/export_site.py -c ipl`, which writes
`forecast.json` and the Keep or release "3-season outlook" from `data/metrics/forecast_ipl.json`). The fits are long and resumable: on a laptop that sleeps, run `fits` as a scheduled
task and watch its `--log` file.

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
git clone https://github.com/Aaryan-Nakhat/cricdesk.git
cd cricdesk
uv sync --group dev --extra ui
cp .env.example .env
# Set LLM_MODEL (+ the provider's key) for the taxonomy
# enrichment — optional.
```

### Run pipelines

```bash
make refresh COLLECTION=ipl   # download → ratings → metrics → site data, one collection
make refresh-all              # every exported league, one export at the end (hours)
make rebuild-all              # same, resumable: re-run to continue after a failure or reboot
bash scripts/rebuild_all.sh --from ratings   # keep the ingested data: refit ratings, metrics, export
uv run python -m cricdesk.pipeline --list      # the steps in order (docs/PIPELINE.md)
make auction-check            # sanity-check the IPL auction on the exported data

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
(`uv run python -m cricdesk.leagues list --exported`; how to add one:
[LEAGUES.md](LEAGUES.md)). The Auction pool and Scout read every league's
ratings at once, so after re-ingesting several leagues refit all of them
before the final `export_site.py`.

`CRICDESK_LEAGUES=/path/to/leagues.toml` points every command at a different
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
| `CRICDESK_HOME` | optional | Where config lives (default `~/.cricdesk`). |
| `CRICDESK_DATA_DIR` | optional | Override the data folder (default: the repo's `data/` in a clone). |
| `CRICDESK_LEAGUES` | optional | Path to a league registry TOML (default: `config/leagues.toml`; see [LEAGUES.md](LEAGUES.md)). |

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
