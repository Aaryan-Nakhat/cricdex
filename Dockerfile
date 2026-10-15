# Multi-stage build for the CricDex Python service.
# Stage 1 installs the locked dependencies into a uv-managed virtualenv (cached layer).
# Stage 2 copies the source + the exported site data the API, CLI and dashboard read.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.5.10

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
COPY scripts ./scripts
COPY tests ./tests
COPY site/public/data ./site/public/data
COPY README.md LICENSE Makefile ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ui

ENV PYTHONPATH=/app/src

EXPOSE 8080
CMD ["uv", "run", "--frozen", "uvicorn", "cricdex.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
