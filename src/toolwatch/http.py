"""Small framework-level HTTP hardening middleware."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestSizeLimitMiddleware:
    """Reject requests whose declared body exceeds the configured limit."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            content_length = next(
                (
                    value
                    for key, value in scope.get("headers", [])
                    if key.lower() == b"content-length"
                ),
                None,
            )
            if content_length is not None:
                try:
                    too_large = int(content_length) > self._max_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b'{"error":{"code":"request_too_large"}}',
                        }
                    )
                    return
        await self._app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Add conservative metadata headers to API responses."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                secure_names = {
                    b"x-content-type-options",
                    b"referrer-policy",
                    b"cache-control",
                }
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in secure_names
                ]
                headers.extend(
                    (
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_headers)
