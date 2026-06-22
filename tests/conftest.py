"""Shared pytest fixtures."""

from collections.abc import AsyncIterator

import pytest

from toolwatch.api.dependencies import (
    close_agent_providers,
    get_adapter_registry,
    get_agent_providers,
    get_terminal_response_cache,
)
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import dispose_engine, get_engine


@pytest.fixture(autouse=True)
async def reset_cached_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Keep environment-derived dependencies isolated between tests."""

    monkeypatch.setenv("OTEL_ENABLED", "false")
    get_settings.cache_clear()
    get_adapter_registry.cache_clear()
    get_agent_providers.cache_clear()
    get_terminal_response_cache.cache_clear()
    get_engine.cache_clear()
    yield
    await close_agent_providers()
    await dispose_engine()
    get_settings.cache_clear()
    get_adapter_registry.cache_clear()
    get_agent_providers.cache_clear()
    get_terminal_response_cache.cache_clear()
