from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4

from harbor_agent.llm.pricing import calculate_cost_usd
from harbor_agent.llm.response import LLMUsage
from harbor_agent.observability.events import RuntimeTraceEvent, TraceEventType
from harbor_agent.observability.langfuse_sink import get_langfuse_sink
from harbor_agent.observability.privacy import safe_content, safe_metadata
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.graph import SPECIALIST_AGENTS, SUPERVISOR_AGENT
from harbor_agent.runtime.sanitizer import sanitize_text
from harbor_agent.services.agent_runtime import (
    list_runtime_trace_events,
    record_runtime_trace_event,
)

_ACTIVE_TRACER: ContextVar[RuntimeTracer | None] = ContextVar("runtime_tracer", default=None)
_EVALUATION: ContextVar[dict[str, Any] | None] = ContextVar("trace_evaluation", default=None)


@contextmanager
def evaluation_context(case_id: str, *, capture_synthetic: bool = False) -> Iterator[None]:
    token = _EVALUATION.set(
        {"case_id": case_id, "data_source": "synthetic", "synthetic_content": capture_synthetic}
    )
    try:
        yield
    finally:
        _EVALUATION.reset(token)


def provider_mode(provider: Any) -> str:
    if provider is None:
        return "deterministic"
    return (
        "model_replay" if getattr(provider, "provider", None) in {"eval", "mock"} else "live_model"
    )


@dataclass
class Observation:
    name: str
    kind: str
    span_id: str
    parent_span_id: str | None
    started_at: datetime
    started_perf: float
    agent_name: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    model: str | None = None
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    usage: LLMUsage | None = None
    handle: Any = None
    start_event_id: str | None = None


