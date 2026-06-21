"""Deterministic JSON canonicalization, hashing, and payload limits."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from toolwatch.domain.common import JSONObject, JSONValue


class PayloadValidationError(ValueError):
    """Base class for safe payload validation failures."""

    code = "invalid_tool_arguments"


class PayloadTooLarge(PayloadValidationError):
    """A canonical payload exceeds its configured byte limit."""


class PayloadTooDeep(PayloadValidationError):
    """A JSON payload exceeds its configured nesting limit."""

    code = "tool_payload_too_deep"


class PayloadStringTooLong(PayloadValidationError):
    """A JSON string exceeds its configured character limit."""


class PayloadNotJson(PayloadValidationError):
    """A value cannot be represented as strict JSON."""


@dataclass(frozen=True, slots=True)
class CanonicalPayload:
    """One validated canonical JSON representation."""

    value: JSONValue
    encoded: bytes
    sha256: str

    @property
    def size_bytes(self) -> int:
        """Return the UTF-8 serialized size."""

        return len(self.encoded)


def canonicalize_json(
    value: object,
    *,
    max_bytes: int,
    max_depth: int,
    max_string_length: int,
) -> CanonicalPayload:
    """Validate strict JSON and serialize it deterministically without mutation."""

    normalized = _normalize(
        value,
        depth=0,
        max_depth=max_depth,
        max_string_length=max_string_length,
    )
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PayloadNotJson("payload is not JSON-compatible") from exc
    if len(encoded) > max_bytes:
        raise PayloadTooLarge("payload exceeds configured byte limit")
    return CanonicalPayload(
        value=normalized,
        encoded=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def canonicalize_object(
    value: Mapping[str, object],
    *,
    max_bytes: int,
    max_depth: int,
    max_string_length: int,
) -> tuple[JSONObject, CanonicalPayload]:
    """Canonicalize a JSON object and preserve its object type."""

    payload = canonicalize_json(
        value,
        max_bytes=max_bytes,
        max_depth=max_depth,
        max_string_length=max_string_length,
    )
    if not isinstance(payload.value, dict):
        raise PayloadNotJson("payload must be a JSON object")
    return payload.value, payload


def request_hash(
    *,
    session_id: UUID,
    tool_name: str,
    tool_version: str,
    canonical_arguments: bytes,
) -> str:
    """Hash an unambiguous length-prefixed execution identity."""

    digest = hashlib.sha256()
    for component in (
        str(session_id).encode(),
        tool_name.encode("utf-8"),
        tool_version.encode("utf-8"),
        canonical_arguments,
    ):
        digest.update(len(component).to_bytes(8, "big"))
        digest.update(component)
    return digest.hexdigest()


def _normalize(
    value: object,
    *,
    depth: int,
    max_depth: int,
    max_string_length: int,
) -> JSONValue:
    if depth > max_depth:
        raise PayloadTooDeep("payload exceeds configured JSON depth")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        if len(value) > max_string_length:
            raise PayloadStringTooLong("payload contains an oversized string")
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise PayloadNotJson("payload contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: JSONObject = {}
        for key, nested in cast(Mapping[object, object], value).items():
            if not isinstance(key, str):
                raise PayloadNotJson("payload contains a non-string object key")
            if len(key) > max_string_length:
                raise PayloadStringTooLong("payload contains an oversized object key")
            result[key] = _normalize(
                nested,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_length=max_string_length,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            _normalize(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_length=max_string_length,
            )
            for item in cast(Sequence[object], value)
        ]
    raise PayloadNotJson("payload is not JSON-compatible")
