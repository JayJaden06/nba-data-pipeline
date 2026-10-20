"""Runtime settings, read from environment variables or a local .env file."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://nba:nba@localhost:5432/nba"

    # stats.nba.com throttles aggressively; stay polite.
    nba_api_min_interval_s: float = 0.6
    nba_api_max_retries: int = 5
    nba_api_timeout_s: int = 30

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        """Hosted Postgres providers hand out postgresql:// URLs; SQLAlchemy needs the driver."""
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