class RuntimeTracer:
    """Persist execution events and mirror their hierarchy to an optional exporter."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.execution_id = f"execution_{uuid4().hex}"
        self.trace_id = uuid4().hex
        self.events: list[RuntimeTraceEvent] = []
        self.context = dict(_EVALUATION.get() or {})
        self._current: ContextVar[Observation | None] = ContextVar(
            f"observation_{self.execution_id}", default=None
        )
        sink = get_langfuse_sink()
        self.sink = sink if sink is not None and sink.accepts(self.trace_id) else None

    @property
    def current(self) -> Observation | None:
        return self._current.get()

    @contextmanager
    def scope(
        self,
        name: str,
        kind: str,
        start_event: TraceEventType | None,
        end_event: TraceEventType | None,
        *,
        agent_name: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
        input: Any = None,
    ) -> Iterator[Observation]:
        parent = self.current
        observation = Observation(
            name=name,
            kind=kind,
            span_id=uuid4().hex[:16],
            parent_span_id=parent.span_id if parent else None,
            started_at=datetime.now(UTC),
            started_perf=perf_counter(),
            agent_name=agent_name or (parent.agent_name if parent else None),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            model=model,
            provider=provider,
            metadata=safe_metadata({**self.context, "provider": provider, **(metadata or {})}),
        )
        if self.sink and (parent is None or parent.handle is not None):
            observation.handle = self.sink.start(
                trace_id=self.trace_id,
                workflow_id=self.workflow_id,
                parent=parent.handle if parent else None,
                name=name,
                kind=kind,
                metadata={
                    **observation.metadata,
                    "workflow_id": self.workflow_id,
                    "execution_id": self.execution_id,
                },
                input=input,
                model=model,
            )
            if observation.handle is not None:
                observation.span_id = observation.handle.id
        token = self._current.set(observation)
        active_token = _ACTIVE_TRACER.set(self)
        error: BaseException | None = None
        try:
            if start_event is not None:
                start = self.emit(
                    start_event, input_summary=_summary(input), export=False, starting=True
                )
                observation.start_event_id = start.event_id
            try:
                yield observation
            except BaseException as exc:
                error = exc
                observation.metadata.setdefault("outcome", "error")
                if observation.metadata["outcome"] == "error":
                    observation.metadata["error_type"] = type(exc).__name__
                raise
            finally:
                observation.metadata.setdefault("outcome", "success")
                if end_event is not None:
                    self.emit(
                        end_event,
                        parent_event_id=observation.start_event_id,
                        output_summary=_summary(observation.output),
                        error=error,
                        usage=observation.usage,
                        started_at=observation.started_at,
                        started_perf=observation.started_perf,
                        export=False,
                    )
        finally:
            try:
                if self.sink:
                    self.sink.finish(
                        observation.handle,
                        output=observation.output,
                        metadata=observation.metadata,
                        usage=observation.usage,
                        cost=calculate_cost_usd(provider, model, observation.usage)
                        if observation.usage
                        else None,
                    )
            finally:
                _ACTIVE_TRACER.reset(active_token)
                self._current.reset(token)

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
        error: BaseException | None = None,
        started_at: datetime | None = None,
        started_perf: float | None = None,
        metadata: dict[str, Any] | None = None,
        export: bool = True,
        starting: bool = False,
    ) -> RuntimeTraceEvent:
        current = self.current
        finished = datetime.now(UTC)
        duration = (
            max(0, int((perf_counter() - started_perf) * 1000)) if started_perf is not None else 0
        )
        started = started_at or (finished - timedelta(milliseconds=duration))
        use = usage or LLMUsage()
        model = model or (current.model if current else None)
        provider = provider or (current.provider if current else None)
        event = RuntimeTraceEvent(
            event_id=f"trace_{uuid4().hex}",
            workflow_id=self.workflow_id,
            execution_id=self.execution_id,
            trace_id=self.trace_id,
            span_id=current.span_id if current else None,
            parent_span_id=current.parent_span_id if current else None,
            sequence=len(self.events) + 1,
            metadata=safe_metadata(
                {**self.context, **(current.metadata if current else {}), **(metadata or {})}
            ),
            event_type=event_type,
            parent_event_id=parent_event_id or (current.start_event_id if current else None),
            agent_name=agent_name or (current.agent_name if current else None),
            tool_name=tool_name or (current.tool_name if current else None),
            tool_call_id=tool_call_id or (current.tool_call_id if current else None),
            started_at=started,
            finished_at=None if starting else finished,
            duration_ms=None if starting else duration,
            model=model,
            provider=provider,
            prompt_tokens=use.prompt_tokens,
            completion_tokens=use.completion_tokens,
            cached_tokens=use.cached_tokens,
            total_tokens=use.total_tokens,
            cost_usd=calculate_cost_usd(provider, model, use),
            input_summary=sanitize_text(input_summary),
            output_summary=sanitize_text(output_summary),
            error_type=type(error).__name__ if error else None,
            error_message=sanitize_text(str(error)) if error else None,
        )
        record_runtime_trace_event(event.model_dump(mode="json"))
        self.events.append(event)
        if current and current.kind == "tool" and event_type == TraceEventType.TOOL_CALL:
            current.start_event_id = event.event_id
            current.tool_call_id = event.tool_call_id
            current.metadata["tool_call_id"] = event.tool_call_id
        if export and self.sink and (current is None or current.handle is not None):
            self.sink.event(
                parent=current.handle if current else None,
                trace_id=self.trace_id,
                workflow_id=self.workflow_id,
                name=event_type.value.lower(),
                metadata={
                    **event.metadata,
                    "event_id": event.event_id,
                    "event_type": event_type.value,
                    "agent_name": event.agent_name,
                    "tool_name": event.tool_name,
                    "error_type": event.error_type,
                },
            )
        if event_type in {
            TraceEventType.ERROR,
            TraceEventType.RETRY,
            TraceEventType.WORKFLOW_END,
            TraceEventType.HUMAN_WAIT,
        }:
            logging.getLogger("harbor_agent.runtime").log(
                logging.WARNING if event.error_type else logging.INFO,
                event_type.value.lower(),
                extra={
                    "context": {
                        "workflow_id": self.workflow_id,
                        "execution_id": self.execution_id,
                        "trace_id": self.trace_id,
                        "event_id": event.event_id,
                        "agent_name": event.agent_name,
                        "tool_name": event.tool_name,
                        "error_type": event.error_type,
                        "status": event.metadata.get("status"),
                    }
                },
            )
        return event

    def persisted(self) -> list[dict[str, Any]]:
        return list_runtime_trace_events(self.workflow_id)


def observed_completion(provider: Any, **kwargs: Any) -> Any:
    tracer = _ACTIVE_TRACER.get()
    if tracer is None:
        return provider.complete(**kwargs)
    messages = kwargs.get("messages") or []
    metadata = {
        "mode": provider_mode(provider),
        "message_count": len(messages),
        "attempt": tracer.current.metadata.get("attempt") if tracer.current else None,
        "cost_basis": "configured_token_prices",
        "prompt_version": hashlib.sha256(
            json.dumps(
                [message.get("content") for message in messages if message.get("role") == "system"],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:16],
    }
    capture = tracer.context.get("synthetic_content") is True
    input = (
        safe_content(messages)
        if capture
        else {
            "message_count": len(messages),
            "allowed_tools": [
                item.get("function", {}).get("name") for item in kwargs.get("tools") or []
            ],
        }
    )
    with tracer.scope(
        "model.proposal",
        "generation",
        TraceEventType.LLM_REQUEST,
        TraceEventType.LLM_RESPONSE,
        model=provider.name,
        provider=provider.provider,
        metadata=metadata,
        input=input,
    ) as observation:
        try:
            response = provider.complete(**kwargs)
        except Exception as exc:
            observation.usage = getattr(exc, "usage", None)
            observation.metadata.update(
                received_response=bool(getattr(exc, "received_response", False)),
                http_status=getattr(exc, "http_status", None),
            )
            raise
        observation.usage = response.usage
        observation.metadata["received_response"] = True
        observation.output = (
            safe_content(response.model_dump(mode="json"))
            if capture
            else _proposal_summary(response, kwargs.get("tools") or [])
        )
        return response


def _proposal_summary(response: Any, schemas: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_tools = {item.get("function", {}).get("name") for item in schemas}
    summary: dict[str, Any] = {
        "proposed_tools": [
            call.name if call.name in allowed_tools else "unknown_tool"
            for call in response.tool_calls
        ],
        "tool_calls": len(response.tool_calls),
    }
    candidate = response.json_content
    if candidate is None and response.content:
        try:
            candidate = json.loads(response.content)
        except (ValueError, TypeError):
            pass
    if isinstance(candidate, dict):
        decision = candidate.get("decision")
        target = candidate.get("next_agent")
        if not response.tool_calls and isinstance(candidate.get("tool_calls"), list):
            calls = candidate["tool_calls"]
            summary["tool_calls"] = len(calls)
            summary["proposed_tools"] = [
                call["tool_name"]
                if isinstance(call, dict)
                and isinstance(call.get("tool_name"), str)
                and call["tool_name"] in allowed_tools
                else "unknown_tool"
                for call in calls
            ]
        if isinstance(decision, str) and decision in DecisionType._value2member_map_:
            summary["decision"] = decision
        if isinstance(target, str) and target in SPECIALIST_AGENTS | {SUPERVISOR_AGENT}:
            summary["next_agent"] = target
    return summary


def arguments_digest(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _summary(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)
