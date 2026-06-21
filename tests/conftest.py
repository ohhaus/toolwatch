"""Shared pytest fixtures."""

from collections.abc import AsyncIterator

import pytest

from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import dispose_engine, get_engine


@pytest.fixture(autouse=True)
async def reset_cached_dependencies() -> AsyncIterator[None]:
    """Keep environment-derived dependencies isolated between tests."""

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    await dispose_engine()
    get_settings.cache_clear()
