"""Integration tests for the reviewed Alembic migration chain."""

from asyncio import run

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

pytestmark = pytest.mark.integration


def _config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_downgrade_and_upgrade(postgres_url: str) -> None:
    """The new migration cleanly reverses and reapplies on PostgreSQL."""

    config = _config(postgres_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0001_bootstrap")

    downgraded_tables = run(_table_names(postgres_url))
    assert "agents" not in downgraded_tables
    assert "tool_definitions" not in downgraded_tables
    assert "agent_sessions" not in downgraded_tables

    command.upgrade(config, "head")
    upgraded_tables = run(_table_names(postgres_url))

    assert {"agents", "tool_definitions", "agent_sessions"} <= upgraded_tables


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)

    def inspect_tables(connection: Connection) -> set[str]:
        return set(inspect(connection).get_table_names())

    async with engine.connect() as connection:
        names = await connection.run_sync(inspect_tables)
    await engine.dispose()
    return names
