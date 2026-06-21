"""Trusted in-process tool adapters."""

from toolwatch.infrastructure.adapters.mock import (
    MockDatabaseAdapter,
    MockEmailAdapter,
    MockGitHubAdapter,
)
from toolwatch.infrastructure.adapters.registry import AdapterRegistry, build_adapter_registry

__all__ = [
    "AdapterRegistry",
    "MockDatabaseAdapter",
    "MockEmailAdapter",
    "MockGitHubAdapter",
    "build_adapter_registry",
]
