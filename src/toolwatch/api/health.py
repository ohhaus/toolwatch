"""Liveness and readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from toolwatch.infrastructure.database.engine import get_engine
from toolwatch.infrastructure.database.health import is_database_available

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
