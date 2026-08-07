from __future__ import annotations

import json
from typing import Any, Protocol, Type
from uuid import uuid4

from pydantic import BaseModel

from harbor_agent.llm.response import LLMResponse, LLMToolCall, LLMUsage
from harbor_agent.runtime.errors import LLMStructuredOutputError, LLMTimeoutError
from harbor_agent.services.source_snapshot import _unsafe_url_reason


class RuntimeLLMProvider(Protocol):
    """Tool-calling provider contract used by new agents and the executor."""

    name: str
    provider: str

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: Type[BaseModel] | None = None,
    ) -> LLMResponse:
        ...


class OpenAICompatibleToolCallingProvider:
    """HTTPS-only OpenAI-compatible Chat Completions adapter with real tool calls."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        provider: str = "openai",
        base_url: str | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency boundary
            raise RuntimeError("Install httpx to use an OpenAI-compatible provider.") from exc
        resolved = (base_url or "https://api.openai.com/v1").rstrip("/")
        reason = _unsafe_url_reason(resolved)
        if reason:
            raise ValueError(f"unsafe model base URL: {reason}")
        self._client = httpx.Client(timeout=timeout_seconds, trust_env=False, follow_redirects=False)
        self._chat_url = f"{resolved}/chat/completions"
        self._headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
        self.name = model
        self.provider = provider
        self.base_url = resolved

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: Type[BaseModel] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {"model": self.name, "messages": messages, "temperature": 0.1, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        elif response_model:
            # Broad JSON-object mode is supported by more compatible providers
            # than the newer strict JSON-schema response format.
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._client.post(self._chat_url, headers=self._headers, json=payload)
        except Exception as exc:
            raise LLMTimeoutError("model provider request failed") from exc
        if response.is_redirect:
            location = response.headers.get("location", "")
            if _unsafe_url_reason(location):
                raise LLMTimeoutError("model provider redirected to an unsafe URL")
        try:
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LLMStructuredOutputError("model provider returned an invalid response") from exc

        message = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls: list[LLMToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
            except (TypeError, json.JSONDecodeError) as exc:
                raise LLMStructuredOutputError("model tool call arguments were not valid JSON") from exc
            tool_calls.append(
                LLMToolCall(
                    call_id=str(raw_call.get("id") or f"call_{uuid4().hex[:12]}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
        usage_data = data.get("usage") or {}
        details = usage_data.get("prompt_tokens_details") or {}
        usage = LLMUsage(
            prompt_tokens=usage_data.get("prompt_tokens"),
            completion_tokens=usage_data.get("completion_tokens"),
            cached_tokens=details.get("cached_tokens"),
        )
        content = message.get("content")
        json_content: dict[str, Any] | None = None
        if response_model and content:
            try:
                parsed = json.loads(content)
                json_content = response_model.model_validate(parsed).model_dump(mode="json")
            except Exception as exc:
                raise LLMStructuredOutputError("model structured output failed Pydantic validation") from exc
        return LLMResponse(
            content=content,
            json_content=json_content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.name,
            provider=self.provider,
            raw_finish_reason=(data.get("choices") or [{}])[0].get("finish_reason"),
        )


class DeterministicMockToolCallingProvider:
    """Test-only provider that returns explicit responses and usage when queued."""

    name = "mock"
    provider = "mock"

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: Type[BaseModel] | None = None,
    ) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        payload: dict[str, Any] = {"decision": "HANDOFF", "reasoning_summary": "Deterministic mock hands control back to supervisor.", "next_agent": "SupervisorAgent"}
        if response_model:
            payload = response_model.model_validate(payload).model_dump(mode="json")
        return LLMResponse(json_content=payload, usage=LLMUsage(prompt_tokens=0, completion_tokens=0), model=self.name, provider=self.provider)
