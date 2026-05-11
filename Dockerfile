# Multi-stage build for the CricDex Python service.
# Stage 1 syncs deps into a uv-managed virtualenv (cached layer).
# Stage 2 copies source + pre-bakes the embedding model so first run is instant.

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
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        libpq-dev \
        git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv_bin /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

FROM deps AS app
COPY src ./src
COPY scripts ./scripts
COPY README.md LICENSE Makefile ./

# Pre-bake the embedding model so runtime never blocks on first download.
# Build runs in a clean environment without the host's HF token; anonymous
# fetch of a public model is the natural default and works fine here.
ENV HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    HF_HOME=/opt/hf-cache
RUN --mount=type=cache,target=/opt/hf-cache \
    uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
    && mkdir -p /app/hf-cache \
    && cp -r /opt/hf-cache/. /app/hf-cache/ 2>/dev/null || true
ENV HF_HOME=/app/hf-cache

ENV PYTHONPATH=/app/src

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "cricdex.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
