"""Explicit idempotent development seed for trusted mock tools."""

import asyncio
from functools import partial

from toolwatch.application.errors import ToolVersionAlreadyExists
from toolwatch.application.tools import ToolService
from toolwatch.domain.tools import RiskLevel, ToolDefinition
from toolwatch.infrastructure.database.engine import (
    dispose_engine,
    get_session_factory,
)
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork


def seed_tools() -> list[ToolDefinition]:
    """Return the reviewed trusted mock tool definitions."""

    return [
        ToolDefinition(
            name="github.list_issues",
            description="List deterministic fixture issues for a repository.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {
                    "repository": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
                    },
                    "state": {"type": "string", "enum": ["open", "closed"]},
                },
                "required": ["repository", "state"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {"type": "integer"},
                                "title": {"type": "string"},
                                "state": {"type": "string", "enum": ["open", "closed"]},
                            },
                            "required": ["number", "title", "state"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["issues"],
                "additionalProperties": False,
            },
            base_risk_level=RiskLevel.LOW,
            adapter_type="mock_github",
            adapter_config={},
        ),
        ToolDefinition(
            name="email.send",
            description="Simulate accepting an email without sending it.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "format": "email"},
                    "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                    "body": {"type": "string", "minLength": 1},
                },
                "required": ["recipient", "subject", "body"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "pattern": "^msg_[0-9a-f]{20}$"},
                    "status": {"const": "accepted"},
                },
                "required": ["message_id", "status"],
                "additionalProperties": False,
            },
            base_risk_level=RiskLevel.MEDIUM,
            adapter_type="mock_email",
            adapter_config={},
        ),
        ToolDefinition(
            name="database.query",
            description="Return fixture rows for one exact allowlisted demo query.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "const": "SELECT id, name FROM projects",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "name": {"type": "string"},
                            },
                            "required": ["id", "name"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["rows"],
                "additionalProperties": False,
            },
            base_risk_level=RiskLevel.LOW,
            adapter_type="mock_database",
            adapter_config={},
        ),
    ]


async def seed() -> None:
    """Register missing mock tools through the application service."""

    service = ToolService(partial(SqlAlchemyUnitOfWork, get_session_factory()))
    for tool in seed_tools():
        try:
            await service.register(tool)
        except ToolVersionAlreadyExists:
            continue
    await dispose_engine()


def main() -> None:
    """Run the asynchronous seed command."""

    asyncio.run(seed())


if __name__ == "__main__":
    main()
