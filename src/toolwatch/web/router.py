"""Server-rendered dashboard router under the configurable UI prefix."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from toolwatch.api.dependencies import get_uow_factory
from toolwatch.application.errors import (
    SessionNotFound,
    ToolCallNotFound,
)
from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.application.queries import DashboardQueryService
from toolwatch.config import Settings, get_settings
from toolwatch.domain.security import AuditEventType
from toolwatch.telemetry.context import current_correlation
from toolwatch.web import presenters
from toolwatch.web.dependencies import STATIC_DIRNAME, get_template_environment
from toolwatch.web.security import security_headers

UowDependency = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]
StatusQuery = Annotated[str | None, Query(alias="status")]
StringQuery = Annotated[str | None, Query()]
OptionalIntQuery = Annotated[int | None, Query(ge=1)]
OffsetQuery = Annotated[int, Query(ge=0)]


_ROUTE_TEMPLATES: dict[str, str] = {
    "dashboard_home": "",
    "dashboard_recent_sessions": "/recent-sessions",
    "sessions_list": "/sessions",
    "sessions_table": "/sessions/table",
    "session_detail": "/sessions/{session_id}",
    "tool_call_detail": "/tool-calls/{call_id}",
    "rules_list": "/rules",
    "audit_list": "/audit-events",
    "attacks_index": "/attacks",
    "attack_detail": "/attacks/{scenario_id}",
    "attack_run": "/attacks/{scenario_id}/run",
}


def create_dashboard_router(settings: Settings) -> APIRouter:
    """Build the dashboard router rooted at the configured UI prefix."""

    if not settings.dashboard_enabled:
        raise RuntimeError("dashboard router built while dashboard_enabled is false")

    router = APIRouter()
    prefix = settings.dashboard_prefix.rstrip("/") or "/ui"

    helpers = _TemplateHelpers(prefix=prefix, settings=settings)

    @router.get(prefix, response_class=HTMLResponse, name="dashboard_home")
    async def dashboard_home(uow_factory: UowDependency) -> HTMLResponse:
        service = DashboardQueryService(uow_factory)
        counts = await service.summary()
        recent_sessions_data = await service.recent_sessions(limit=5)
        recent_high_risk = await service.recent_high_risk_calls(limit=5)
        summary = presenters.dashboard_summary(
            counts,
            recent_sessions=recent_sessions_data,
            recent_high_risk=recent_high_risk,
        )
        sessions_items = summary.recent_sessions
        pagination = presenters.pagination_view(
            limit=len(sessions_items) or 1,
            offset=0,
            total=len(sessions_items),
        )
        return helpers.render(
            "dashboard.html",
            summary=summary,
            sessions=sessions_items,
            pagination=pagination,
        )

    @router.get(
        f"{prefix}/recent-sessions",
        response_class=HTMLResponse,
        name="dashboard_recent_sessions",
    )
    async def dashboard_recent_sessions_fragment(
        uow_factory: UowDependency,
    ) -> HTMLResponse:
        service = DashboardQueryService(uow_factory)
        recent = await service.recent_sessions(limit=5)
        sessions = tuple(presenters.session_list_item(item) for item in recent)
        pagination = presenters.pagination_view(
            limit=len(sessions) or 1,
            offset=0,
            total=len(sessions),
        )
        return helpers.render_fragment(
            "sessions/_table.html",
            sessions=sessions,
            pagination=pagination,
        )

    @router.get(f"{prefix}/sessions", response_class=HTMLResponse, name="sessions_list")
    async def sessions_list(
        uow_factory: UowDependency,
        session_status: StatusQuery = None,
        agent_id: StringQuery = None,
        limit: OptionalIntQuery = None,
        offset: OffsetQuery = 0,
    ) -> HTMLResponse:
        normalized_limit = helpers.page_limit(limit)
        parsed_agent = _parse_uuid(agent_id)
        normalized_status = _parse_session_status(session_status)
        service = DashboardQueryService(uow_factory)
        page = await service.list_sessions(
            agent_id=parsed_agent,
            status=normalized_status,
            limit=normalized_limit,
            offset=offset,
        )
        sessions = tuple(presenters.session_list_item(item) for item in page.items)
        pagination = presenters.pagination_view(
            limit=normalized_limit,
            offset=offset,
            total=page.total,
        )
        filters = {"status": normalized_status, "agent_id": agent_id}
        return helpers.render(
            "sessions/list.html",
            sessions=sessions,
            pagination=pagination,
            filters=filters,
        )

    @router.get(
        f"{prefix}/sessions/table",
        response_class=HTMLResponse,
        name="sessions_table",
    )
    async def sessions_table_fragment(
        uow_factory: UowDependency,
        session_status: StatusQuery = None,
        agent_id: StringQuery = None,
        limit: OptionalIntQuery = None,
        offset: OffsetQuery = 0,
    ) -> HTMLResponse:
        normalized_limit = helpers.page_limit(limit)
        parsed_agent = _parse_uuid(agent_id)
        normalized_status = _parse_session_status(session_status)
        service = DashboardQueryService(uow_factory)
        page = await service.list_sessions(
            agent_id=parsed_agent,
            status=normalized_status,
            limit=normalized_limit,
            offset=offset,
        )
        sessions = tuple(presenters.session_list_item(item) for item in page.items)
        pagination = presenters.pagination_view(
            limit=normalized_limit,
            offset=offset,
            total=page.total,
        )
        return helpers.render_fragment(
            "sessions/_table.html",
            sessions=sessions,
            pagination=pagination,
        )

    @router.get(
        f"{prefix}/sessions/{{session_id}}",
        response_class=HTMLResponse,
        name="session_detail",
    )
    async def session_detail_page(
        session_id: UUID,
        uow_factory: UowDependency,
    ) -> HTMLResponse:
        service = DashboardQueryService(uow_factory)
        try:
            timeline = await service.session_timeline(session_id)
        except SessionNotFound:
            return helpers.render_error(
                code="session_not_found",
                heading="Session not found",
                message="The session was not found.",
                status_code=404,
            )
        session_view = presenters.session_detail(timeline)
        return helpers.render("sessions/detail.html", session=session_view)

    @router.get(
        f"{prefix}/tool-calls/{{call_id}}",
        response_class=HTMLResponse,
        name="tool_call_detail",
    )
    async def tool_call_detail_page(
        call_id: UUID,
        uow_factory: UowDependency,
    ) -> HTMLResponse:
        service = DashboardQueryService(uow_factory)
        try:
            view = await service.tool_call_view(call_id)
        except ToolCallNotFound:
            return helpers.render_error(
                code="tool_call_not_found",
                heading="Tool call not found",
                message="The tool call was not found.",
                status_code=404,
            )
        detail = presenters.tool_call_detail(
            view,
            jaeger_ui_base_url=settings.jaeger_ui_public_url,
        )
        return helpers.render("tool_calls/detail.html", call=detail)

    @router.get(f"{prefix}/rules", response_class=HTMLResponse, name="rules_list")
    async def rules_list_page(
        uow_factory: UowDependency,
        enabled: Annotated[bool | None, Query()] = None,
        limit: OptionalIntQuery = None,
        offset: OffsetQuery = 0,
    ) -> HTMLResponse:
        normalized_limit = helpers.page_limit(limit)
        service = DashboardQueryService(uow_factory)
        page = await service.list_rules(
            enabled=enabled,
            limit=normalized_limit,
            offset=offset,
        )
        rules = tuple(presenters.rule_view(rule) for rule in page.items)
        pagination = presenters.pagination_view(
            limit=normalized_limit,
            offset=offset,
            total=page.total,
        )
        return helpers.render("rules/list.html", rules=rules, pagination=pagination)

    @router.get(f"{prefix}/audit-events", response_class=HTMLResponse, name="audit_list")
    async def audit_list_page(
        uow_factory: UowDependency,
        event_type: StringQuery = None,
        trace_id: StringQuery = None,
        correlation_id: StringQuery = None,
        limit: OptionalIntQuery = None,
        offset: OffsetQuery = 0,
    ) -> HTMLResponse:
        normalized_limit = helpers.page_limit(limit)
        parsed_event_type = _parse_audit_event_type(event_type)
        validated_trace = _validated_trace_id(trace_id)
        validated_correlation = _validated_uuid(correlation_id)
        async with uow_factory() as uow:
            page = await uow.audit_events.list(
                session_id=None,
                tool_call_id=None,
                event_type=parsed_event_type,
                trace_id=validated_trace,
                correlation_id=validated_correlation,
                limit=normalized_limit,
                offset=offset,
            )
        events = tuple(presenters.audit_event_view(event) for event in page.items)
        pagination = presenters.pagination_view(
            limit=normalized_limit,
            offset=offset,
            total=page.total,
        )
        return helpers.render(
            "audit/list.html",
            events=events,
            pagination=pagination,
            filters={
                "event_type": event_type,
                "trace_id": validated_trace,
                "correlation_id": validated_correlation,
            },
            event_types=[value.value for value in AuditEventType],
        )

    if settings.attack_lab_enabled:
        from toolwatch.attack_lab.registry import (
            STATIC_REGISTRY,
            list_scenarios,
        )
        from toolwatch.attack_lab.runner import AttackLabRunner

        @router.get(
            f"{prefix}/attacks",
            response_class=HTMLResponse,
            name="attacks_index",
        )
        async def attacks_index_page() -> HTMLResponse:
            scenarios = tuple(
                presenters.attack_scenario_view(scenario) for scenario in list_scenarios()
            )
            return helpers.render("attacks/index.html", scenarios=scenarios)

        @router.get(
            f"{prefix}/attacks/{{scenario_id}}",
            response_class=HTMLResponse,
            name="attack_detail",
        )
        async def attack_detail_page(scenario_id: str) -> HTMLResponse:
            scenario = STATIC_REGISTRY.get(scenario_id)
            if scenario is None:
                return helpers.render_error(
                    code="attack_scenario_not_found",
                    heading="Attack scenario not found",
                    message="The Attack Lab scenario was not found.",
                    status_code=404,
                )
            return helpers.render(
                "attacks/detail.html",
                scenario=presenters.attack_scenario_view(scenario),
            )

        @router.post(
            f"{prefix}/attacks/{{scenario_id}}/run",
            response_class=HTMLResponse,
            name="attack_run",
        )
        async def attack_run(scenario_id: str, request: Request) -> HTMLResponse:
            scenario = STATIC_REGISTRY.get(scenario_id)
            if scenario is None:
                return helpers.render_error(
                    code="attack_scenario_not_found",
                    heading="Attack scenario not found",
                    message="The Attack Lab scenario was not found.",
                    status_code=404,
                )
            if not _is_safe_origin(request):
                return helpers.render_error(
                    code="forbidden",
                    heading="Forbidden",
                    message="Cross-origin attack execution is not allowed.",
                    status_code=403,
                )
            runner = AttackLabRunner.from_running_app(request.app)
            result = await runner.run(scenario)
            view = presenters.attack_run_result_view(result)
            return helpers.render("attacks/result.html", result=view)

        attack_handlers: tuple[Callable[..., Awaitable[HTMLResponse]], ...] = (
            attacks_index_page,
            attack_detail_page,
            attack_run,
        )
    else:
        attack_handlers = ()

    # Tag handlers so pyright does not warn that decorated callbacks are unused.
    handlers: tuple[Callable[..., Awaitable[HTMLResponse]], ...] = (
        dashboard_home,
        dashboard_recent_sessions_fragment,
        sessions_list,
        sessions_table_fragment,
        session_detail_page,
        tool_call_detail_page,
        rules_list_page,
        audit_list_page,
        *attack_handlers,
    )
    _ = handlers
    return router


class _TemplateHelpers:
    """Render templates with consistent context and security headers."""

    def __init__(self, *, prefix: str, settings: Settings) -> None:
        self._prefix = prefix
        self._settings = settings

    def page_limit(self, value: int | None) -> int:
        if value is None:
            return self._settings.dashboard_page_size
        return max(1, min(value, self._settings.dashboard_max_page_size))

    def url(self, name: str, **params: object) -> str:
        if name not in _ROUTE_TEMPLATES:
            raise KeyError(f"unknown dashboard route: {name}")
        return self._prefix + _ROUTE_TEMPLATES[name].format(**params)

    def static_url(self, filename: str) -> str:
        safe = filename.replace("/", "").replace("\\", "")
        return f"{self._prefix}/static/{safe}"

    def build_query(self, **params: object) -> str:
        cleaned = {
            key: str(value) for key, value in params.items() if value is not None and value != ""
        }
        return urlencode(cleaned, doseq=True)

    def context(self, **extra: object) -> dict[str, object]:
        ctx: dict[str, object] = {
            "url": self.url,
            "static_url": self.static_url,
            "build_query": self.build_query,
            "attack_lab_enabled": self._settings.attack_lab_enabled,
            "environment": self._settings.environment,
            "refresh_seconds": self._settings.dashboard_refresh_seconds,
            "max_page_size": self._settings.dashboard_max_page_size,
        }
        ctx.update(extra)
        return ctx

    def render(self, template_name: str, **context: object) -> HTMLResponse:
        env = get_template_environment()
        template = env.get_template(template_name)
        body = template.render(**self.context(**context))
        response = HTMLResponse(content=body)
        _apply_headers(response, html=True)
        return response

    def render_fragment(self, template_name: str, **context: object) -> HTMLResponse:
        env = get_template_environment()
        template = env.get_template(template_name)
        body = template.render(**self.context(**context))
        response = HTMLResponse(content=body)
        _apply_headers(response, html=True)
        return response

    def render_error(
        self,
        *,
        code: str,
        heading: str,
        message: str,
        status_code: int,
    ) -> HTMLResponse:
        env = get_template_environment()
        template = env.get_template("components/error.html")
        body = template.render(
            **self.context(
                code=code,
                heading=heading,
                message=message,
                correlation_id=current_correlation().correlation_id,
            )
        )
        response = HTMLResponse(content=body, status_code=status_code)
        _apply_headers(response, html=True)
        return response


def _apply_headers(response: Response, *, html: bool) -> None:
    for name, value in security_headers(html=html).items():
        response.headers[name] = value


def mount_dashboard(application: FastAPI) -> None:
    """Mount the dashboard router, static files, and security headers."""

    settings = get_settings()
    if not settings.dashboard_enabled:
        return
    prefix = settings.dashboard_prefix.rstrip("/") or "/ui"
    application.include_router(create_dashboard_router(settings))

    static_root = _static_directory()
    application.mount(
        f"{prefix}/static",
        _SecureStaticFiles(directory=str(static_root), html=False),
        name="dashboard_static",
    )


def _static_directory() -> object:
    from pathlib import Path

    return Path(__file__).parent / STATIC_DIRNAME


class _SecureStaticFiles(StaticFiles):
    """StaticFiles wrapper that adds dashboard security headers to every asset."""

    async def get_response(self, path: str, scope: Any) -> Response:  # type: ignore[override]
        response = await super().get_response(path, scope)
        for name, value in security_headers(html=False).items():
            response.headers[name] = value
        response.headers.setdefault("Cache-Control", "public, max-age=300, immutable")
        return response


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _validated_trace_id(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if len(value) != 32:
        return None
    if any(character not in "0123456789abcdef" for character in value):
        return None
    return value


def _validated_uuid(value: str | None) -> str | None:
    parsed = _parse_uuid(value)
    return str(parsed) if parsed is not None else None


def _parse_session_status(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value in {"active", "completed", "failed"}:
        return value
    return None


def _parse_audit_event_type(value: str | None) -> AuditEventType | None:
    if value is None or value == "":
        return None
    try:
        return AuditEventType(value)
    except ValueError:
        return None


def _is_safe_origin(request: Request) -> bool:
    referer = request.headers.get("referer") or request.headers.get("origin")
    if referer is None:
        return True
    host = request.headers.get("host")
    if host is None:
        return False
    return f"//{host}/" in referer or referer.endswith(f"//{host}")


def route_names() -> Iterable[str]:
    """Expose the registered dashboard route names for tests."""

    return tuple(_ROUTE_TEMPLATES.keys())


_ = Mapping  # quiet unused import for the typing surface
