"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    default_tool_timeout_seconds: float = Field(default=10.0, gt=0, le=60.0)
    max_tool_timeout_seconds: float = Field(default=30.0, gt=0, le=300.0)
    max_tool_arguments_bytes: int = Field(default=65_536, ge=1)
    max_tool_result_bytes: int = Field(default=524_288, ge=1)
    max_json_depth: int = Field(default=20, ge=1, le=100)
    max_string_length: int = Field(default=51_200, ge=1)
    redaction_enabled: bool = True
    redaction_replacement: str = Field(default="[REDACTED]", min_length=1, max_length=100)
    redaction_fingerprints_enabled: bool = True
    redaction_fingerprint_key: str = Field(
        default="development-only-redaction-key-change-me",
        min_length=16,
    )
    redaction_include_fingerprint_prefix: bool = False
    redaction_additional_patterns: tuple[str, ...] = ()
    max_redaction_depth: int = Field(default=20, ge=1, le=100)
    max_redaction_nodes: int = Field(default=10_000, ge=1, le=1_000_000)
    store_redacted_arguments: bool = True
    store_redacted_results: bool = True

    @model_validator(mode="after")
    def validate_redaction_key(self) -> "Settings":
        """Reject unsafe production-like fingerprint configuration."""

        if not self.redaction_enabled:
            raise ValueError("Security Pipeline v1 requires redaction to remain enabled")
        if not self.store_redacted_arguments or not self.store_redacted_results:
            raise ValueError(
                "Security Pipeline v1 requires sanitized payload persistence for replay"
            )
        if (
            self.redaction_enabled
            and self.redaction_fingerprints_enabled
            and self.environment.lower() not in {"development", "test"}
            and (
                len(self.redaction_fingerprint_key) < 32
                or "development" in self.redaction_fingerprint_key.lower()
            )
        ):
            raise ValueError("production redaction fingerprints require a strong independent key")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings through one controlled cache."""

    return Settings()
