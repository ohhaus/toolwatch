"""Run the bounded local ToolWatch agent loop from the command line."""

import argparse
import asyncio
from functools import partial

from toolwatch.api.dependencies import get_adapter_registry
from toolwatch.application.agent_runs import AgentRunService, StartAgentRun
from toolwatch.application.sessions import CreateSession, SessionService
from toolwatch.config import get_settings
from toolwatch.domain.agents import AgentIdentity
from toolwatch.infrastructure.agents import FakeAgentProvider, OllamaAgentProvider
from toolwatch.infrastructure.database.engine import dispose_engine, get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork
from toolwatch.telemetry import build_telemetry_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m toolwatch.agent")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run one bounded synchronous agent loop")
    run.add_argument("prompt")
    run.add_argument("--provider", choices=("fake", "ollama"), default=None)
    run.add_argument("--model", default=None)
    return parser


async def _run(prompt: str, provider_name: str | None, model_name: str | None) -> int:
    settings = get_settings()
    provider = provider_name or settings.agent_provider
    model = model_name or (
        settings.ollama_model if provider == "ollama" else settings.fake_agent_model
    )
    uow_factory = partial(SqlAlchemyUnitOfWork, get_session_factory())
    session = await SessionService(uow_factory).create(
        CreateSession(
            agent_identity=AgentIdentity(
                name="toolwatch-agent-cli",
                provider=provider,
                model_name=model,
                version="1",
            )
        )
    )
    telemetry = build_telemetry_runtime(settings)
    ollama = OllamaAgentProvider(settings.ollama_base_url)
    service = AgentRunService(
        uow_factory=uow_factory,
        adapters=get_adapter_registry(),
        providers={
            "fake": FakeAgentProvider(),
            "ollama": ollama,
        },
        settings=settings,
        telemetry=telemetry,
    )
    try:
        result = await service.start(
            StartAgentRun(
                session_id=session.session.id,
                prompt=prompt,
                provider=provider,
                model=model,
            )
        )
        print(result.run.final_answer_redacted or "")
        print(f"run_id: {result.run.id}")
        for call in result.tool_calls:
            print(
                f"tool: {call.tool} status={call.status} "
                f"decision={call.decision or '-'} risk={call.risk or '-'}"
            )
        print(
            f"dashboard: http://localhost:8000{settings.dashboard_prefix}/agent-runs/{result.run.id}"
        )
        if settings.jaeger_ui_public_url and result.run.trace_id:
            print(f"trace: {settings.jaeger_ui_public_url.rstrip('/')}/trace/{result.run.trace_id}")
        return 0
    finally:
        await ollama.aclose()
        telemetry.shutdown()
        await dispose_engine()


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(asyncio.run(_run(args.prompt, args.provider, args.model)))


if __name__ == "__main__":
    main()
