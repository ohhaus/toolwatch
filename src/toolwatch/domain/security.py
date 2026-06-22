"""Framework-independent security pipeline domain values."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from fnmatch import fnmatchcase
from uuid import UUID, uuid4

from toolwatch.domain.common import (
    DomainValidationError,
    JSONObject,
    JSONValue,
    empty_json_object,
    require_non_empty,
    require_utc,
    utc_now,
    validate_json_object,
)
from toolwatch.domain.tools import RiskLevel


class RiskFlagCode(StrEnum):
    """Stable deterministic risk findings."""

    WRITE_OPERATION = "write_operation"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    SENSITIVE_INPUT = "sensitive_input"
    SENSITIVE_OUTPUT = "sensitive_output"
    DESTRUCTIVE_SQL = "destructive_sql"
    WRITE_SQL = "write_sql"
    MULTIPLE_SQL_STATEMENTS = "multiple_sql_statements"
    POSSIBLE_COMMAND_INJECTION = "possible_command_injection"
    POSSIBLE_PATH_TRAVERSAL = "possible_path_traversal"
    POSSIBLE_SSRF_TARGET = "possible_ssrf_target"
    POSSIBLE_INDIRECT_PROMPT_INJECTION = "possible_indirect_prompt_injection"
    OVERSIZED_PAYLOAD = "oversized_payload"
    UNKNOWN_OPERATION = "unknown_operation"


class RiskFlagSource(StrEnum):
    """Pipeline stage that produced a flag."""

    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class RiskFlag:
    """Safe risk evidence that never includes a full payload."""

    code: RiskFlagCode
    severity: RiskLevel
    message: str
    safe_evidence: JSONObject = field(default_factory=empty_json_object)
    source: RiskFlagSource = RiskFlagSource.INPUT
    id: UUID = field(default_factory=uuid4)
    tool_call_id: UUID | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_non_empty(self.message, "message")
        object.__setattr__(
            self,
            "safe_evidence",
            validate_json_object(self.safe_evidence, "safe_evidence"),
        )
        require_utc(self.created_at, "created_at")

    def for_call(self, call_id: UUID) -> "RiskFlag":
        """Bind a classified flag to a persisted tool call."""

        return RiskFlag(
            id=self.id,
            tool_call_id=call_id,
            code=self.code,
            severity=self.severity,
            message=self.message,
            safe_evidence=self.safe_evidence,
            source=self.source,
            created_at=self.created_at,
        )


class RuleAction(StrEnum):
    """Deterministic runtime rule actions."""

    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class BlockingRule:
    """Persisted, tightly constrained runtime rule."""

    name: str
    description: str
    enabled: bool
    priority: int
    tool_pattern: str
    conditions: JSONObject
    action: RuleAction
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.description, "description")
        require_non_empty(self.tool_pattern, "tool_pattern")
        normalized = validate_json_object(self.conditions, "conditions")
        _validate_conditions(normalized)
        if "result_has_flag" in normalized and self.action is RuleAction.BLOCK:
            raise DomainValidationError("result rules cannot use the block action")
        object.__setattr__(self, "conditions", normalized)
        require_utc(self.created_at, "created_at")
        require_utc(self.updated_at, "updated_at")

    def matches_tool(self, tool_name: str) -> bool:
        """Match an exact name or a simple shell-style wildcard pattern."""

        return fnmatchcase(tool_name, self.tool_pattern)


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One safe matched-rule record."""

    rule_id: UUID
    rule_name: str
    action: RuleAction
    priority: int


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Deterministic aggregate rule result."""

    action: RuleAction
    matches: tuple[RuleMatch, ...]


class AuditEventType(StrEnum):
    """Append-only application audit event types."""

    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    TOOL_CALL_RECEIVED = "tool_call.received"
    TOOL_CALL_VALIDATED = "tool_call.validated"
    TOOL_CALL_RISK_CLASSIFIED = "tool_call.risk_classified"
    TOOL_CALL_FLAGGED = "tool_call.flagged"
    TOOL_CALL_BLOCKED = "tool_call.blocked"
    TOOL_CALL_STARTED = "tool_call.started"
    TOOL_CALL_COMPLETED = "tool_call.completed"
    TOOL_CALL_FAILED = "tool_call.failed"
    TOOL_CALL_TIMED_OUT = "tool_call.timed_out"
    REDACTION_APPLIED = "redaction.applied"
    RULE_MATCHED = "rule.matched"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Safe append-only audit event."""

    session_id: UUID
    event_type: AuditEventType
    payload_redacted: JSONObject
    tool_call_id: UUID | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_non_empty(self.actor_type, "actor_type")
        if self.trace_id is not None and (
            len(self.trace_id) != 32
            or any(character not in "0123456789abcdef" for character in self.trace_id)
        ):
            raise DomainValidationError("trace_id must be a lowercase 32-character hex value")
        if self.correlation_id is not None:
            try:
                UUID(self.correlation_id)
            except ValueError as exc:
                raise DomainValidationError("correlation_id must be a UUID") from exc
        object.__setattr__(
            self,
            "payload_redacted",
            validate_json_object(self.payload_redacted, "payload_redacted"),
        )
        require_utc(self.created_at, "created_at")


def risk_max(*levels: RiskLevel) -> RiskLevel:
    """Return the highest ordered risk level."""

    order = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }
    return max(levels, key=order.__getitem__)


def risk_at_least(value: RiskLevel, threshold: RiskLevel) -> bool:
    """Return whether a risk meets an ordered threshold."""

    return risk_max(value, threshold) is value


def json_path_value(value: JSONValue, path: str) -> JSONValue | None:
    """Resolve a small dot-separated JSON object/array path."""

    current: JSONValue = value
    normalized = path.removeprefix("$.").removeprefix("$")
    if not normalized:
        return current
    for component in normalized.split("."):
        if isinstance(current, dict):
            if component not in current:
                return None
            current = current[component]
        elif isinstance(current, list) and component.isdigit():
            index = int(component)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _validate_conditions(conditions: JSONObject) -> None:
    supported = {
        "tool_equals",
        "tool_matches",
        "risk_at_least",
        "has_flag",
        "argument_path_equals",
        "argument_path_matches",
        "result_has_flag",
    }
    if not conditions or any(key not in supported for key in conditions):
        raise DomainValidationError("conditions contain unsupported keys")
    for key, value in conditions.items():
        if key in {
            "tool_equals",
            "tool_matches",
            "risk_at_least",
            "has_flag",
            "result_has_flag",
        } and not isinstance(value, str):
            raise DomainValidationError(f"{key} must be a string")
        if key == "risk_at_least" and value not in {level.value for level in RiskLevel}:
            raise DomainValidationError("risk_at_least contains an invalid risk level")
        if key in {"tool_matches"} and isinstance(value, str):
            _validate_safe_regex(value)
        if key in {"argument_path_equals", "argument_path_matches"}:
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("path"), str)
                or "value" not in value
            ):
                raise DomainValidationError(f"{key} must contain path and value")
            pattern = value.get("value")
            if key == "argument_path_matches" and isinstance(pattern, str):
                _validate_safe_regex(pattern)


def _validate_safe_regex(pattern: str) -> None:
    """Reject expensive or highly expressive regex features."""

    import re

    if (
        len(pattern) > 256
        or re.search(r"\\[1-9]|\(\?[:=!<]|(?:\*|\+|\{[^}]+\})(?:\*|\+|\{)", pattern) is not None
    ):
        raise DomainValidationError("rule regex contains unsupported constructs")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise DomainValidationError("rule regex is invalid") from exc
