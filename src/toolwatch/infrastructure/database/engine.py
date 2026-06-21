"""Async SQLAlchemy engine and session factories."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from toolwatch.config import Settings, get_settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async PostgreSQL engine without opening a connection."""

    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args={"timeout": settings.database_connect_timeout_seconds},
    )


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the lazily created process engine."""

    return create_engine(get_settings())


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory bound to the process engine."""

    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def dispose_engine() -> None:
    """Dispose pooled connections and clear cached database factories."""

    engine = get_engine()
    await engine.dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
