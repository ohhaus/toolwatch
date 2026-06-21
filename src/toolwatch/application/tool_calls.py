"""Tool-call execution orchestration with payload-free persistence."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from toolwatch.application.errors import (
    AdapterNotConfigured,
    ExecutionInProgress,
    IdempotencyConflict,
    InvalidToolArguments,
    InvalidToolResult,
    MockQueryNotSupported,
    SessionNotActive,
    SessionNotFound,
    ToolArgumentsTooLarge,
    ToolCallNotFound,
    ToolDisabled,
    ToolExecutionFailed,
    ToolNotFound,
    ToolPayloadTooDeep,
    ToolResultPayloadTooDeep,
    ToolResultTooLarge,
    ToolTimeout,
)
from toolwatch.application.ports import Page, RepositoryConflict, UnitOfWorkFactory
from toolwatch.config import Settings
from toolwatch.domain.common import JSONObject, JSONValue
from toolwatch.domain.sessions import SessionStatus
from toolwatch.domain.tool_calls import (
    AdapterExecutionError,
    ToolAdapterRegistry,
    ToolCall,
    ToolCallStatus,
    ToolExecutionContext,
    ToolResultMetadata,
)
from toolwatch.domain.tools import ToolDefinition
from toolwatch.security.payloads import (
    CanonicalPayload,
    PayloadStringTooLong,
    PayloadTooDeep,
    PayloadTooLarge,
    canonicalize_json,
    canonicalize_object,
    request_hash,
)
from toolwatch.security.schema import validate_instance

logger = logging.getLogger("toolwatch.tool_calls")
IDEMPOTENCY_CONSTRAINT = "uq_tool_calls_idempotency_key"
SAFE_EXECUTION_ERROR = "The trusted tool adapter could not complete the call."


@dataclass(frozen=True, slots=True)
class ExecuteToolCall:
    """Validated API input for one execution attempt."""

    session_id: UUID
    tool_name: str
    tool_version: str
    arguments: Mapping[str, object]
    idempotency_key: UUID
    parent_call_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ToolCallExecution:
    """Direct response containing transient validated output."""

    call: ToolCall
    tool: ToolDefinition
    result: JSONValue
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallDetail:
    """Payload-free read model."""

    call: ToolCall
    tool: ToolDefinition


@dataclass(frozen=True, slots=True)
class ToolCallFilters:
    """Bounded deterministic call-list filters."""

    status: ToolCallStatus | None = None
    limit: int = 50
    offset: int = 0


class TerminalResponseCache:
    """Process-local replay cache required while result persistence is forbidden."""

    def __init__(self) -> None:
        self._items: dict[UUID, ToolCallExecution] = {}

    def get(self, idempotency_key: UUID) -> ToolCallExecution | None:
        """Return a terminal response retained by this process."""

        return self._items.get(idempotency_key)

    def put(self, idempotency_key: UUID, response: ToolCallExecution) -> None:
        """Retain one validated terminal response without logging it."""

        self._items[idempotency_key] = response


class ToolCallService:
    """Execute trusted adapters while keeping raw payloads out of persistence."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        adapters: ToolAdapterRegistry,
        settings: Settings,
        response_cache: TerminalResponseCache,
    ) -> None:
        self._uow_factory = uow_factory
        self._adapters = adapters
        self._settings = settings
        self._response_cache = response_cache

    async def execute(self, request: ExecuteToolCall) -> ToolCallExecution:
        """Execute a validated trusted call with short database transactions."""

        arguments, canonical_arguments = self._canonical_arguments(request.arguments)
        canonical_request_hash = request_hash(
            session_id=request.session_id,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            canonical_arguments=canonical_arguments.encoded,
        )
        existing = await self._existing_outcome(request.idempotency_key, canonical_request_hash)
        if existing is not None:
            return existing

        call, tool = await self._create_received(
            request,
            arguments_hash=canonical_arguments.sha256,
            canonical_request_hash=canonical_request_hash,
        )
        self._log("tool_call_received", call, tool)
        validating = await self._transition(call, ToolCallStatus.VALIDATING)

        if validate_instance(tool.input_schema, arguments):
            await self._reject(validating, tool, "invalid_tool_arguments")
            raise InvalidToolArguments

        executing = await self._transition(validating, ToolCallStatus.EXECUTING)
        self._log("tool_call_started", executing, tool)
        adapter = self._adapters.get(tool.adapter_type)
        if adapter is None:
            await self._fail(executing, tool, "adapter_not_configured")
            raise AdapterNotConfigured

        context = ToolExecutionContext(
            call_id=executing.id,
            session_id=executing.session_id,
            tool_name=tool.name,
            tool_version=tool.version,
            adapter_config=tool.adapter_config,
        )
        timeout = self._timeout_for(tool)
        try:
            raw_result = await asyncio.wait_for(
                adapter.execute(arguments=arguments, context=context),
                timeout=timeout,
            )
        except TimeoutError:
            terminal = await self._transition(
                executing,
                ToolCallStatus.TIMED_OUT,
                error_code="tool_timeout",
                error_message_safe="The trusted tool adapter timed out.",
            )
            self._log("tool_call_timed_out", terminal, tool)
            raise ToolTimeout from None
        except AdapterExecutionError as exc:
            public_error = (
                MockQueryNotSupported
                if exc.code == "mock_query_not_supported"
                else ToolExecutionFailed
            )
            await self._fail(executing, tool, exc.code)
            raise public_error from None
        except Exception:
            await self._fail(executing, tool, "tool_execution_failed")
            raise ToolExecutionFailed from None

        canonical_result = await self._canonical_result(raw_result, executing, tool)
        schema_valid = True
        if tool.output_schema is not None:
            schema_valid = not validate_instance(tool.output_schema, canonical_result.value)

        metadata = ToolResultMetadata(
            tool_call_id=executing.id,
            payload_hash=canonical_result.sha256,
            content_type="application/json",
            size_bytes=canonical_result.size_bytes,
            schema_valid=schema_valid,
        )
        if not schema_valid:
            terminal = await self._finalize(
                executing,
                ToolCallStatus.FAILED,
                metadata=metadata,
                error_code="invalid_tool_result",
                error_message_safe="The trusted adapter returned an invalid result.",
            )
            self._log("tool_call_failed", terminal, tool)
            raise InvalidToolResult

        terminal = await self._finalize(
            executing,
            ToolCallStatus.SUCCEEDED,
            metadata=metadata,
        )
        response = ToolCallExecution(call=terminal, tool=tool, result=canonical_result.value)
        self._response_cache.put(request.idempotency_key, response)
        self._log("tool_call_succeeded", terminal, tool)
        return response

    async def get(self, call_id: UUID) -> ToolCallDetail:
        """Return a payload-free call detail."""

        async with self._uow_factory() as uow:
            call = await uow.tool_calls.get_by_id(call_id)
            if call is None:
                raise ToolCallNotFound
            tool = await uow.tools.get_by_id(call.tool_definition_id)
            if tool is None:
                raise ToolCallNotFound
        return ToolCallDetail(call=call, tool=tool)

    async def list_for_session(
        self,
        session_id: UUID,
        filters: ToolCallFilters,
    ) -> Page[ToolCallDetail]:
        """List one session's calls by sequence number without payloads."""

        async with self._uow_factory() as uow:
            session = await uow.sessions.get_by_id(session_id)
            if session is None:
                raise SessionNotFound
            page = await uow.tool_calls.list(
                session_id=session_id,
                status=filters.status,
                limit=filters.limit,
                offset=filters.offset,
            )
            details: list[ToolCallDetail] = []
            for call in page.items:
                tool = await uow.tools.get_by_id(call.tool_definition_id)
                if tool is None:
                    raise ToolCallNotFound
                details.append(ToolCallDetail(call=call, tool=tool))
        return Page(details, page.total, page.limit, page.offset)

    def _canonical_arguments(
        self,
        arguments: Mapping[str, object],
    ) -> tuple[JSONObject, CanonicalPayload]:
        try:
            return canonicalize_object(
                arguments,
                max_bytes=self._settings.max_tool_arguments_bytes,
                max_depth=self._settings.max_json_depth,
                max_string_length=self._settings.max_string_length,
            )
        except PayloadTooDeep:
            raise ToolPayloadTooDeep from None
        except PayloadTooLarge:
            raise ToolArgumentsTooLarge from None
        except PayloadStringTooLong:
            raise ToolArgumentsTooLarge from None

    async def _canonical_result(
        self,
        result: object,
        call: ToolCall,
        tool: ToolDefinition,
    ) -> CanonicalPayload:
        try:
            return canonicalize_json(
                result,
                max_bytes=self._settings.max_tool_result_bytes,
                max_depth=self._settings.max_json_depth,
                max_string_length=self._settings.max_string_length,
            )
        except PayloadTooDeep:
            await self._fail(call, tool, "tool_payload_too_deep")
            raise ToolResultPayloadTooDeep from None
        except (PayloadTooLarge, PayloadStringTooLong):
            await self._fail(call, tool, "tool_result_too_large")
            raise ToolResultTooLarge from None
        except ValueError:
            await self._fail(call, tool, "invalid_tool_result")
            raise InvalidToolResult from None

    async def _existing_outcome(
        self,
        key: UUID,
        canonical_request_hash: str,
    ) -> ToolCallExecution | None:
        async with self._uow_factory() as uow:
            existing = await uow.tool_calls.get_by_idempotency_key(key)
        if existing is None:
            return None
        if existing.request_hash != canonical_request_hash:
            raise IdempotencyConflict
        cached = self._response_cache.get(key)
        if cached is not None:
            return ToolCallExecution(
                call=cached.call,
                tool=cached.tool,
                result=cached.result,
                replayed=True,
            )
        if existing.status.terminal and existing.status is not ToolCallStatus.SUCCEEDED:
            self._raise_terminal_error(existing)
        raise ExecutionInProgress

    async def _create_received(
        self,
        request: ExecuteToolCall,
        *,
        arguments_hash: str,
        canonical_request_hash: str,
    ) -> tuple[ToolCall, ToolDefinition]:
        async with self._uow_factory() as uow:
            session = await uow.sessions.get_by_id(request.session_id, for_update=True)
            if session is None:
                raise SessionNotFound
            if session.status is not SessionStatus.ACTIVE:
                raise SessionNotActive
            tool = await uow.tools.get_by_name_and_version(
                request.tool_name,
                request.tool_version,
            )
            if tool is None:
                raise ToolNotFound
            if not tool.enabled:
                raise ToolDisabled
            existing = await uow.tool_calls.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_hash != canonical_request_hash:
                    raise IdempotencyConflict
                raise ExecutionInProgress
            sequence_number = await uow.tool_calls.next_sequence_number(session.id)
            call = ToolCall(
                session_id=session.id,
                tool_definition_id=tool.id,
                parent_call_id=request.parent_call_id,
                sequence_number=sequence_number,
                arguments_hash=arguments_hash,
                request_hash=canonical_request_hash,
                idempotency_key=request.idempotency_key,
            )
            try:
                call = await uow.tool_calls.create(call)
                await uow.commit()
            except RepositoryConflict as exc:
                if exc.constraint_name == IDEMPOTENCY_CONSTRAINT:
                    raise IdempotencyConflict from None
                raise
        return call, tool

    async def _transition(
        self,
        call: ToolCall,
        status: ToolCallStatus,
        *,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> ToolCall:
        changed = call.transition_to(
            status,
            error_code=error_code,
            error_message_safe=error_message_safe,
        )
        async with self._uow_factory() as uow:
            changed = await uow.tool_calls.update(changed)
            await uow.commit()
        return changed

    async def _finalize(
        self,
        call: ToolCall,
        status: ToolCallStatus,
        *,
        metadata: ToolResultMetadata,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> ToolCall:
        terminal = call.transition_to(
            status,
            error_code=error_code,
            error_message_safe=error_message_safe,
        )
        async with self._uow_factory() as uow:
            await uow.tool_results.create(metadata)
            terminal = await uow.tool_calls.update(terminal)
            await uow.commit()
        return terminal

    async def _reject(self, call: ToolCall, tool: ToolDefinition, code: str) -> None:
        terminal = await self._transition(
            call,
            ToolCallStatus.REJECTED,
            error_code=code,
            error_message_safe="Tool arguments do not match the registered schema.",
        )
        self._log("tool_call_rejected", terminal, tool)

    async def _fail(self, call: ToolCall, tool: ToolDefinition, code: str) -> None:
        terminal = await self._transition(
            call,
            ToolCallStatus.FAILED,
            error_code=code,
            error_message_safe=SAFE_EXECUTION_ERROR,
        )
        self._log("tool_call_failed", terminal, tool)

    def _timeout_for(self, tool: ToolDefinition) -> float:
        configured = tool.adapter_config.get("timeout_seconds")
        if (
            isinstance(configured, int | float)
            and not isinstance(configured, bool)
            and configured > 0
        ):
            return min(float(configured), self._settings.max_tool_timeout_seconds)
        return min(
            self._settings.default_tool_timeout_seconds,
            self._settings.max_tool_timeout_seconds,
        )

    @staticmethod
    def _raise_terminal_error(call: ToolCall) -> None:
        error_types = {
            "invalid_tool_arguments": InvalidToolArguments,
            "adapter_not_configured": AdapterNotConfigured,
            "tool_execution_failed": ToolExecutionFailed,
            "mock_query_not_supported": MockQueryNotSupported,
            "tool_timeout": ToolTimeout,
            "invalid_tool_result": InvalidToolResult,
            "tool_result_too_large": ToolResultTooLarge,
            "tool_payload_too_deep": ToolResultPayloadTooDeep,
        }
        error_type = error_types.get(call.error_code or "", ToolExecutionFailed)
        raise error_type

    @staticmethod
    def _log(event: str, call: ToolCall, tool: ToolDefinition) -> None:
        logger.info(
            event,
            extra={
                "call_id": str(call.id),
                "session_id": str(call.session_id),
                "tool_name": tool.name,
                "tool_version": tool.version,
                "status": call.status.value,
                "duration_ms": call.duration_ms,
                "error_code": call.error_code,
            },
        )
