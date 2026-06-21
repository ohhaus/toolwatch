"""SQLAlchemy implementations of application repository ports."""

from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from toolwatch.application.ports import Page, RepositoryConflict
from toolwatch.domain.agents import Agent, AgentIdentity
from toolwatch.domain.common import JSONObject
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.infrastructure.database.models import (
    AgentModel,
    AgentSessionModel,
    ToolDefinitionModel,
)


class SqlAlchemyAgentRepository:
    """Persist and resolve logical agents."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        model = await self._session.get(AgentModel, agent_id)
        return _agent_from_model(model) if model is not None else None

    async def find_by_identity(self, identity: AgentIdentity) -> Agent | None:
        statement = select(AgentModel).where(
            AgentModel.name == identity.name,
            AgentModel.provider == identity.provider,
            AgentModel.model_name == identity.model_name,
            AgentModel.version_key == (identity.version or ""),
        )
        model = await self._session.scalar(statement)
        return _agent_from_model(model) if model is not None else None

    async def create(self, agent: Agent) -> Agent:
        values = {
            "id": agent.id,
            "name": agent.identity.name,
            "provider": agent.identity.provider,
            "model_name": agent.identity.model_name,
            "version": agent.identity.version,
            "version_key": agent.identity.version or "",
            "metadata_": agent.metadata,
            "created_at": agent.created_at,
        }
        statement = (
            insert(AgentModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_agents_identity")
            .returning(AgentModel)
        )
        created = (await self._session.scalars(statement)).one_or_none()
        if created is not None:
            return _agent_from_model(created)
        existing = await self.find_by_identity(agent.identity)
        if existing is None:
            raise RuntimeError("agent upsert did not return a row")
        return existing


class SqlAlchemyToolRepository:
    """Persist trusted tool registry entries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tool_id: UUID) -> ToolDefinition | None:
        model = await self._session.get(ToolDefinitionModel, tool_id)
        return _tool_from_model(model) if model is not None else None

    async def get_by_name_and_version(self, name: str, version: str) -> ToolDefinition | None:
        statement = select(ToolDefinitionModel).where(
            ToolDefinitionModel.name == name,
            ToolDefinitionModel.version == version,
        )
        model = await self._session.scalar(statement)
        return _tool_from_model(model) if model is not None else None

    async def list(
        self,
        *,
        enabled: bool | None,
        risk_level: RiskLevel | None,
        name: str | None,
        limit: int,
        offset: int,
    ) -> Page[ToolDefinition]:
        statement: Select[tuple[ToolDefinitionModel]] = select(ToolDefinitionModel)
        count_statement = select(func.count()).select_from(ToolDefinitionModel)
        conditions: list[ColumnElement[bool]] = []
        if enabled is not None:
            conditions.append(ToolDefinitionModel.enabled == enabled)
        if risk_level is not None:
            conditions.append(ToolDefinitionModel.base_risk_level == risk_level.value)
        if name is not None:
            conditions.append(ToolDefinitionModel.name == name)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(
                ToolDefinitionModel.name,
                ToolDefinitionModel.version,
                ToolDefinitionModel.id,
            )
            .limit(limit)
            .offset(offset)
        )
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page(
            items=[_tool_from_model(model) for model in models],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create(self, tool: ToolDefinition) -> ToolDefinition:
        model = _tool_to_model(tool)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            constraint = _constraint_name(exc)
            raise RepositoryConflict(str(constraint or "unknown_constraint")) from exc
        return _tool_from_model(model)

    async def set_enabled(self, tool: ToolDefinition) -> ToolDefinition:
        model = await self._session.get(ToolDefinitionModel, tool.id)
        if model is None:
            raise RuntimeError("tool disappeared during update")
        model.enabled = tool.enabled
        model.updated_at = tool.updated_at
        await self._session.flush()
        return _tool_from_model(model)


class SqlAlchemySessionRepository:
    """Persist agent sessions and lifecycle changes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentSession | None:
        statement = select(AgentSessionModel).where(AgentSessionModel.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        model = await self._session.scalar(statement)
        return _session_from_model(model) if model is not None else None

    async def list(
        self,
        *,
        agent_id: UUID | None,
        status: SessionStatus | None,
        limit: int,
        offset: int,
    ) -> Page[AgentSession]:
        statement: Select[tuple[AgentSessionModel]] = select(AgentSessionModel)
        count_statement = select(func.count()).select_from(AgentSessionModel)
        conditions: list[ColumnElement[bool]] = []
        if agent_id is not None:
            conditions.append(AgentSessionModel.agent_id == agent_id)
        if status is not None:
            conditions.append(AgentSessionModel.status == status.value)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(
                AgentSessionModel.started_at.desc(),
                AgentSessionModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page(
            items=[_session_from_model(model) for model in models],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create(self, session: AgentSession) -> AgentSession:
        model = AgentSessionModel(
            id=session.id,
            agent_id=session.agent_id,
            external_session_id=session.external_session_id,
            user_prompt_redacted=session.user_prompt_redacted,
            status=session.status.value,
            started_at=session.started_at,
            finished_at=session.finished_at,
            metadata_=session.metadata,
        )
        self._session.add(model)
        await self._session.flush()
        return _session_from_model(model)

    async def update_status(self, session: AgentSession) -> AgentSession:
        model = await self._session.get(AgentSessionModel, session.id)
        if model is None:
            raise RuntimeError("session disappeared during update")
        model.status = session.status.value
        model.finished_at = session.finished_at
        await self._session.flush()
        return _session_from_model(model)


def _agent_from_model(model: AgentModel) -> Agent:
    return Agent(
        id=model.id,
        identity=AgentIdentity(
            name=model.name,
            provider=model.provider,
            model_name=model.model_name,
            version=model.version,
        ),
        metadata=cast(JSONObject, model.metadata_),
        created_at=model.created_at,
    )


def _tool_to_model(tool: ToolDefinition) -> ToolDefinitionModel:
    return ToolDefinitionModel(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        version=tool.version,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        base_risk_level=tool.base_risk_level.value,
        enabled=tool.enabled,
        adapter_type=tool.adapter_type,
        adapter_config=tool.adapter_config,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _tool_from_model(model: ToolDefinitionModel) -> ToolDefinition:
    return ToolDefinition(
        id=model.id,
        name=model.name,
        description=model.description,
        version=model.version,
        input_schema=cast(JSONObject, model.input_schema),
        output_schema=cast(JSONObject | None, model.output_schema),
        base_risk_level=RiskLevel(model.base_risk_level),
        enabled=model.enabled,
        adapter_type=model.adapter_type,
        adapter_config=cast(JSONObject, model.adapter_config),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _session_from_model(model: AgentSessionModel) -> AgentSession:
    return AgentSession(
        id=model.id,
        agent_id=model.agent_id,
        external_session_id=model.external_session_id,
        user_prompt_redacted=model.user_prompt_redacted,
        status=SessionStatus(model.status),
        started_at=model.started_at,
        finished_at=model.finished_at,
        metadata=cast(JSONObject, model.metadata_),
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    current: BaseException | None = exc.orig
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        constraint = getattr(current, "constraint_name", None)
        if isinstance(constraint, str):
            return constraint
        current = current.__cause__ or current.__context__
    return None
