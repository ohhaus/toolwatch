"""FastAPI application factory for ToolWatch."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from toolwatch.api.errors import register_error_handlers
from toolwatch.api.router import api_router
from toolwatch.config import get_settings
from toolwatch.infrastructure.database.engine import dispose_engine
from toolwatch.telemetry import TelemetryRuntime, build_telemetry_runtime
from toolwatch.telemetry.logging import configure_logging
from toolwatch.telemetry.middleware import ObservabilityMiddleware
from toolwatch.web.router import mount_dashboard


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Dispose cached infrastructure resources during application shutdown."""

    yield
    application.state.telemetry.shutdown()
    await dispose_engine()


def create_app(telemetry: TelemetryRuntime | None = None) -> FastAPI:
    """Create and configure a ToolWatch API application."""

    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        service=settings.otel_service_name,
        environment=settings.environment,
    )
    runtime = telemetry or build_telemetry_runtime(settings)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.state.telemetry = runtime
    register_error_handlers(application)
    application.include_router(api_router)
    mount_dashboard(application)
    application.add_middleware(ObservabilityMiddleware, runtime=runtime)
    _document_correlation_header(application)
    return application


def _document_correlation_header(application: FastAPI) -> None:
    """Document the middleware response header on every OpenAPI operation."""

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            routes=application.routes,
        )
        paths = cast(dict[str, object], schema.get("paths", {}))
        for path_value in paths.values():
            if not isinstance(path_value, dict):
                continue
            path = cast(dict[str, object], path_value)
            for operation_value in path.values():
                if not isinstance(operation_value, dict):
                    continue
                operation = cast(dict[str, object], operation_value)
                responses = operation.get("responses")
                if not isinstance(responses, dict):
                    continue
                for response_value in cast(dict[str, object], responses).values():
                    if not isinstance(response_value, dict):
                        continue
                    response = cast(dict[str, object], response_value)
                    headers = response.setdefault("headers", {})
                    if isinstance(headers, dict):
                        cast(dict[str, object], headers)["X-Correlation-ID"] = {
                            "description": "Canonical request correlation UUID.",
                            "schema": {"type": "string", "format": "uuid"},
                        }
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi


app = create_app()
