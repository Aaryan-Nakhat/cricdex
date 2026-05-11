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
make docker-embed-rules             # MiniLM → Qdrant collection 'rules_clauses'
make docker-ingest-cricsheet        # download a Cricsheet collection → Parquet + DuckDB
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
# Fill in HF_TOKEN (personal, for first-time MiniLM download),
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
| `HF_TOKEN` | for first-time local model download | Use a personal read token; never a work one. The Docker image pre-bakes the MiniLM model so this is irrelevant inside the container. |
| `GEMINI_TMP_URL` | for LLM-synthesised answers | Stop-gap proxy endpoint (`/generate`, `/generate_json`). Replace with personal `GEMINI_API_KEY` + `google-genai` before public launch. |
| `GEMINI_TMP_API_KEY` | optional | Sent as `x-api-key` if the proxy needs auth. |
| `QDRANT_URL` | for server-mode Qdrant | When unset the code falls back to embedded on-disk storage under `data/rules/qdrant/`. The Docker Compose stack auto-sets it to `http://qdrant:6333`. |
| `DATABASE_URL` / `REDIS_URL` / `NEO4J_*` | wait for those modules | Documented but unused until scout / cache / graph land. |

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
  MiniLM model (~90 MB) and `uv sync` (~1.5 GB of wheels). Subsequent
  builds reuse those layers and finish in seconds.
