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
# True when running from a clone of the repo (as opposed to an installed package).
IN_CHECKOUT = (ROOT / "pyproject.toml").exists()

# CRICDEX_HOME defaults to `~/.cricdex/`: config.toml, and data/ for an installed package.
CRICDEX_HOME = Path(os.environ.get("CRICDEX_HOME", str(Path.home() / ".cricdex")))

# DATA_DIR (DuckDB, metric JSON, curated player facts): CRICDEX_DATA_DIR if set; else the repo's data/ when
# running from a clone (it ships the curated files); else ~/.cricdex/data. It no longer depends on whether a
# folder happens to exist, so `cricdex init` can't switch a checkout over to an empty directory.
if os.environ.get("CRICDEX_DATA_DIR"):
    DATA_DIR = Path(os.environ["CRICDEX_DATA_DIR"])
elif IN_CHECKOUT:
    DATA_DIR = ROOT / "data"
else:
    DATA_DIR = CRICDEX_HOME / "data"

# Curated player facts (LLM taxonomy, Wikidata DOB / photo) — one place for writers and readers.
CURATED_DIR = DATA_DIR / "curated"
# The exported site JSON the web app, CLI, TUI and dashboard read.
SITE_DATA = ROOT / "site" / "public" / "data"

CONFIG_PATH = CRICDEX_HOME / "config.toml"

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
    # Optional: override the provider key / endpoint (a self-hosted or custom server).
    llm_api_key: str = _setting("llm_api_key")
    llm_api_base: str = _setting("llm_api_base")

    # Local infra (sensible defaults, rarely touched).
    duckdb_path: str = str(DATA_DIR / "cricdex.duckdb")
    redis_url: str = _setting("redis_url", "redis://localhost:6379/0")


settings = Settings()
