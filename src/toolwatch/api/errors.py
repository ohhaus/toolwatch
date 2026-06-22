"""Sanitized public error mapping."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from toolwatch.application.errors import ApplicationError
from toolwatch.domain.common import DomainValidationError
from toolwatch.telemetry.context import current_correlation


class ErrorBody(BaseModel):
    """Stable machine-readable error body."""

    code: str
    message: str
    correlation_id: str


class ErrorResponse(BaseModel):
    """Public error envelope."""

    error: ErrorBody


class InternalErrorResponse(ErrorResponse):
    """OpenAPI model for sanitized unexpected failures."""


class ValidationErrorResponse(ErrorResponse):
    """OpenAPI model for sanitized request validation failures."""


class NotFoundErrorResponse(ErrorResponse):
    """OpenAPI model for missing resources."""


class ConflictErrorResponse(ErrorResponse):
    """OpenAPI model for conflicting writes or state transitions."""


class BadGatewayErrorResponse(ErrorResponse):
    """OpenAPI model for sanitized adapter failures."""


class GatewayTimeoutErrorResponse(ErrorResponse):
    """OpenAPI model for sanitized adapter timeouts."""


class ForbiddenErrorResponse(ErrorResponse):
    """OpenAPI model for deterministic runtime blocks."""


def register_error_handlers(application: FastAPI) -> None:
    """Register fixed handlers that never expose infrastructure exceptions."""

    application.add_exception_handler(ApplicationError, _application_error)
    application.add_exception_handler(DomainValidationError, _domain_validation_error)
    application.add_exception_handler(RequestValidationError, _request_validation_error)
    application.add_exception_handler(Exception, _internal_error)


def error_responses(
    *,
    not_found: bool = False,
    conflict: bool = False,
    bad_gateway: bool = False,
    gateway_timeout: bool = False,
    forbidden: bool = False,
) -> dict[int | str, dict[str, Any]]:
    """Build reusable OpenAPI response declarations."""

    responses: dict[int | str, dict[str, Any]] = {
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ValidationErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": InternalErrorResponse},
    }
    if not_found:
        responses[status.HTTP_404_NOT_FOUND] = {"model": NotFoundErrorResponse}
    if conflict:
        responses[status.HTTP_409_CONFLICT] = {"model": ConflictErrorResponse}
    if bad_gateway:
        responses[status.HTTP_502_BAD_GATEWAY] = {"model": BadGatewayErrorResponse}
    if gateway_timeout:
        responses[status.HTTP_504_GATEWAY_TIMEOUT] = {"model": GatewayTimeoutErrorResponse}
    if forbidden:
        responses[status.HTTP_403_FORBIDDEN] = {"model": ForbiddenErrorResponse}
    return responses


async def _application_error(_: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, ApplicationError) else ApplicationError()
    return _response(error.status_code, error.code, _message_for(error.code))


async def _domain_validation_error(_: Request, __: Exception) -> JSONResponse:
    return _response(422, "invalid_request", "The request violates a domain constraint.")


async def _request_validation_error(_: Request, __: Exception) -> JSONResponse:
    return _response(422, "invalid_request", "The request is invalid.")


async def _internal_error(_: Request, __: Exception) -> JSONResponse:
    return _response(500, "internal_error", "An internal error occurred.")


def _response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            correlation_id=current_correlation().correlation_id,
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _message_for(code: str) -> str:
    messages = {
        "tool_version_already_exists": "The tool version is already registered.",
        "tool_not_found": "The tool was not found.",
        "session_not_found": "The session was not found.",
        "session_not_active": "The session is not active.",
        "invalid_session_transition": "The session transition is not allowed.",
        "tool_disabled": "The tool is disabled.",
        "tool_call_not_found": "The tool call was not found.",
        "invalid_tool_arguments": "Tool arguments do not match the registered schema.",
        "adapter_not_configured": "The trusted adapter is not configured.",
        "tool_execution_failed": "The trusted tool adapter failed.",
        "mock_query_not_supported": "The mock database query is not supported.",
        "tool_timeout": "The trusted tool adapter timed out.",
        "invalid_tool_result": "The trusted tool adapter returned an invalid result.",
        "tool_arguments_too_large": "Tool arguments exceed the configured size limit.",
        "tool_result_too_large": "The tool result exceeds the configured size limit.",
        "tool_payload_too_deep": "The tool payload exceeds the configured depth limit.",
        "idempotency_conflict": "The idempotency key was reused for another request.",
        "execution_in_progress": "An execution with this idempotency key is in progress.",
        "tool_call_blocked": "The tool call was blocked by a runtime safety rule.",
        "blocking_rule_not_found": "The blocking rule was not found.",
        "blocking_rule_already_exists": "The blocking rule name is already in use.",
    }
    return messages.get(code, "The request could not be completed.")
