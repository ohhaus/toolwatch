"""Tool registry use cases."""

from dataclasses import dataclass
from uuid import UUID

from toolwatch.application.errors import ToolNotFound, ToolVersionAlreadyExists
from toolwatch.application.ports import Page, RepositoryConflict, UnitOfWorkFactory
from toolwatch.domain.tools import RiskLevel, ToolDefinition

TOOL_UNIQUE_CONSTRAINT = "uq_tool_definitions_name_version"


@dataclass(frozen=True, slots=True)
class ToolFilters:
    """Bounded registry listing filters."""

    enabled: bool | None = None
    risk_level: RiskLevel | None = None
    name: str | None = None
    limit: int = 50
    offset: int = 0


class ToolService:
    """Orchestrate trusted tool registry transactions."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def register(self, tool: ToolDefinition) -> ToolDefinition:
        """Register a unique tool version."""

        async with self._uow_factory() as uow:
            try:
                created = await uow.tools.create(tool)
                await uow.commit()
            except RepositoryConflict as exc:
                if exc.constraint_name == TOOL_UNIQUE_CONSTRAINT:
                    raise ToolVersionAlreadyExists from None
                raise
        return created

    async def get(self, tool_id: UUID) -> ToolDefinition:
        """Return one tool or a stable not-found error."""

        async with self._uow_factory() as uow:
            tool = await uow.tools.get_by_id(tool_id)
        if tool is None:
            raise ToolNotFound
        return tool

    async def list(self, filters: ToolFilters) -> Page[ToolDefinition]:
        """List tools in deterministic order."""

        async with self._uow_factory() as uow:
            return await uow.tools.list(
                enabled=filters.enabled,
                risk_level=filters.risk_level,
                name=filters.name,
                limit=filters.limit,
                offset=filters.offset,
            )

    async def set_enabled(self, tool_id: UUID, enabled: bool) -> ToolDefinition:
        """Enable or disable one registry entry."""

        async with self._uow_factory() as uow:
            current = await uow.tools.get_by_id(tool_id)
            if current is None:
                raise ToolNotFound
            updated = await uow.tools.set_enabled(current.set_enabled(enabled))
            await uow.commit()
        return updated
