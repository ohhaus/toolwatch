"""Read-only dashboard query services."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from toolwatch.application.errors import SessionNotFound, ToolCallNotFound
from toolwatch.application.ports import Page, UnitOfWork, UnitOfWorkFactory
from toolwatch.domain.agents import Agent, AgentRun, AgentRunStatus, ModelCall
from toolwatch.domain.common import JSONValue
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import ToolCall, ToolCallStatus
from toolwatch.domain.tools import ToolDefinition


@dataclass(frozen=True, slots=True)
class DashboardCounts:
    """Aggregate counters for the dashboard summary."""

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


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """One session list-page row including aggregated tool-call statistics."""

    session: AgentSession
    agent: Agent
    tool_call_count: int
    highest_risk: str
    blocked_count: int
    flagged_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class ToolCallTimelineEntry:
    """One ordered tool-call row inside a session timeline."""

    call: ToolCall
    tool: ToolDefinition
    flag_codes: tuple[str, ...]
    matched_rule_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionTimeline:
    """A full session timeline including its agent identity and audit events."""

    session: AgentSession
    agent: Agent
    tool_calls: tuple[ToolCallTimelineEntry, ...]
    audit_events: tuple[AuditEvent, ...]


@dataclass(frozen=True, slots=True)
class ToolCallView:
    """One sanitized tool-call detail bundle including audit history."""

    call: ToolCall
    tool: ToolDefinition
    result: JSONValue | None
    flags: tuple[RiskFlag, ...]
    matched_rule_names: tuple[str, ...]
    audit_events: tuple[AuditEvent, ...]


@dataclass(frozen=True, slots=True)
class AgentRunDashboardView:
    """Safe agent-run detail for server-rendered pages."""

    run: AgentRun
    model_calls: tuple[ModelCall, ...]
    tool_calls: tuple[ToolCallTimelineEntry, ...]
    audit_events: tuple[AuditEvent, ...]


class DashboardQueryService:
    """Compose existing application reads for the read-only dashboard."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def summary(self) -> DashboardCounts:
        """Return aggregate counters using bounded queries."""

        async with self._uow_factory() as uow:
            sessions = await uow.sessions.list(
                agent_id=None,
                status=None,
                limit=200,
                offset=0,
            )
            active = await uow.sessions.list(
                agent_id=None,
                status=SessionStatus.ACTIVE,
                limit=1,
                offset=0,
            )
            total_calls = 0
            blocked = 0
            flagged = 0
            failed = 0
            timed_out = 0
            risk_flag_total = 0
            for session in sessions.items:
                calls = await uow.tool_calls.list(
                    session_id=session.id,
                    status=None,
                    limit=500,
                    offset=0,
                )
                total_calls += calls.total
                for call in calls.items:
                    if call.status is ToolCallStatus.BLOCKED:
                        blocked += 1
                    if call.decision.value == "flag":
                        flagged += 1
                    if call.status is ToolCallStatus.FAILED:
                        failed += 1
                    if call.status is ToolCallStatus.TIMED_OUT:
                        timed_out += 1
                    flags = await uow.risk_flags.list_for_tool_call(call.id)
                    risk_flag_total += len(flags)
            redaction_events = await uow.audit_events.list(
                session_id=None,
                tool_call_id=None,
                event_type=AuditEventType.REDACTION_APPLIED,
                trace_id=None,
                correlation_id=None,
                limit=1,
                offset=0,
            )
        return DashboardCounts(
            total_sessions=sessions.total,
            active_sessions=active.total,
            total_tool_calls=total_calls,
            blocked_tool_calls=blocked,
            flagged_tool_calls=flagged,
            failed_tool_calls=failed,
            timed_out_tool_calls=timed_out,
            replayed_tool_calls=0,
            risk_flags=risk_flag_total,
            redaction_events=redaction_events.total,
        )

    async def list_sessions(
        self,
        *,
        agent_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> Page[SessionSummary]:
        """List newest sessions first with aggregated tool-call statistics."""

        async with self._uow_factory() as uow:
            session_status = SessionStatus(status) if status else None
            page = await uow.sessions.list(
                agent_id=agent_id,
                status=session_status,
                limit=limit,
                offset=offset,
            )
            summaries: list[SessionSummary] = []
            for session in page.items:
                agent = await uow.agents.get_by_id(session.agent_id)
                if agent is None:
                    raise SessionNotFound
                calls = await uow.tool_calls.list(
                    session_id=session.id,
                    status=None,
                    limit=200,
                    offset=0,
                )
                summaries.append(_session_summary(session, agent, calls.items))
        return Page(summaries, page.total, page.limit, page.offset)

    async def session_timeline(self, session_id: UUID) -> SessionTimeline:
        """Return one session with its ordered tool-calls and audit events."""

        async with self._uow_factory() as uow:
            session = await uow.sessions.get_by_id(session_id)
            if session is None:
                raise SessionNotFound
            agent = await uow.agents.get_by_id(session.agent_id)
            if agent is None:
                raise SessionNotFound
            calls_page = await uow.tool_calls.list(
                session_id=session_id,
                status=None,
                limit=200,
                offset=0,
            )
            entries: list[ToolCallTimelineEntry] = []
            for call in calls_page.items:
                tool = await uow.tools.get_by_id(call.tool_definition_id)
                if tool is None:
                    raise ToolCallNotFound
                flags = await uow.risk_flags.list_for_tool_call(call.id)
                rule_names = await _rule_names(uow, call.matched_rule_ids)
                entries.append(
                    ToolCallTimelineEntry(
                        call=call,
                        tool=tool,
                        flag_codes=tuple(flag.code.value for flag in flags),
                        matched_rule_names=rule_names,
                    )
                )
            audit_page = await uow.audit_events.list(
                session_id=session_id,
                tool_call_id=None,
                event_type=None,
                trace_id=None,
                correlation_id=None,
                limit=200,
                offset=0,
            )
        return SessionTimeline(
            session=session,
            agent=agent,
            tool_calls=tuple(entries),
            audit_events=tuple(audit_page.items),
        )

    async def tool_call_view(self, call_id: UUID) -> ToolCallView:
        """Return one sanitized call with its result, flags, rules, and audit events."""

        async with self._uow_factory() as uow:
            call = await uow.tool_calls.get_by_id(call_id)
            if call is None:
                raise ToolCallNotFound
            tool = await uow.tools.get_by_id(call.tool_definition_id)
            if tool is None:
                raise ToolCallNotFound
            metadata = await uow.tool_results.get_by_tool_call_id(call.id)
            flags = await uow.risk_flags.list_for_tool_call(call.id)
            rule_names = await _rule_names(uow, call.matched_rule_ids)
            audit_page = await uow.audit_events.list(
                session_id=None,
                tool_call_id=call.id,
                event_type=None,
                trace_id=None,
                correlation_id=None,
                limit=200,
                offset=0,
            )
        return ToolCallView(
            call=call,
            tool=tool,
            result=metadata.redacted_payload if metadata is not None else None,
            flags=tuple(flags),
            matched_rule_names=rule_names,
            audit_events=tuple(audit_page.items),
        )

    async def list_rules(
        self,
        *,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[BlockingRule]:
        """List validated blocking rules."""

        async with self._uow_factory() as uow:
            return await uow.rules.list(enabled=enabled, limit=limit, offset=offset)

    async def list_agent_runs(
        self,
        *,
        status: AgentRunStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentRun]:
        """List newest safe agent runs."""

        async with self._uow_factory() as uow:
            return await uow.agent_runs.list(
                session_id=None,
                provider=None,
                model_name=None,
                status=status,
                started_from=None,
                started_to=None,
                limit=limit,
                offset=offset,
            )

    async def agent_run_view(self, run_id: UUID) -> AgentRunDashboardView:
        """Return one run with safe model/tool/audit metadata."""

        async with self._uow_factory() as uow:
            run = await uow.agent_runs.get_by_id(run_id)
            if run is None:
                from toolwatch.application.errors import AgentRunNotFound

                raise AgentRunNotFound
            model_calls = tuple(await uow.model_calls.list_for_run(run_id))
            calls = await uow.tool_calls.list_for_agent_run(run_id)
            entries: list[ToolCallTimelineEntry] = []
            for call in calls:
                tool = await uow.tools.get_by_id(call.tool_definition_id)
                if tool is None:
                    raise ToolCallNotFound
                flags = await uow.risk_flags.list_for_tool_call(call.id)
                entries.append(
                    ToolCallTimelineEntry(
                        call=call,
                        tool=tool,
                        flag_codes=tuple(flag.code.value for flag in flags),
                        matched_rule_names=await _rule_names(uow, call.matched_rule_ids),
                    )
                )
            audit_page = await uow.audit_events.list(
                session_id=run.session_id,
                tool_call_id=None,
                event_type=None,
                trace_id=None,
                correlation_id=None,
                limit=500,
                offset=0,
            )
            run_events = tuple(
                event
                for event in audit_page.items
                if event.payload_redacted.get("agent_run_id") == str(run.id)
            )
        return AgentRunDashboardView(
            run=run,
            model_calls=model_calls,
            tool_calls=tuple(entries),
            audit_events=run_events,
        )

    async def recent_sessions(self, limit: int = 5) -> tuple[SessionSummary, ...]:
        """Return newest sessions with aggregated statistics."""

        page = await self.list_sessions(agent_id=None, status=None, limit=limit, offset=0)
        return tuple(page.items)

    async def recent_high_risk_calls(self, limit: int = 5) -> tuple[ToolCallTimelineEntry, ...]:
        """Return newest critical/high-risk or terminal-non-success calls."""

        async with self._uow_factory() as uow:
            sessions_page = await uow.sessions.list(
                agent_id=None,
                status=None,
                limit=20,
                offset=0,
            )
            entries: list[ToolCallTimelineEntry] = []
            for session in sessions_page.items:
                calls = await uow.tool_calls.list(
                    session_id=session.id,
                    status=None,
                    limit=50,
                    offset=0,
                )
                for call in calls.items:
                    flagged = call.risk_level.value in {
                        "high",
                        "critical",
                    } or call.status.value in {"blocked", "failed", "timed_out"}
                    if not flagged:
                        continue
                    tool = await uow.tools.get_by_id(call.tool_definition_id)
                    if tool is None:
                        continue
                    flags = await uow.risk_flags.list_for_tool_call(call.id)
                    rule_names = await _rule_names(uow, call.matched_rule_ids)
                    entries.append(
                        ToolCallTimelineEntry(
                            call=call,
                            tool=tool,
                            flag_codes=tuple(flag.code.value for flag in flags),
                            matched_rule_names=rule_names,
                        )
                    )
            entries.sort(key=lambda entry: entry.call.created_at, reverse=True)
            return tuple(entries[:limit])


def _session_summary(
    session: AgentSession,
    agent: Agent,
    calls: Sequence[ToolCall],
) -> SessionSummary:
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    highest = "low"
    blocked = 0
    flagged = 0
    failed = 0
    for call in calls:
        if risk_order[call.risk_level.value] > risk_order[highest]:
            highest = call.risk_level.value
        if call.status.value == "blocked":
            blocked += 1
        if call.decision.value == "flag":
            flagged += 1
        if call.status.value in {"failed", "timed_out"}:
            failed += 1
    return SessionSummary(
        session=session,
        agent=agent,
        tool_call_count=len(calls),
        highest_risk=highest,
        blocked_count=blocked,
        flagged_count=flagged,
        failed_count=failed,
    )


async def _rule_names(uow: UnitOfWork, rule_ids: tuple[UUID, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for rule_id in rule_ids:
        rule = await uow.rules.get_by_id(rule_id)
        if rule is not None:
            names.append(rule.name)
    return tuple(names)
