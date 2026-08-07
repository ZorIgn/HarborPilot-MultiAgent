from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMUsage(BaseModel):
    """Usage reported by a provider. Values are never estimated from latency."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class LLMToolCall(BaseModel):
    """A real provider-generated tool call, not a trace label."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized response returned by every supported LLM provider."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    json_content: dict[str, Any] | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model: str | None = None
    provider: str | None = None
    raw_finish_reason: str | None = None
