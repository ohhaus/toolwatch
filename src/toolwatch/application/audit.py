"""Read-only audit-event use cases."""

from dataclasses import dataclass
from uuid import UUID

from toolwatch.application.errors import SessionNotFound, ToolCallNotFound
from toolwatch.application.ports import Page, UnitOfWorkFactory
from toolwatch.domain.security import AuditEvent, AuditEventType


@dataclass(frozen=True, slots=True)
class AuditFilters:
    """Bounded deterministic audit filters."""

    session_id: UUID | None = None
    tool_call_id: UUID | None = None
    event_type: AuditEventType | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    limit: int = 50
    offset: int = 0


class AuditService:
    """Read sanitized append-only audit events."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list(self, filters: AuditFilters) -> Page[AuditEvent]:
        async with self._uow_factory() as uow:
            if (
                filters.session_id is not None
                and await uow.sessions.get_by_id(filters.session_id) is None
            ):
                raise SessionNotFound
            if (
                filters.tool_call_id is not None
                and await uow.tool_calls.get_by_id(filters.tool_call_id) is None
            ):
                raise ToolCallNotFound
            return await uow.audit_events.list(
                session_id=filters.session_id,
                tool_call_id=filters.tool_call_id,
                event_type=filters.event_type,
                trace_id=filters.trace_id,
                correlation_id=filters.correlation_id,
                limit=filters.limit,
                offset=filters.offset,
            )
