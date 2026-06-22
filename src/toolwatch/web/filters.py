"""Jinja2 template filters and globals."""

from datetime import datetime, timezone

_RISK_TONES = {
    "low": "tone-neutral",
    "medium": "tone-caution",
    "high": "tone-warning",
    "critical": "tone-danger",
}

_STATUS_TONES = {
    "succeeded": "tone-success",
    "received": "tone-neutral",
    "validating": "tone-neutral",
    "evaluating": "tone-neutral",
    "executing": "tone-neutral",
    "rejected": "tone-error",
    "blocked": "tone-danger",
    "failed": "tone-error",
    "timed_out": "tone-error",
}

_DECISION_TONES = {
    "allow": "tone-success",
    "flag": "tone-warning",
    "block": "tone-danger",
    "reject": "tone-error",
}


def isoformat_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def humanize_utc(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def duration_label(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "—"
    if milliseconds < 1_000:
        return f"{milliseconds} ms"
    seconds = milliseconds / 1_000
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes = seconds / 60
    return f"{minutes:.2f} min"


def risk_tone(value: str) -> str:
    return _RISK_TONES.get(value, "tone-neutral")


def status_tone(value: str) -> str:
    return _STATUS_TONES.get(value, "tone-neutral")


def decision_tone(value: str) -> str:
    return _DECISION_TONES.get(value, "tone-neutral")
