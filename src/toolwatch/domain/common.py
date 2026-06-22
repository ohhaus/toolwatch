"""Shared framework-independent domain primitives."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

MAX_JSON_DEPTH = 20
MAX_JSON_BYTES = 65_536


class DomainValidationError(ValueError):
    """Raised when an entity would violate a domain invariant."""


def empty_json_object() -> JSONObject:
    """Return a correctly typed empty JSON object."""

    return {}


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def require_utc(value: datetime, field_name: str) -> None:
    """Require a timezone-aware timestamp expressed in UTC."""

    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise DomainValidationError(f"{field_name} must be timezone-aware UTC")


def require_non_empty(value: str, field_name: str) -> None:
    """Require a non-empty, non-whitespace string."""

    if not value.strip():
        raise DomainValidationError(f"{field_name} must be non-empty")


def validate_json_object(
    value: Mapping[str, object],
    field_name: str,
    *,
    max_depth: int = MAX_JSON_DEPTH,
    max_bytes: int = MAX_JSON_BYTES,
) -> JSONObject:
    """Validate and copy a bounded JSON-compatible object."""

    normalized = _validate_json_value(value, field_name, depth=0, max_depth=max_depth)
    if not isinstance(normalized, dict):
        raise DomainValidationError(f"{field_name} must be a JSON object")

    import json

    if len(json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode()) > max_bytes:
        raise DomainValidationError(f"{field_name} is too large")
    return normalized


def validate_json_value(
    value: object,
    field_name: str,
    *,
    max_depth: int = MAX_JSON_DEPTH,
) -> JSONValue:
    """Validate and copy one bounded JSON-compatible value."""

    return _validate_json_value(value, field_name, depth=0, max_depth=max_depth)


def _validate_json_value(
    value: object,
    field_name: str,
    *,
    depth: int,
    max_depth: int,
) -> JSONValue:
    if depth > max_depth:
        raise DomainValidationError(f"{field_name} exceeds maximum JSON depth")
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise DomainValidationError(f"{field_name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: JSONObject = {}
        mapping = cast(Mapping[object, object], value)
        for key, nested in mapping.items():
            if not isinstance(key, str):
                raise DomainValidationError(f"{field_name} contains a non-string key")
            result[key] = _validate_json_value(
                nested,
                field_name,
                depth=depth + 1,
                max_depth=max_depth,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        sequence = cast(Sequence[object], value)
        return [
            _validate_json_value(item, field_name, depth=depth + 1, max_depth=max_depth)
            for item in sequence
        ]
    raise DomainValidationError(f"{field_name} must be JSON-compatible")
