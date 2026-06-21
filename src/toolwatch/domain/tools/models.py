"""Trusted tool definition domain entity."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    DomainValidationError,
    JSONObject,
    require_non_empty,
    require_utc,
    utc_now,
    validate_json_object,
)

TOOL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SECRET_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
}


class RiskLevel(StrEnum):
    """Stored base risk classification for a registered tool."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A trusted, versioned tool registry entry."""

    name: str
    description: str
    version: str
    input_schema: JSONObject
    output_schema: JSONObject | None
    base_risk_level: RiskLevel
    adapter_type: str
    adapter_config: JSONObject
    enabled: bool = True
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if TOOL_NAME_PATTERN.fullmatch(self.name) is None:
            raise DomainValidationError(
                "name must contain lowercase namespace segments separated by '.', '_' or '-'"
            )
        require_non_empty(self.description, "description")
        require_non_empty(self.version, "version")
        require_non_empty(self.adapter_type, "adapter_type")
        normalized_input = validate_json_schema(self.input_schema, "input_schema", object_only=True)
        normalized_output = (
            validate_json_schema(self.output_schema, "output_schema", object_only=False)
            if self.output_schema is not None
            else None
        )
        normalized_config = validate_json_object(self.adapter_config, "adapter_config")
        _reject_secret_config_keys(normalized_config)
        object.__setattr__(self, "input_schema", normalized_input)
        object.__setattr__(self, "output_schema", normalized_output)
        object.__setattr__(self, "adapter_config", normalized_config)
        require_utc(self.created_at, "created_at")
        require_utc(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise DomainValidationError("updated_at must not precede created_at")

    def set_enabled(self, enabled: bool, *, now: datetime | None = None) -> "ToolDefinition":
        """Return an updated registry entry."""

        changed_at = now or utc_now()
        require_utc(changed_at, "updated_at")
        if enabled == self.enabled:
            return self
        return replace(self, enabled=enabled, updated_at=changed_at)


def validate_json_schema(
    value: Mapping[str, object],
    field_name: str,
    *,
    object_only: bool,
) -> JSONObject:
    """Validate a supported JSON Schema Draft 2020-12 document."""

    schema = validate_json_object(value, field_name)
    from toolwatch.security.schema import validate_schema_document

    return validate_schema_document(schema, field_name, object_only=object_only)


def _reject_secret_config_keys(value: JSONObject) -> None:
    for key, nested in value.items():
        if key.lower() in SECRET_CONFIG_KEYS:
            raise DomainValidationError("adapter_config must reference secrets indirectly")
        if isinstance(nested, dict):
            _reject_secret_config_keys(nested)
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    _reject_secret_config_keys(item)
