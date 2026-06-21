"""Integration tests for PostgreSQL readiness."""

from collections.abc import Iterator

import httpx
import pytest
from testcontainers.postgres import PostgresContainer  # pyright: ignore[reportMissingTypeStubs]

from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import get_engine
from toolwatch.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Start a disposable PostgreSQL instance and expose an async URL."""

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


def configure_database(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    """Point controlled application dependencies at a test database."""

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.mark.asyncio
async def test_ready_when_postgresql_is_available(
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
) -> None:
    """The ready probe succeeds after executing a real PostgreSQL query."""

    configure_database(monkeypatch, postgres_url)
    transport = httpx.ASGITransport(app=create_app())

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}


@pytest.mark.asyncio
async def test_not_ready_response_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection failures produce a stable response without infrastructure details."""

    unavailable_url = "postgresql+asyncpg://private_user:private_password@127.0.0.1:1/private_db"
    configure_database(monkeypatch, unavailable_url)
    transport = httpx.ASGITransport(app=create_app())

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    serialized_response = response.text
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "private_password" not in serialized_response
    assert unavailable_url not in serialized_response
