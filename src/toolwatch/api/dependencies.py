"""Business API dependency construction."""

from functools import lru_cache, partial

from fastapi import Request

from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.tool_calls import TerminalResponseCache
from toolwatch.infrastructure.adapters import AdapterRegistry, build_adapter_registry
from toolwatch.infrastructure.database.engine import get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork
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
