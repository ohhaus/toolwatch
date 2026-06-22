"""Tool-call execution and sanitized read APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import (
    get_adapter_registry,
    get_telemetry,
    get_terminal_response_cache,
    get_uow_factory,
)
from toolwatch.api.errors import ErrorBody, ErrorResponse, error_responses
from toolwatch.application.errors import ToolCallBlocked
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.tool_calls import (
    ExecuteToolCall,
    TerminalResponseCache,
    ToolCallDetail,
    ToolCallExecution,
    ToolCallFilters,
    ToolCallService,
)
from toolwatch.config import Settings, get_settings
from toolwatch.domain.common import JSONObject, JSONValue
from toolwatch.domain.tool_calls import ToolCallDecision, ToolCallStatus
from toolwatch.domain.tools import RiskLevel
from toolwatch.infrastructure.adapters import AdapterRegistry
from toolwatch.telemetry import TelemetryRuntime
from toolwatch.telemetry.context import current_correlation

router = APIRouter(tags=["tool-calls"])


class ToolCallExecuteRequest(BaseModel):
    """Request to execute one trusted registered tool version."""

    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    tool: str = Field(min_length=3, max_length=255)
    tool_version: str = Field(min_length=1, max_length=255)
    arguments: dict[str, object]
    parent_call_id: UUID | None = None


class ToolCallExecuteResponse(BaseModel):
    """Sanitized direct or persistently replayed response."""

    call_id: UUID
    status: ToolCallStatus
    decision: ToolCallDecision
    risk: RiskLevel
    flags: list[str]
    matched_rules: list[str]
    tool: str
    tool_version: str
    duration_ms: int | None
    result: JSONValue | None


class ToolCallError(BaseModel):
    """Safe persisted terminal error."""

    code: str
    message: str


class ToolCallResponse(BaseModel):
    """Sanitized persisted tool-call representation."""

    id: UUID
    session_id: UUID
    parent_call_id: UUID | None
    tool: str
    tool_version: str
    sequence_number: int
    status: ToolCallStatus
    decision: ToolCallDecision
    risk: RiskLevel
    flags: list[str]
    matched_rules: list[str]
    arguments: JSONObject
    result: JSONValue | None
    duration_ms: int | None
    error: ToolCallError | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ToolCallListResponse(BaseModel):
    """Paginated sanitized session call history."""

    items: list[ToolCallResponse]
    limit: int
    offset: int
    total: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
AdapterDependency = Annotated[AdapterRegistry, Depends(get_adapter_registry)]
CacheDependency = Annotated[TerminalResponseCache, Depends(get_terminal_response_cache)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
TelemetryDependency = Annotated[TelemetryRuntime, Depends(get_telemetry)]


@router.post(
    "/api/v1/tool-calls",
    response_model=ToolCallExecuteResponse,
    responses=error_responses(
        not_found=True,
        conflict=True,
        bad_gateway=True,
        gateway_timeout=True,
        forbidden=True,
    ),
)
async def execute_tool_call(
    request: ToolCallExecuteRequest,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    cache: CacheDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ToolCallExecuteResponse | JSONResponse:
    """Execute a trusted adapter after deterministic security evaluation."""

    service = ToolCallService(uow_factory, adapters, settings, cache, telemetry)
    try:
        execution = await service.execute(
            ExecuteToolCall(
                session_id=request.session_id,
                tool_name=request.tool,
                tool_version=request.tool_version,
                arguments=request.arguments,
                idempotency_key=idempotency_key,
                parent_call_id=request.parent_call_id,
            )
        )
    except ToolCallBlocked as exc:
        if not isinstance(exc.outcome, ToolCallExecution):
            raise
        outcome = exc.outcome
        body = {
            "call_id": str(outcome.call.id),
            "status": outcome.call.status.value,
            "decision": outcome.call.decision.value,
            "risk": outcome.call.risk_level.value,
            "flags": [flag.code.value for flag in outcome.flags],
            "matched_rules": list(outcome.matched_rules),
            "error": ErrorResponse(
                error=ErrorBody(
                    code=exc.code,
                    message="The tool call was blocked by a runtime safety rule.",
                    correlation_id=current_correlation().correlation_id,
                )
            ).model_dump()["error"],
        }
        return JSONResponse(status_code=403, content=body)
    return _execution_response(execution)


@router.get(
    "/api/v1/tool-calls/{call_id}",
    response_model=ToolCallResponse,
    responses=error_responses(not_found=True),
)
async def get_tool_call(
    call_id: UUID,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    cache: CacheDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
) -> ToolCallResponse:
    """Return one persisted call with sanitized payloads only."""

    detail = await ToolCallService(uow_factory, adapters, settings, cache, telemetry).get(call_id)
    return _call_response(detail)


@router.get(
    "/api/v1/sessions/{session_id}/tool-calls",
    response_model=ToolCallListResponse,
    responses=error_responses(not_found=True),
)
async def list_session_tool_calls(
    session_id: UUID,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    cache: CacheDependency,
    settings: SettingsDependency,
    telemetry: TelemetryDependency,
    call_status: Annotated[ToolCallStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ToolCallListResponse:
    """List calls by monotonically increasing session sequence number."""

    service = ToolCallService(uow_factory, adapters, settings, cache, telemetry)
    page = await service.list_for_session(
        session_id,
        ToolCallFilters(status=call_status, limit=limit, offset=offset),
    )
    return ToolCallListResponse(
        items=[_call_response(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _execution_response(execution: ToolCallExecution) -> ToolCallExecuteResponse:
    return ToolCallExecuteResponse(
        call_id=execution.call.id,
        status=execution.call.status,
        decision=execution.call.decision,
        risk=execution.call.risk_level,
        flags=[flag.code.value for flag in execution.flags],
        matched_rules=list(execution.matched_rules),
        tool=execution.tool.name,
        tool_version=execution.tool.version,
        duration_ms=execution.call.duration_ms,
        result=execution.result,
    )


def _call_response(detail: ToolCallDetail) -> ToolCallResponse:
    call = detail.call
    error = (
        ToolCallError(
            code=call.error_code,
            message=call.error_message_safe or "The call did not complete.",
        )
        if call.error_code is not None
        else None
    )
    return ToolCallResponse(
        id=call.id,
        session_id=call.session_id,
        parent_call_id=call.parent_call_id,
        tool=detail.tool.name,
        tool_version=detail.tool.version,
        sequence_number=call.sequence_number,
        status=call.status,
        decision=call.decision,
        risk=call.risk_level,
        flags=[flag.code.value for flag in detail.flags],
        matched_rules=list(detail.matched_rules),
        arguments=call.redacted_arguments,
        result=detail.result,
        duration_ms=call.duration_ms,
        error=error,
        started_at=call.started_at,
        finished_at=call.finished_at,
        created_at=call.created_at,
    )
