from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from harbor_agent.config import get_settings
from harbor_agent.llm.response import LLMResponse, LLMUsage
from harbor_agent.observability import langfuse_sink
from harbor_agent.observability import trace as trace_module
from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.langfuse_sink import LangfuseSink
from harbor_agent.observability.trace import RuntimeTracer, observed_completion
from harbor_agent.services import agent_runtime


class _Provider:
    name = "gpt-test"
    provider = "openai"

    def complete(self, **_: Any) -> LLMResponse:
        return LLMResponse(
            json_content={"decision": "COMPLETE"},
            usage=LLMUsage(prompt_tokens=11, completion_tokens=7, cached_tokens=3),
            model=self.name,
            provider=self.provider,
        )


def _langfuse_sink(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sample_rate: float = 1.0,
) -> tuple[LangfuseSink, Any, Any, list[httpx.Request]]:
    pytest.importorskip("langfuse")
    import langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    settings = get_settings()
    public_key = f"pk-test-{uuid4().hex}"
    secret_key = f"sk-test-{uuid4().hex}"
    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", SecretStr(public_key))
    monkeypatch.setattr(settings, "langfuse_secret_key", SecretStr(secret_key))
    monkeypatch.setattr(settings, "langfuse_base_url", "http://127.0.0.1:9999")
    monkeypatch.setattr(settings, "langfuse_sample_rate", sample_rate)

    real_constructor = langfuse.Langfuse

    def constructor(**kwargs: Any) -> Any:
        kwargs.update(
            tracer_provider=provider,
            span_exporter=exporter,
            httpx_client=httpx.Client(transport=httpx.MockTransport(transport)),
            flush_at=1,
            flush_interval=0.01,
        )
        return real_constructor(**kwargs)

    monkeypatch.setattr(langfuse, "Langfuse", constructor)
    langfuse_sink.get_langfuse_sink.cache_clear()
    sink = langfuse_sink.get_langfuse_sink()
    assert sink is not None
    return sink, exporter, sink.client, requests


def test_langfuse_hierarchy_has_local_ids_session_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink, exporter, _, _ = _langfuse_sink(monkeypatch)
    original_sink = trace_module.get_langfuse_sink
    trace_module.get_langfuse_sink = lambda: sink
    try:
        tracer = RuntimeTracer("workflow-hierarchy")
        with tracer.scope(
            "workflow.run",
            "span",
            TraceEventType.WORKFLOW_STARTED,
            TraceEventType.WORKFLOW_END,
            input={"goal": "test"},
        ) as root:
            with tracer.scope(
                "reviewer",
                "agent",
                TraceEventType.AGENT_STARTED,
                TraceEventType.AGENT_END,
                agent_name="ReviewerAgent",
            ) as agent:
                observed_completion(
                    _Provider(),
                    messages=[{"role": "user", "content": "A prompt that must stay local."}],
                )
                with tracer.scope(
                    "catalog.lookup",
                    "tool",
                    TraceEventType.TOOL_CALL,
                    TraceEventType.TOOL_RESULT,
                    agent_name="ReviewerAgent",
                    tool_name="catalog.lookup",
                    tool_call_id="call-1",
                    input={"query": "course"},
                ) as tool:
                    tool.output = {"items": 1}
            root.output = {"status": "COMPLETED"}

        sink.client.flush()
        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert set(spans) == {"workflow.run", "reviewer", "model.proposal", "catalog.lookup"}
        root_span = spans["workflow.run"]
        agent_span = spans["reviewer"]
        generation_span = spans["model.proposal"]
        tool_span = spans["catalog.lookup"]

        expected_trace_id = int(tracer.trace_id, 16)
        assert all(span.context.trace_id == expected_trace_id for span in spans.values())
        assert root_span.attributes["langfuse.internal.as_root"] is True
        assert agent_span.parent is not None
        assert agent_span.parent.span_id == root_span.context.span_id
        assert generation_span.parent is not None
        assert generation_span.parent.span_id == agent_span.context.span_id
        assert tool_span.parent is not None
        assert tool_span.parent.span_id == agent_span.context.span_id
        assert all(span.attributes["session.id"] == "workflow-hierarchy" for span in spans.values())

        persisted = tracer.persisted()
        assert persisted
        assert {event["trace_id"] for event in persisted} == {tracer.trace_id}
        assert {event["execution_id"] for event in persisted} == {tracer.execution_id}
        assert root.span_id == root_span.context.span_id.to_bytes(8, "big").hex()
        assert agent.span_id == agent_span.context.span_id.to_bytes(8, "big").hex()
        assert generation_span.context.span_id.to_bytes(8, "big").hex() in {
            event["span_id"] for event in persisted if event["event_type"] == "LLM_RESPONSE"
        }
        assert tool.span_id == tool_span.context.span_id.to_bytes(8, "big").hex()
        assert all(event["span_id"] is not None for event in persisted)
        assert all(event["parent_span_id"] == agent.span_id for event in persisted if event["event_type"] in {"LLM_REQUEST", "LLM_RESPONSE", "TOOL_CALL", "TOOL_RESULT"})
    finally:
        trace_module.get_langfuse_sink = original_sink
        sink.client.flush()


