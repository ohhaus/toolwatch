"""Runtime blocking-rule management API."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field

from toolwatch.api.dependencies import get_uow_factory
from toolwatch.api.errors import error_responses
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.rules import RuleService
from toolwatch.domain.common import JSONObject
from toolwatch.domain.security import BlockingRule, RuleAction

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


class RuleCreateRequest(BaseModel):
    """Validated finite rule schema."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10_000)
    enabled: bool = True
    priority: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    tool_pattern: str = Field(min_length=1, max_length=255)
    conditions: dict[str, object]
    action: RuleAction


class RulePatchRequest(BaseModel):
    """Allowed mutable rule fields."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    action: RuleAction | None = None
    description: str | None = Field(default=None, min_length=1, max_length=10_000)


class RuleResponse(BaseModel):
    """Public validated rule representation."""

    id: UUID
    name: str
    description: str
    enabled: bool
    priority: int
    tool_pattern: str
    conditions: JSONObject
    action: RuleAction
    created_at: datetime
    updated_at: datetime


class RuleListResponse(BaseModel):
    items: list[RuleResponse]
    total: int
    limit: int
    offset: int


UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]


@router.post(
    "",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(conflict=True),
)
async def create_rule(request: RuleCreateRequest, uow_factory: UowDependency) -> RuleResponse:
    rule = BlockingRule(
        name=request.name,
        description=request.description,
        enabled=request.enabled,
        priority=request.priority,
        tool_pattern=request.tool_pattern,
        conditions=cast(JSONObject, request.conditions),
        action=request.action,
    )
    return _response(await RuleService(uow_factory).create(rule))


@router.get("", response_model=RuleListResponse, responses=error_responses())
async def list_rules(
    uow_factory: UowDependency,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RuleListResponse:
    page = await RuleService(uow_factory).list(enabled=enabled, limit=limit, offset=offset)
    return RuleListResponse(
        items=[_response(rule) for rule in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{rule_id}", response_model=RuleResponse, responses=error_responses(not_found=True))
async def get_rule(rule_id: UUID, uow_factory: UowDependency) -> RuleResponse:
    return _response(await RuleService(uow_factory).get(rule_id))


@router.patch(
    "/{rule_id}",
    response_model=RuleResponse,
    responses=error_responses(not_found=True),
)
async def patch_rule(
    rule_id: UUID,
    request: RulePatchRequest,
    uow_factory: UowDependency,
) -> RuleResponse:
    return _response(
        await RuleService(uow_factory).update(
            rule_id,
            enabled=request.enabled,
            priority=request.priority,
            action=request.action,
            description=request.description,
        )
    )


def _response(rule: BlockingRule) -> RuleResponse:
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        enabled=rule.enabled,
        priority=rule.priority,
        tool_pattern=rule.tool_pattern,
        conditions=rule.conditions,
        action=rule.action,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
