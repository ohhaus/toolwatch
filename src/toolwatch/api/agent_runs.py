"""Synchronous safe agent-run API."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import (
    get_adapter_registry,
    get_agent_providers,
    get_shutdown_manager,
    get_telemetry,
    get_uow_factory,
)
from toolwatch.api.errors import error_responses
from toolwatch.application.agent_runs import (
    AgentRunDetail,
    AgentRunFilters,
    AgentRunService,
    StartAgentRun,
)
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.config import Settings, get_settings
from toolwatch.domain.agents import (
    AgentProvider,
    AgentRun,
    AgentRunStatus,
    AgentToolCallSummary,
    ModelCall,
    ModelCallStatus,
)
from toolwatch.infrastructure.adapters import AdapterRegistry
from toolwatch.shutdown import ShutdownManager
from toolwatch.telemetry import TelemetryRuntime

router = APIRouter(prefix="/api/v1/agent-runs", tags=["agent-runs"])


class AgentRunCreateRequest(BaseModel):
    """Start one bounded synchronous local-provider run."""

    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    prompt: str = Field(min_length=1, max_length=65_536)
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=255)


class AgentToolCallResponse(BaseModel):
    call_id: UUID | None
    tool: str
    status: str
    decision: str | None
    risk: str | None
    error_code: str | None


class ModelCallResponse(BaseModel):
    id: UUID
    turn_number: int
    provider: str
    model: str
    status: ModelCallStatus
    requested_tool_count: int
    prompt_token_count: int | None
    completion_token_count: int | None
    total_duration_ms: int | None
    load_duration_ms: int | None
    error_code: str | None
    trace_id: str | None
    correlation_id: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentRunResponse(BaseModel):
    run_id: UUID
    session_id: UUID
    provider: str
    model: str
    status: AgentRunStatus
    turn_count: int
    tool_call_count: int
    final_answer: str | None
    error_code: str | None
    tool_calls: list[AgentToolCallResponse]
    model_calls: list[ModelCallResponse]
    trace_id: str | None
    correlation_id: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentRunListItem(BaseModel):
    run_id: UUID
    session_id: UUID
    provider: str
    model: str
    status: AgentRunStatus
    turn_count: int
    tool_call_count: int
    final_answer: str | None
    error_code: str | None
    trace_id: str | None
    correlation_id: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunListItem]
    total: int
    limit: int
    offset: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
AdapterDependency = Annotated[AdapterRegistry, Depends(get_adapter_registry)]
ProviderDependency = Annotated[Mapping[str, AgentProvider], Depends(get_agent_providers)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
TelemetryDependency = Annotated[TelemetryRuntime, Depends(get_telemetry)]
ShutdownDependency = Annotated[ShutdownManager, Depends(get_shutdown_manager)]


@router.post(
    "",
    response_model=AgentRunResponse,
    responses=error_responses(
        not_found=True,
        conflict=True,
        bad_gateway=True,
        gateway_timeout=True,
    ),
)
async def start_agent_run(
    request: AgentRunCreateRequest,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    providers: ProviderDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
    shutdown: ShutdownDependency,
) -> AgentRunResponse:
    service = AgentRunService(
        uow_factory=uow_factory,
        adapters=adapters,
        providers=providers,
        settings=settings,
        telemetry=telemetry,
        accepting_work=lambda: shutdown.accepting,
    )
    result = await service.start(
        StartAgentRun(
            session_id=request.session_id,
            prompt=request.prompt,
            provider=request.provider,
            model=request.model,
        )
    )
    detail = await service.get(result.run.id)
    return _detail_response(detail)


@router.get(
    "/{run_id}",
    response_model=AgentRunResponse,
    responses=error_responses(not_found=True),
)
async def get_agent_run(
    run_id: UUID,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    providers: ProviderDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
    shutdown: ShutdownDependency,
) -> AgentRunResponse:
    service = AgentRunService(
        uow_factory=uow_factory,
        adapters=adapters,
        providers=providers,
        settings=settings,
        telemetry=telemetry,
        accepting_work=lambda: shutdown.accepting,
    )
    return _detail_response(await service.get(run_id))


@router.get("", response_model=AgentRunListResponse)
async def list_agent_runs(
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    providers: ProviderDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
    shutdown: ShutdownDependency,
    session_id: Annotated[UUID | None, Query()] = None,
    provider: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    model: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    run_status: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
    started_from: Annotated[datetime | None, Query()] = None,
    started_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentRunListResponse:
    service = AgentRunService(
        uow_factory=uow_factory,
        adapters=adapters,
        providers=providers,
        settings=settings,
        telemetry=telemetry,
        accepting_work=lambda: shutdown.accepting,
    )
    page = await service.list(
        AgentRunFilters(
            session_id=session_id,
            provider=provider,
            model=model,
            status=run_status,
            started_from=started_from,
            started_to=started_to,
            limit=limit,
            offset=offset,
        )
    )
    return AgentRunListResponse(
        items=[_run_item(run) for run in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _detail_response(detail: AgentRunDetail) -> AgentRunResponse:
    run = detail.run
    return AgentRunResponse(
        **_run_item(run).model_dump(),
        tool_calls=[_tool_call_response(call) for call in detail.tool_calls],
        model_calls=[_model_call_response(call) for call in detail.model_calls],
    )


def _run_item(run: AgentRun) -> AgentRunListItem:
    return AgentRunListItem(
        run_id=run.id,
        session_id=run.session_id,
        provider=run.provider,
        model=run.model_name,
        status=run.status,
        turn_count=run.turn_count,
        tool_call_count=run.tool_call_count,
        final_answer=run.final_answer_redacted,
        error_code=run.error_code,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _tool_call_response(call: AgentToolCallSummary) -> AgentToolCallResponse:
    return AgentToolCallResponse(
        call_id=call.call_id,
        tool=call.tool,
        status=call.status,
        decision=call.decision,
        risk=call.risk,
        error_code=call.error_code,
    )


def _model_call_response(call: ModelCall) -> ModelCallResponse:
    return ModelCallResponse(
        id=call.id,
        turn_number=call.turn_number,
        provider=call.provider,
        model=call.model_name,
        status=call.status,
        requested_tool_count=call.requested_tool_count,
        prompt_token_count=call.prompt_token_count,
        completion_token_count=call.completion_token_count,
        total_duration_ms=call.total_duration_ms,
        load_duration_ms=call.load_duration_ms,
        error_code=call.error_code,
        trace_id=call.trace_id,
        correlation_id=call.correlation_id,
        started_at=call.started_at,
        finished_at=call.finished_at,
    )
