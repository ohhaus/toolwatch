"""Tool-call execution domain model."""

from toolwatch.domain.tool_calls.adapters import (
    AdapterExecutionError,
    ToolAdapter,
    ToolAdapterRegistry,
    ToolExecutionContext,
)
from toolwatch.domain.tool_calls.models import (
    AdapterExecutionResult,
    InvalidToolCallTransition,
    ToolCall,
    ToolCallDecision,
    ToolCallStatus,
    ToolResultMetadata,
)

__all__ = [
    "AdapterExecutionResult",
    "AdapterExecutionError",
    "InvalidToolCallTransition",
    "ToolCall",
    "ToolCallDecision",
    "ToolCallStatus",
    "ToolAdapter",
    "ToolAdapterRegistry",
    "ToolExecutionContext",
    "ToolResultMetadata",
]
