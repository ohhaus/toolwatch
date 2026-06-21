"""Sanitized public error mapping."""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from toolwatch.application.errors import ApplicationError
from toolwatch.domain.common import DomainValidationError


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
    body = ErrorResponse(error=ErrorBody(code=code, message=message, correlation_id=str(uuid4())))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _message_for(code: str) -> str:
    messages = {
        "tool_version_already_exists": "The tool version is already registered.",
        "tool_not_found": "The tool was not found.",
        "session_not_found": "The session was not found.",
        "invalid_session_transition": "The session transition is not allowed.",
    }
    return messages.get(code, "The request could not be completed.")
