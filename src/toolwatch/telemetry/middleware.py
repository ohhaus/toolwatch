"""ASGI request tracing, bounded correlation, and HTTP metrics."""

from time import perf_counter

from opentelemetry import propagate
from opentelemetry.trace import SpanKind
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from toolwatch.telemetry.context import correlation_context, normalize_correlation_id
from toolwatch.telemetry.provider import TelemetryRuntime

CORRELATION_HEADER = b"x-correlation-id"


class ObservabilityMiddleware:
    """Instrument HTTP without reading bodies, query strings, cookies, or authorization."""

    def __init__(self, app: ASGIApp, runtime: TelemetryRuntime) -> None:
        self._app = app
        self._runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
            if key.lower() in {b"traceparent", b"tracestate", CORRELATION_HEADER}
        }
        correlation_id = normalize_correlation_id(headers.get("x-correlation-id"))
        extracted = propagate.extract(headers)
        method = str(scope.get("method", "UNKNOWN")).upper()[:16]
        status_code = 500
        started = perf_counter()

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.append((CORRELATION_HEADER, correlation_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        with correlation_context(correlation_id):
            with self._runtime.tracing.span(
                f"{method} request",
                kind=SpanKind.SERVER,
                attributes={"http.request.method": method},
                context=extracted,
            ) as span:
                try:
                    await self._app(scope, receive, send_with_correlation)
                except Exception as exc:
                    span.set_error("internal_error", type(exc))
                    raise
                finally:
                    route = _route_template(scope)
                    duration = perf_counter() - started
                    span.set_attributes(
                        {
                            "http.route": route,
                            "http.response.status_code": status_code,
                        }
                    )
                    labels = {
                        "method": method,
                        "route": route,
                        "status_code": str(status_code),
                    }
                    self._runtime.metrics.counter("toolwatch_http_requests_total", labels)
                    self._runtime.metrics.histogram(
                        "toolwatch_http_request_duration_seconds",
                        duration,
                        labels,
                    )


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and len(path) <= 255:
        return path
    return "unmatched"
