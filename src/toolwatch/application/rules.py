"""Blocking-rule management use cases."""

from dataclasses import replace
from uuid import UUID

from toolwatch.application.errors import (
    BlockingRuleAlreadyExists,
    BlockingRuleNotFound,
)
from toolwatch.application.ports import Page, RepositoryConflict, UnitOfWorkFactory
from toolwatch.domain.common import utc_now
from toolwatch.domain.security import BlockingRule, RuleAction

RULE_NAME_CONSTRAINT = "uq_blocking_rules_name"


class RuleService:
    """Manage validated deterministic rules."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def create(self, rule: BlockingRule) -> BlockingRule:
        async with self._uow_factory() as uow:
            try:
                created = await uow.rules.create(rule)
                await uow.commit()
            except RepositoryConflict as exc:
                if exc.constraint_name == RULE_NAME_CONSTRAINT:
                    raise BlockingRuleAlreadyExists from None
                raise
        return created

    async def get(self, rule_id: UUID) -> BlockingRule:
        async with self._uow_factory() as uow:
            rule = await uow.rules.get_by_id(rule_id)
        if rule is None:
            raise BlockingRuleNotFound
        return rule

    async def list(
        self,
        *,
        enabled: bool | None,
        limit: int,
        offset: int,
    ) -> Page[BlockingRule]:
        async with self._uow_factory() as uow:
            return await uow.rules.list(enabled=enabled, limit=limit, offset=offset)

    async def update(
        self,
        rule_id: UUID,
        *,
        enabled: bool | None,
        priority: int | None,
        action: RuleAction | None,
        description: str | None,
    ) -> BlockingRule:
        async with self._uow_factory() as uow:
            current = await uow.rules.get_by_id(rule_id)
            if current is None:
                raise BlockingRuleNotFound
            updated = replace(
                current,
                enabled=current.enabled if enabled is None else enabled,
                priority=current.priority if priority is None else priority,
                action=current.action if action is None else action,
                description=current.description if description is None else description,
                updated_at=utc_now(),
            )
            updated = await uow.rules.update(updated)
            await uow.commit()
        return updated
