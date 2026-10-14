"""Project-wide settings.

CricDex is a terminal-first tool. Credentials live in:

  1. Environment variables (highest precedence)
  2. `$CRICDEX_HOME/config.toml` — the user-facing CLI config
     (defaults to `~/.cricdex/config.toml`, see `cricdex config set`)
  3. `.env` in the repo root — dev-convenience fallback only

Only one credential is user-relevant:

- `llm_model` (+ the provider's own key, or `llm_api_key` / `llm_api_base`)
  — optional, only for the LLM taxonomy enrichment. Any provider LiteLLM supports.

Everything else (DuckDB path, Redis URL) is local-only — sensible
defaults, forget.
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

    # LLM (taxonomy enrichment only) — any LiteLLM model string, see common/llm.py.
    llm_model: str = _setting("llm_model")
    # Optional: override the provider key / endpoint (self-hosted or OpenAI-compatible server).
    llm_api_key: str = _setting("llm_api_key")
    llm_api_base: str = _setting("llm_api_base")

    # Local infra (sensible defaults, rarely touched).
    duckdb_path: str = str(DATA_DIR / "cricdex.duckdb")
    redis_url: str = _setting("redis_url", "redis://localhost:6379/0")


settings = Settings()
