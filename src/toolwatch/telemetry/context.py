"""Bounded request correlation independent of tracing availability."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID, uuid4

from opentelemetry import trace

_correlation_id: ContextVar[str | None] = ContextVar("toolwatch_correlation_id", default=None)


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Safe identifiers for logs, audit records, and public errors."""

    correlation_id: str
    trace_id: str | None
    span_id: str | None


def normalize_correlation_id(value: str | None) -> str:
    """Reuse only canonical UUID input; otherwise create a server identifier."""

    if value is not None and len(value) <= 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


@contextmanager
def correlation_context(correlation_id: str) -> Generator[None]:
    """Bind one validated correlation identifier to the current async context."""

    token: Token[str | None] = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


def current_correlation() -> CorrelationContext:
    """Read normalized active trace identifiers without creating spans."""

    span_context = trace.get_current_span().get_span_context()
    trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
    span_id = f"{span_context.span_id:016x}" if span_context.is_valid else None
    return CorrelationContext(
        correlation_id=_correlation_id.get() or str(uuid4()),
        trace_id=trace_id,
        span_id=span_id,
    )


def is_trace_id(value: str) -> bool:
    """Validate a W3C lowercase trace identifier."""

    return len(value) == 32 and value != "0" * 32 and all(c in "0123456789abcdef" for c in value)
