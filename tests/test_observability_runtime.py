from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from harbor_agent.evals.model_replay import PolicyEnvelopeReplayProvider
from harbor_agent.evals.runner import AgentEvalRunner
from harbor_agent.observability import langfuse_sink
from harbor_agent.observability.logging import RuntimeLogFormatter


def test_resume_has_separate_executions_in_one_workflow():
    runner = AgentEvalRunner()
    case = next(case for case in runner.load_cases() if case.case_id == "resume_after_user")
    result = runner.run_case(case)
    assert result["passed"]
    events = result["trace_events"]
    starts = [event for event in events if event["event_type"] == "WORKFLOW_STARTED"]
    ends = [event for event in events if event["event_type"] == "WORKFLOW_END"]
    assert len(starts) == len(ends) == 2
    assert len({event["workflow_id"] for event in events}) == 1
    assert len({event["execution_id"] for event in starts}) == 2
    assert len({event["trace_id"] for event in starts}) == 2
    assert [event["metadata"]["action"] for event in starts] == ["start", "resume"]
    assert ends[0]["metadata"]["status"] == "WAITING_USER"
    assert ends[1]["metadata"]["status"] == "COMPLETED"
    for start, end in zip(starts, ends):
        assert start["span_id"] == end["span_id"]
        assert start["parent_span_id"] is None
        assert end["parent_event_id"] == start["event_id"]
        assert start["duration_ms"] is None
        assert end["duration_ms"] >= 0
        assert datetime.fromisoformat(start["started_at"]) <= datetime.fromisoformat(
            end["finished_at"]
        )
        execution = [event for event in events if event["execution_id"] == start["execution_id"]]
        assert [event["sequence"] for event in execution] == list(range(1, len(execution) + 1))


def test_human_gate_is_a_wait_not_an_executed_tool():
    runner = AgentEvalRunner()
    case = next(case for case in runner.load_cases() if case.case_id == "human_escalation")
    result = runner.run_case(case)
    assert result["passed"] and result["status"] == "WAITING_HUMAN"
    events = result["trace_events"]
    call = next(event for event in events if event["event_type"] == "TOOL_CALL")
    end = next(event for event in events if event["event_type"] == "TOOL_RESULT")
    assert end["tool_call_id"] == call["tool_call_id"]
    assert end["span_id"] == call["span_id"]
    assert end["parent_event_id"] == call["event_id"]
    assert end["metadata"]["tool_executed"] is False
    assert end["metadata"]["outcome"] == "waiting_human"
    assert end["error_type"] is None
    assert events[-1]["event_type"] == "WORKFLOW_END"


def test_eval_scores_link_each_execution_and_report_actual_mode(monkeypatch):
    class Scores:
        def __init__(self):
            self.calls = []

        def score(self, **kwargs):
            self.calls.append(kwargs)

    sink = Scores()
    monkeypatch.setattr("harbor_agent.evals.runner.get_langfuse_sink", lambda: sink)
    runner = AgentEvalRunner(llm=PolicyEnvelopeReplayProvider(), model_driven=True)
    case = next(
        case for case in runner.load_cases() if case.case_id == "normal_background_assessment"
    )
    result = runner.run_case(case)
    assert result["passed"] and result["mode"] == "model_replay"
    assert sink.calls == [
        {"trace_id": trace_id, "case_id": case.case_id, "passed": True}
        for trace_id in result["trace_ids"]
    ]
    # This fixture invokes deterministic tools even in a model-replay suite.
    case = next(case for case in runner.load_cases() if case.case_id == "source_fetch_failure")
    assert runner.run_case(case)["mode"] == "deterministic"


def test_human_resolution_is_inside_resume_execution():
    runner = AgentEvalRunner()
    case = next(case for case in runner.load_cases() if case.case_id == "resume_after_human")
    result = runner.run_case(case)
    assert result["passed"]
    events = result["trace_events"]
    resolution = next(event for event in events if event["event_type"] == "HUMAN_RESOLUTION")
    start = next(event for event in events if event["event_type"] == "WORKFLOW_STARTED")
    assert start["metadata"]["action"] == "resume"
    assert resolution["execution_id"] == start["execution_id"]
    assert resolution["span_id"] == start["span_id"]
    assert resolution["metadata"]["action"] == "resolve_conflicts"
    assert resolution["metadata"]["conflict_count"] == 1


