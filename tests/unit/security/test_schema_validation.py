"""Tests for the restricted Draft 2020-12 validation boundary."""

import pytest

from toolwatch.domain.common import DomainValidationError, JSONObject
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.security.payloads import PayloadStringTooLong, PayloadTooDeep, canonicalize_json
from toolwatch.security.schema import validate_instance

SCHEMA: JSONObject = {
    "type": "object",
    "properties": {
        "recipient": {"type": "string", "format": "email"},
        "state": {"type": "string", "enum": ["open", "closed"]},
        "nested": {
            "type": "object",
            "properties": {"id": {"type": "string", "format": "uuid"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    "required": ["recipient", "state", "nested"],
    "additionalProperties": False,
}


def test_valid_arguments_and_formats() -> None:
    issues = validate_instance(
        SCHEMA,
        {
            "recipient": "user@example.com",
            "state": "open",
            "nested": {"id": "123e4567-e89b-12d3-a456-426614174000"},
        },
    )

    assert issues == []


@pytest.mark.parametrize(
    ("arguments", "path"),
    [
        ({"recipient": "user@example.com", "state": "open"}, "$"),
        (
            {
                "recipient": "invalid",
                "state": "open",
                "nested": {"id": "123e4567-e89b-12d3-a456-426614174000"},
            },
            "$.recipient",
        ),
        (
            {
                "recipient": "user@example.com",
                "state": "other",
                "nested": {"id": "123e4567-e89b-12d3-a456-426614174000"},
            },
            "$.state",
        ),
        (
            {
                "recipient": "user@example.com",
                "state": "open",
                "nested": {"id": "123e4567-e89b-12d3-a456-426614174000"},
                "extra": True,
            },
            "$",
        ),
    ],
)
def test_invalid_arguments_have_safe_paths(arguments: dict[str, object], path: str) -> None:
    issues = validate_instance(SCHEMA, arguments)  # type: ignore[arg-type]

    assert issues
    assert issues[0].path == path


def test_unsupported_reference_is_rejected_at_registration() -> None:
    with pytest.raises(DomainValidationError):
        ToolDefinition(
            name="demo.tool",
            description="Demo",
            version="1",
            input_schema={"type": "object", "$ref": "https://example.test/schema"},
            output_schema=None,
            base_risk_level=RiskLevel.LOW,
            adapter_type="mock_github",
            adapter_config={},
        )


def test_payload_depth_and_string_limits() -> None:
    with pytest.raises(PayloadTooDeep):
        canonicalize_json(
            {"a": {"b": {"c": 1}}},
            max_bytes=1000,
            max_depth=1,
            max_string_length=100,
        )
    with pytest.raises(PayloadStringTooLong):
        canonicalize_json(
            {"value": "too long"},
            max_bytes=1000,
            max_depth=10,
            max_string_length=3,
        )
