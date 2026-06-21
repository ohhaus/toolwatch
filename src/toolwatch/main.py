"""FastAPI application factory for ToolWatch."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from toolwatch.api.errors import register_error_handlers
from toolwatch.api.router import api_router
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Dispose cached infrastructure resources during application shutdown."""

    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure a ToolWatch API application."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    register_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
