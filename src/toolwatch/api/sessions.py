"""Agent Sessions HTTP API."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import get_uow_factory
from toolwatch.api.errors import error_responses
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.sessions import (
    CreateSession,
    SessionFilters,
    SessionService,
    SessionWithAgent,
)
from toolwatch.config import get_settings
from toolwatch.domain.agents import AgentIdentity
from toolwatch.domain.common import JSONObject
from toolwatch.domain.sessions import SessionStatus
from toolwatch.security.prompt import prepare_prompt_for_storage

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


class AgentRequest(BaseModel):
    """Logical agent identity supplied when opening a session."""

    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=255)
    model_name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, object] = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    """Request to resolve an agent and open a session."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent": {
                    "name": "local-demo-agent",
                    "provider": "ollama",
                    "model_name": "qwen3:4b",
                    "version": "1",
                },
                "external_session_id": "client-session-123",
                "user_prompt": "Check open issues in demo/backend",
                "metadata": {"source": "demo"},
            }
        }
    )

    agent: AgentRequest
    external_session_id: str | None = Field(default=None, min_length=1, max_length=255)
    user_prompt: str | None = Field(default=None, max_length=65_536)
    metadata: dict[str, object] = Field(default_factory=dict)


class SessionCompleteRequest(BaseModel):
    """Allowed terminal session transition."""

    model_config = ConfigDict(extra="forbid")
    status: SessionStatus


class AgentResponse(BaseModel):
    """Public logical agent representation."""

    id: UUID
    name: str
    provider: str
    model_name: str
    version: str | None
    metadata: JSONObject
    created_at: datetime


class SessionResponse(BaseModel):
    """Public session representation; prompt content is never returned."""

    id: UUID
    agent: AgentResponse
    external_session_id: str | None
    status: SessionStatus
    started_at: datetime
    finished_at: datetime | None
    metadata: JSONObject


class SessionListResponse(BaseModel):
    """Paginated session response."""

    items: list[SessionResponse]
    limit: int
    offset: int
    total: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(),
)
async def create_session(
    request: SessionCreateRequest,
    uow_factory: UowDependency,
) -> SessionResponse:
    """Resolve or create an agent and start a session in one transaction."""

    settings = get_settings()
    created = await SessionService(uow_factory).create(
        CreateSession(
            agent_identity=AgentIdentity(
                name=request.agent.name,
                provider=request.agent.provider,
                model_name=request.agent.model_name,
                version=request.agent.version,
            ),
            agent_metadata=cast(JSONObject, request.agent.metadata),
            external_session_id=request.external_session_id,
            user_prompt_redacted=prepare_prompt_for_storage(
                request.user_prompt,
                store_prompts=settings.store_prompts,
            ),
            metadata=cast(JSONObject, request.metadata),
        )
    )
    return _session_response(created)


@router.get("", response_model=SessionListResponse, responses=error_responses())
async def list_sessions(
    uow_factory: UowDependency,
    agent_id: Annotated[UUID | None, Query()] = None,
    session_status: Annotated[SessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionListResponse:
    """List newest sessions first."""

    page = await SessionService(uow_factory).list(
        SessionFilters(
            agent_id=agent_id,
            status=session_status,
            limit=limit,
            offset=offset,
        )
    )
    return SessionListResponse(
        items=[_session_response(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses=error_responses(not_found=True),
)
async def get_session(session_id: UUID, uow_factory: UowDependency) -> SessionResponse:
    """Get one session and its agent identity."""

    return _session_response(await SessionService(uow_factory).get(session_id))


@router.post(
    "/{session_id}/complete",
    response_model=SessionResponse,
    responses=error_responses(not_found=True, conflict=True),
)
async def complete_session(
    session_id: UUID,
    request: SessionCompleteRequest,
    uow_factory: UowDependency,
) -> SessionResponse:
    """Complete or fail an active session."""

    if request.status is SessionStatus.ACTIVE:
        from toolwatch.application.errors import InvalidSessionTransitionError

        raise InvalidSessionTransitionError
    return _session_response(await SessionService(uow_factory).complete(session_id, request.status))


def _session_response(value: SessionWithAgent) -> SessionResponse:
    identity = value.agent.identity
    return SessionResponse(
        id=value.session.id,
        agent=AgentResponse(
            id=value.agent.id,
            name=identity.name,
            provider=identity.provider,
            model_name=identity.model_name,
            version=identity.version,
            metadata=value.agent.metadata,
            created_at=value.agent.created_at,
        ),
        external_session_id=value.session.external_session_id,
        status=value.session.status,
        started_at=value.session.started_at,
        finished_at=value.session.finished_at,
        metadata=value.session.metadata,
    )
