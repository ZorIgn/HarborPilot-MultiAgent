from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from harbor_agent.config import Settings


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
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "请先执行 `pip install -r requirements-llm.txt` 安装大模型依赖。"
            ) from exc
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self._model = model
        self.name = model
        self.provider = provider
        self.base_url = base_url

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
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=messages,
            temperature=0.2,
            stream=False,
        )
        try:
            response = self._client.chat.completions.create(
                **kwargs,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            message = str(exc).lower()
            if "response_format" not in message and "json_object" not in message:
                raise
            response = self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or "{}"
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
