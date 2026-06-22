"""Deterministic redaction, risk, rule, audit, execution, and replay pipeline."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
    ToolCallBlocked,
    ToolCallNotFound,
    ToolDisabled,
    ToolExecutionFailed,
    ToolNotFound,
    ToolPayloadTooDeep,
    ToolResultPayloadTooDeep,
    ToolResultTooLarge,
    ToolTimeout,
)
from toolwatch.application.ports import Page, RepositoryConflict, UnitOfWork, UnitOfWorkFactory
from toolwatch.config import Settings
from toolwatch.domain.common import JSONObject, JSONValue
from toolwatch.domain.security import (
    AuditEvent,
    AuditEventType,
    RiskFlag,
    RuleAction,
)
from toolwatch.domain.sessions import SessionStatus
from toolwatch.domain.tool_calls import (
    AdapterExecutionError,
    ToolAdapterRegistry,
    ToolCall,
    ToolCallDecision,
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
from toolwatch.security.redaction import DeterministicRedactor, RedactionLimitExceeded
from toolwatch.security.risk import classify_input, classify_output
from toolwatch.security.rules import evaluate_rules
from toolwatch.security.schema import validate_instance
from toolwatch.telemetry import TelemetryRuntime
from toolwatch.telemetry.context import current_correlation
from toolwatch.telemetry.metrics import Metrics
from toolwatch.telemetry.tracing import Tracing

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
    """Sanitized terminal response, including persistent replay data."""

    call: ToolCall
    tool: ToolDefinition
    result: JSONValue | None
    flags: tuple[RiskFlag, ...] = ()
    matched_rules: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallDetail:
    """Sanitized persisted call read model."""

    call: ToolCall
    tool: ToolDefinition
    result: JSONValue | None
    flags: tuple[RiskFlag, ...]
    matched_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ToolCallFilters:
    """Bounded deterministic call-list filters."""

    status: ToolCallStatus | None = None
    limit: int = 50
    offset: int = 0


class TerminalResponseCache:
    """Compatibility shim; PostgreSQL is the terminal replay authority."""

    def get(self, idempotency_key: UUID) -> ToolCallExecution | None:
        """Always defer replay to persisted sanitized state."""

        del idempotency_key
        return None

    def put(self, idempotency_key: UUID, response: ToolCallExecution) -> None:
        """Retain no process-local payload state."""

        del idempotency_key, response


class ToolCallService:
    """Execute trusted adapters through the Security Pipeline v1 boundary."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        adapters: ToolAdapterRegistry,
        settings: Settings,
        response_cache: TerminalResponseCache | None = None,
        telemetry: TelemetryRuntime | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._adapters = adapters
        self._settings = settings
        self._response_cache = response_cache
        self._telemetry = telemetry or TelemetryRuntime(
            tracing=Tracing(None),
            metrics=Metrics(enabled=False),
        )
        self._redactor = DeterministicRedactor(
            replacement=settings.redaction_replacement,
            fingerprint_key=(
                settings.redaction_fingerprint_key
                if settings.redaction_fingerprints_enabled
                else None
            ),
            include_fingerprint_prefix=settings.redaction_include_fingerprint_prefix,
            max_depth=settings.max_redaction_depth,
            max_nodes=settings.max_redaction_nodes,
            additional_patterns=settings.redaction_additional_patterns,
        )

    async def execute(self, request: ExecuteToolCall) -> ToolCallExecution:
        """Execute or persistently replay one validated trusted call."""

        with self._telemetry.tracing.span("toolwatch.execute_tool_call") as root_span:
            return await self._execute(request, root_span)

    async def _execute(self, request: ExecuteToolCall, root_span: object) -> ToolCallExecution:
        del root_span
        with self._telemetry.tracing.span("toolwatch.validate_arguments") as payload_span:
            try:
                arguments, canonical_arguments = self._canonical_arguments(request.arguments)
            except Exception as exc:
                payload_span.set_error(getattr(exc, "code", "invalid_arguments"), type(exc))
                self._telemetry.metrics.counter(
                    "toolwatch_validation_failures_total",
                    {"error_code": getattr(exc, "code", "invalid_arguments")},
                )
                raise
        canonical_request_hash = request_hash(
            session_id=request.session_id,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            canonical_arguments=canonical_arguments.encoded,
        )
        with self._telemetry.tracing.span("toolwatch.replay_tool_call") as replay_span:
            with self._telemetry.metrics.timer(
                "toolwatch_db_operation_duration_seconds",
                {"operation": "lookup_replay"},
            ):
                existing = await self._existing_outcome(
                    request.idempotency_key,
                    canonical_request_hash,
                )
        if existing is not None:
            replay_span.set_attributes(
                {
                    "toolwatch.replayed": True,
                    "toolwatch.call.status": existing.call.status.value,
                }
            )
            self._record_terminal_metrics(existing, replayed=True)
            return existing

        with self._telemetry.metrics.timer(
            "toolwatch_db_operation_duration_seconds",
            {"operation": "create_received"},
        ):
            call, tool = await self._create_received(
                request,
                arguments_hash=canonical_arguments.sha256,
                canonical_request_hash=canonical_request_hash,
            )
        self._log("tool_call_received", call, tool)
        validating = await self._transition(
            call,
            ToolCallStatus.VALIDATING,
            audit_type=None,
        )

        with self._telemetry.tracing.span("toolwatch.validate_arguments") as validation_span:
            validation_issues = validate_instance(tool.input_schema, arguments)
            validation_span.set_attributes(
                {
                    "validation.valid": not validation_issues,
                    "validation.error_count": len(validation_issues),
                }
            )
        if validation_issues:
            await self._reject(validating, tool, "invalid_tool_arguments")
            self._telemetry.metrics.counter(
                "toolwatch_validation_failures_total",
                {"error_code": "invalid_tool_arguments"},
            )
            raise InvalidToolArguments

        with self._telemetry.tracing.span("toolwatch.redact_arguments") as redaction_span:
            try:
                redacted_arguments = self._redactor.redact(arguments)
            except RedactionLimitExceeded:
                redaction_span.set_error("tool_payload_too_deep", RedactionLimitExceeded)
                await self._reject(validating, tool, "tool_payload_too_deep")
                raise ToolPayloadTooDeep from None
            redaction_span.set_attributes(
                {"redaction.finding_count": len(redacted_arguments.findings)}
            )
            self._telemetry.metrics.counter(
                "toolwatch_redactions_total",
                amount=len(redacted_arguments.findings),
            )
        if not isinstance(redacted_arguments.value, dict):
            await self._reject(validating, tool, "invalid_tool_arguments")
            raise InvalidToolArguments

        with self._telemetry.tracing.span("toolwatch.classify_risk") as risk_span:
            input_assessment = classify_input(tool, arguments, redacted_arguments.findings)
            risk_span.set_attributes({"risk.level": input_assessment.level.value})
        with self._telemetry.tracing.span("toolwatch.evaluate_rules") as rules_span:
            evaluating, input_flags, input_rule_names = await self._evaluate_input(
                validating,
                tool,
                redacted_arguments=redacted_arguments.value,
                redaction_count=len(redacted_arguments.findings),
                risk_level=input_assessment.level,
                flags=list(input_assessment.flags),
            )
            rules_span.set_attributes(
                {
                    "rule.match_count": len(input_rule_names),
                    "decision": evaluating.decision.value,
                }
            )
        for flag in input_flags:
            self._telemetry.metrics.counter(
                "toolwatch_risk_flags_total",
                {"flag_code": flag.code.value, "risk_level": flag.severity.value},
            )
        if input_rule_names:
            self._telemetry.metrics.counter(
                "toolwatch_rule_matches_total",
                {"rule_action": evaluating.decision.value},
                len(input_rule_names),
            )
        if evaluating.status is ToolCallStatus.BLOCKED:
            outcome = ToolCallExecution(
                call=evaluating,
                tool=tool,
                result=None,
                flags=tuple(input_flags),
                matched_rules=tuple(input_rule_names),
            )
            self._log("tool_call_blocked", evaluating, tool)
            self._record_terminal_metrics(outcome)
            raise ToolCallBlocked(outcome)

        executing = await self._transition(
            evaluating,
            ToolCallStatus.EXECUTING,
            decision=evaluating.decision,
            audit_type=AuditEventType.TOOL_CALL_STARTED,
        )
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
        with self._telemetry.tracing.span(
            f"execute_tool {tool.name}",
            attributes=self._tool_span_attributes(executing, tool, replayed=False),
        ) as execute_span:
            try:
                raw_result = await asyncio.wait_for(
                    adapter.execute(arguments=arguments, context=context),
                    timeout=self._timeout_for(tool),
                )
                execute_span.set_attributes({"toolwatch.call.status": "succeeded"})
            except TimeoutError:
                execute_span.set_error("tool_timeout", TimeoutError)
                execute_span.set_attributes({"toolwatch.call.status": "timed_out"})
                terminal = await self._transition(
                    executing,
                    ToolCallStatus.TIMED_OUT,
                    error_code="tool_timeout",
                    error_message_safe="The trusted tool adapter timed out.",
                    audit_type=AuditEventType.TOOL_CALL_TIMED_OUT,
                )
                self._log("tool_call_timed_out", terminal, tool)
                self._record_terminal_metrics(
                    ToolCallExecution(call=terminal, tool=tool, result=None)
                )
                raise ToolTimeout from None
            except AdapterExecutionError as exc:
                execute_span.set_error(exc.code, type(exc))
                execute_span.set_attributes({"toolwatch.call.status": "failed"})
                public_error = (
                    MockQueryNotSupported
                    if exc.code == "mock_query_not_supported"
                    else ToolExecutionFailed
                )
                await self._fail(executing, tool, exc.code)
                raise public_error from None
            except Exception as exc:
                execute_span.set_error("tool_execution_failed", type(exc))
                execute_span.set_attributes({"toolwatch.call.status": "failed"})
                await self._fail(executing, tool, "tool_execution_failed")
                raise ToolExecutionFailed from None

        with self._telemetry.tracing.span("toolwatch.validate_result") as result_validation_span:
            canonical_result = await self._canonical_result(raw_result, executing, tool)
            schema_valid = tool.output_schema is None or not validate_instance(
                tool.output_schema, canonical_result.value
            )
            result_validation_span.set_attributes(
                {
                    "validation.valid": schema_valid,
                    "validation.error_count": 0 if schema_valid else 1,
                }
            )
            if not schema_valid:
                result_validation_span.set_error("invalid_tool_result")
        with self._telemetry.tracing.span("toolwatch.redact_result") as result_redaction_span:
            try:
                redacted_result = self._redactor.redact(canonical_result.value)
            except RedactionLimitExceeded:
                result_redaction_span.set_error("tool_payload_too_deep", RedactionLimitExceeded)
                await self._fail(executing, tool, "tool_payload_too_deep")
                raise ToolResultPayloadTooDeep from None
            result_redaction_span.set_attributes(
                {"redaction.finding_count": len(redacted_result.findings)}
            )
            self._telemetry.metrics.counter(
                "toolwatch_redactions_total",
                amount=len(redacted_result.findings),
            )
        sanitized_result = self._canonical_sanitized_result(redacted_result.value)
        output_assessment = classify_output(
            sanitized_result.value,
            redacted_result.findings,
            executing.risk_level,
        )
        output_flags = list(output_assessment.flags)
        if not schema_valid:
            decision = ToolCallDecision.FLAG if output_flags else executing.decision
            metadata = ToolResultMetadata(
                tool_call_id=executing.id,
                redacted_payload=None,
                payload_hash=canonical_result.sha256,
                content_type="application/json",
                size_bytes=canonical_result.size_bytes,
                schema_valid=False,
            )
            terminal = await self._finalize(
                executing,
                ToolCallStatus.FAILED,
                metadata=metadata,
                flags=output_flags,
                matched_rule_ids=executing.matched_rule_ids,
                decision=decision,
                risk_level=output_assessment.level,
                redaction_count=len(redacted_result.findings),
                error_code="invalid_tool_result",
                error_message_safe="The trusted adapter returned an invalid result.",
            )
            self._log("tool_call_failed", terminal, tool)
            self._record_terminal_metrics(ToolCallExecution(call=terminal, tool=tool, result=None))
            raise InvalidToolResult

        async with self._uow_factory() as uow:
            rules = await uow.rules.list_enabled()
        result_evaluation = evaluate_rules(
            rules,
            tool_name=tool.name,
            risk_level=output_assessment.level,
            flags=output_flags,
            arguments=executing.redacted_arguments,
            result_phase=True,
        )
        for flag in output_flags:
            self._telemetry.metrics.counter(
                "toolwatch_risk_flags_total",
                {"flag_code": flag.code.value, "risk_level": flag.severity.value},
            )
        if result_evaluation.matches:
            self._telemetry.metrics.counter(
                "toolwatch_rule_matches_total",
                {"rule_action": result_evaluation.action.value},
                len(result_evaluation.matches),
            )
        all_flags = [*input_flags, *output_flags]
        decision = executing.decision
        if output_flags or result_evaluation.action is RuleAction.FLAG:
            decision = ToolCallDecision.FLAG
        matched_ids = tuple(
            [*executing.matched_rule_ids, *(match.rule_id for match in result_evaluation.matches)]
        )
        matched_names = tuple(
            [*input_rule_names, *(match.rule_name for match in result_evaluation.matches)]
        )
        metadata = ToolResultMetadata(
            tool_call_id=executing.id,
            redacted_payload=(
                sanitized_result.value if self._settings.store_redacted_results else None
            ),
            payload_hash=canonical_result.sha256,
            content_type="application/json",
            size_bytes=canonical_result.size_bytes,
            schema_valid=True,
            truncated=False,
        )
        with self._telemetry.tracing.span("toolwatch.persist_terminal_result"):
            with self._telemetry.metrics.timer(
                "toolwatch_db_operation_duration_seconds",
                {"operation": "persist_terminal"},
            ):
                terminal = await self._finalize(
                    executing,
                    ToolCallStatus.SUCCEEDED,
                    metadata=metadata,
                    flags=output_flags,
                    matched_rule_ids=matched_ids,
                    decision=decision,
                    risk_level=output_assessment.level,
                    redaction_count=len(redacted_result.findings),
                    matched_rule_names=tuple(
                        match.rule_name for match in result_evaluation.matches
                    ),
                )
        response = ToolCallExecution(
            call=terminal,
            tool=tool,
            result=sanitized_result.value,
            flags=tuple(all_flags),
            matched_rules=matched_names,
        )
        self._log("tool_call_succeeded", terminal, tool)
        self._record_terminal_metrics(response)
        return response

    async def get(self, call_id: UUID) -> ToolCallDetail:
        """Return one sanitized persisted call."""

        async with self._uow_factory() as uow:
            call = await uow.tool_calls.get_by_id(call_id)
            if call is None:
                raise ToolCallNotFound
            tool = await uow.tools.get_by_id(call.tool_definition_id)
            if tool is None:
                raise ToolCallNotFound
            metadata = await uow.tool_results.get_by_tool_call_id(call.id)
            flags = await uow.risk_flags.list_for_tool_call(call.id)
            rule_names = await self._rule_names(uow, call.matched_rule_ids)
        return ToolCallDetail(
            call=call,
            tool=tool,
            result=metadata.redacted_payload if metadata is not None else None,
            flags=tuple(flags),
            matched_rules=rule_names,
        )

    async def list_for_session(
        self,
        session_id: UUID,
        filters: ToolCallFilters,
    ) -> Page[ToolCallDetail]:
        """List one session's calls with sanitized payloads."""

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
                metadata = await uow.tool_results.get_by_tool_call_id(call.id)
                flags = await uow.risk_flags.list_for_tool_call(call.id)
                details.append(
                    ToolCallDetail(
                        call=call,
                        tool=tool,
                        result=metadata.redacted_payload if metadata is not None else None,
                        flags=tuple(flags),
                        matched_rules=await self._rule_names(uow, call.matched_rule_ids),
                    )
                )
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
        except (PayloadTooLarge, PayloadStringTooLong):
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

    def _canonical_sanitized_result(self, result: JSONValue) -> CanonicalPayload:
        try:
            return canonicalize_json(
                result,
                max_bytes=self._settings.max_tool_result_bytes,
                max_depth=self._settings.max_json_depth,
                max_string_length=self._settings.max_string_length,
            )
        except (PayloadTooLarge, PayloadStringTooLong):
            raise ToolResultTooLarge from None
        except PayloadTooDeep:
            raise ToolResultPayloadTooDeep from None

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
            tool = await uow.tools.get_by_id(existing.tool_definition_id)
            if tool is None:
                raise ToolCallNotFound
            flags = tuple(await uow.risk_flags.list_for_tool_call(existing.id))
            matched_rules = await self._rule_names(uow, existing.matched_rule_ids)
            metadata = await uow.tool_results.get_by_tool_call_id(existing.id)
        outcome = ToolCallExecution(
            call=existing,
            tool=tool,
            result=metadata.redacted_payload if metadata is not None else None,
            flags=flags,
            matched_rules=matched_rules,
            replayed=True,
        )
        if existing.status is ToolCallStatus.SUCCEEDED:
            if metadata is None or metadata.truncated:
                raise ExecutionInProgress
            return outcome
        if existing.status is ToolCallStatus.BLOCKED:
            raise ToolCallBlocked(outcome)
        if existing.status.terminal:
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
            tool = await uow.tools.get_by_name_and_version(request.tool_name, request.tool_version)
            if tool is None:
                raise ToolNotFound
            if not tool.enabled:
                raise ToolDisabled
            existing = await uow.tool_calls.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_hash != canonical_request_hash:
                    raise IdempotencyConflict
                raise ExecutionInProgress
            call = ToolCall(
                session_id=session.id,
                tool_definition_id=tool.id,
                parent_call_id=request.parent_call_id,
                sequence_number=await uow.tool_calls.next_sequence_number(session.id),
                arguments_hash=arguments_hash,
                request_hash=canonical_request_hash,
                idempotency_key=request.idempotency_key,
            )
            try:
                call = await uow.tool_calls.create(call)
                await uow.audit_events.create(
                    self._audit(call, tool, AuditEventType.TOOL_CALL_RECEIVED)
                )
                await uow.commit()
                self._telemetry.metrics.counter("toolwatch_audit_events_total")
            except RepositoryConflict as exc:
                if exc.constraint_name == IDEMPOTENCY_CONSTRAINT:
                    raise IdempotencyConflict from None
                raise
        return call, tool

    async def _evaluate_input(
        self,
        call: ToolCall,
        tool: ToolDefinition,
        *,
        redacted_arguments: JSONObject,
        redaction_count: int,
        risk_level: object,
        flags: list[RiskFlag],
    ) -> tuple[ToolCall, list[RiskFlag], list[str]]:
        from toolwatch.domain.tools import RiskLevel

        if not isinstance(risk_level, RiskLevel):
            raise TypeError("risk_level must be RiskLevel")
        async with self._uow_factory() as uow:
            rules = await uow.rules.list_enabled()
            evaluation = evaluate_rules(
                rules,
                tool_name=tool.name,
                risk_level=risk_level,
                flags=flags,
                arguments=redacted_arguments,
            )
            decision = ToolCallDecision.ALLOW
            if flags or evaluation.action is RuleAction.FLAG:
                decision = ToolCallDecision.FLAG
            evaluating = call.transition_to(
                ToolCallStatus.EVALUATING,
                decision=decision,
                risk_level=risk_level,
                matched_rule_ids=tuple(match.rule_id for match in evaluation.matches),
            )
            evaluating = replace(
                evaluating,
                redacted_arguments=(
                    redacted_arguments if self._settings.store_redacted_arguments else {}
                ),
            )
            evaluating = await uow.tool_calls.update(evaluating)
            bound_flags = [flag.for_call(call.id) for flag in flags]
            await uow.risk_flags.create_many(bound_flags)
            events = [
                self._audit(call, tool, AuditEventType.TOOL_CALL_VALIDATED),
                self._audit(
                    evaluating,
                    tool,
                    AuditEventType.REDACTION_APPLIED,
                    {"redaction_count": redaction_count},
                ),
                self._audit(
                    evaluating,
                    tool,
                    AuditEventType.TOOL_CALL_RISK_CLASSIFIED,
                    {
                        "risk_level": risk_level.value,
                        "flag_codes": [flag.code.value for flag in flags],
                    },
                ),
            ]
            if flags or evaluation.action is RuleAction.FLAG:
                events.append(self._audit(evaluating, tool, AuditEventType.TOOL_CALL_FLAGGED))
            for match in evaluation.matches:
                events.append(
                    self._audit(
                        evaluating,
                        tool,
                        AuditEventType.RULE_MATCHED,
                        {"rule_id": str(match.rule_id), "action": match.action.value},
                    )
                )
            if evaluation.action is RuleAction.BLOCK:
                evaluating = evaluating.transition_to(
                    ToolCallStatus.BLOCKED,
                    decision=ToolCallDecision.BLOCK,
                    matched_rule_ids=tuple(match.rule_id for match in evaluation.matches),
                    error_code="tool_call_blocked",
                    error_message_safe="The tool call was blocked by a runtime safety rule.",
                )
                evaluating = await uow.tool_calls.update(evaluating)
                events.append(self._audit(evaluating, tool, AuditEventType.TOOL_CALL_BLOCKED))
            await uow.audit_events.create_many(events)
            await uow.commit()
            self._telemetry.metrics.counter(
                "toolwatch_audit_events_total",
                amount=len(events),
            )
        return evaluating, bound_flags, [match.rule_name for match in evaluation.matches]

    async def _transition(
        self,
        call: ToolCall,
        status: ToolCallStatus,
        *,
        decision: ToolCallDecision | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        audit_type: AuditEventType | None,
    ) -> ToolCall:
        changed = call.transition_to(
            status,
            decision=decision,
            error_code=error_code,
            error_message_safe=error_message_safe,
        )
        async with self._uow_factory() as uow:
            changed = await uow.tool_calls.update(changed)
            if audit_type is not None:
                tool = await uow.tools.get_by_id(changed.tool_definition_id)
                if tool is None:
                    raise ToolCallNotFound
                await uow.audit_events.create(self._audit(changed, tool, audit_type))
            await uow.commit()
            if audit_type is not None:
                self._telemetry.metrics.counter("toolwatch_audit_events_total")
        return changed

    async def _finalize(
        self,
        call: ToolCall,
        status: ToolCallStatus,
        *,
        metadata: ToolResultMetadata,
        flags: list[RiskFlag],
        matched_rule_ids: tuple[UUID, ...],
        decision: ToolCallDecision | None = None,
        risk_level: object | None = None,
        redaction_count: int = 0,
        matched_rule_names: tuple[str, ...] = (),
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> ToolCall:
        from toolwatch.domain.tools import RiskLevel

        next_risk = risk_level if isinstance(risk_level, RiskLevel) else call.risk_level
        terminal = call.transition_to(
            status,
            decision=decision,
            risk_level=next_risk,
            matched_rule_ids=matched_rule_ids,
            error_code=error_code,
            error_message_safe=error_message_safe,
        )
        async with self._uow_factory() as uow:
            await uow.tool_results.create(metadata)
            bound_flags = [flag.for_call(call.id) for flag in flags]
            await uow.risk_flags.create_many(bound_flags)
            terminal = await uow.tool_calls.update(terminal)
            tool = await uow.tools.get_by_id(call.tool_definition_id)
            if tool is None:
                raise ToolCallNotFound
            events: list[AuditEvent] = []
            if redaction_count:
                events.append(
                    self._audit(
                        terminal,
                        tool,
                        AuditEventType.REDACTION_APPLIED,
                        {"redaction_count": redaction_count},
                    )
                )
            for name in matched_rule_names:
                events.append(
                    self._audit(
                        terminal,
                        tool,
                        AuditEventType.RULE_MATCHED,
                        {"rule_name": name, "action": "flag"},
                    )
                )
            if flags or decision is ToolCallDecision.FLAG:
                events.append(self._audit(terminal, tool, AuditEventType.TOOL_CALL_FLAGGED))
            events.append(
                self._audit(
                    terminal,
                    tool,
                    (
                        AuditEventType.TOOL_CALL_COMPLETED
                        if status is ToolCallStatus.SUCCEEDED
                        else AuditEventType.TOOL_CALL_FAILED
                    ),
                )
            )
            await uow.audit_events.create_many(events)
            await uow.commit()
            self._telemetry.metrics.counter(
                "toolwatch_audit_events_total",
                amount=len(events),
            )
        return terminal

    async def _reject(self, call: ToolCall, tool: ToolDefinition, code: str) -> None:
        terminal = await self._transition(
            call,
            ToolCallStatus.REJECTED,
            error_code=code,
            error_message_safe="Tool arguments do not match the registered schema.",
            audit_type=AuditEventType.TOOL_CALL_FAILED,
        )
        self._log("tool_call_rejected", terminal, tool)

    async def _fail(self, call: ToolCall, tool: ToolDefinition, code: str) -> ToolCall:
        terminal = await self._transition(
            call,
            ToolCallStatus.FAILED,
            error_code=code,
            error_message_safe=SAFE_EXECUTION_ERROR,
            audit_type=AuditEventType.TOOL_CALL_FAILED,
        )
        self._log("tool_call_failed", terminal, tool)
        self._record_terminal_metrics(ToolCallExecution(call=terminal, tool=tool, result=None))
        return terminal

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
    async def _rule_names(
        uow: "UnitOfWork",
        rule_ids: tuple[UUID, ...],
    ) -> tuple[str, ...]:
        names: list[str] = []
        for rule_id in rule_ids:
            rule = await uow.rules.get_by_id(rule_id)
            if rule is not None:
                names.append(rule.name)
        return tuple(names)

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
        raise error_types.get(call.error_code or "", ToolExecutionFailed)

    @staticmethod
    def _audit(
        call: ToolCall,
        tool: ToolDefinition,
        event_type: AuditEventType,
        extra: JSONObject | None = None,
    ) -> AuditEvent:
        payload: JSONObject = {
            "tool": tool.name,
            "tool_version": tool.version,
            "status": call.status.value,
            "decision": call.decision.value,
            "risk_level": call.risk_level.value,
        }
        if call.error_code is not None:
            payload["error_code"] = call.error_code
        if extra:
            payload.update(extra)
        return AuditEvent(
            session_id=call.session_id,
            tool_call_id=call.id,
            event_type=event_type,
            payload_redacted=payload,
            trace_id=current_correlation().trace_id,
            correlation_id=current_correlation().correlation_id,
        )

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
                "decision": call.decision.value,
                "risk_level": call.risk_level.value,
                "duration_ms": call.duration_ms,
                "error_code": call.error_code,
            },
        )

    @staticmethod
    def _tool_span_attributes(
        call: ToolCall,
        tool: ToolDefinition,
        *,
        replayed: bool,
    ) -> dict[str, object]:
        return {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool.name,
            "gen_ai.tool.type": "function",
            "toolwatch.tool.version": tool.version,
            "toolwatch.tool.adapter_type": tool.adapter_type,
            "toolwatch.risk.level": call.risk_level.value,
            "toolwatch.decision": call.decision.value,
            "toolwatch.call.status": call.status.value,
            "toolwatch.replayed": replayed,
        }

    def _record_terminal_metrics(
        self,
        execution: ToolCallExecution,
        *,
        replayed: bool = False,
    ) -> None:
        call = execution.call
        tool = execution.tool
        labels = {
            "tool_name": tool.name,
            "tool_version": tool.version,
            "adapter_type": tool.adapter_type,
            "status": call.status.value,
            "decision": call.decision.value,
            "risk_level": call.risk_level.value,
            "replayed": str(replayed or execution.replayed).lower(),
        }
        self._telemetry.metrics.counter("toolwatch_tool_calls_total", labels)
        if call.duration_ms is not None:
            self._telemetry.metrics.histogram(
                "toolwatch_tool_call_duration_seconds",
                call.duration_ms / 1000,
                labels,
            )
        if call.status is ToolCallStatus.BLOCKED:
            self._telemetry.metrics.counter("toolwatch_tool_calls_blocked_total", labels)
        if call.status is ToolCallStatus.TIMED_OUT:
            self._telemetry.metrics.counter("toolwatch_tool_timeouts_total", labels)
        if call.status is ToolCallStatus.FAILED:
            self._telemetry.metrics.counter(
                "toolwatch_tool_calls_failed_total",
                {
                    "tool_name": tool.name,
                    "tool_version": tool.version,
                    "adapter_type": tool.adapter_type,
                    "error_code": call.error_code or "unknown",
                },
            )
        if replayed or execution.replayed:
            self._telemetry.metrics.counter("toolwatch_tool_calls_replayed_total", labels)
