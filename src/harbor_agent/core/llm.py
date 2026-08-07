from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from harbor_agent.config import Settings

from harbor_agent.services.source_snapshot import _unsafe_url_reason

class LLMProvider(Protocol):
    name: str
    provider: str

    def complete_json(self, system: str, user: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class MockLLMProvider:
    name: str = "mock"
    provider: str = "mock"

    def complete_json(self, system: str, user: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "Mock model response generated for reproducible local development.",
            "system_digest": system[:120],
            "user_digest": user[:240],
            "schema_keys": list(schema_hint.keys()),
        }


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        provider: str = "openai",
        base_url: str | None = None,
        timeout_seconds: float = 30,
    ):
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "请先执行 `pip install -r requirements-llm.txt` 安装大模型依赖。"
            ) from exc
        resolved_base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        unsafe_reason = _unsafe_url_reason(resolved_base_url)
        if unsafe_reason:
            raise ValueError(f"unsafe model base URL: {unsafe_reason}")
        self._client = httpx.Client(timeout=timeout_seconds, trust_env=False, follow_redirects=False)
        self._chat_url = f"{resolved_base_url}/chat/completions"
        self._headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        self._model = model
        self.name = model
        self.provider = provider
        self.base_url = resolved_base_url

    def complete_json(self, system: str, user: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": f"{system}\n只返回 JSON，不要 Markdown。"},
            {
                "role": "user",
                "content": (
                    f"{user}\n\n请返回一个紧凑 JSON 对象，字段参考：\n"
                    f"{json.dumps(schema_hint, ensure_ascii=False)}"
                ),
            },
        ]
        payload: dict[str, Any] = dict(
            model=self._model,
            messages=messages,
            temperature=0.2,
            stream=False,
        )
        response = self._client.post(self._chat_url, headers=self._headers, json=payload)
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"model provider returned HTTP {response.status_code}") from exc
        data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"summary": text}


OpenAILLMProvider = OpenAICompatibleLLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider = (settings.llm_provider or settings.llm_mode).lower()
    if settings.llm_mode.lower() == "openai" and provider == "mock":
        provider = "openai"
    if provider in {"openai", "deepseek", "compatible"}:
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("真实大模型模式需要 OPENAI_API_KEY 或页面输入 API Key。")
        base_url = settings.openai_base_url
        if provider == "deepseek":
            base_url = "https://api.deepseek.com"
        return OpenAICompatibleLLMProvider(
            api_key=api_key,
            model=settings.openai_model,
            provider=provider,
            base_url=base_url,
        )
    return MockLLMProvider()
