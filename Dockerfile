# Multi-stage build for the CricDex Python service.
# Stage 1 installs the locked dependencies into a uv-managed virtualenv (cached layer).
# Stage 2 copies the source + the exported site data the API, CLI and dashboard read.

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
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra ui

FROM deps AS app
COPY src ./src
# the league registry (config/leagues.toml): every league list in the code reads it
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests
COPY site/public/data ./site/public/data
COPY README.md LICENSE Makefile ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ui

ENV PYTHONPATH=/app/src
# `uv run` (CMD, compose, Makefile) must not pull the dev group in at container start
ENV UV_NO_DEV=1

EXPOSE 8080
CMD ["uv", "run", "--frozen", "uvicorn", "cricdex.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
