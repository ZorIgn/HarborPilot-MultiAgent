from __future__ import annotations

import httpx
import pytest

from harbor_agent.llm import pricing
from harbor_agent.llm import provider as provider_module
from harbor_agent.llm.provider import OpenAICompatibleToolCallingProvider
from harbor_agent.llm.response import LLMUsage
from harbor_agent.runtime.errors import LLMProviderError, LLMStructuredOutputError, LLMTimeoutError


def _provider(handler, monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleToolCallingProvider:
    monkeypatch.setattr(provider_module, "_unsafe_url_reason", lambda url: None)
    provider = OpenAICompatibleToolCallingProvider(
        api_key="test-secret",
        model="test-model",
        provider="test-provider",
        base_url="https://api.openai.com/v1",
    )
    provider._client.close()
    provider._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )
    return provider


def _response_payload(*, arguments: str = "{}") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "lookup", "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 7},
        },
    }


def test_invalid_tool_arguments_retain_response_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response_payload(arguments="{"), request=request)

    provider = _provider(handler, monkeypatch)

    with pytest.raises(LLMStructuredOutputError) as raised:
        provider.complete(messages=[], tools=[{"type": "function"}])

    error = raised.value
    assert error.usage is not None
    assert error.usage.prompt_tokens == 12
    assert error.usage.completion_tokens == 5
    assert error.usage.cached_tokens == 7
    assert error.model == "test-model"
    assert error.provider == "test-provider"
    assert error.received_response is True


def test_success_response_preserves_cached_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response_payload(), request=request)

    result = _provider(handler, monkeypatch).complete(messages=[], tools=[{"type": "function"}])

    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 5
    assert result.usage.cached_tokens == 7


def test_timeout_is_classified_without_provider_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=request)

    with pytest.raises(LLMTimeoutError) as raised:
        _provider(handler, monkeypatch).complete(messages=[])

    error = raised.value
    assert type(error) is LLMTimeoutError
    assert not isinstance(error, LLMProviderError)
    assert "private timeout details" not in str(error)
    assert "api.openai.com" not in str(error)
    assert "test-secret" not in str(error)


def test_network_error_is_distinct_from_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private connection details", request=request)

    with pytest.raises(LLMProviderError) as raised:
        _provider(handler, monkeypatch).complete(messages=[])

    error = raised.value
    assert not isinstance(error, LLMTimeoutError)
    assert not isinstance(error, LLMStructuredOutputError)
    assert error.received_response is False
    assert "private connection details" not in str(error)
    assert "api.openai.com" not in str(error)
    assert "test-secret" not in str(error)


def test_http_429_is_provider_error_without_body_or_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "private response body"}},
            request=request,
        )

    with pytest.raises(LLMProviderError) as raised:
        _provider(handler, monkeypatch).complete(messages=[])

    error = raised.value
    assert not isinstance(error, LLMTimeoutError)
    assert error.http_status == 429
    assert error.http_status == 429
    assert error.received_response is True
    assert "private response body" not in str(error)
    assert "api.openai.com" not in str(error)
    assert "test-secret" not in str(error)


def test_malformed_choices_retain_response_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
            request=request,
        )

    with pytest.raises(LLMStructuredOutputError) as raised:
        _provider(handler, monkeypatch).complete(messages=[])

    error = raised.value
    assert error.usage is not None
    assert error.usage.total_tokens == 6
    assert error.received_response is True


def test_partial_usage_and_incomplete_pricing_stay_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LLMUsage(prompt_tokens=3).total_tokens is None
    assert LLMUsage(completion_tokens=2).total_tokens is None

    monkeypatch.setattr(
        pricing,
        "load_model_pricing",
        lambda: {"test-provider/test-model": {"input_per_1m": 1.0, "output_per_1m": 2.0}},
    )
    usage = LLMUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=10)
    assert pricing.calculate_cost_usd("test-provider", "test-model", usage) is None
    assert pricing.calculate_cost_usd(
        "test-provider", "test-model", LLMUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=101)
    ) is None
