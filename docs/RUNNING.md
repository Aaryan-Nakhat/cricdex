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
cp .env.example .env
# Open .env and fill in any credentials you have (GEMINI_TMP_URL powers
# the player-taxonomy enrichment; the rest are optional).
make docker-up
```

This brings up one service:

| Service | Container name | Port | Purpose |
|---|---|---|---|
| `cricdex` | `cricdex-app` | 8080 | FastAPI app (`/health` for liveness) |

### Run the data pipelines (one-shot)

```bash
make docker-ingest-cricsheet        # download a Cricsheet collection → Parquet + DuckDB
make docker-ingest-people           # Cricsheet People Register (cross-IDs)
make docker-metrics-all COLLECTION=ipl  # compute every novel metric → data/metrics/
```

### Browse the leaderboards

```bash
make docker-dashboard-up   # Streamlit on http://localhost:8511
make docker-dashboard-down # stop it
```

### Scout look-alikes

Cross-competition look-alike finder (IPL / SMAT / BBL / SA20 / CPL /
Blast), shared with the web via `cricdex.web_parity`.

```bash
cricdex scout look-alikes "V Kohli" -c ipl
```

UI: dashboard page **Scout** (web-identical).

### Auction room

Real-rules IPL auction Monte-Carlo, shared with the web via
`cricdex.web_parity`.

```bash
cricdex auction room -c ipl
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
  JSON, curated JSON, exported snapshots. Editable from the host.
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
uv sync --group dev
cp .env.example .env
# Fill in GEMINI_TMP_URL (+ GEMINI_TMP_API_KEY) for the taxonomy
# enrichment, etc. — all optional.
```

### Run pipelines

```bash
uv run python scripts/ingest_cricsheet.py --collection recently_played_30_male
uv run python scripts/compute_metrics.py all -c ipl
```

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
| `GEMINI_TMP_URL` | for the taxonomy enrichment | Stop-gap proxy endpoint (`/generate`, `/generate_json`). Replace with personal `GEMINI_API_KEY` + `google-genai` before public launch. |
| `GEMINI_TMP_API_KEY` | optional | Sent as `x-api-key` if the proxy needs auth. |
| `DATABASE_URL` / `REDIS_URL` | wait for those modules | Documented but unused until the cache module lands. |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | for `make backup` | Cloudflare R2 backup target. Always-free 10 GB / zero egress. Create a bucket + API token at `dash.cloudflare.com → R2 → Manage R2 API Tokens`. Without these, the local `data/` directory is the only copy of artifacts that took a while to build. |

### Off-VM persistence

`data/` is `.gitignore`d and the Cricsheet DuckDB, computed metrics, and
Bayes ratings are the only copies on disk. To survive a VM rebuild, push
them to Cloudflare R2 (private bucket, 10 GB free forever, zero egress):

```bash
# one-time R2 setup: create a bucket, mint an API token, paste creds into .env
make backup WHAT=all                  # tarball + upload metrics + cricsheet
make backup-list                      # show all stamps in the bucket
make restore WHAT=all                 # pull the latest tarball back over data/
make restore WHAT=all STAMP=20260513-164100   # pin a specific timestamp
```

## Troubleshooting

- **Cricsheet download failures**: large collections (`all`, `tests_male`,
  `t20s_male`) can be hundreds of MB. The downloader caches by zip name
  so re-running resumes from the cached zip.

- **Docker build very slow first time**: `uv sync` pulls ~2 GB of wheels
  (torch + jax dominate). Subsequent builds reuse those layers and finish
  in seconds.
