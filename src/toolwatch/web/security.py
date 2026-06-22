"""Browser security headers for dashboard responses."""

from collections.abc import Mapping

CONTENT_SECURITY_POLICY: str = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

PERMISSIONS_POLICY: str = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
)


def security_headers(*, html: bool, dashboard_prefix: str | None = None) -> Mapping[str, str]:
    """Return the headers attached to every dashboard or static response."""

    del dashboard_prefix
    headers: dict[str, str] = {
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": PERMISSIONS_POLICY,
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if html:
        headers["Cache-Control"] = "no-store"
    return headers
