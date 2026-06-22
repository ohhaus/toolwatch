"""Deterministic in-memory telemetry runtime for tests."""

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from toolwatch.telemetry.metrics import Metrics
from toolwatch.telemetry.provider import TelemetryRuntime
from toolwatch.telemetry.tracing import Tracing


def build_in_memory_runtime() -> tuple[TelemetryRuntime, InMemorySpanExporter]:
    """Return an isolated provider and synchronous in-memory exporter."""

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "toolwatch-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    runtime = TelemetryRuntime(
        tracing=Tracing(provider.get_tracer("toolwatch-test")),
        metrics=Metrics(enabled=True),
        provider=provider,
    )
    return runtime, exporter
