"""Pure presenters from application/domain values to view models."""

import json
from collections.abc import Iterable

from toolwatch.application.queries import (
    AgentRunDashboardView,
    DashboardCounts,
    SessionSummary,
    SessionTimeline,
    ToolCallTimelineEntry,
    ToolCallView,
)
from toolwatch.domain.agents import Agent
from toolwatch.domain.common import JSONValue
from toolwatch.domain.security import (
    AuditEvent,
    BlockingRule,
    RiskFlag,
)
from toolwatch.domain.tool_calls import ToolCall
from toolwatch.domain.tools import ToolDefinition
from toolwatch.telemetry.context import is_trace_id
from toolwatch.web.view_models import (
    AgentRunDetail,
    AgentRunListItem,
    AgentView,
    AttackRunResultView,
    AttackScenarioView,
    AuditEventView,
    DashboardSummary,
    ModelCallView,
    PaginationView,
    RiskFlagView,
    RuleView,
    SessionDetail,
    SessionListItem,
    ToolCallDetail,
    ToolCallTimelineItem,
)

MAX_JSON_RENDER_BYTES = 12_288
MAX_STRING_RENDER_LENGTH = 2_048


def _bound_string(value: str, *, limit: int = MAX_STRING_RENDER_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def safe_json(value: JSONValue | None, *, limit: int = MAX_JSON_RENDER_BYTES) -> tuple[str, bool]:
    """Pretty-print a sanitized JSON value, bounded for safe HTML rendering."""

    if value is None:
        return "", False
    rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    if len(rendered) > limit:
        return rendered[:limit] + "\n… truncated for display", True
    return rendered, False


def agent_view(agent: Agent) -> AgentView:
    return AgentView(
        id=agent.id,
        name=_bound_string(agent.identity.name, limit=255),
        provider=_bound_string(agent.identity.provider, limit=255),
        model_name=_bound_string(agent.identity.model_name, limit=255),
        version=(
            _bound_string(agent.identity.version, limit=255)
            if agent.identity.version is not None
            else None
        ),
    )


def session_list_item(summary: SessionSummary) -> SessionListItem:
    return SessionListItem(
        id=summary.session.id,
        agent=agent_view(summary.agent),
        status=summary.session.status.value,
        started_at=summary.session.started_at,
        finished_at=summary.session.finished_at,
        tool_call_count=summary.tool_call_count,
        highest_risk=summary.highest_risk,
        blocked_count=summary.blocked_count,
        flagged_count=summary.flagged_count,
        failed_count=summary.failed_count,
    )


def tool_call_timeline_item(entry: ToolCallTimelineEntry) -> ToolCallTimelineItem:
    call = entry.call
    return ToolCallTimelineItem(
        id=call.id,
        sequence_number=call.sequence_number,
        tool_name=_bound_string(entry.tool.name, limit=255),
        tool_version=_bound_string(entry.tool.version, limit=255),
        status=call.status.value,
        decision=call.decision.value,
        risk_level=call.risk_level.value,
        flag_codes=tuple(_bound_string(code, limit=100) for code in entry.flag_codes),
        matched_rule_names=tuple(
            _bound_string(name, limit=255) for name in entry.matched_rule_names
        ),
        duration_ms=call.duration_ms,
        started_at=call.started_at,
        finished_at=call.finished_at,
        created_at=call.created_at,
        error_code=(_bound_string(call.error_code, limit=100) if call.error_code else None),
        error_message_safe=(
            _bound_string(call.error_message_safe, limit=500) if call.error_message_safe else None
        ),
    )


def audit_event_view(event: AuditEvent) -> AuditEventView:
    payload_json, _ = safe_json(event.payload_redacted, limit=4_096)
    return AuditEventView(
        id=event.id,
        event_type=event.event_type.value,
        actor_type=_bound_string(event.actor_type, limit=100),
        actor_id=(_bound_string(event.actor_id, limit=255) if event.actor_id else None),
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        created_at=event.created_at,
        payload_json=payload_json,
    )


def risk_flag_view(flag: RiskFlag) -> RiskFlagView:
    evidence_json, _ = safe_json(flag.safe_evidence, limit=2_048)
    return RiskFlagView(
        code=_bound_string(flag.code.value, limit=100),
        severity=flag.severity.value,
        message=_bound_string(flag.message, limit=500),
        source=flag.source.value,
        safe_evidence_json=evidence_json,
    )


def session_detail(timeline: SessionTimeline) -> SessionDetail:
    return SessionDetail(
        id=timeline.session.id,
        agent=agent_view(timeline.agent),
        status=timeline.session.status.value,
        started_at=timeline.session.started_at,
        finished_at=timeline.session.finished_at,
        external_session_id=(
            _bound_string(timeline.session.external_session_id, limit=255)
            if timeline.session.external_session_id
            else None
        ),
        tool_calls=tuple(tool_call_timeline_item(entry) for entry in timeline.tool_calls),
        audit_events=tuple(audit_event_view(event) for event in timeline.audit_events),
    )


def tool_call_detail(
    view: ToolCallView,
    *,
    jaeger_ui_base_url: str | None,
) -> ToolCallDetail:
    call: ToolCall = view.call
    tool: ToolDefinition = view.tool
    arguments_json, arguments_truncated = safe_json(call.redacted_arguments)
    if view.result is None:
        result_json: str | None = None
        result_truncated = False
    else:
        result_json, result_truncated = safe_json(view.result)
    trace_ids = {event.trace_id for event in view.audit_events if event.trace_id}
    correlation_ids = {event.correlation_id for event in view.audit_events if event.correlation_id}
    primary_trace = next(
        (tid for tid in sorted(trace_ids) if is_trace_id(tid)),
        None,
    )
    jaeger_link = _build_jaeger_link(jaeger_ui_base_url, primary_trace)
    return ToolCallDetail(
        id=call.id,
        session_id=call.session_id,
        parent_call_id=call.parent_call_id,
        tool_name=_bound_string(tool.name, limit=255),
        tool_version=_bound_string(tool.version, limit=255),
        sequence_number=call.sequence_number,
        status=call.status.value,
        decision=call.decision.value,
        risk_level=call.risk_level.value,
        started_at=call.started_at,
        finished_at=call.finished_at,
        duration_ms=call.duration_ms,
        created_at=call.created_at,
        error_code=(_bound_string(call.error_code, limit=100) if call.error_code else None),
        error_message_safe=(
            _bound_string(call.error_message_safe, limit=500) if call.error_message_safe else None
        ),
        arguments_json=arguments_json,
        arguments_truncated=arguments_truncated,
        result_json=result_json,
        result_truncated=result_truncated,
        flags=tuple(risk_flag_view(flag) for flag in view.flags),
        matched_rule_names=tuple(
            _bound_string(name, limit=255) for name in view.matched_rule_names
        ),
        audit_events=tuple(audit_event_view(event) for event in view.audit_events),
        correlation_ids=tuple(sorted(correlation_ids)),
        trace_ids=tuple(sorted(trace_ids)),
        jaeger_link=jaeger_link,
    )


def rule_view(rule: BlockingRule) -> RuleView:
    summary_parts: list[str] = []
    for key, value in rule.conditions.items():
        if isinstance(value, str):
            summary_parts.append(f"{key}={_bound_string(value, limit=80)}")
        elif isinstance(value, dict):
            path = value.get("path")
            target = value.get("value")
            if isinstance(path, str) and isinstance(target, str):
                summary_parts.append(
                    f"{key}({_bound_string(path, limit=40)} ~ {_bound_string(target, limit=40)})"
                )
            else:
                summary_parts.append(f"{key}=…")
        else:
            summary_parts.append(f"{key}=…")
    return RuleView(
        id=rule.id,
        name=_bound_string(rule.name, limit=255),
        description=_bound_string(rule.description, limit=1_000),
        enabled=rule.enabled,
        priority=rule.priority,
        tool_pattern=_bound_string(rule.tool_pattern, limit=255),
        action=rule.action.value,
        condition_summary=_bound_string(" · ".join(summary_parts), limit=500),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def agent_run_list_item(run: object) -> AgentRunListItem:
    from toolwatch.domain.agents import AgentRun

    if not isinstance(run, AgentRun):
        raise TypeError("run must be AgentRun")
    return AgentRunListItem(
        id=run.id,
        session_id=run.session_id,
        provider=_bound_string(run.provider, limit=50),
        model_name=_bound_string(run.model_name, limit=255),
        status=run.status.value,
        turn_count=run.turn_count,
        tool_call_count=run.tool_call_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_code=_bound_string(run.error_code, limit=100) if run.error_code else None,
    )


def agent_run_detail(
    view: AgentRunDashboardView,
    *,
    jaeger_ui_base_url: str | None,
) -> AgentRunDetail:
    run = view.run
    return AgentRunDetail(
        id=run.id,
        session_id=run.session_id,
        provider=_bound_string(run.provider, limit=50),
        model_name=_bound_string(run.model_name, limit=255),
        status=run.status.value,
        turn_count=run.turn_count,
        tool_call_count=run.tool_call_count,
        final_answer=(
            _bound_string(run.final_answer_redacted, limit=12_288)
            if run.final_answer_redacted
            else None
        ),
        error_code=_bound_string(run.error_code, limit=100) if run.error_code else None,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        model_calls=tuple(
            ModelCallView(
                turn_number=call.turn_number,
                status=call.status.value,
                requested_tool_count=call.requested_tool_count,
                prompt_token_count=call.prompt_token_count,
                completion_token_count=call.completion_token_count,
                total_duration_ms=call.total_duration_ms,
                load_duration_ms=call.load_duration_ms,
                error_code=call.error_code,
                started_at=call.started_at,
                finished_at=call.finished_at,
            )
            for call in view.model_calls
        ),
        tool_calls=tuple(tool_call_timeline_item(entry) for entry in view.tool_calls),
        audit_events=tuple(audit_event_view(event) for event in view.audit_events),
        jaeger_link=_build_jaeger_link(jaeger_ui_base_url, run.trace_id),
    )


def dashboard_summary(
    counts: DashboardCounts,
    *,
    recent_sessions: Iterable[SessionSummary],
    recent_high_risk: Iterable[ToolCallTimelineEntry],
) -> DashboardSummary:
    return DashboardSummary(
        total_sessions=counts.total_sessions,
        active_sessions=counts.active_sessions,
        total_tool_calls=counts.total_tool_calls,
        blocked_tool_calls=counts.blocked_tool_calls,
        flagged_tool_calls=counts.flagged_tool_calls,
        failed_tool_calls=counts.failed_tool_calls,
        timed_out_tool_calls=counts.timed_out_tool_calls,
        replayed_tool_calls=counts.replayed_tool_calls,
        risk_flags=counts.risk_flags,
        redaction_events=counts.redaction_events,
        recent_sessions=tuple(session_list_item(item) for item in recent_sessions),
        recent_high_risk_calls=tuple(tool_call_timeline_item(entry) for entry in recent_high_risk),
    )


def pagination_view(*, limit: int, offset: int, total: int) -> PaginationView:
    previous_offset = max(0, offset - limit)
    next_offset = offset + limit
    has_previous = offset > 0
    has_next = next_offset < total
    return PaginationView(
        limit=limit,
        offset=offset,
        total=total,
        has_previous=has_previous,
        has_next=has_next,
        previous_offset=previous_offset,
        next_offset=next_offset if has_next else offset,
    )


def attack_scenario_view(scenario: object) -> AttackScenarioView:
    from toolwatch.attack_lab.models import AttackScenario

    if not isinstance(scenario, AttackScenario):
        raise TypeError("scenario must be AttackScenario")
    return AttackScenarioView(
        id=scenario.id,
        name=_bound_string(scenario.name, limit=255),
        description=_bound_string(scenario.description, limit=1_000),
        category=scenario.category,
        severity=scenario.severity,
        tool_name=_bound_string(scenario.tool_name, limit=255),
        tool_version=_bound_string(scenario.tool_version, limit=255),
        expected_decision=scenario.expected.decision,
        expected_status=scenario.expected.status,
        expected_risk=scenario.expected.risk,
        expected_flags=tuple(scenario.expected.flags),
        expected_adapter_called=scenario.expected.adapter_called,
    )


def attack_run_result_view(result: object) -> AttackRunResultView:
    from toolwatch.attack_lab.models import AttackRunResult
    from toolwatch.web.view_models import AttackAssertionView

    if not isinstance(result, AttackRunResult):
        raise TypeError("result must be AttackRunResult")
    return AttackRunResultView(
        scenario=attack_scenario_view(result.scenario),
        passed=result.passed,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_ms=result.duration_ms,
        tool_call_id=result.tool_call_id,
        session_id=result.session_id,
        observed_status=result.observed_status,
        observed_decision=result.observed_decision,
        observed_risk=result.observed_risk,
        observed_flags=tuple(_bound_string(code, limit=100) for code in result.observed_flags),
        matched_rules=tuple(_bound_string(name, limit=255) for name in result.matched_rules),
        adapter_called=result.adapter_called,
        replayed=result.replayed,
        trace_id=result.trace_id if result.trace_id and is_trace_id(result.trace_id) else None,
        correlation_id=result.correlation_id,
        assertions=tuple(
            AttackAssertionView(
                name=_bound_string(assertion.name, limit=120),
                passed=assertion.passed,
                expected=_bound_string(assertion.expected, limit=500),
                observed_safe=_bound_string(assertion.observed_safe, limit=500),
            )
            for assertion in result.assertions
        ),
    )


def _build_jaeger_link(base_url: str | None, trace_id: str | None) -> str | None:
    if not base_url or not trace_id:
        return None
    if not is_trace_id(trace_id):
        return None
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return None
    return f"{base_url.rstrip('/')}/trace/{trace_id}"
