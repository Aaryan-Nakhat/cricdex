from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    jina_api_key: str = ""
    cohere_api_key: str = ""

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