def test_synthetic_capture_rejects_custom_dataset(tmp_path):
    with pytest.raises(ValueError, match="repository evaluation fixtures"):
        AgentEvalRunner(cases_path=tmp_path / "private.json", capture_synthetic_content=True)


def test_exported_token_buckets_do_not_double_count_cache():
    from harbor_agent.llm.response import LLMUsage

    class Handle:
        def update(self, **kwargs):
            self.values = kwargs

        def end(self):
            pass

    sink = langfuse_sink.LangfuseSink(None)
    handle = Handle()
    sink.finish(
        handle,
        output=None,
        metadata={},
        usage=LLMUsage(prompt_tokens=10, cached_tokens=4, completion_tokens=2),
        cost=None,
    )
    assert handle.values["usage_details"] == {"input": 6, "input_cached_tokens": 4, "output": 2}
    sink.finish(
        handle,
        output=None,
        metadata={},
        usage=LLMUsage(prompt_tokens=10, cached_tokens=99, completion_tokens=2),
        cost=None,
    )
    assert handle.values["usage_details"] == {"input": 10, "output": 2}


def test_missing_credentials_disables_remote_export(monkeypatch):
    from harbor_agent.config import Settings

    settings = Settings(
        _env_file=None, langfuse_enabled=True, langfuse_public_key=None, langfuse_secret_key=None
    )
    monkeypatch.setattr(langfuse_sink, "get_settings", lambda: settings)
    assert langfuse_sink.get_langfuse_sink() is None


def test_unavailable_optional_sdk_disables_remote_export(monkeypatch):
    import builtins

    from harbor_agent.config import Settings

    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    )
    monkeypatch.setattr(langfuse_sink, "get_settings", lambda: settings)
    original_import = builtins.__import__

    def import_without_sdk(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("SDK not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_sdk)
    assert langfuse_sink.get_langfuse_sink() is None


def test_proposal_summary_handles_json_calls_without_exporting_unknown_strings():
    from harbor_agent.llm.response import LLMResponse
    from harbor_agent.observability.trace import _proposal_summary

    response = LLMResponse(
        json_content={
            "decision": "CALL_TOOL",
            "next_agent": "Private Student Name",
            "tool_calls": [
                {"tool_name": "lookup", "arguments": {"name": "Private Student Name"}},
                {"tool_name": "Private Student Name"},
            ],
        }
    )
    summary = _proposal_summary(response, [{"function": {"name": "lookup"}}])
    assert summary == {
        "decision": "CALL_TOOL",
        "tool_calls": 2,
        "proposed_tools": ["lookup", "unknown_tool"],
    }


def test_application_lifespan_initializes_and_shuts_down_exporter(monkeypatch):
    from harbor_agent import app as application

    calls = []
    monkeypatch.setattr(application, "configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(application, "get_langfuse_sink", lambda: calls.append("start"))
    monkeypatch.setattr(application, "shutdown_observability", lambda: calls.append("shutdown"))

    async def run():
        async with application.lifespan(application.app):
            assert calls == ["logging", "start"]

    asyncio.run(run())
    assert calls == ["logging", "start", "shutdown"]


def test_structured_diagnostics_have_correlation_without_exception_payload():
    import logging

    record = logging.LogRecord(
        "harbor_agent.runtime", logging.ERROR, "", 0, "model.failed", (), None
    )
    record.context = {
        "workflow_id": "workflow_test",
        "execution_id": "execution_test",
        "trace_id": "abcd",
        "error_type": "RuntimeError",
        "exception": "secret raw provider body",
        "profile": {"name": "Student Name"},
    }
    rendered = RuntimeLogFormatter().format(record)
    payload = json.loads(rendered)
    assert payload["trace_id"] == "abcd"
    assert payload["event"] == "model.failed"
    assert payload["error_type"] == "RuntimeError"
    assert "secret" not in rendered and "Student Name" not in rendered
