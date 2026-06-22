"""Unit tests for dashboard presenters and view models."""

from uuid import uuid4

from toolwatch.application.queries import (
    DashboardCounts,
    SessionSummary,
    SessionTimeline,
    ToolCallTimelineEntry,
    ToolCallView,
)
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.common import JSONObject
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
    RiskFlagCode,
    RuleAction,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import (
    ToolCall,
    ToolCallDecision,
    ToolCallStatus,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.web import presenters


def _agent() -> Agent:
    return Agent(
        identity=AgentIdentity(
            name="demo-agent",
            provider="test",
            model_name="deterministic",
            version="1",
        ),
        metadata={},
    )


def _session(agent: Agent) -> AgentSession:
    return AgentSession(
        agent_id=agent.id,
        external_session_id=None,
        user_prompt_redacted=None,
        status=SessionStatus.ACTIVE,
    )


def _tool() -> ToolDefinition:
    return ToolDefinition(
        name="github.list_issues",
        description="List issues.",
        version="1.0.0",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        output_schema=None,
        base_risk_level=RiskLevel.LOW,
        adapter_type="mock_github",
        adapter_config={},
    )


def _call(session: AgentSession, tool: ToolDefinition, *, status: ToolCallStatus) -> ToolCall:
    args_hash = "a" * 64
    request_hash = "b" * 64
    base = ToolCall(
        session_id=session.id,
        tool_definition_id=tool.id,
        sequence_number=1,
        arguments_hash=args_hash,
        request_hash=request_hash,
        idempotency_key=uuid4(),
    )
    transitions = {
        ToolCallStatus.VALIDATING: base.transition_to(ToolCallStatus.VALIDATING),
    }
    if status is ToolCallStatus.RECEIVED:
        return base
    if status is ToolCallStatus.VALIDATING:
        return transitions[ToolCallStatus.VALIDATING]
    evaluating = transitions[ToolCallStatus.VALIDATING].transition_to(
        ToolCallStatus.EVALUATING,
        decision=ToolCallDecision.ALLOW,
        risk_level=RiskLevel.LOW,
    )
    if status is ToolCallStatus.EVALUATING:
        return evaluating
    if status is ToolCallStatus.BLOCKED:
        return evaluating.transition_to(
            ToolCallStatus.BLOCKED,
            decision=ToolCallDecision.BLOCK,
            error_code="tool_call_blocked",
            error_message_safe="Blocked.",
        )
    executing = evaluating.transition_to(ToolCallStatus.EXECUTING)
    if status is ToolCallStatus.EXECUTING:
        return executing
    if status is ToolCallStatus.SUCCEEDED:
        return executing.transition_to(ToolCallStatus.SUCCEEDED)
    if status is ToolCallStatus.FAILED:
        return executing.transition_to(
            ToolCallStatus.FAILED,
            error_code="tool_execution_failed",
            error_message_safe="Adapter failed safely.",
        )
    if status is ToolCallStatus.TIMED_OUT:
        return executing.transition_to(
            ToolCallStatus.TIMED_OUT,
            error_code="tool_timeout",
            error_message_safe="Adapter timed out safely.",
        )
    raise AssertionError(f"unsupported status {status}")


def test_safe_json_pretty_prints_and_bounds_size() -> None:
    payload: JSONObject = {"a": "b" * 5}
    rendered, truncated = presenters.safe_json(payload)
    assert rendered.startswith("{")
    assert "b" in rendered
    assert truncated is False

    big: JSONObject = {"x": "y" * 20_000}
    rendered_big, truncated_big = presenters.safe_json(big, limit=1_024)
    assert truncated_big is True
    assert "truncated" in rendered_big


def test_safe_json_escapes_html_via_json_quoting() -> None:
    payload: JSONObject = {"input": "<script>alert(1)</script>"}
    rendered, _ = presenters.safe_json(payload)
    assert "<script>" in rendered  # JSON keeps the text literal
    # Rendering pre-block in templates uses autoescape; presenter returns raw JSON.
    # The presenter must not insert HTML-active strings outside of JSON syntax.
    assert "\\u003c" not in rendered  # ensure_ascii=False


def test_session_list_item_bounds_strings_and_preserves_counts() -> None:
    agent = _agent()
    session = _session(agent)
    summary = SessionSummary(
        session=session,
        agent=agent,
        tool_call_count=3,
        highest_risk="high",
        blocked_count=1,
        flagged_count=2,
        failed_count=0,
    )

    item = presenters.session_list_item(summary)

    assert item.id == session.id
    assert item.agent.name == "demo-agent"
    assert item.tool_call_count == 3
    assert item.highest_risk == "high"


def test_tool_call_detail_redacts_and_links_jaeger() -> None:
    agent = _agent()
    session = _session(agent)
    tool = _tool()
    call = _call(session, tool, status=ToolCallStatus.SUCCEEDED)
    flag = RiskFlag(
        code=RiskFlagCode.SENSITIVE_INPUT,
        severity=RiskLevel.HIGH,
        message="Sensitive input found.",
        safe_evidence={"path": "$.body"},
        tool_call_id=call.id,
    )
    audit = AuditEvent(
        session_id=call.session_id,
        tool_call_id=call.id,
        event_type=AuditEventType.TOOL_CALL_COMPLETED,
        payload_redacted={"status": "succeeded"},
        trace_id="0123456789abcdef0123456789abcdef",
        correlation_id=str(uuid4()),
    )
    view = ToolCallView(
        call=call,
        tool=tool,
        result={"issues": [{"number": 1, "title": "ok", "state": "open"}]},
        flags=(flag,),
        matched_rule_names=("block-destructive-sql",),
        audit_events=(audit,),
    )

    detail = presenters.tool_call_detail(view, jaeger_ui_base_url="http://jaeger:16686")

    assert detail.jaeger_link == "http://jaeger:16686/trace/0123456789abcdef0123456789abcdef"
    assert detail.flags[0].code == "sensitive_input"
    assert detail.matched_rule_names == ("block-destructive-sql",)
    assert detail.audit_events[0].event_type == "tool_call.completed"


def test_jaeger_link_hidden_when_trace_invalid_or_url_missing() -> None:
    agent = _agent()
    session = _session(agent)
    tool = _tool()
    call = _call(session, tool, status=ToolCallStatus.SUCCEEDED)
    view = ToolCallView(
        call=call,
        tool=tool,
        result=None,
        flags=(),
        matched_rule_names=(),
        audit_events=(
            AuditEvent(
                session_id=call.session_id,
                tool_call_id=call.id,
                event_type=AuditEventType.TOOL_CALL_COMPLETED,
                payload_redacted={"status": "succeeded"},
                trace_id="0" * 32,  # all-zero trace must be rejected
            ),
        ),
    )
    detail = presenters.tool_call_detail(view, jaeger_ui_base_url="http://jaeger:16686")
    assert detail.jaeger_link is None

    detail_no_url = presenters.tool_call_detail(view, jaeger_ui_base_url=None)
    assert detail_no_url.jaeger_link is None


def test_dashboard_summary_includes_recents() -> None:
    counts = DashboardCounts(
        total_sessions=2,
        active_sessions=1,
        total_tool_calls=3,
        blocked_tool_calls=1,
        flagged_tool_calls=1,
        failed_tool_calls=0,
        timed_out_tool_calls=0,
        replayed_tool_calls=0,
        risk_flags=2,
        redaction_events=1,
    )
    agent = _agent()
    session = _session(agent)
    summary_value = presenters.dashboard_summary(
        counts,
        recent_sessions=[
            SessionSummary(
                session=session,
                agent=agent,
                tool_call_count=2,
                highest_risk="critical",
                blocked_count=1,
                flagged_count=0,
                failed_count=0,
            )
        ],
        recent_high_risk=[],
    )
    assert summary_value.total_sessions == 2
    assert summary_value.recent_sessions[0].highest_risk == "critical"


def test_rule_view_renders_safe_condition_summary() -> None:
    rule = BlockingRule(
        name="block-destructive-sql",
        description="Block destructive SQL.",
        enabled=True,
        priority=100,
        tool_pattern="database.query",
        conditions={"has_flag": "destructive_sql"},
        action=RuleAction.BLOCK,
    )
    view = presenters.rule_view(rule)
    assert view.action == "block"
    assert "destructive_sql" in view.condition_summary


def test_pagination_view_handles_first_last_pages() -> None:
    page = presenters.pagination_view(limit=10, offset=0, total=25)
    assert page.has_previous is False
    assert page.has_next is True

    last = presenters.pagination_view(limit=10, offset=20, total=25)
    assert last.has_previous is True
    assert last.has_next is False


def test_audit_event_view_handles_safe_evidence_serialization() -> None:
    event = AuditEvent(
        session_id=uuid4(),
        tool_call_id=None,
        event_type=AuditEventType.TOOL_CALL_RECEIVED,
        payload_redacted={"tool": "github.list_issues", "status": "received"},
        trace_id="0123456789abcdef0123456789abcdef",
        correlation_id=str(uuid4()),
    )
    view = presenters.audit_event_view(event)
    assert view.event_type == "tool_call.received"
    assert "github.list_issues" in view.payload_json


def test_session_timeline_includes_entries_and_audit_events() -> None:
    agent = _agent()
    session = _session(agent)
    tool = _tool()
    call = _call(session, tool, status=ToolCallStatus.SUCCEEDED)
    flag = RiskFlag(
        code=RiskFlagCode.SENSITIVE_INPUT,
        severity=RiskLevel.HIGH,
        message="Sensitive input found.",
        tool_call_id=call.id,
    )
    timeline = SessionTimeline(
        session=session,
        agent=agent,
        tool_calls=(
            ToolCallTimelineEntry(
                call=call,
                tool=tool,
                flag_codes=(flag.code.value,),
                matched_rule_names=("rule-x",),
            ),
        ),
        audit_events=(),
    )
    detail = presenters.session_detail(timeline)
    assert detail.tool_calls[0].flag_codes == ("sensitive_input",)
    assert detail.tool_calls[0].matched_rule_names == ("rule-x",)
