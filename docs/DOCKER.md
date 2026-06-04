# Docker design notes

End goal: anyone can `git clone && cp .env.example .env && make docker-up`
and have the whole stack — the ETL CLIs and the API server — running with
no manual provisioning. The stack is file-driven (DuckDB + exported JSON);
there is no vector or graph database. This file captures the design choices
behind the image and Compose layout so the next person extending it
doesn't have to rediscover them.

## Image strategy

Single Python image built in two stages:

1. **`deps`** — uses the official `ghcr.io/astral-sh/uv` binary on a
   `python:3.12-slim` base, copies `pyproject.toml`, runs `uv sync
   --no-install-project --no-dev` so dependency resolution is cached.
2. **`app`** — copies `src/` + `scripts/`. No model weights are baked in;
   the stack is file-driven and needs no embedding model at runtime.

Buildkit cache mounts (`--mount=type=cache,target=/root/.cache/uv`) make
incremental rebuilds fast.

## Compose layout

Only one service comes up by default:

- **`cricdex`** — the app image. Reads `.env` for secrets and serves the
  FastAPI app; the ETL CLIs run as one-shot tasks against the same image.

Postgres / Redis are present in the file as commented-out placeholders.
Uncomment as the cache module comes online so the stack stays minimal
during early-Phase work. There is no vector or graph DB service.

### Volume strategy

| Volume | Type | Purpose |
|---|---|---|
| `./data` → `/app/data` | bind | Cricsheet downloads, DuckDB, metrics / ratings JSON, curated JSON, exported snapshots. Editable from the host. |
| `./src` → `/app/src` | bind (dev) | Hot-reload of code. Drop this mount in prod images. |
| `./scripts` → `/app/scripts` | bind (dev) | Same rationale. |

### Network

Compose creates a default bridge network. The `cricdex` app exposes its
FastAPI port on the host for ad-hoc inspection.

## Running pipelines vs running the server

The default `CMD` runs the FastAPI app (`uvicorn cricdex.api.main:app`).
ETL CLIs are one-shot tasks, so they run via `docker compose run --rm
cricdex uv run python scripts/<thing>.py`. The `Makefile` wraps each
common task so contributors don't have to memorise the flags.

### Why `docker compose run --rm` and not `docker compose exec`?

`run` creates a fresh container per invocation and tears it down, so
long-running ETL tasks don't accumulate background processes inside the
API container. `exec` is fine for interactive work and is exposed via
`make docker-shell`.

## Adding a new service

1. Add the service block to `docker-compose.yml` with a pinned image tag.
2. If the app reads it, add the connection env var(s) in `.env.example`
   and an override in the `cricdex.environment` block so the local
   default points at the compose service name (`http://redis:6379`
   etc.).
3. Add a named volume (or bind mount) for persistence.
4. Add a `healthcheck` and a `depends_on: {<service>: {condition:
   service_healthy}}` on the `cricdex` service so the app waits for it.
5. Document it here.

## Why not Compose `profiles`?

We may move to profiles (`docker compose --profile cache up`) once we
have many optional services. For now the stack is small enough that
explicit comments + uncomment-on-demand is simpler and easier to read.

## Production deployment (future)

The same image is the deployment artefact. Two paths anticipated:

- **Oracle Cloud Free Tier ARM** — single VM, `docker compose up` with
  the production overlay (drops the dev source mounts, sets explicit
  resource limits, enables logging driver).
- **Cloudflare Workers** — the API can also be packaged as a small Worker
  that serves the exported JSON snapshot. Out of scope until the API
  surface stabilises.
