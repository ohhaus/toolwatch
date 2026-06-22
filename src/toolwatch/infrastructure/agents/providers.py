"""Deterministic fake and optional local Ollama agent providers."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx

from toolwatch.domain.agents import (
    AgentMessage,
    AgentMessageRole,
    AgentProviderOptions,
    AgentProviderResponse,
    ModelUsage,
    ProviderToolDefinition,
    RequestedToolCall,
)
from toolwatch.domain.common import JSONObject


class AgentProviderError(Exception):
    """Stable provider failure whose raw details are never exposed."""

    def __init__(self, code: str = "agent_provider_error") -> None:
        super().__init__(code)
        self.code = code


class FakeAgentProvider:
    """Deterministic no-network provider with optional scripted responses."""

    def __init__(self, responses: Sequence[AgentProviderResponse] | None = None) -> None:
        self._responses = tuple(responses) if responses is not None else None
        self.invocation_count = 0

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ProviderToolDefinition],
        options: AgentProviderOptions,
    ) -> AgentProviderResponse:
        del model, options
        index = self.invocation_count
        self.invocation_count += 1
        if self._responses is not None:
            if index >= len(self._responses):
                raise AgentProviderError("agent_provider_error")
            return self._responses[index]
        return self._default_response(messages, tools)

    @staticmethod
    def _default_response(
        messages: Sequence[AgentMessage],
        tools: Sequence[ProviderToolDefinition],
    ) -> AgentProviderResponse:
        if any(message.role is AgentMessageRole.TOOL for message in messages):
            return AgentProviderResponse(content="The requested ToolWatch operation was processed.")
        prompt = next(
            (
                message.content or ""
                for message in reversed(messages)
                if message.role is AgentMessageRole.USER
            ),
            "",
        ).lower()
        available = {tool.name for tool in tools}
        if "issue" in prompt and "github_list_issues" in available:
            return AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        name="github_list_issues",
                        arguments={"repository": "demo/backend", "state": "open"},
                        provider_call_id="fake-call-1",
                    ),
                ),
            )
        if any(word in prompt for word in ("drop", "delete", "table")) and (
            "database_query" in available
        ):
            return AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        name="database_query",
                        arguments={"query": "DROP TABLE projects"},
                        provider_call_id="fake-call-1",
                    ),
                ),
            )
        if "email" in prompt and "email_send" in available:
            return AgentProviderResponse(
                content=None,
                tool_calls=(
                    RequestedToolCall(
                        name="email_send",
                        arguments={
                            "recipient": "demo@example.com",
                            "subject": "ToolWatch summary",
                            "body": "Deterministic fake-provider summary.",
                        },
                        provider_call_id="fake-call-1",
                    ),
                ),
            )
        return AgentProviderResponse(content="No tool call was needed.")


class OllamaAgentProvider:
    """Local Ollama `/api/chat` client with bounded safe error mapping."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[AgentMessage],
        tools: Sequence[ProviderToolDefinition],
        options: AgentProviderOptions,
    ) -> AgentProviderResponse:
        payload = {
            "model": model,
            "stream": False,
            "think": options.think,
            "messages": [_message_payload(message) for message in messages],
            "tools": [_tool_payload(tool) for tool in tools],
        }
        if options.keep_alive is not None:
            payload["keep_alive"] = options.keep_alive
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=options.timeout_seconds,
            ) as client:
                response = await client.post("/api/chat", json=payload)
        except httpx.TimeoutException:
            raise AgentProviderError("ollama_timeout") from None
        except httpx.HTTPError:
            raise AgentProviderError("ollama_unavailable") from None
        if response.status_code == 404:
            raise AgentProviderError("ollama_model_not_found")
        if response.status_code >= 400:
            raise AgentProviderError("ollama_unavailable")
        if len(response.content) > options.max_response_bytes:
            raise AgentProviderError("ollama_invalid_response")
        try:
            body = response.json()
        except ValueError:
            raise AgentProviderError("ollama_invalid_response") from None
        return _parse_ollama_response(body)

    async def health(self, timeout_seconds: float = 2.0) -> bool:
        """Check Ollama availability without generating or loading a model."""

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout_seconds,
            ) as client:
                response = await client.get("/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def _message_payload(message: AgentMessage) -> dict[str, object]:
    result: dict[str, object] = {"role": message.role.value}
    if message.content is not None:
        result["content"] = message.content
    if message.tool_call_id is not None:
        result["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                }
            }
            for call in message.tool_calls
        ]
    return result


def _tool_payload(tool: ProviderToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_ollama_response(value: object) -> AgentProviderResponse:
    if not isinstance(value, dict):
        raise AgentProviderError("ollama_invalid_response")
    body = cast(Mapping[str, object], value)
    message = body.get("message")
    if not isinstance(message, dict):
        raise AgentProviderError("ollama_invalid_response")
    message_map = cast(Mapping[str, object], message)
    content = message_map.get("content")
    if content is not None and not isinstance(content, str):
        raise AgentProviderError("ollama_invalid_response")
    raw_calls = message_map.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        raise AgentProviderError("ollama_invalid_response")
    calls: list[RequestedToolCall] = []
    for index, raw_call in enumerate(cast(list[object], raw_calls)):
        if not isinstance(raw_call, dict):
            raise AgentProviderError("ollama_invalid_response")
        raw_call_map = cast(Mapping[str, object], raw_call)
        function = raw_call_map.get("function")
        if not isinstance(function, dict):
            raise AgentProviderError("ollama_invalid_response")
        function_map = cast(Mapping[str, object], function)
        name = function_map.get("name")
        if not isinstance(name, str):
            raise AgentProviderError("ollama_invalid_response")
        arguments = function_map.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                raise AgentProviderError("ollama_invalid_response") from None
        if not isinstance(arguments, dict):
            raise AgentProviderError("ollama_invalid_response")
        call_id = raw_call_map.get("id")
        if call_id is not None and not isinstance(call_id, str):
            raise AgentProviderError("ollama_invalid_response")
        calls.append(
            RequestedToolCall(
                name=name,
                arguments=cast(JSONObject, arguments),
                provider_call_id=call_id or f"ollama-call-{index + 1}",
            )
        )
    thinking = message_map.get("thinking")
    if thinking is not None and not isinstance(thinking, str):
        thinking = None
    response_model = body.get("model")
    if response_model is not None and not isinstance(response_model, str):
        response_model = None
    return AgentProviderResponse(
        content=content,
        tool_calls=tuple(calls),
        usage=ModelUsage(
            prompt_tokens=_optional_nonnegative_int(body.get("prompt_eval_count")),
            completion_tokens=_optional_nonnegative_int(body.get("eval_count")),
            total_duration_ms=_nanoseconds_to_ms(body.get("total_duration")),
            load_duration_ms=_nanoseconds_to_ms(body.get("load_duration")),
        ),
        response_model=response_model,
        thinking=thinking,
    )


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _nanoseconds_to_ms(value: object) -> int | None:
    nanoseconds = _optional_nonnegative_int(value)
    return nanoseconds // 1_000_000 if nanoseconds is not None else None


_ = JSONObject
