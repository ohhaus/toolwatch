"""Structured JSON logging with correlation fields and strict safe extras."""

import json
import logging
from datetime import UTC, datetime
from typing import Final

from toolwatch.telemetry.context import current_correlation

SAFE_EXTRA_FIELDS: Final = frozenset(
    {
        "call_id",
        "session_id",
        "tool_name",
        "tool_version",
        "status",
        "decision",
        "risk_level",
        "duration_ms",
        "error_code",
    }
)


class CorrelationFilter(logging.Filter):
    """Attach normalized context without changing trace state."""

    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def filter(self, record: logging.LogRecord) -> bool:
        context = current_correlation()
        record.correlation_id = context.correlation_id
        record.trace_id = context.trace_id
        record.span_id = context.span_id
        record.service = self._service
        record.environment = self._environment
        return True


class SafeJsonFormatter(logging.Formatter):
    """Serialize only server-controlled lifecycle metadata."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": str(record.msg)[:255],
            "service": getattr(record, "service", "toolwatch"),
            "environment": getattr(record, "environment", "unknown"),
            "correlation_id": getattr(record, "correlation_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
        }
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, str | int | float | bool) or value is None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(*, level: str, service: str, environment: str) -> None:
    """Install one safe process handler and suppress raw exporter diagnostics."""

    handler = logging.StreamHandler()
    handler.set_name("toolwatch-safe")
    handler.setFormatter(SafeJsonFormatter())
    handler.addFilter(CorrelationFilter(service, environment))
    root = logging.getLogger()
    root.handlers = [
        existing for existing in root.handlers if existing.get_name() != "toolwatch-safe"
    ]
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("opentelemetry.exporter").setLevel(logging.CRITICAL)
