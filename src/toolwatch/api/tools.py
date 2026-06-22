"""Tool Registry HTTP API."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import get_telemetry, get_uow_factory
from toolwatch.api.errors import error_responses
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.tools import ToolFilters, ToolService
from toolwatch.domain.common import JSONObject
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.telemetry import TelemetryRuntime

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


class ToolCreateRequest(BaseModel):
    """Request to add a trusted tool version."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "github.list_issues",
                "description": "List GitHub issues for a repository",
                "version": "1.0.0",
                "input_schema": {
                    "type": "object",
                    "properties": {"repository": {"type": "string"}},
                    "required": ["repository"],
                    "additionalProperties": False,
                },
                "output_schema": {"type": "array", "items": {"type": "object"}},
                "base_risk_level": "low",
                "enabled": True,
                "adapter_type": "mock",
                "adapter_config": {"fixture": "github_issues"},
            }
        }
    )

    name: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=1, max_length=10_000)
    version: str = Field(min_length=1, max_length=255)
    input_schema: dict[str, object]
    output_schema: dict[str, object] | None = None
    base_risk_level: RiskLevel
    enabled: bool = True
    adapter_type: str = Field(min_length=1, max_length=100)
    adapter_config: dict[str, object] = Field(default_factory=dict)


class ToolUpdateRequest(BaseModel):
    """The only supported registry mutation after creation."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool


class ToolResponse(BaseModel):
    """Public registry representation; adapter configuration is deliberately omitted."""

    id: UUID
    name: str
    description: str
    version: str
    input_schema: JSONObject
    output_schema: JSONObject | None
    base_risk_level: RiskLevel
    enabled: bool
    adapter_type: str
    created_at: datetime
    updated_at: datetime


class ToolListResponse(BaseModel):
    """Paginated tool registry response."""

    items: list[ToolResponse]
    limit: int
    offset: int
    total: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
TelemetryDependency = Annotated[TelemetryRuntime, Depends(get_telemetry)]


@router.post(
    "",
    response_model=ToolResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(conflict=True),
)
async def register_tool(
    request: ToolCreateRequest,
    uow_factory: UowDependency,
    telemetry: TelemetryDependency,
) -> ToolResponse:
    """Register a trusted, immutable tool version."""

    tool = ToolDefinition(
        name=request.name,
        description=request.description,
        version=request.version,
        input_schema=cast(JSONObject, request.input_schema),
        output_schema=cast(JSONObject | None, request.output_schema),
        base_risk_level=request.base_risk_level,
        enabled=request.enabled,
        adapter_type=request.adapter_type,
        adapter_config=cast(JSONObject, request.adapter_config),
    )
    with telemetry.tracing.span("toolwatch.register_tool"):
        return _tool_response(await ToolService(uow_factory).register(tool))


@router.get("", response_model=ToolListResponse, responses=error_responses())
async def list_tools(
    uow_factory: UowDependency,
    enabled: Annotated[bool | None, Query()] = None,
    risk_level: Annotated[RiskLevel | None, Query()] = None,
    name: Annotated[str | None, Query(min_length=3, max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ToolListResponse:
    """List registry entries in deterministic name/version order."""

    page = await ToolService(uow_factory).list(
        ToolFilters(
            enabled=enabled,
            risk_level=risk_level,
            name=name,
            limit=limit,
            offset=offset,
        )
    )
    return ToolListResponse(
        items=[_tool_response(tool) for tool in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{tool_id}", response_model=ToolResponse, responses=error_responses(not_found=True))
async def get_tool(tool_id: UUID, uow_factory: UowDependency) -> ToolResponse:
    """Get one registered tool."""

    return _tool_response(await ToolService(uow_factory).get(tool_id))


@router.patch(
    "/{tool_id}",
    response_model=ToolResponse,
    responses=error_responses(not_found=True),
)
async def set_tool_enabled(
    tool_id: UUID,
    request: ToolUpdateRequest,
    uow_factory: UowDependency,
) -> ToolResponse:
    """Enable or disable one registered tool."""

    return _tool_response(await ToolService(uow_factory).set_enabled(tool_id, request.enabled))


def _tool_response(tool: ToolDefinition) -> ToolResponse:
    return ToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        version=tool.version,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        base_risk_level=tool.base_risk_level,
        enabled=tool.enabled,
        adapter_type=tool.adapter_type,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )
