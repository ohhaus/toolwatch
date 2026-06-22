"""Read-only sanitized audit-event APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from toolwatch.api.dependencies import get_uow_factory
from toolwatch.api.errors import error_responses
from toolwatch.application.audit import AuditFilters, AuditService
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.domain.common import JSONObject
from toolwatch.domain.security import AuditEvent, AuditEventType

router = APIRouter(tags=["audit"])


class AuditEventResponse(BaseModel):
    id: UUID
    session_id: UUID
    tool_call_id: UUID | None
    event_type: AuditEventType
    actor_type: str
    actor_id: str | None
    payload: JSONObject
    trace_id: str | None
    created_at: datetime


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    limit: int
    offset: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]


@router.get("/api/v1/audit-events", response_model=AuditEventListResponse)
async def list_audit_events(
    uow_factory: UowDependency,
    event_type: Annotated[AuditEventType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await _list(uow_factory, event_type=event_type, limit=limit, offset=offset)


@router.get(
    "/api/v1/sessions/{session_id}/audit-events",
    response_model=AuditEventListResponse,
    responses=error_responses(not_found=True),
)
async def list_session_audit_events(
    session_id: UUID,
    uow_factory: UowDependency,
    event_type: Annotated[AuditEventType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await _list(
        uow_factory,
        session_id=session_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/tool-calls/{call_id}/audit-events",
    response_model=AuditEventListResponse,
    responses=error_responses(not_found=True),
)
async def list_call_audit_events(
    call_id: UUID,
    uow_factory: UowDependency,
    event_type: Annotated[AuditEventType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    return await _list(
        uow_factory,
        tool_call_id=call_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )


async def _list(
    uow_factory: UnitOfWorkFactory,
    *,
    session_id: UUID | None = None,
    tool_call_id: UUID | None = None,
    event_type: AuditEventType | None,
    limit: int,
    offset: int,
) -> AuditEventListResponse:
    page = await AuditService(uow_factory).list(
        AuditFilters(
            session_id=session_id,
            tool_call_id=tool_call_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
    )
    return AuditEventListResponse(
        items=[_response(event) for event in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        session_id=event.session_id,
        tool_call_id=event.tool_call_id,
        event_type=event.event_type,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        payload=event.payload_redacted,
        trace_id=event.trace_id,
        created_at=event.created_at,
    )
