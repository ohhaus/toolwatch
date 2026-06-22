"""SQLAlchemy unit of work implementation."""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from toolwatch.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyAgentRepository,
    SqlAlchemyAgentRunRepository,
    SqlAlchemyAuditEventRepository,
    SqlAlchemyBlockingRuleRepository,
    SqlAlchemyModelCallRepository,
    SqlAlchemyRiskFlagRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyToolCallRepository,
    SqlAlchemyToolRepository,
    SqlAlchemyToolResultMetadataRepository,
)


class SqlAlchemyUnitOfWork:
    """Own one async SQLAlchemy session and transaction."""

    agents: SqlAlchemyAgentRepository
    tools: SqlAlchemyToolRepository
    sessions: SqlAlchemySessionRepository
    tool_calls: SqlAlchemyToolCallRepository
    tool_results: SqlAlchemyToolResultMetadataRepository
    risk_flags: SqlAlchemyRiskFlagRepository
    rules: SqlAlchemyBlockingRuleRepository
    audit_events: SqlAlchemyAuditEventRepository
    agent_runs: SqlAlchemyAgentRunRepository
    model_calls: SqlAlchemyModelCallRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        session = self._session_factory()
        self._session = session
        self.agents = SqlAlchemyAgentRepository(session)
        self.tools = SqlAlchemyToolRepository(session)
        self.sessions = SqlAlchemySessionRepository(session)
        self.tool_calls = SqlAlchemyToolCallRepository(session)
        self.tool_results = SqlAlchemyToolResultMetadataRepository(session)
        self.risk_flags = SqlAlchemyRiskFlagRepository(session)
        self.rules = SqlAlchemyBlockingRuleRepository(session)
        self.audit_events = SqlAlchemyAuditEventRepository(session)
        self.agent_runs = SqlAlchemyAgentRunRepository(session)
        self.model_calls = SqlAlchemyModelCallRepository(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        if session.in_transaction():
            await session.rollback()
        await session.close()

    async def commit(self) -> None:
        """Commit the use-case transaction."""

        await self._require_session().commit()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session
