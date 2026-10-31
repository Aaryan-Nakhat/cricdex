# Multi-stage build for the CricDesk Python service.
# Stage 1 installs the locked dependencies into a uv-managed virtualenv (cached layer).
# Stage 2 copies the source + the exported site data the API, CLI and dashboard read.
# Everything runs as the unprivileged user `app` (uid 1000), never as root.

ARG PYTHON_VERSION=3.12
# uv.lock is written in lock format `version = 1, revision = 3`; uv older than ~0.8 can't
# read it, so keep this at (or near) the uv that writes the lock.
ARG UV_VERSION=0.11.19

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv_bin

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=on
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl build-essential git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv_bin /uv /usr/local/bin/uv
# Unprivileged runtime user. uid 1000 matches the first user on most Linux hosts, so the
# bind-mounted data/ stays writable; another uid can be set with `user:` in compose.
RUN useradd --create-home --uid 1000 --user-group app \
    && mkdir -p /app \
    && chown app:app /app
WORKDIR /app
USER app

FROM base AS deps
COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-install-project --no-dev --extra ui

FROM deps AS app
COPY --chown=app:app src ./src
# the league registry (config/leagues.toml): every league list in the code reads it
COPY --chown=app:app config ./config
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app tests ./tests
COPY --chown=app:app site/public/data ./site/public/data
COPY --chown=app:app README.md LICENSE Makefile ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --extra ui \
    && mkdir -p data

ENV PYTHONPATH=/app/src
# `uv run` (CMD, compose, Makefile) must not pull the dev group in at container start
ENV UV_NO_DEV=1

EXPOSE 8080
# 0.0.0.0 is inside the container only (the port mapping needs it). docker-compose.yml publishes
# the port on the host's 127.0.0.1, so the API is not reachable from the network by default.
CMD ["uv", "run", "--frozen", "uvicorn", "cricdesk.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
