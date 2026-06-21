"""Framework-independent trusted adapter contracts."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from toolwatch.domain.common import JSONObject, JSONValue


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Safe server-controlled context supplied to a trusted adapter."""

    call_id: UUID
    session_id: UUID
    tool_name: str
    tool_version: str
    adapter_config: JSONObject


class ToolAdapter(Protocol):
    """Execute one already-validated tool call."""

    async def execute(
        self,
        *,
        arguments: Mapping[str, JSONValue],
        context: ToolExecutionContext,
    ) -> JSONValue: ...


class ToolAdapterRegistry(Protocol):
    """Resolve only server-controlled adapter implementations."""

    def get(self, adapter_type: str) -> ToolAdapter | None: ...


class AdapterExecutionError(Exception):
    """Stable adapter failure whose message is never exposed publicly."""

    def __init__(self, code: str = "tool_execution_failed") -> None:
        super().__init__(code)
        self.code = code