def test_default_completion_export_excludes_prompt_and_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    sink, exporter, _, _ = _langfuse_sink(monkeypatch)
    original_sink = trace_module.get_langfuse_sink
    trace_module.get_langfuse_sink = lambda: sink
    try:
        tracer = RuntimeTracer("workflow-privacy")
        with tracer.scope("workflow.run", "span", None, None) as observation:
            observed_completion(
                _Provider(),
                messages=[
                    {
                        "role": "system",
                        "content": "Private prompt jane.doe@example.com +1 555 555 5555",
                    },
                    {"role": "user", "content": "Do not export this prompt."},
                ],
            )
            observation.output = {"status": "ok"}

        sink.client.flush()
        spans = exporter.get_finished_spans()
        generation = next(span for span in spans if span.name == "model.proposal")
        serialized = json.dumps(dict(generation.attributes), ensure_ascii=False)
        assert "Private prompt" not in serialized
        assert "Do not export this prompt" not in serialized
        assert "jane.doe@example.com" not in serialized
        assert "+1 555 555 5555" not in serialized
        assert "message_count" in serialized
        assert "prompt_version" in serialized
        persisted = json.dumps(tracer.persisted(), ensure_ascii=False)
        assert "Private prompt" not in persisted
        assert "Do not export this prompt" not in persisted
        assert "jane.doe@example.com" not in persisted
        assert "+1 555 555 5555" not in persisted
    finally:
        trace_module.get_langfuse_sink = original_sink
        sink.client.flush()


def test_sdk_mask_callback_sanitizes_actual_export(monkeypatch: pytest.MonkeyPatch) -> None:
    sink, exporter, client, _ = _langfuse_sink(monkeypatch)
    try:
        raw = client.start_observation(
            name="raw-sdk-observation",
            as_type="span",
            input={
                "secret": "abc",
                "email": "alice@example.com",
                "phone": "+1 555 555 5555",
            },
            metadata={"email": "alice@example.com"},
        )
        raw.update(
            output={
                "secret": "abc",
                "email": "alice@example.com",
                "phone": "+1 555 555 5555",
            }
        )
        raw.end()
        sink.client.flush()

        exported = next(span for span in exporter.get_finished_spans() if span.name == "raw-sdk-observation")
        assert "alice@example.com" not in json.dumps(dict(exported.attributes), ensure_ascii=False)
        assert "+1 555 555 5555" not in json.dumps(dict(exported.attributes), ensure_ascii=False)
        assert json.loads(exported.attributes["langfuse.observation.input"])["secret"] == "[redacted]"
    finally:
        sink.client.flush()


