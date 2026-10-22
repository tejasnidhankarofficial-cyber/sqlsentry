from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr
    openai_model: str = "gpt-4o-mini"

    db_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "olist"
    readonly_password: SecretStr
    audit_password: SecretStr

    app_password: SecretStr            # shared password for the web app
    auth_secret: SecretStr             # signs session tokens
    allowed_users: str = ""            # comma-separated usernames; empty = any valid username
    token_ttl_hours: int = 12
    daily_limit_per_user: int = 50     # questions per user per UTC day
    daily_limit_global: int = 500      # hard ceiling across all users (protects the LLM bill)
    max_question_chars: int = 500

    max_rows: int = 1000          # hard cap on rows returned by any query
    max_repairs: int = 2          # LLM retries after a guard/DB error
    statement_timeout_ms: int = 5000
    schema_card_path: Path = ROOT / "db" / "schema_card.yaml"

    @property
    def allowed_user_set(self) -> frozenset[str]:
        return frozenset(u.strip().lower() for u in self.allowed_users.split(",") if u.strip())

    def db_url(self, role: str, password: SecretStr) -> str:
        return (f"postgresql+psycopg://{role}:{password.get_secret_value()}"
                f"@{self.db_host}:{self.postgres_port}/{self.postgres_db}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
