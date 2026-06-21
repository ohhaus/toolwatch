"""Restricted JSON Schema Draft 2020-12 validation."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from toolwatch.domain.common import DomainValidationError, JSONObject, JSONValue

SUPPORTED_KEYWORDS = {
    "$schema",
    "additionalProperties",
    "const",
    "description",
    "enum",
    "format",
    "items",
    "maxLength",
    "maximum",
    "minLength",
    "minimum",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
}
FORBIDDEN_KEYWORDS = {"$ref", "$dynamicRef", "$recursiveRef", "$dynamicAnchor", "$anchor"}
SUPPORTED_FORMATS = {"email", "uri", "uuid", "date-time"}
FORMAT_CHECKER = FormatChecker(formats=SUPPORTED_FORMATS)


@dataclass(frozen=True, slots=True)
class SchemaValidationIssue:
    """Safe deterministic validation issue without payload values."""

    path: str
    message: str


def validate_schema_document(
    schema: JSONObject,
    field_name: str,
    *,
    object_only: bool,
) -> JSONObject:
    """Validate a bounded, non-referencing schema from the supported subset."""

    if object_only and schema.get("type") != "object":
        raise DomainValidationError(f"{field_name} top-level type must be 'object'")
    _validate_supported_keywords(schema, field_name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise DomainValidationError(f"{field_name} is not a valid JSON Schema") from exc
    return schema


def validate_instance(schema: JSONObject, value: JSONValue) -> list[SchemaValidationIssue]:
    """Return deterministic, safe validation issues for one JSON value."""

    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = sorted(
        cast(
            Iterable[ValidationError],
            validator.iter_errors(value),  # pyright: ignore[reportUnknownMemberType]
        ),
        key=_error_sort_key,
    )
    return [
        SchemaValidationIssue(path=_safe_path(error), message=_generic_message(error))
        for error in errors
    ]


def _validate_supported_keywords(schema: JSONObject, field_name: str) -> None:
    for keyword, value in schema.items():
        if keyword in FORBIDDEN_KEYWORDS:
            raise DomainValidationError(f"{field_name} contains unsupported references")
        if keyword not in SUPPORTED_KEYWORDS:
            raise DomainValidationError(f"{field_name} contains unsupported keyword '{keyword}'")
        if keyword == "format" and value not in SUPPORTED_FORMATS:
            raise DomainValidationError(f"{field_name} contains unsupported format")
        if keyword == "properties" and isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, dict):
                    _validate_supported_keywords(nested, field_name)
        elif keyword in {"items", "additionalProperties"} and isinstance(value, dict):
            _validate_supported_keywords(value, field_name)


def _error_sort_key(error: ValidationError) -> tuple[str, str]:
    return (_safe_path(error), _validator_name(error))


def _safe_path(error: ValidationError) -> str:
    parts = [str(part) for part in error.absolute_path]
    return "$" if not parts else "$." + ".".join(parts)


def _generic_message(error: ValidationError) -> str:
    messages = {
        "additionalProperties": "Additional properties are not allowed.",
        "const": "Value does not match the required constant.",
        "enum": "Value is not one of the allowed values.",
        "format": "Value does not match the required format.",
        "items": "Array item is invalid.",
        "maxLength": "String is longer than allowed.",
        "maximum": "Number is greater than allowed.",
        "minLength": "String is shorter than allowed.",
        "minimum": "Number is less than allowed.",
        "pattern": "String does not match the required pattern.",
        "required": "A required property is missing.",
        "type": "Value has the wrong type.",
    }
    return messages.get(_validator_name(error), "Value does not match the schema.")


def _validator_name(error: ValidationError) -> str:
    return error.validator if isinstance(error.validator, str) else ""
