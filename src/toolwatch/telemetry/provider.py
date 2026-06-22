"""OpenTelemetry provider construction and fail-open exporter lifecycle."""

import logging
from dataclasses import dataclass
from enum import StrEnum

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from toolwatch.config import Settings
from toolwatch.telemetry.metrics import Metrics
from toolwatch.telemetry.tracing import Tracing

logger = logging.getLogger("toolwatch.telemetry")


class ExporterStatus(StrEnum):
    """Safe coarse exporter state."""

    DISABLED = "disabled"
    CONFIGURED = "configured"
    DEGRADED = "degraded"


class SafeSpanExporter(SpanExporter):
    """Collapse exporter failures without leaking endpoints or exception text."""

    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter
        self.failures = 0

    def export(self, spans: object) -> SpanExportResult:
        try:
            result = self._exporter.export(spans)  # type: ignore[arg-type]
        except Exception:
            self.failures += 1
            logger.warning(
                "telemetry_export_failed",
                extra={"error_code": "telemetry_export_failed"},
            )
            return SpanExportResult.FAILURE
        if result is SpanExportResult.FAILURE:
            self.failures += 1
        return result

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:
            self.failures += 1

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return self._exporter.force_flush(timeout_millis)
        except Exception:
            self.failures += 1
            return False


@dataclass(slots=True)
class TelemetryRuntime:
    """Owned tracing, metrics, and exporter resources for one FastAPI app."""

    tracing: Tracing
    metrics: Metrics
    provider: TracerProvider | None = None
    exporter: SafeSpanExporter | None = None
    degraded: bool = False

    @property
    def exporter_status(self) -> ExporterStatus:
        if self.provider is None:
            return ExporterStatus.DISABLED
        if self.degraded or (self.exporter is not None and self.exporter.failures):
            return ExporterStatus.DEGRADED
        return ExporterStatus.CONFIGURED

    def shutdown(self) -> None:
        """Flush and close providers without affecting application shutdown."""

        if self.provider is None:
            return
        try:
            self.provider.force_flush(timeout_millis=2_000)
            self.provider.shutdown()
        except Exception:
            logger.warning(
                "telemetry_shutdown_failed",
                extra={"error_code": "telemetry_shutdown_failed"},
            )


def build_telemetry_runtime(settings: Settings) -> TelemetryRuntime:
    """Build a no-op or OTLP runtime without connecting during startup."""

    metrics = Metrics(
        enabled=settings.metrics_enabled and settings.otel_metrics_exporter == "prometheus"
    )
    if not settings.otel_enabled:
        return TelemetryRuntime(tracing=Tracing(None), metrics=metrics)

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
            "deployment.environment.name": settings.environment,
            "telemetry.sdk.language": "python",
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_trace_sample_ratio)),
    )
    safe_exporter: SafeSpanExporter | None = None
    if settings.otel_traces_exporter == "otlp":
        try:
            exporter = OTLPSpanExporter(
                endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces",
                timeout=2,
            )
            safe_exporter = SafeSpanExporter(exporter)
            provider.add_span_processor(BatchSpanProcessor(safe_exporter))
        except Exception:
            logger.warning(
                "telemetry_configuration_invalid",
                extra={"error_code": "telemetry_configuration_invalid"},
            )
    return TelemetryRuntime(
        tracing=Tracing(provider.get_tracer(settings.otel_service_name, settings.app_version)),
        metrics=metrics,
        provider=provider,
        exporter=safe_exporter,
        degraded=settings.otel_traces_exporter == "otlp" and safe_exporter is None,
    )
