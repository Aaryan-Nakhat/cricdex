"""Project-wide settings loaded from `.env`.

`.env` is loaded into `os.environ` at import time so that third-party
libraries (notably HuggingFace, which reads HF_TOKEN directly from the
process env) see the personal credentials in this `.env` rather than any
shared on-disk token under ~/.cache/huggingface/token. This keeps personal
project work strictly separated from work credentials living on the VM.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    gemini_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    jina_api_key: str = ""
    cohere_api_key: str = ""

    hf_token: str = ""

    qdrant_url: str = ""
    qdrant_api_key: str = ""

    database_url: str = "postgresql://localhost:5432/cricdex"
    duckdb_path: str = str(DATA_DIR / "cricdex.duckdb")

    redis_url: str = "redis://localhost:6379/0"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "cricdex/0.1"

    telegram_bot_token: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
