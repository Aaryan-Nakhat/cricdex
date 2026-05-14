"""Project-wide settings.

CricDex is a terminal-first tool. Credentials live in:

  1. Environment variables (highest precedence)
  2. `$CRICDEX_HOME/config.toml` — the user-facing CLI config
     (defaults to `~/.cricdex/config.toml`, see `cricdex config set`)
  3. `.env` in the repo root — dev-convenience fallback only

Only two credentials are user-relevant:

- `gemini_api_key` (or `gemini_tmp_url` + `gemini_tmp_api_key` for the
  legacy work proxy) — needed for rules Q&A, translate, match reports.
- `jina_api_key` — optional, enables cross-encoder rerank in rules
  retrieval. Falls back to RRF order if unset.

Everything else (Neo4j password, embedded Qdrant, DuckDB path) is
local-only — set sensible defaults and forget.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

# CRICDEX_HOME defaults to `~/.cricdex/`. Inside it: config.toml, data/,
# cache/, logs/. Devs running from a repo checkout can override with the
# env var to point at the repo's `data/` dir for convenience.
CRICDEX_HOME = Path(os.environ.get("CRICDEX_HOME", str(Path.home() / ".cricdex")))

# DATA_DIR: prefer ~/.cricdex/data when populated; fall back to repo
# data/ for dev so existing scripts keep working without migration.
_HOME_DATA = CRICDEX_HOME / "data"
_REPO_DATA = ROOT / "data"
DATA_DIR = _HOME_DATA if _HOME_DATA.exists() else _REPO_DATA

CONFIG_PATH = CRICDEX_HOME / "config.toml"
CACHE_DIR = CRICDEX_HOME / "cache"
LOG_DIR = CRICDEX_HOME / "logs"

# .env in the repo root is loaded only when it exists — useful for dev,
# ignored by an end-user `uvx cricdex` install.
load_dotenv(ROOT / ".env", override=False)


def _read_toml_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


_TOML = _read_toml_config()


def _setting(name: str, default: str = "") -> str:
    env = os.environ.get(name.upper())
    if env:
        return env
    return str(_TOML.get(name, default))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    # LLM (rules QA, translate, match reports).
    gemini_api_key: str = _setting("gemini_api_key")
    # Legacy work-hosted proxy. Phased out once user supplies a personal
    # gemini_api_key. Both fields are read; non-empty wins.
    gemini_tmp_url: str = _setting("gemini_tmp_url")
    gemini_tmp_api_key: str = _setting("gemini_tmp_api_key")

    # Optional: cross-encoder rerank on rules retrieval. Falls back to
    # RRF order if empty.
    jina_api_key: str = _setting("jina_api_key")

    # Local infra (sensible defaults, rarely touched).
    qdrant_url: str = _setting("qdrant_url")
    duckdb_path: str = str(DATA_DIR / "cricdex.duckdb")
    redis_url: str = _setting("redis_url", "redis://localhost:6379/0")

    neo4j_uri: str = _setting("neo4j_uri", "bolt://localhost:7687")
    neo4j_user: str = _setting("neo4j_user", "neo4j")
    neo4j_password: str = _setting("neo4j_password", "cricdex_dev")


settings = Settings()
