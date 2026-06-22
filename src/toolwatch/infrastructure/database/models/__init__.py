"""Import persistence models so SQLAlchemy metadata is complete."""

from toolwatch.infrastructure.database.models.agents import AgentModel
from toolwatch.infrastructure.database.models.security import (
    AuditEventModel,
    BlockingRuleModel,
    RiskFlagModel,
)
from toolwatch.infrastructure.database.models.sessions import AgentSessionModel
from toolwatch.infrastructure.database.models.tool_calls import (
    ToolCallModel,
    ToolResultMetadataModel,
)
from toolwatch.infrastructure.database.models.tools import ToolDefinitionModel

__all__ = [
    "AgentModel",
    "AgentSessionModel",
    "AuditEventModel",
    "BlockingRuleModel",
    "RiskFlagModel",
    "ToolCallModel",
    "ToolDefinitionModel",
    "ToolResultMetadataModel",
]
