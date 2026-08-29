from __future__ import annotations

import json
from typing import Any

from harbor_agent.llm.response import LLMResponse, LLMToolCall, LLMUsage
from harbor_agent.runtime.errors import LLMStructuredOutputError


class PolicyEnvelopeReplayProvider:
    """Exercise the real model-driven runtime with reproducible safe choices.

    This provider is an execution-path fixture, not a model-quality surrogate.
    It reads only the policy envelopes that production Agents send to an LLM
    and selects the first permitted route or the complete ordered tool prefix.
    The resulting decisions still pass through the normal reducer, Executor,
    tool registry, checkpoint store and trace pipeline.
    """

    name = "policy-envelope-replay"
    provider = "eval"

    def __init__(self) -> None:
        self.call_count = 0

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model=None,
    ) -> LLMResponse:
        self.call_count += 1
        context = _latest_json_context(messages)
        usage = LLMUsage(prompt_tokens=1, completion_tokens=1)

        envelope = context.get("runtime_policy_envelope")
        if isinstance(envelope, dict):
            decision = str(envelope.get("decision") or "")
            if decision == "CALL_TOOL":
                calls = list(envelope.get("tool_calls") or [])
                if not calls:
                    raise LLMStructuredOutputError(
                        "CALL_TOOL policy envelope did not expose an executable call"
                    )
                return LLMResponse(
                    tool_calls=[
                        LLMToolCall(
                            call_id=f"replay_{self.call_count}_{index}",
                            name=str(item.get("tool_name") or ""),
                            arguments=dict(item.get("arguments") or {}),
                        )
                        for index, item in enumerate(calls, start=1)
                    ],
                    usage=usage,
                    model=self.name,
                    provider=self.provider,
                )
            payload: dict[str, Any] = {
                "decision": decision,
                "reasoning_summary": "Select the runtime-permitted policy action.",
            }
            if envelope.get("next_agent"):
                payload["next_agent"] = envelope["next_agent"]
            if envelope.get("user_question"):
                payload["user_question"] = envelope["user_question"]
            if envelope.get("human_review_reason"):
                payload["human_review_reason"] = envelope["human_review_reason"]
            return LLMResponse(
                json_content=payload,
                usage=usage,
                model=self.name,
                provider=self.provider,
            )

        routes = list(context.get("available_routes") or [])
        if routes:
            target = str(routes[0].get("target") or "")
            decision = (
                "COMPLETE"
                if target == "END"
                else "ASK_USER"
                if target == "ASK_USER"
                else "HUMAN_REVIEW"
                if target == "HUMAN_REVIEW"
                else "BLOCKED"
                if target == "BLOCKED"
                else "HANDOFF"
            )
            payload = {
                "decision": decision,
                "reasoning_summary": str(
                    routes[0].get("policy_reason")
                    or "Select the first policy-safe Supervisor route."
                ),
            }
            if decision == "HANDOFF":
                payload["next_agent"] = target
            return LLMResponse(
                json_content=payload,
                usage=usage,
                model=self.name,
                provider=self.provider,
            )

        raise LLMStructuredOutputError(
            "model replay received no runtime policy envelope or Supervisor routes"
        )


def _latest_json_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and (
            "runtime_policy_envelope" in value or "available_routes" in value
        ):
            return value
    return {}
