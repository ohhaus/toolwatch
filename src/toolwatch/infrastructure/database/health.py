"""Database health probes."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def is_database_available(engine: AsyncEngine) -> bool:
    """Return whether PostgreSQL can execute a lightweight query."""

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        # Infrastructure failures are deliberately collapsed into a boolean so
        # public health responses never expose connection strings or internals.
        return False
    return True
