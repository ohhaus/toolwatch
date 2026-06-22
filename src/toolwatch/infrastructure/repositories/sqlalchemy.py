"""SQLAlchemy implementations of application repository ports."""

from builtins import list as list_type
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from toolwatch.application.ports import Page, RepositoryConflict
from toolwatch.domain.agents import (
    Agent,
    AgentIdentity,
    AgentRun,
    AgentRunStatus,
    ModelCall,
    ModelCallStatus,
)
from toolwatch.domain.common import JSONObject
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    BlockingRule,
    RiskFlag,
    RiskFlagCode,
    RiskFlagSource,
    RuleAction,
)
from toolwatch.domain.sessions import AgentSession, SessionStatus
from toolwatch.domain.tool_calls import (
    ToolCall,
    ToolCallDecision,
    ToolCallStatus,
    ToolResultMetadata,
)
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.infrastructure.database.models import (
    AgentModel,
    AgentRunModel,
    AgentSessionModel,
    AuditEventModel,
    BlockingRuleModel,
    ModelCallModel,
    RiskFlagModel,
    ToolCallModel,
    ToolDefinitionModel,
    ToolResultMetadataModel,
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


class SqlAlchemyAgentRunRepository:
    """Persist and query safe agent-run lifecycle metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, run_id: UUID) -> AgentRun | None:
        model = await self._session.get(AgentRunModel, run_id)
        return _agent_run_from_model(model) if model is not None else None

    async def list(
        self,
        *,
        session_id: UUID | None,
        provider: str | None,
        model_name: str | None,
        status: AgentRunStatus | None,
        started_from: datetime | None,
        started_to: datetime | None,
        limit: int,
        offset: int,
    ) -> Page[AgentRun]:
        conditions: list[ColumnElement[bool]] = []
        if session_id is not None:
            conditions.append(AgentRunModel.session_id == session_id)
        if provider is not None:
            conditions.append(AgentRunModel.provider == provider)
        if model_name is not None:
            conditions.append(AgentRunModel.model_name == model_name)
        if status is not None:
            conditions.append(AgentRunModel.status == status.value)
        if started_from is not None:
            conditions.append(AgentRunModel.started_at >= started_from)
        if started_to is not None:
            conditions.append(AgentRunModel.started_at <= started_to)
        statement = select(AgentRunModel)
        count_statement = select(func.count()).select_from(AgentRunModel)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(AgentRunModel.started_at.desc(), AgentRunModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page([_agent_run_from_model(model) for model in models], total, limit, offset)

    async def create(self, run: AgentRun) -> AgentRun:
        model = _agent_run_to_model(run)
        self._session.add(model)
        await self._session.flush()
        return _agent_run_from_model(model)

    async def update(self, run: AgentRun) -> AgentRun:
        model = await self._session.get(AgentRunModel, run.id)
        if model is None:
            raise RuntimeError("agent run disappeared during update")
        model.status = run.status.value
        model.turn_count = run.turn_count
        model.tool_call_count = run.tool_call_count
        model.final_answer_redacted = run.final_answer_redacted
        model.error_code = run.error_code
        model.finished_at = run.finished_at
        model.updated_at = run.updated_at
        await self._session.flush()
        return _agent_run_from_model(model)

    async def claim_stale_running(
        self,
        *,
        updated_before: datetime,
        limit: int,
    ) -> list_type[AgentRun]:
        statement = (
            select(AgentRunModel)
            .where(
                AgentRunModel.status == AgentRunStatus.RUNNING.value,
                AgentRunModel.updated_at < updated_before,
            )
            .order_by(AgentRunModel.updated_at, AgentRunModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_agent_run_from_model(model) for model in await self._session.scalars(statement)]


class SqlAlchemyModelCallRepository:
    """Persist safe provider-call metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_run(self, agent_run_id: UUID) -> list[ModelCall]:
        statement = (
            select(ModelCallModel)
            .where(ModelCallModel.agent_run_id == agent_run_id)
            .order_by(ModelCallModel.turn_number, ModelCallModel.id)
        )
        return [_model_call_from_model(model) for model in await self._session.scalars(statement)]

    async def create(self, call: ModelCall) -> ModelCall:
        model = _model_call_to_model(call)
        self._session.add(model)
        await self._session.flush()
        return _model_call_from_model(model)

    async def update(self, call: ModelCall) -> ModelCall:
        model = await self._session.get(ModelCallModel, call.id)
        if model is None:
            raise RuntimeError("model call disappeared during update")
        model.status = call.status.value
        model.requested_tool_count = call.requested_tool_count
        model.prompt_token_count = call.prompt_token_count
        model.completion_token_count = call.completion_token_count
        model.total_duration_ms = call.total_duration_ms
        model.load_duration_ms = call.load_duration_ms
        model.error_code = call.error_code
        model.finished_at = call.finished_at
        await self._session.flush()
        return _model_call_from_model(model)

    async def claim_stale_started(
        self,
        *,
        started_before: datetime,
        limit: int,
    ) -> list[ModelCall]:
        statement = (
            select(ModelCallModel)
            .where(
                ModelCallModel.status == ModelCallStatus.STARTED.value,
                ModelCallModel.started_at < started_before,
            )
            .order_by(ModelCallModel.started_at, ModelCallModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_model_call_from_model(model) for model in await self._session.scalars(statement)]


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


class SqlAlchemyToolCallRepository:
    """Persist and query payload-free tool-call lifecycles."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, call_id: UUID) -> ToolCall | None:
        model = await self._session.get(ToolCallModel, call_id)
        return _tool_call_from_model(model) if model is not None else None

    async def get_by_idempotency_key(self, key: UUID) -> ToolCall | None:
        statement = select(ToolCallModel).where(ToolCallModel.idempotency_key == key)
        model = await self._session.scalar(statement)
        return _tool_call_from_model(model) if model is not None else None

    async def list(
        self,
        *,
        session_id: UUID,
        status: ToolCallStatus | None,
        limit: int,
        offset: int,
    ) -> Page[ToolCall]:
        conditions: list[ColumnElement[bool]] = [ToolCallModel.session_id == session_id]
        if status is not None:
            conditions.append(ToolCallModel.status == status.value)
        statement = (
            select(ToolCallModel)
            .where(*conditions)
            .order_by(ToolCallModel.sequence_number, ToolCallModel.id)
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count()).select_from(ToolCallModel).where(*conditions)
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page(
            items=[_tool_call_from_model(model) for model in models],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_for_agent_run(self, agent_run_id: UUID) -> list_type[ToolCall]:
        statement = (
            select(ToolCallModel)
            .where(ToolCallModel.agent_run_id == agent_run_id)
            .order_by(ToolCallModel.sequence_number, ToolCallModel.id)
        )
        return [_tool_call_from_model(model) for model in await self._session.scalars(statement)]

    async def next_sequence_number(self, session_id: UUID) -> int:
        statement = select(func.max(ToolCallModel.sequence_number)).where(
            ToolCallModel.session_id == session_id
        )
        current = await self._session.scalar(statement)
        return int(current or 0) + 1

    async def create(self, call: ToolCall) -> ToolCall:
        model = _tool_call_to_model(call)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            constraint = _constraint_name(exc)
            raise RepositoryConflict(str(constraint or "unknown_constraint")) from exc
        return _tool_call_from_model(model)

    async def update(self, call: ToolCall) -> ToolCall:
        model = await self._session.get(ToolCallModel, call.id)
        if model is None:
            raise RuntimeError("tool call disappeared during update")
        model.status = call.status.value
        model.decision = call.decision.value
        model.risk_level = call.risk_level.value
        model.matched_rule_ids = [str(rule_id) for rule_id in call.matched_rule_ids]
        model.redacted_arguments = call.redacted_arguments
        model.started_at = call.started_at
        model.finished_at = call.finished_at
        model.duration_ms = call.duration_ms
        model.error_code = call.error_code
        model.error_message_safe = call.error_message_safe
        model.updated_at = call.updated_at
        await self._session.flush()
        return _tool_call_from_model(model)

    async def claim_stale_executing(
        self,
        *,
        updated_before: datetime,
        limit: int,
    ) -> list_type[ToolCall]:
        statement = (
            select(ToolCallModel)
            .where(
                ToolCallModel.status == ToolCallStatus.EXECUTING.value,
                ToolCallModel.updated_at < updated_before,
            )
            .order_by(ToolCallModel.updated_at, ToolCallModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_tool_call_from_model(model) for model in await self._session.scalars(statement)]


class SqlAlchemyToolResultMetadataRepository:
    """Persist one safe result metadata row per tool call."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tool_call_id(self, call_id: UUID) -> ToolResultMetadata | None:
        statement = select(ToolResultMetadataModel).where(
            ToolResultMetadataModel.tool_call_id == call_id
        )
        model = await self._session.scalar(statement)
        return _tool_result_from_model(model) if model is not None else None

    async def create(self, metadata: ToolResultMetadata) -> ToolResultMetadata:
        model = ToolResultMetadataModel(
            id=metadata.id,
            tool_call_id=metadata.tool_call_id,
            payload_hash=metadata.payload_hash,
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
            schema_valid=metadata.schema_valid,
            redacted_payload=metadata.redacted_payload,
            truncated=metadata.truncated,
            created_at=metadata.created_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            constraint = _constraint_name(exc)
            raise RepositoryConflict(str(constraint or "unknown_constraint")) from exc
        return _tool_result_from_model(model)


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


def _agent_run_to_model(run: AgentRun) -> AgentRunModel:
    return AgentRunModel(
        id=run.id,
        session_id=run.session_id,
        provider=run.provider,
        model_name=run.model_name,
        status=run.status.value,
        turn_count=run.turn_count,
        tool_call_count=run.tool_call_count,
        final_answer_redacted=run.final_answer_redacted,
        error_code=run.error_code,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _agent_run_from_model(model: AgentRunModel) -> AgentRun:
    return AgentRun(
        id=model.id,
        session_id=model.session_id,
        provider=model.provider,
        model_name=model.model_name,
        status=AgentRunStatus(model.status),
        turn_count=model.turn_count,
        tool_call_count=model.tool_call_count,
        final_answer_redacted=model.final_answer_redacted,
        error_code=model.error_code,
        trace_id=model.trace_id,
        correlation_id=model.correlation_id,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _model_call_to_model(call: ModelCall) -> ModelCallModel:
    return ModelCallModel(
        id=call.id,
        agent_run_id=call.agent_run_id,
        turn_number=call.turn_number,
        provider=call.provider,
        model_name=call.model_name,
        status=call.status.value,
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


def _model_call_from_model(model: ModelCallModel) -> ModelCall:
    return ModelCall(
        id=model.id,
        agent_run_id=model.agent_run_id,
        turn_number=model.turn_number,
        provider=model.provider,
        model_name=model.model_name,
        status=ModelCallStatus(model.status),
        requested_tool_count=model.requested_tool_count,
        prompt_token_count=model.prompt_token_count,
        completion_token_count=model.completion_token_count,
        total_duration_ms=model.total_duration_ms,
        load_duration_ms=model.load_duration_ms,
        error_code=model.error_code,
        trace_id=model.trace_id,
        correlation_id=model.correlation_id,
        started_at=model.started_at,
        finished_at=model.finished_at,
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


def _tool_call_to_model(call: ToolCall) -> ToolCallModel:
    return ToolCallModel(
        id=call.id,
        agent_run_id=call.agent_run_id,
        session_id=call.session_id,
        tool_definition_id=call.tool_definition_id,
        parent_call_id=call.parent_call_id,
        sequence_number=call.sequence_number,
        arguments_hash=call.arguments_hash,
        request_hash=call.request_hash,
        idempotency_key=call.idempotency_key,
        status=call.status.value,
        decision=call.decision.value,
        risk_level=call.risk_level.value,
        matched_rule_ids=[str(rule_id) for rule_id in call.matched_rule_ids],
        redacted_arguments=call.redacted_arguments,
        started_at=call.started_at,
        finished_at=call.finished_at,
        duration_ms=call.duration_ms,
        error_code=call.error_code,
        error_message_safe=call.error_message_safe,
        created_at=call.created_at,
        updated_at=call.updated_at,
    )


def _tool_call_from_model(model: ToolCallModel) -> ToolCall:
    return ToolCall(
        id=model.id,
        agent_run_id=model.agent_run_id,
        session_id=model.session_id,
        tool_definition_id=model.tool_definition_id,
        parent_call_id=model.parent_call_id,
        sequence_number=model.sequence_number,
        arguments_hash=model.arguments_hash,
        request_hash=model.request_hash,
        idempotency_key=model.idempotency_key,
        status=ToolCallStatus(model.status),
        decision=ToolCallDecision(model.decision),
        risk_level=RiskLevel(model.risk_level),
        matched_rule_ids=tuple(UUID(value) for value in model.matched_rule_ids),
        redacted_arguments=model.redacted_arguments,
        started_at=model.started_at,
        finished_at=model.finished_at,
        duration_ms=model.duration_ms,
        error_code=model.error_code,
        error_message_safe=model.error_message_safe,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _tool_result_from_model(model: ToolResultMetadataModel) -> ToolResultMetadata:
    return ToolResultMetadata(
        id=model.id,
        tool_call_id=model.tool_call_id,
        payload_hash=model.payload_hash,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        schema_valid=model.schema_valid,
        redacted_payload=model.redacted_payload,
        truncated=model.truncated,
        created_at=model.created_at,
    )


class SqlAlchemyRiskFlagRepository:
    """Persist safe deterministic risk flags."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_tool_call(self, call_id: UUID) -> list[RiskFlag]:
        statement = (
            select(RiskFlagModel)
            .where(RiskFlagModel.tool_call_id == call_id)
            .order_by(RiskFlagModel.created_at, RiskFlagModel.code, RiskFlagModel.id)
        )
        return [_risk_flag_from_model(model) for model in await self._session.scalars(statement)]

    async def create_many(self, flags: list[RiskFlag]) -> list[RiskFlag]:
        models = [
            RiskFlagModel(
                id=flag.id,
                tool_call_id=flag.tool_call_id,
                code=flag.code.value,
                severity=flag.severity.value,
                message=flag.message,
                safe_evidence=flag.safe_evidence,
                source=flag.source.value,
                created_at=flag.created_at,
            )
            for flag in flags
        ]
        self._session.add_all(models)
        await self._session.flush()
        return [_risk_flag_from_model(model) for model in models]


class SqlAlchemyBlockingRuleRepository:
    """Persist and resolve runtime rules."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, rule_id: UUID) -> BlockingRule | None:
        model = await self._session.get(BlockingRuleModel, rule_id)
        return _rule_from_model(model) if model is not None else None

    async def list(
        self,
        *,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[BlockingRule]:
        conditions: list[ColumnElement[bool]] = []
        if enabled is not None:
            conditions.append(BlockingRuleModel.enabled == enabled)
        statement = select(BlockingRuleModel)
        count_statement = select(func.count()).select_from(BlockingRuleModel)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(
                BlockingRuleModel.priority.desc(),
                BlockingRuleModel.name,
                BlockingRuleModel.id,
            )
            .limit(limit)
            .offset(offset)
        )
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page([_rule_from_model(model) for model in models], total, limit, offset)

    async def list_enabled(self) -> list_type[BlockingRule]:
        page = await self.list(enabled=True, limit=10_000, offset=0)
        return page.items

    async def create(self, rule: BlockingRule) -> BlockingRule:
        model = _rule_to_model(rule)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise RepositoryConflict(str(_constraint_name(exc) or "unknown_constraint")) from exc
        return _rule_from_model(model)

    async def update(self, rule: BlockingRule) -> BlockingRule:
        model = await self._session.get(BlockingRuleModel, rule.id)
        if model is None:
            raise RuntimeError("blocking rule disappeared during update")
        model.description = rule.description
        model.enabled = rule.enabled
        model.priority = rule.priority
        model.action = rule.action.value
        model.updated_at = rule.updated_at
        await self._session.flush()
        return _rule_from_model(model)


class SqlAlchemyAuditEventRepository:
    """Append-only audit-event repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        session_id: UUID | None,
        tool_call_id: UUID | None,
        event_type: AuditEventType | None,
        trace_id: str | None,
        correlation_id: str | None,
        limit: int,
        offset: int,
    ) -> Page[AuditEvent]:
        conditions: list[ColumnElement[bool]] = []
        if session_id is not None:
            conditions.append(AuditEventModel.session_id == session_id)
        if tool_call_id is not None:
            conditions.append(AuditEventModel.tool_call_id == tool_call_id)
        if event_type is not None:
            conditions.append(AuditEventModel.event_type == event_type.value)
        if trace_id is not None:
            conditions.append(AuditEventModel.trace_id == trace_id)
        if correlation_id is not None:
            conditions.append(AuditEventModel.correlation_id == correlation_id)
        statement = select(AuditEventModel)
        count_statement = select(func.count()).select_from(AuditEventModel)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(AuditEventModel.created_at, AuditEventModel.id)
            .limit(limit)
            .offset(offset)
        )
        models = list((await self._session.scalars(statement)).all())
        total = int((await self._session.scalar(count_statement)) or 0)
        return Page([_audit_from_model(model) for model in models], total, limit, offset)

    async def create(self, event: AuditEvent) -> AuditEvent:
        return (await self.create_many([event]))[0]

    async def create_many(
        self,
        events: list_type[AuditEvent],
    ) -> list_type[AuditEvent]:
        models = [
            AuditEventModel(
                id=event.id,
                session_id=event.session_id,
                tool_call_id=event.tool_call_id,
                event_type=event.event_type.value,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                payload_redacted=event.payload_redacted,
                trace_id=event.trace_id,
                correlation_id=event.correlation_id,
                created_at=event.created_at,
            )
            for event in events
        ]
        self._session.add_all(models)
        await self._session.flush()
        return [_audit_from_model(model) for model in models]


def _risk_flag_from_model(model: RiskFlagModel) -> RiskFlag:
    return RiskFlag(
        id=model.id,
        tool_call_id=model.tool_call_id,
        code=RiskFlagCode(model.code),
        severity=RiskLevel(model.severity),
        message=model.message,
        safe_evidence=cast(JSONObject, model.safe_evidence),
        source=RiskFlagSource(model.source),
        created_at=model.created_at,
    )


def _rule_to_model(rule: BlockingRule) -> BlockingRuleModel:
    return BlockingRuleModel(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        enabled=rule.enabled,
        priority=rule.priority,
        tool_pattern=rule.tool_pattern,
        conditions=rule.conditions,
        action=rule.action.value,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _rule_from_model(model: BlockingRuleModel) -> BlockingRule:
    return BlockingRule(
        id=model.id,
        name=model.name,
        description=model.description,
        enabled=model.enabled,
        priority=model.priority,
        tool_pattern=model.tool_pattern,
        conditions=cast(JSONObject, model.conditions),
        action=RuleAction(model.action),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _audit_from_model(model: AuditEventModel) -> AuditEvent:
    return AuditEvent(
        id=model.id,
        session_id=model.session_id,
        tool_call_id=model.tool_call_id,
        event_type=AuditEventType(model.event_type),
        actor_type=model.actor_type,
        actor_id=model.actor_id,
        payload_redacted=cast(JSONObject, model.payload_redacted),
        trace_id=model.trace_id,
        correlation_id=model.correlation_id,
        created_at=model.created_at,
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
