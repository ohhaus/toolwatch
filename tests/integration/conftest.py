"""Shared real-PostgreSQL fixtures for integration tests."""

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer  # pyright: ignore[reportMissingTypeStubs]

from alembic import command


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start one disposable PostgreSQL 17 instance for the integration suite."""

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


def migrate(database_url: str, revision: str) -> None:
    """Apply an Alembic revision to the disposable database."""

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


@pytest.fixture(scope="session")
def migrated_database_url(postgres_url: str) -> str:
    """Upgrade the disposable database to the current head."""

    migrate(postgres_url, "head")
    return postgres_url


@pytest.fixture
async def clean_database(migrated_database_url: str) -> AsyncIterator[str]:
    """Remove business rows while preserving the migrated schema."""

    engine = create_async_engine(migrated_database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE model_calls, audit_events, risk_flags, blocking_rules, "
                "tool_result_metadata, tool_calls, agent_sessions, "
                "agent_runs, tool_definitions, agents RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()
    yield migrated_database_url
