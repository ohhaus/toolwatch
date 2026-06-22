"""Safe OpenTelemetry tracing facade with no payload-bearing API."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from toolwatch.telemetry.attributes import safe_span_attributes


class Span(Protocol):
    """Small application-facing span interface."""

    def set_attributes(self, attributes: Mapping[str, object]) -> None: ...

    def set_error(
        self,
        error_code: str,
        exception_type: type[BaseException] | None = None,
    ) -> None: ...


class _OtelSpan:
    def __init__(self, span: trace.Span) -> None:
        self._span = span

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        for key, value in safe_span_attributes(attributes).items():
            self._span.set_attribute(key, value)

    def set_error(
        self,
        error_code: str,
        exception_type: type[BaseException] | None = None,
    ) -> None:
        self._span.set_status(Status(StatusCode.ERROR))
        self._span.set_attribute("toolwatch.error.code", error_code[:100])
        if exception_type is not None:
            self._span.set_attribute("exception.type", exception_type.__name__[:100])


@dataclass(slots=True)
class Tracing:
    """Create bounded spans or act as a deterministic no-op."""

    tracer: trace.Tracer | None

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        context: Any = None,
    ) -> Generator[Span]:
        """Create one span without recording exception messages or stack traces."""

        if self.tracer is None:
            yield _OtelSpan(trace.INVALID_SPAN)
            return
        with self.tracer.start_as_current_span(
            name[:255],
            kind=kind,
            context=context,
            record_exception=False,
            set_status_on_exception=False,
            attributes=safe_span_attributes(attributes or {}),
        ) as span:
            yield _OtelSpan(span)
