"""Agent session use cases."""

from dataclasses import dataclass, field
from uuid import UUID

from toolwatch.application.errors import (
    InvalidSessionTransitionError,
    SessionNotFound,
)
from toolwatch.application.ports import Page, UnitOfWorkFactory
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.common import JSONObject, empty_json_object
from toolwatch.domain.security import AuditEvent, AuditEventType
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.sessions.models import InvalidSessionTransition


@dataclass(frozen=True, slots=True)
class CreateSession:
    """Input for atomically resolving an agent and creating a session."""

    agent_identity: AgentIdentity
    agent_metadata: JSONObject = field(default_factory=empty_json_object)
    external_session_id: str | None = None
    user_prompt_redacted: str | None = None
    metadata: JSONObject = field(default_factory=empty_json_object)


@dataclass(frozen=True, slots=True)
class SessionWithAgent:
    """Session read model including its agent identity."""

    session: AgentSession
    agent: Agent


@dataclass(frozen=True, slots=True)
class SessionFilters:
    """Bounded session listing filters."""

    agent_id: UUID | None = None
    status: SessionStatus | None = None
    limit: int = 50
    offset: int = 0


class SessionService:
    """Orchestrate agent resolution and session lifecycle transactions."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def create(self, request: CreateSession) -> SessionWithAgent:
        """Resolve or create the logical agent and start an active session atomically."""

        async with self._uow_factory() as uow:
            agent = await uow.agents.find_by_identity(request.agent_identity)
            if agent is None:
                agent = await uow.agents.create(
                    Agent(identity=request.agent_identity, metadata=request.agent_metadata)
                )
            session = await uow.sessions.create(
                AgentSession(
                    agent_id=agent.id,
                    external_session_id=request.external_session_id,
                    user_prompt_redacted=request.user_prompt_redacted,
                    metadata=request.metadata,
                )
            )
            await uow.audit_events.create(
                AuditEvent(
                    session_id=session.id,
                    event_type=AuditEventType.SESSION_STARTED,
                    payload_redacted={"status": session.status.value},
                )
            )
            await uow.commit()
        return SessionWithAgent(session=session, agent=agent)

    async def get(self, session_id: UUID) -> SessionWithAgent:
        """Return one session and its agent."""

        async with self._uow_factory() as uow:
            session = await uow.sessions.get_by_id(session_id)
            if session is None:
                raise SessionNotFound
            agent = await uow.agents.get_by_id(session.agent_id)
            if agent is None:
                raise SessionNotFound
        return SessionWithAgent(session=session, agent=agent)

    async def list(self, filters: SessionFilters) -> Page[SessionWithAgent]:
        """List newest sessions first with their agent identities."""

        async with self._uow_factory() as uow:
            page = await uow.sessions.list(
                agent_id=filters.agent_id,
                status=filters.status,
                limit=filters.limit,
                offset=filters.offset,
            )
            items: list[SessionWithAgent] = []
            for session in page.items:
                agent = await uow.agents.get_by_id(session.agent_id)
                if agent is None:
                    raise SessionNotFound
                items.append(SessionWithAgent(session=session, agent=agent))
        return Page(items=items, total=page.total, limit=page.limit, offset=page.offset)

    async def complete(
        self,
        session_id: UUID,
        status: SessionStatus,
    ) -> SessionWithAgent:
        """Apply an idempotent terminal transition while locking the session row."""

        async with self._uow_factory() as uow:
            session = await uow.sessions.get_by_id(session_id, for_update=True)
            if session is None:
                raise SessionNotFound
            try:
                terminal = session.transition_to(status)
            except InvalidSessionTransition as exc:
                raise InvalidSessionTransitionError from exc
            if terminal is not session:
                terminal = await uow.sessions.update_status(terminal)
                await uow.audit_events.create(
                    AuditEvent(
                        session_id=terminal.id,
                        event_type=AuditEventType.SESSION_COMPLETED,
                        payload_redacted={"status": terminal.status.value},
                    )
                )
                await uow.commit()
            agent = await uow.agents.get_by_id(terminal.agent_id)
            if agent is None:
                raise SessionNotFound
        return SessionWithAgent(session=terminal, agent=agent)
