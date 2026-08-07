from __future__ import annotations

from harbor_agent.llm.response import LLMUsage


def merge_usage(current: LLMUsage, incoming: LLMUsage) -> LLMUsage:
    """Accumulate only provider-reported usage fields."""

    def add(left: int | None, right: int | None) -> int | None:
        if left is None and right is None:
            return None
        return (left or 0) + (right or 0)

    return LLMUsage(
        prompt_tokens=add(current.prompt_tokens, incoming.prompt_tokens),
        completion_tokens=add(current.completion_tokens, incoming.completion_tokens),
        cached_tokens=add(current.cached_tokens, incoming.cached_tokens),
    )
