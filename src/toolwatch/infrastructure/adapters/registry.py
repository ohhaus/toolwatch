"""Immutable allowlist of trusted adapter implementations."""

from collections.abc import Mapping
from types import MappingProxyType

from toolwatch.domain.tool_calls import ToolAdapter
from toolwatch.infrastructure.adapters.mock import (
    MockDatabaseAdapter,
    MockEmailAdapter,
    MockGitHubAdapter,
)


class AdapterRegistry:
    """Resolve adapters only from an explicitly constructed immutable mapping."""

    def __init__(self, adapters: Mapping[str, ToolAdapter]) -> None:
        self._adapters = MappingProxyType(dict(adapters))

    def get(self, adapter_type: str) -> ToolAdapter | None:
        """Return an allowlisted adapter implementation."""

        return self._adapters.get(adapter_type)


def build_adapter_registry() -> AdapterRegistry:
    """Build the production registry without dynamic loading or global counters."""

    return AdapterRegistry(
        {
            "mock_github": MockGitHubAdapter(),
            "mock_email": MockEmailAdapter(),
            "mock_database": MockDatabaseAdapter(),
        }
    )
