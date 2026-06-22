"""Prometheus-compatible metrics endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from toolwatch.api.dependencies import get_telemetry
from toolwatch.config import get_settings
from toolwatch.telemetry import TelemetryRuntime

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=True)
def metrics(
    runtime: Annotated[TelemetryRuntime, Depends(get_telemetry)],
) -> Response:
    """Render isolated process metrics when enabled."""

    settings = get_settings()
    if not settings.metrics_enabled or settings.metrics_path != "/metrics":
        raise HTTPException(status_code=404)
    return Response(
        content=runtime.metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
