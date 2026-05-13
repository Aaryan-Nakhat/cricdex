# Running CricDex

Two supported paths: **Docker (recommended for first-time users)** and **local uv**.

## A. Docker — anyone, one command

### Prerequisites

- Docker Engine 24+
- Docker Compose v2 (`docker compose` subcommand)
- ~4 GB free disk for the image + Qdrant volume + raw PDF cache

### Boot the stack

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
cp .env.example .env
# Open .env and fill in any credentials you have (GEMINI_TMP_URL is
# required if you want LLM-synthesised answers; the rest are optional).
make docker-up
```

This brings up two services:

| Service | Container name | Port | Purpose |
|---|---|---|---|
| `qdrant`  | `cricdex-qdrant` | 6333 (HTTP) / 6334 (gRPC) | Vector store |
| `cricdex` | `cricdex-app` | 8080 | FastAPI app (`/health` for liveness) |

### Run the data pipelines (one-shot)

```bash
make docker-ingest-rules-download   # fetch verified rulebook PDFs into ./data/rules/raw/
make docker-ingest-rules-parse      # pdfplumber → clause JSONL in ./data/rules/parsed/
make docker-embed-rules             # snowflake-arctic-embed-l-v2 (truncate_dim=384) → Qdrant 'rules_clauses'
make docker-ingest-cricsheet        # download a Cricsheet collection → Parquet + DuckDB
make docker-ingest-people           # Cricsheet People Register (cross-IDs)
make docker-metrics-all COLLECTION=ipl  # compute every novel metric → data/metrics/
```

### Browse the leaderboards

```bash
make docker-dashboard-up   # Streamlit on http://localhost:8511
make docker-dashboard-down # stop it
```

### Ask a rule question

```bash
make docker-query Q="what is the impact player rule in IPL" FORMATS=ipl
```

Or via the HTTP API once it exposes a `/rules/ask` endpoint (todo). For
now query via the CLI through `docker compose run --rm cricdex`.

### Other useful targets

```bash
make docker-logs    # tail app logs
make docker-shell   # interactive shell inside the app container
make docker-test    # run pytest inside the container
make docker-down    # stop everything
```

### Skip the local build — pull from GHCR

After every push to `main` the CI builds `ghcr.io/aaryan-nakhat/cricdex:latest`
and publishes it. To bring the stack up against the pre-built image
(no ~10-min local build):

```bash
make docker-up-prod
```

This composes `docker-compose.yml` + `docker-compose.prod.yml` — the
prod overlay drops the dev `./src` / `./scripts` bind-mounts so the
running container matches what CI produced.

### Volume layout

- `qdrant_data` (named volume) — vector index persistence.
- `./data` (bind mount) — raw PDFs, parsed JSONL, curated supplementary
  clauses, Cricsheet downloads, Parquet snapshots. Editable from the host.
- `./src`, `./scripts` (bind mount) — code is hot-reloaded into the container
  so iteration is fast. Comment those mounts out in `docker-compose.yml`
  for a frozen image.

## B. Local uv (faster inner loop, single Python process)

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) 0.5+
- Optional: a Qdrant server if you don't want the embedded on-disk variant

### Setup

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync --group dev
cp .env.example .env
# Fill in HF_TOKEN (personal, for first-time snowflake-arctic-embed-l-v2 download),
# GEMINI_TMP_URL (+ GEMINI_TMP_API_KEY) for LLM answers, etc.
```

### Run pipelines

```bash
uv run python scripts/ingest_rules.py download
uv run python scripts/ingest_rules.py parse-pdfs
uv run python scripts/embed_rules.py embed
uv run python scripts/embed_rules.py query "what is the impact player rule" --formats ipl
uv run python scripts/ingest_cricsheet.py --collection recently_played_30_male
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
| `HF_TOKEN` | for first-time local model download | Use a personal read token; never a work one. The Docker image pre-bakes the snowflake-arctic-embed-l-v2 weights so this is irrelevant inside the container. |
| `GEMINI_TMP_URL` | for LLM-synthesised answers | Stop-gap proxy endpoint (`/generate`, `/generate_json`). Replace with personal `GEMINI_API_KEY` + `google-genai` before public launch. |
| `GEMINI_TMP_API_KEY` | optional | Sent as `x-api-key` if the proxy needs auth. |
| `QDRANT_URL` | for server-mode Qdrant | When unset the code falls back to embedded on-disk storage under `data/rules/qdrant/`. The Docker Compose stack auto-sets it to `http://qdrant:6333`. |
| `DATABASE_URL` / `REDIS_URL` / `NEO4J_*` | wait for those modules | Documented but unused until scout / cache / graph land. |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | for `make backup` | Cloudflare R2 backup target. Always-free 10 GB / zero egress. Create a bucket + API token at `dash.cloudflare.com → R2 → Manage R2 API Tokens`. Without these, the local `data/` directory is the only copy of indexes that took 43 min to build. |

### Off-VM persistence

`data/` is `.gitignore`d and the local Qdrant index, Cricsheet DuckDB,
and computed metrics are the only copies on disk. To survive a VM
rebuild, push them to Cloudflare R2 (private bucket, 10 GB free
forever, zero egress):

```bash
# one-time R2 setup: create a bucket, mint an API token, paste creds into .env
make backup WHAT=all                  # tarball + upload data/rules + metrics + cricsheet
make backup WHAT=rules                # narrower; just the 57 MB Qdrant + parsed JSONL
make backup-list                      # show all stamps in the bucket
make restore WHAT=rules               # pull the latest 'rules' tarball back over data/
make restore WHAT=rules STAMP=20260513-164100   # pin a specific timestamp
```

## Troubleshooting

- **HuggingFace 401 on local first run**: the host's `~/.cache/huggingface/token`
  contains a stale (likely work) token. Set `HF_TOKEN` to a personal token
  in `.env` — the project loads it from `.env` into the process env which
  takes precedence over the on-disk token.

- **Qdrant client closed prematurely**: harmless Python finalizer ordering
  warning from `qdrant_client` in embedded mode; the upsert / query has
  already completed by the time you see it.

- **Cricsheet download failures**: large collections (`all`, `tests_male`,
  `t20s_male`) can be hundreds of MB. The downloader caches by zip name
  so re-running resumes from the cached zip.

- **Docker build very slow first time**: the build pre-downloads the
  snowflake-arctic-embed-l-v2 weights (~2 GB) and `uv sync` (~2 GB of
  wheels — torch + jax dominate). Subsequent builds reuse those layers
  and finish in seconds.
