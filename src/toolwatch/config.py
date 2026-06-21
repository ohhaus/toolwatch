"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from toolwatch import __version__

DEFAULT_DATABASE_URL = "postgresql+asyncpg://toolwatch:toolwatch@localhost:5432/toolwatch"


class Settings(BaseSettings):
    """Validated ToolWatch runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ToolWatch"
    app_version: str = __version__
    environment: str = "development"
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    store_prompts: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings through one controlled cache."""

    return Settings()
