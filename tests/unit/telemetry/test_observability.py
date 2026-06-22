"""Unit tests for bounded correlation, tracing, metrics, and telemetry safety."""

import logging
from uuid import uuid4

import httpx
import pytest
from opentelemetry.sdk.trace.export import SpanExportResult

from toolwatch.config import Settings
from toolwatch.main import create_app
from toolwatch.telemetry.attributes import safe_span_attributes, validate_metric_labels
from toolwatch.telemetry.context import correlation_context, is_trace_id, normalize_correlation_id
from toolwatch.telemetry.logging import CorrelationFilter, SafeJsonFormatter
from toolwatch.telemetry.metrics import Metrics
from toolwatch.telemetry.provider import SafeSpanExporter, build_telemetry_runtime
from toolwatch.telemetry.testing import build_in_memory_runtime


def test_correlation_and_trace_identifier_validation() -> None:
    value = str(uuid4())

    assert normalize_correlation_id(value) == value
    assert normalize_correlation_id("not-a-uuid") != "not-a-uuid"
    assert is_trace_id("1" * 32)
    assert not is_trace_id("0" * 32)
    assert not is_trace_id("secret")


def test_attribute_and_metric_label_allowlists_drop_or_reject_unknown_data() -> None:
    sentinel = "sentinel-attribute-417c"

    assert safe_span_attributes(
        {
            "gen_ai.tool.name": "demo.execute",
            "tool.arguments": sentinel,
            "exception.message": sentinel,
        }
    ) == {"gen_ai.tool.name": "demo.execute"}
    with pytest.raises(ValueError):
        validate_metric_labels({"correlation_id": sentinel})


def test_metrics_are_isolated_and_use_explicit_buckets() -> None:
    first = Metrics(enabled=True)
    second = Metrics(enabled=True)
    labels = {"status": "succeeded"}

    first.counter("toolwatch_sessions_total", labels)
    first.histogram("toolwatch_tool_call_duration_seconds", 0.1, labels)

    rendered = first.render().decode()
    assert 'toolwatch_sessions_total{status="succeeded"} 1.0' in rendered
    assert 'le="0.1"' in rendered
    assert "toolwatch_sessions_total" not in second.render().decode()


def test_structured_logging_contains_correlation_without_unknown_extras() -> None:
    runtime, _ = build_in_memory_runtime()
    correlation_id = str(uuid4())
    record = logging.LogRecord(
        "toolwatch.test",
        logging.INFO,
        "",
        0,
        "safe_event",
        (),
        None,
    )
    record.__dict__["arguments"] = "UNIQUE_LOG_ARGUMENT_SECRET_b881"

    with correlation_context(correlation_id):
        with runtime.tracing.span("toolwatch.test"):
            CorrelationFilter("toolwatch", "test").filter(record)
            rendered = SafeJsonFormatter().format(record)

    assert correlation_id in rendered
    assert '"trace_id":null' not in rendered
    assert '"span_id":null' not in rendered
    assert "UNIQUE_LOG_ARGUMENT_SECRET_b881" not in rendered
    runtime.shutdown()


@pytest.mark.asyncio
async def test_request_span_correlation_and_w3c_parent_propagation() -> None:
    runtime, exporter = build_in_memory_runtime()
    correlation_id = str(uuid4())
    remote_trace_id = "1234567890abcdef1234567890abcdef"
    transport = httpx.ASGITransport(app=create_app(runtime))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health/live",
            headers={
                "X-Correlation-ID": correlation_id,
                "traceparent": f"00-{remote_trace_id}-1234567890abcdef-01",
            },
        )

    span = next(item for item in exporter.get_finished_spans() if item.kind.name == "SERVER")
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert span.context is not None
    assert f"{span.context.trace_id:032x}" == remote_trace_id
    assert span.parent is not None
    assert f"{span.parent.span_id:016x}" == "1234567890abcdef"
    assert span.attributes is not None
    assert "http.route" in span.attributes
    runtime.shutdown()


@pytest.mark.asyncio
async def test_malformed_trace_and_correlation_headers_fail_safely() -> None:
    runtime, exporter = build_in_memory_runtime()
    transport = httpx.ASGITransport(app=create_app(runtime))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health/live",
            headers={
                "X-Correlation-ID": "UNIQUE_BAD_CORRELATION_SECRET_842a",
                "traceparent": "malformed-secret-trace-header",
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "UNIQUE_BAD_CORRELATION_SECRET_842a"
    assert "UNIQUE_BAD_CORRELATION_SECRET_842a" not in repr(exporter.get_finished_spans())
    runtime.shutdown()


@pytest.mark.asyncio
async def test_metrics_endpoint_enabled_and_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _ = build_in_memory_runtime()
    transport = httpx.ASGITransport(app=create_app(runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health/live")
        enabled = await client.get("/metrics")

    assert enabled.status_code == 200
    assert "toolwatch_http_requests_total" in enabled.text
    runtime.shutdown()

    monkeypatch.setenv("METRICS_ENABLED", "false")
    from toolwatch.config import get_settings

    get_settings.cache_clear()
    disabled_runtime, _ = build_in_memory_runtime()
    disabled_transport = httpx.ASGITransport(app=create_app(disabled_runtime))
    async with httpx.AsyncClient(
        transport=disabled_transport,
        base_url="http://test",
    ) as client:
        disabled = await client.get("/metrics")
    assert disabled.status_code == 404
    disabled_runtime.shutdown()


def test_disabled_runtime_and_safe_exporter_failure() -> None:
    runtime = build_telemetry_runtime(Settings(otel_enabled=False, metrics_enabled=False))

    class BrokenExporter:
        def export(self, spans: object) -> SpanExportResult:
            del spans
            raise RuntimeError("UNIQUE_EXPORTER_EXCEPTION_SECRET_a81c")

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            del timeout_millis
            return True

    safe = SafeSpanExporter(BrokenExporter())  # type: ignore[arg-type]

    with runtime.tracing.span("disabled-span"):
        pass
    assert safe.export(()) is SpanExportResult.FAILURE
    assert safe.failures == 1
    assert runtime.metrics.render() == b""
    runtime.shutdown()
