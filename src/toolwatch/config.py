"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

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
    otel_enabled: bool = True
    otel_service_name: str = Field(default="toolwatch", min_length=1, max_length=100)
    otel_service_version: str = Field(default=__version__, min_length=1, max_length=100)
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_otlp_protocol: Literal["http/protobuf"] = "http/protobuf"
    otel_traces_exporter: Literal["otlp", "none"] = "otlp"
    otel_metrics_exporter: Literal["prometheus", "none"] = "prometheus"
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_semconv_stability_opt_in: str = "gen_ai_latest_experimental"
    metrics_enabled: bool = True
    metrics_path: str = Field(default="/metrics", pattern=r"^/[A-Za-z0-9/_-]*$")
    dashboard_enabled: bool = True
    dashboard_prefix: str = Field(default="/ui", pattern=r"^/[A-Za-z0-9/_-]*$")
    dashboard_page_size: int = Field(default=25, ge=1, le=100)
    dashboard_max_page_size: int = Field(default=100, ge=1, le=500)
    dashboard_refresh_seconds: int = Field(default=10, ge=5, le=3_600)
    attack_lab_enabled: bool = True
    jaeger_ui_public_url: str | None = None
    agent_provider: Literal["fake", "ollama"] = "fake"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = Field(default="qwen3:4b", min_length=1, max_length=255)
    ollama_allowed_models: str = "qwen3:4b"
    fake_agent_model: str = Field(default="fake-v1", min_length=1, max_length=255)
    fake_agent_allowed_models: str = "fake-v1"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    ollama_keep_alive: str = Field(default="10m", min_length=1, max_length=32)
    ollama_think: bool = False
    agent_max_turns: int = Field(default=8, ge=1, le=32)
    agent_max_tool_calls: int = Field(default=16, ge=0, le=128)
    agent_max_tools_per_turn: int = Field(default=4, ge=1, le=32)
    agent_max_exposed_tools: int = Field(default=64, ge=0, le=256)
    agent_max_message_bytes: int = Field(default=65_536, ge=1)
    agent_max_conversation_bytes: int = Field(default=262_144, ge=1)
    agent_max_provider_response_bytes: int = Field(default=1_048_576, ge=1)
    agent_run_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    agent_store_final_answer: bool = True

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
        parsed = urlsplit(self.ollama_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must be a credential-free local HTTP(S) URL")
        if self.ollama_model not in self.allowed_ollama_models:
            raise ValueError("OLLAMA_MODEL must be present in OLLAMA_ALLOWED_MODELS")
        if self.fake_agent_model not in self.allowed_fake_models:
            raise ValueError("FAKE_AGENT_MODEL must be present in FAKE_AGENT_ALLOWED_MODELS")
        if self.agent_max_conversation_bytes < self.agent_max_message_bytes:
            raise ValueError("agent conversation limit must be at least one message")
        return self

    @property
    def allowed_ollama_models(self) -> frozenset[str]:
        """Return the bounded configured Ollama model allowlist."""

        return _model_allowlist(self.ollama_allowed_models)

    @property
    def allowed_fake_models(self) -> frozenset[str]:
        """Return the bounded configured fake-provider model allowlist."""

        return _model_allowlist(self.fake_agent_allowed_models)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings through one controlled cache."""

    return Settings()


def _model_allowlist(value: str) -> frozenset[str]:
    models = frozenset(item.strip() for item in value.split(",") if item.strip())
    if not models or len(models) > 32 or any(len(model) > 255 for model in models):
        raise ValueError("model allowlist is invalid")
    return models