def test_score_export_flushes_to_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    sink, _, client, requests = _langfuse_sink(monkeypatch)
    trace_id = "0123456789abcdef0123456789abcdef"

    sink.score(trace_id=trace_id, case_id="case-42", passed=True)
    client.flush()

    ingestion_requests = [
        request for request in requests if "/api/public/ingestion" in str(request.url)
    ]
    assert len(ingestion_requests) == 1
    payload = json.loads(ingestion_requests[0].content)
    assert payload["metadata"]["batch_size"] == 1
    assert len(payload["batch"]) == 1
    score = payload["batch"][0]
    assert score["type"] == "score-create"
    assert score["body"] == {
        "id": f"{trace_id}-case-passed",
        "name": "case_passed",
        "environment": "development",
        "value": 1.0,
        "metadata": {"case_id": "case-42"},
        "traceId": trace_id,
        "dataType": "BOOLEAN",
    }


def test_sync_langfuse_failures_do_not_escape_runtime_boundary() -> None:
    class BrokenHandle:
        id = "0123456789abcdef"

        def update(self, **_: Any) -> None:
            raise RuntimeError("update unavailable")

        def end(self) -> None:
            raise RuntimeError("end unavailable")

    class BrokenClient:
        def start_observation(self, **_: Any) -> Any:
            raise RuntimeError("start unavailable")

        def create_event(self, **_: Any) -> None:
            raise RuntimeError("event unavailable")

        def create_score(self, **_: Any) -> None:
            raise RuntimeError("score unavailable")

        def shutdown(self) -> None:
            raise RuntimeError("shutdown unavailable")

    sink = LangfuseSink(BrokenClient())
    assert sink.start(
        trace_id="0123456789abcdef0123456789abcdef",
        workflow_id="workflow-errors",
        parent=None,
        name="workflow.run",
        kind="span",
        metadata={},
    ) is None
    sink.finish(
        BrokenHandle(),
        output={"ok": True},
        metadata={"outcome": "success"},
        usage=None,
        cost=None,
    )
    sink.event(
        parent=None,
        trace_id="0123456789abcdef0123456789abcdef",
        workflow_id="workflow-errors",
        name="runtime_event",
        metadata={},
    )
    sink.score(trace_id="0123456789abcdef0123456789abcdef", case_id="case-1", passed=True)

    original_sink = trace_module.get_langfuse_sink
    trace_module.get_langfuse_sink = lambda: sink
    try:
        tracer = RuntimeTracer("workflow-errors")
        with tracer.scope("workflow.run", "span", None, None):
            response = observed_completion(_Provider(), messages=[])
        assert isinstance(response, LLMResponse)
        assert tracer.persisted()
    finally:
        trace_module.get_langfuse_sink = original_sink
    sink.shutdown()


def test_sampling_zero_keeps_local_trace_events(monkeypatch: pytest.MonkeyPatch) -> None:
    sink, exporter, client, requests = _langfuse_sink(monkeypatch, sample_rate=0.0)
    monkeypatch.setattr(trace_module, "get_langfuse_sink", lambda: sink)
    tracer = RuntimeTracer("workflow-sampled-out")

    with tracer.scope(
        "workflow.run",
        "span",
        TraceEventType.WORKFLOW_STARTED,
        TraceEventType.WORKFLOW_END,
    ):
        tracer.emit(TraceEventType.AGENT_STARTED, agent_name="SampledOutAgent")
    sink.score(trace_id=tracer.trace_id, case_id="sampled-out", passed=True)
    client.flush()

    assert tracer.sink is None
    assert exporter.get_finished_spans() == ()
    assert requests == []
    events = tracer.persisted()
    assert [event["event_type"] for event in events] == [
        "WORKFLOW_STARTED",
        "AGENT_STARTED",
        "WORKFLOW_END",
    ]
    assert {event["trace_id"] for event in events} == {tracer.trace_id}
    assert all(event["span_id"] is not None for event in events)


