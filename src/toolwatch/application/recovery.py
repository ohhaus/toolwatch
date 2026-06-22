"""Conservative recovery of stale non-terminal execution records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from toolwatch.application.ports import (
    AgentRunRepository,
    AuditEventRepository,
    ModelCallRepository,
    ToolCallRepository,
)
from toolwatch.config import Settings
from toolwatch.domain.agents import AgentRun, AgentRunStatus, ModelCall, ModelCallStatus
from toolwatch.domain.common import JSONObject, utc_now
from toolwatch.domain.security import AuditEvent, AuditEventType
from toolwatch.domain.tool_calls import ToolCall, ToolCallStatus
from toolwatch.telemetry import TelemetryRuntime
from toolwatch.telemetry.context import current_correlation


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Counts of records moved to conservative terminal states."""

    tool_calls: int = 0
    agent_runs: int = 0
    model_calls: int = 0

    @property
    def total(self) -> int:
        return self.tool_calls + self.agent_runs + self.model_calls


class RecoveryToolCallRepository(ToolCallRepository, Protocol):
    async def claim_stale_executing(
        self, *, updated_before: datetime, limit: int
    ) -> list[ToolCall]: ...


class RecoveryAgentRunRepository(AgentRunRepository, Protocol):
    async def claim_stale_running(
        self, *, updated_before: datetime, limit: int
    ) -> list[AgentRun]: ...


class RecoveryModelCallRepository(ModelCallRepository, Protocol):
    async def claim_stale_started(
        self, *, started_before: datetime, limit: int
    ) -> list[ModelCall]: ...


class RecoveryUnitOfWork(Protocol):
    @property
    def tool_calls(self) -> RecoveryToolCallRepository: ...

    @property
    def agent_runs(self) -> RecoveryAgentRunRepository: ...

    @property
    def model_calls(self) -> RecoveryModelCallRepository: ...

    @property
    def audit_events(self) -> AuditEventRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


RecoveryUnitOfWorkFactory = Callable[[], RecoveryUnitOfWork]


class RecoveryService:
    """Fail stale work closed without retrying any external operation."""

    def __init__(
        self,
        *,
        uow_factory: RecoveryUnitOfWorkFactory,
        settings: Settings,
        telemetry: TelemetryRuntime,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._telemetry = telemetry

    async def run(self) -> RecoveryResult:
        """Recover all records stale at the command's fixed cutoff time."""

        if not self._settings.recovery_enabled:
            return RecoveryResult()
        now = utc_now()
        tool_calls = await self._recover_tool_calls(
            now=now,
            cutoff=now - timedelta(seconds=self._settings.tool_call_stale_after_seconds),
        )
        model_calls = await self._recover_model_calls(
            now=now,
            cutoff=now - timedelta(seconds=self._settings.model_call_stale_after_seconds),
        )
        agent_runs = await self._recover_agent_runs(
            now=now,
            cutoff=now - timedelta(seconds=self._settings.agent_run_stale_after_seconds),
        )
        return RecoveryResult(
            tool_calls=tool_calls,
            agent_runs=agent_runs,
            model_calls=model_calls,
        )

    async def _recover_tool_calls(self, *, now: datetime, cutoff: datetime) -> int:
        recovered = 0
        while True:
            async with self._uow_factory() as uow:
                calls = await uow.tool_calls.claim_stale_executing(
                    updated_before=cutoff,
                    limit=self._settings.recovery_batch_size,
                )
                for call in calls:
                    terminal = call.transition_to(
                        ToolCallStatus.FAILED,
                        now=now,
                        error_code="execution_state_unknown",
                        error_message_safe=(
                            "Execution was interrupted and its external side effect is unknown."
                        ),
                    )
                    await uow.tool_calls.update(terminal)
                    await uow.audit_events.create(
                        self._audit(
                            session_id=call.session_id,
                            tool_call_id=call.id,
                            event_type=AuditEventType.TOOL_CALL_RECOVERED,
                            payload={
                                "status": "failed",
                                "error_code": "execution_state_unknown",
                            },
                        )
                    )
                await uow.commit()
            self._record("tool_call", len(calls))
            recovered += len(calls)
            if len(calls) < self._settings.recovery_batch_size:
                return recovered

    async def _recover_model_calls(self, *, now: datetime, cutoff: datetime) -> int:
        recovered = 0
        while True:
            async with self._uow_factory() as uow:
                calls = await uow.model_calls.claim_stale_started(
                    started_before=cutoff,
                    limit=self._settings.recovery_batch_size,
                )
                for call in calls:
                    terminal = replace(
                        call,
                        status=ModelCallStatus.FAILED,
                        error_code="model_call_interrupted",
                        finished_at=now,
                    )
                    await uow.model_calls.update(terminal)
                    run = await uow.agent_runs.get_by_id(call.agent_run_id)
                    if run is not None:
                        await uow.audit_events.create(
                            self._audit(
                                session_id=run.session_id,
                                event_type=AuditEventType.MODEL_CALL_RECOVERED,
                                payload={
                                    "agent_run_id": str(run.id),
                                    "turn_number": call.turn_number,
                                    "status": "failed",
                                    "error_code": "model_call_interrupted",
                                },
                            )
                        )
                await uow.commit()
            self._record("model_call", len(calls))
            recovered += len(calls)
            if len(calls) < self._settings.recovery_batch_size:
                return recovered

    async def _recover_agent_runs(self, *, now: datetime, cutoff: datetime) -> int:
        recovered = 0
        while True:
            async with self._uow_factory() as uow:
                runs = await uow.agent_runs.claim_stale_running(
                    updated_before=cutoff,
                    limit=self._settings.recovery_batch_size,
                )
                for run in runs:
                    terminal = run.finish(
                        AgentRunStatus.FAILED,
                        now=now,
                        error_code="agent_run_interrupted",
                    )
                    await uow.agent_runs.update(terminal)
                    await uow.audit_events.create(
                        self._audit(
                            session_id=run.session_id,
                            event_type=AuditEventType.AGENT_RUN_RECOVERED,
                            payload={
                                "agent_run_id": str(run.id),
                                "status": "failed",
                                "error_code": "agent_run_interrupted",
                            },
                        )
                    )
                await uow.commit()
            self._record("agent_run", len(runs))
            recovered += len(runs)
            if len(runs) < self._settings.recovery_batch_size:
                return recovered

    def _record(self, operation: str, amount: int) -> None:
        if amount:
            self._telemetry.metrics.counter(
                "toolwatch_recoveries_total",
                {"operation": operation, "status": "failed"},
                amount,
            )
            self._telemetry.metrics.counter("toolwatch_audit_events_total", amount=amount)

    @staticmethod
    def _audit(
        *,
        session_id: UUID,
        event_type: AuditEventType,
        payload: JSONObject,
        tool_call_id: UUID | None = None,
    ) -> AuditEvent:
        correlation = current_correlation()
        return AuditEvent(
            session_id=session_id,
            tool_call_id=tool_call_id,
            event_type=event_type,
            payload_redacted=payload,
            trace_id=correlation.trace_id,
            correlation_id=correlation.correlation_id,
        )
