"""Tool-call execution and payload-free read APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import (
    get_adapter_registry,
    get_terminal_response_cache,
    get_uow_factory,
)
from toolwatch.api.errors import error_responses
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
from toolwatch.domain.common import JSONValue
from toolwatch.domain.tool_calls import ToolCallDecision, ToolCallStatus
from toolwatch.infrastructure.adapters import AdapterRegistry

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
    """Direct response containing validated transient adapter output."""

    call_id: UUID
    status: ToolCallStatus
    decision: ToolCallDecision
    tool: str
    tool_version: str
    duration_ms: int | None
    result: JSONValue


class ToolCallError(BaseModel):
    """Safe persisted terminal error."""

    code: str
    message: str


class ToolCallResponse(BaseModel):
    """Payload-free persisted tool-call representation."""

    id: UUID
    session_id: UUID
    parent_call_id: UUID | None
    tool: str
    tool_version: str
    sequence_number: int
    status: ToolCallStatus
    decision: ToolCallDecision
    duration_ms: int | None
    error: ToolCallError | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ToolCallListResponse(BaseModel):
    """Paginated session call history."""

    items: list[ToolCallResponse]
    limit: int
    offset: int
    total: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
AdapterDependency = Annotated[AdapterRegistry, Depends(get_adapter_registry)]
CacheDependency = Annotated[TerminalResponseCache, Depends(get_terminal_response_cache)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/api/v1/tool-calls",
    response_model=ToolCallExecuteResponse,
    responses=error_responses(
        not_found=True,
        conflict=True,
        bad_gateway=True,
        gateway_timeout=True,
    ),
)
async def execute_tool_call(
    request: ToolCallExecuteRequest,
    uow_factory: UowDependency,
    adapters: AdapterDependency,
    cache: CacheDependency,
    settings: SettingsDependency,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ToolCallExecuteResponse:
    """Execute a trusted adapter after deterministic validation."""

    execution = await ToolCallService(uow_factory, adapters, settings, cache).execute(
        ExecuteToolCall(
            session_id=request.session_id,
            tool_name=request.tool,
            tool_version=request.tool_version,
            arguments=request.arguments,
            idempotency_key=idempotency_key,
            parent_call_id=request.parent_call_id,
        )
    )
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
) -> ToolCallResponse:
    """Return one persisted call without arguments or result payload."""

    service = ToolCallService(uow_factory, adapters, settings, cache)
    return _call_response(await service.get(call_id))


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
    call_status: Annotated[ToolCallStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ToolCallListResponse:
    """List calls by monotonically increasing session sequence number."""

    service = ToolCallService(uow_factory, adapters, settings, cache)
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
        duration_ms=call.duration_ms,
        error=error,
        started_at=call.started_at,
        finished_at=call.finished_at,
        created_at=call.created_at,
    )
