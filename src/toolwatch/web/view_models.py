"""Immutable view models rendered by Jinja templates."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    """Aggregated counters and recency lists shown on the dashboard home."""

    total_sessions: int
    active_sessions: int
    total_tool_calls: int
    blocked_tool_calls: int
    flagged_tool_calls: int
    failed_tool_calls: int
    timed_out_tool_calls: int
    replayed_tool_calls: int
    risk_flags: int
    redaction_events: int
    recent_sessions: tuple["SessionListItem", ...]
    recent_high_risk_calls: tuple["ToolCallTimelineItem", ...]


@dataclass(frozen=True, slots=True)
class AgentView:
    """Sanitized agent identity for rendering."""

    id: UUID
    name: str
    provider: str
    model_name: str
    version: str | None


@dataclass(frozen=True, slots=True)
class SessionListItem:
    """One row on the sessions list page."""

    id: UUID
    agent: AgentView
    status: str
    started_at: datetime
    finished_at: datetime | None
    tool_call_count: int
    highest_risk: str
    blocked_count: int
    flagged_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class AuditEventView:
    """One sanitized append-only audit event displayed in a timeline."""

    id: UUID
    event_type: str
    actor_type: str
    actor_id: str | None
    trace_id: str | None
    correlation_id: str | None
    created_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class ToolCallTimelineItem:
    """One row within a session tool-call timeline."""

    id: UUID
    sequence_number: int
    tool_name: str
    tool_version: str
    status: str
    decision: str
    risk_level: str
    flag_codes: tuple[str, ...]
    matched_rule_names: tuple[str, ...]
    duration_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    error_code: str | None
    error_message_safe: str | None


@dataclass(frozen=True, slots=True)
class SessionDetail:
    """Session detail view with tool-call timeline and audit events."""

    id: UUID
    agent: AgentView
    status: str
    started_at: datetime
    finished_at: datetime | None
    external_session_id: str | None
    tool_calls: tuple[ToolCallTimelineItem, ...]
    audit_events: tuple[AuditEventView, ...]


@dataclass(frozen=True, slots=True)
class RiskFlagView:
    """One risk flag rendered as inert escaped data."""

    code: str
    severity: str
    message: str
    source: str
    safe_evidence_json: str


@dataclass(frozen=True, slots=True)
class ToolCallDetail:
    """Sanitized tool-call detail rendered on its own page."""

    id: UUID
    session_id: UUID
    parent_call_id: UUID | None
    tool_name: str
    tool_version: str
    sequence_number: int
    status: str
    decision: str
    risk_level: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    error_code: str | None
    error_message_safe: str | None
    arguments_json: str
    arguments_truncated: bool
    result_json: str | None
    result_truncated: bool
    flags: tuple[RiskFlagView, ...]
    matched_rule_names: tuple[str, ...]
    audit_events: tuple[AuditEventView, ...]
    correlation_ids: tuple[str, ...]
    trace_ids: tuple[str, ...]
    jaeger_link: str | None


@dataclass(frozen=True, slots=True)
class RuleView:
    """Sanitized blocking rule shown on the rules list."""

    id: UUID
    name: str
    description: str
    enabled: bool
    priority: int
    tool_pattern: str
    action: str
    condition_summary: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AgentRunListItem:
    id: UUID
    session_id: UUID
    provider: str
    model_name: str
    status: str
    turn_count: int
    tool_call_count: int
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ModelCallView:
    turn_number: int
    status: str
    requested_tool_count: int
    prompt_token_count: int | None
    completion_token_count: int | None
    total_duration_ms: int | None
    load_duration_ms: int | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class AgentRunDetail:
    id: UUID
    session_id: UUID
    provider: str
    model_name: str
    status: str
    turn_count: int
    tool_call_count: int
    final_answer: str | None
    error_code: str | None
    trace_id: str | None
    correlation_id: str | None
    started_at: datetime
    finished_at: datetime | None
    model_calls: tuple[ModelCallView, ...]
    tool_calls: tuple[ToolCallTimelineItem, ...]
    audit_events: tuple[AuditEventView, ...]
    jaeger_link: str | None


@dataclass(frozen=True, slots=True)
class PaginationView:
    """Bounded pagination metadata for list pages."""

    limit: int
    offset: int
    total: int
    has_previous: bool
    has_next: bool
    previous_offset: int
    next_offset: int


@dataclass(frozen=True, slots=True)
class AttackAssertionView:
    """One safe assertion result rendered after an attack run."""

    name: str
    passed: bool
    expected: str
    observed_safe: str


@dataclass(frozen=True, slots=True)
class AttackScenarioView:
    """A read-only static scenario description."""

    id: str
    name: str
    description: str
    category: str
    severity: str
    tool_name: str
    tool_version: str
    expected_decision: str | None
    expected_status: str | None
    expected_risk: str | None
    expected_flags: tuple[str, ...]
    expected_adapter_called: bool | None


@dataclass(frozen=True, slots=True)
class AttackRunResultView:
    """One Attack Lab run report rendered as escaped data."""

    scenario: AttackScenarioView
    passed: bool
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    tool_call_id: UUID | None
    session_id: UUID | None
    observed_status: str | None
    observed_decision: str | None
    observed_risk: str | None
    observed_flags: tuple[str, ...]
    matched_rules: tuple[str, ...]
    adapter_called: bool | None
    replayed: bool
    trace_id: str | None
    correlation_id: str | None
    assertions: tuple[AttackAssertionView, ...] = field(default_factory=tuple)
