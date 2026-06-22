"""Business API dependency construction."""

from collections.abc import Mapping
from functools import lru_cache, partial

from fastapi import Request

from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.tool_calls import TerminalResponseCache
from toolwatch.config import get_settings
from toolwatch.domain.agents import AgentProvider
from toolwatch.infrastructure.adapters import AdapterRegistry, build_adapter_registry
from toolwatch.infrastructure.agents import FakeAgentProvider, OllamaAgentProvider
from toolwatch.infrastructure.database.engine import get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork
from toolwatch.shutdown import ShutdownManager
from toolwatch.telemetry import TelemetryRuntime


def get_uow_factory() -> UnitOfWorkFactory:
    """Construct units of work lazily from the process session factory."""

    return partial(SqlAlchemyUnitOfWork, get_session_factory())


@lru_cache(maxsize=1)
def get_adapter_registry() -> AdapterRegistry:
    """Return the immutable process adapter allowlist."""

    return build_adapter_registry()


@lru_cache(maxsize=1)
def get_terminal_response_cache() -> TerminalResponseCache:
    """Return the process-local transient idempotent response cache."""

    return TerminalResponseCache()


def get_telemetry(request: Request) -> TelemetryRuntime:
    """Return the application-owned observability runtime."""

    runtime = request.app.state.telemetry
    if not isinstance(runtime, TelemetryRuntime):
        raise RuntimeError("telemetry runtime is not configured")
    return runtime


@lru_cache(maxsize=1)
def get_agent_providers() -> Mapping[str, AgentProvider]:
    """Construct request-scoped providers; fake scripts never leak across runs."""

    settings = get_settings()
    return {
        "fake": FakeAgentProvider(),
        "ollama": OllamaAgentProvider(settings.ollama_base_url),
    }


async def close_agent_providers() -> None:
    """Close reusable provider clients and clear the provider cache."""

    providers = get_agent_providers()
    ollama = providers.get("ollama")
    if isinstance(ollama, OllamaAgentProvider):
        await ollama.aclose()
    get_agent_providers.cache_clear()


def get_shutdown_manager(request: Request) -> ShutdownManager:
    """Return the application shutdown coordinator."""

    manager = request.app.state.shutdown_manager
    if not isinstance(manager, ShutdownManager):
        raise RuntimeError("shutdown manager is not configured")
    return manager