def test_concurrent_traces_do_not_cross_workflow_or_local_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink, exporter, client, _ = _langfuse_sink(monkeypatch)
    original_sink = trace_module.get_langfuse_sink
    trace_module.get_langfuse_sink = lambda: sink
    agent_runtime._ensure_multi_agent_schema()
    root_barrier = Barrier(2)
    generation_barrier = Barrier(2)

    def run(workflow_id: str) -> tuple[str, str, list[dict[str, Any]]]:
        tracer = RuntimeTracer(workflow_id)
        with (
            tracer.scope(
                "workflow.run",
                "span",
                TraceEventType.WORKFLOW_STARTED,
                TraceEventType.WORKFLOW_END,
            ),
            tracer.scope(
                "agent",
                "agent",
                TraceEventType.AGENT_STARTED,
                TraceEventType.AGENT_END,
                agent_name=workflow_id,
            ),
        ):
            root_barrier.wait(timeout=10)
            with tracer.scope(
                "model.proposal",
                "generation",
                TraceEventType.LLM_REQUEST,
                TraceEventType.LLM_RESPONSE,
                model="gpt-test",
                provider="mock",
            ) as generation:
                generation.output = {"workflow_id": workflow_id}
                generation.usage = LLMUsage(prompt_tokens=2, completion_tokens=1)
                generation_barrier.wait(timeout=10)
        return tracer.trace_id, tracer.execution_id, tracer.persisted()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(run, ("workflow-concurrent-a", "workflow-concurrent-b"))
        client.flush()
    finally:
        trace_module.get_langfuse_sink = original_sink

    assert first[0] != second[0]
    assert first[1] != second[1]
    spans = exporter.get_finished_spans()
    assert len(spans) == 6
    for workflow_id, result in zip(
        ("workflow-concurrent-a", "workflow-concurrent-b"),
        (first, second),
    ):
        trace_id, execution_id, events = result
        assert events
        assert {event["workflow_id"] for event in events} == {workflow_id}
        assert {event["trace_id"] for event in events} == {trace_id}
        assert {event["execution_id"] for event in events} == {execution_id}

        own_spans = [span for span in spans if span.attributes["session.id"] == workflow_id]
        assert {span.name for span in own_spans} == {"workflow.run", "agent", "model.proposal"}
        assert {span.context.trace_id for span in own_spans} == {int(trace_id, 16)}
        root = next(span for span in own_spans if span.name == "workflow.run")
        agent = next(span for span in own_spans if span.name == "agent")
        generation = next(span for span in own_spans if span.name == "model.proposal")
        assert root.attributes["langfuse.internal.as_root"] is True
        assert agent.parent is not None and agent.parent.span_id == root.context.span_id
        assert generation.parent is not None and generation.parent.span_id == agent.context.span_id


def test_reentering_same_event_is_idempotent_and_changed_payload_is_rejected() -> None:
    event = {
        "event_id": "trace_reentry",
        "workflow_id": "workflow-reentry",
        "execution_id": "execution-reentry",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "span_id": "0123456789abcdef",
        "parent_span_id": None,
        "sequence": 1,
        "metadata": {"event_type": "LLM_RESPONSE"},
        "parent_event_id": None,
        "event_type": "LLM_RESPONSE",
        "agent_name": "ReviewerAgent",
        "tool_name": None,
        "tool_call_id": None,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": 10,
        "model": "gpt-test",
        "provider": "openai",
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "cached_tokens": 3,
        "total_tokens": 18,
        "cost_usd": 0.01,
        "input_summary": "message_count=1",
        "output_summary": "tool_calls=0",
        "error_type": None,
        "error_message": None,
    }

    agent_runtime.record_runtime_trace_event(event)
    agent_runtime.record_runtime_trace_event(dict(event))
    with sqlite3.connect(agent_runtime.DB_PATH) as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM runtime_trace_events WHERE event_id = ?",
            (event["event_id"],),
        ).fetchone()[0]
        usage_count = connection.execute(
            "SELECT COUNT(*) FROM llm_usage WHERE trace_event_id = ?",
            (event["event_id"],),
        ).fetchone()[0]
    assert event_count == 1
    assert usage_count == 1

    changed = dict(event, output_summary="different output")
    with pytest.raises(ValueError, match="trace event IDs cannot be reused"):
        agent_runtime.record_runtime_trace_event(changed)
