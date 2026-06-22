"""Liveness and readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from toolwatch.api.dependencies import get_telemetry
from toolwatch.config import Settings, get_settings
from toolwatch.infrastructure.agents import OllamaAgentProvider
from toolwatch.infrastructure.database.engine import get_engine
from toolwatch.infrastructure.database.health import is_database_available
from toolwatch.telemetry import TelemetryRuntime

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    """Response returned when the API process is alive."""

    status: Literal["ok"] = "ok"
    service: Literal["toolwatch"] = "toolwatch"


class ReadinessResponse(BaseModel):
    """Response returned when the API can serve database-backed requests."""

    status: Literal["ready"] = "ready"
    database: Literal["available"] = "available"


class NotReadyResponse(BaseModel):
    """Sanitized response returned when a required dependency is unavailable."""

    status: Literal["not_ready"] = "not_ready"
    database: Literal["unavailable"] = "unavailable"


class TelemetryHealthResponse(BaseModel):
    """Safe non-readiness telemetry state."""

    status: Literal["ok", "degraded", "disabled"]
    tracing: Literal["configured", "disabled"]
    exporter: Literal["configured", "degraded", "disabled"]


class OllamaHealthResponse(BaseModel):
    """Coarse optional local-provider state that never gates readiness."""

    status: Literal["available", "degraded", "disabled"]
    provider: Literal["ollama", "fake"]


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Report process liveness without consulting downstream services."""

    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": NotReadyResponse}},
)
async def readiness(
    engine: Annotated[AsyncEngine, Depends(get_engine)],
) -> ReadinessResponse | JSONResponse:
    """Report whether PostgreSQL accepts a lightweight query."""

    if await is_database_available(engine):
        return ReadinessResponse()

    response = NotReadyResponse()
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )


@router.get("/telemetry", response_model=TelemetryHealthResponse)
def telemetry_health(
    runtime: Annotated[TelemetryRuntime, Depends(get_telemetry)],
) -> TelemetryHealthResponse:
    """Expose only coarse provider state; Jaeger does not gate readiness."""

    exporter = runtime.exporter_status.value
    if exporter == "disabled":
        status_value = "disabled"
        tracing = "disabled"
    elif exporter == "degraded":
        status_value = "degraded"
        tracing = "configured"
    else:
        status_value = "ok"
        tracing = "configured"
    return TelemetryHealthResponse(
        status=status_value,
        tracing=tracing,
        exporter=exporter,
    )


@router.get("/ollama", response_model=OllamaHealthResponse)
async def ollama_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OllamaHealthResponse:
    """Check the local Ollama control endpoint without model generation."""

    if settings.agent_provider != "ollama":
        return OllamaHealthResponse(status="disabled", provider="fake")
    provider = OllamaAgentProvider(settings.ollama_base_url)
    try:
        available = await provider.health()
    finally:
        await provider.aclose()
    return OllamaHealthResponse(
        status="available" if available else "degraded",
        provider="ollama",
    )
