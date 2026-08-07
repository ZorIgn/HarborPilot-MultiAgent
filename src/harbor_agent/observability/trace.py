from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from harbor_agent.llm.pricing import calculate_cost_usd
from harbor_agent.llm.response import LLMUsage
from harbor_agent.observability.events import RuntimeTraceEvent, TraceEventType
from harbor_agent.runtime.sanitizer import sanitize_text
from harbor_agent.services.agent_runtime import list_runtime_trace_events, record_runtime_trace_event


class RuntimeTracer:
    """Records real agent/tool/runtime actions and persists normalized events."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.events: list[RuntimeTraceEvent] = []

    def emit(
        self,
        event_type: TraceEventType,
        *,
        agent_name: str | None = None,
        parent_event_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        usage: LLMUsage | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        error: Exception | None = None,
        started_at: datetime | None = None,
        started_perf: float | None = None,
    ) -> RuntimeTraceEvent:
        started = started_at or datetime.now(UTC)
        finished = datetime.now(UTC)
        duration = int((perf_counter() - started_perf) * 1000) if started_perf is not None else 0
        use = usage or LLMUsage()
        event = RuntimeTraceEvent(
            event_id=f"trace_{uuid4().hex}",
            workflow_id=self.workflow_id,
            event_type=event_type,
            parent_event_id=parent_event_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            model=model,
            provider=provider,
            prompt_tokens=use.prompt_tokens,
            completion_tokens=use.completion_tokens,
            cached_tokens=use.cached_tokens,
            total_tokens=use.total_tokens,
            cost_usd=calculate_cost_usd(provider, model, use),
            input_summary=_safe_summary(input_summary),
            output_summary=_safe_summary(output_summary),
            error_type=type(error).__name__ if error else None,
            error_message=_safe_summary(str(error)) if error else None,
        )
        self.events.append(event)
        record_runtime_trace_event(event.model_dump(mode="json"))
        return event

    def persisted(self) -> list[dict[str, Any]]:
        return list_runtime_trace_events(self.workflow_id)


def _safe_summary(value: str | None) -> str | None:
    # Apply the same camel/kebab/snake/nested-key policy used by SQLite
    # persistence, including to in-memory trace events returned to callers.
    return sanitize_text(value)
