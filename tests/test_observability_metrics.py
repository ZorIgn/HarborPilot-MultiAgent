from __future__ import annotations

from harbor_agent.evals.metrics import aggregate_eval_metrics


def test_error_diagnostics_do_not_duplicate_invalid_tool_attempts():
    metrics = aggregate_eval_metrics(
        [
            {
                "trace_events": [
                    _event("TOOL_RESULT", error_type="ToolArgumentValidationError"),
                    _event("ERROR", error_type="ToolArgumentValidationError"),
                    _event("TOOL_RESULT", metadata={"tool_executed": True}),
                ],
            }
        ]
    )
    assert metrics["tool_argument_validity"] == 0.5


def test_missing_response_marker_and_negative_cost_are_not_success():
    metrics = aggregate_eval_metrics(
        [
            {
                "trace_events": [
                    _event("LLM_REQUEST"),
                    _event("LLM_RESPONSE", cost_usd=-1),
                ],
            }
        ]
    )
    assert metrics["llm_received_response_count"] == 0
    assert metrics["cost_complete"] is False
    assert metrics["known_cost_usd"] is None


def _event(
    event_type: str,
    *,
    duration_ms: int | None = None,
    metadata: dict | None = None,
    **fields: object,
) -> dict:
    event = {
        "event_type": event_type,
        "duration_ms": duration_ms,
        "execution_id": "execution-1",
        "trace_id": "trace-1",
        "span_id": f"span-{event_type.lower()}",
        "parent_span_id": None,
        "metadata": metadata or {},
    }
    event.update(fields)
    return event


def test_eval_metrics_use_case_and_workflow_status_contracts() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "passed": True,
                "operation": "workflow",
                "status": "COMPLETED",
                "formal_use_ready": False,
                "trace_events": [
                    _event("WORKFLOW_STARTED", duration_ms=900),
                    _event("WORKFLOW_END", duration_ms=30, metadata={"status": "WAITING_USER"}),
                    _event("LLM_REQUEST", duration_ms=800, prompt_tokens=100, cost_usd=8.0),
                    _event(
                        "LLM_RESPONSE",
                        duration_ms=10,
                        metadata={"outcome": "success", "received_response": True},
                        prompt_tokens=3,
                        completion_tokens=2,
                        total_tokens=5,
                        cost_usd=0.25,
                    ),
                    _event("TOOL_CALL", duration_ms=700),
                    _event("TOOL_RESULT", duration_ms=7, metadata={"tool_executed": True}),
                ],
            },
            {
                "passed": False,
                "operation": "workflow",
                "status": "FAILED",
                "formal_use_ready": True,
                "trace_events": [
                    _event("WORKFLOW_STARTED", duration_ms=1000),
                    _event("WORKFLOW_END", duration_ms=70, metadata={"status": "COMPLETED"}),
                    _event("LLM_REQUEST", duration_ms=600, prompt_tokens=200),
                    _event(
                        "LLM_RESPONSE",
                        duration_ms=20,
                        metadata={"outcome": "error", "received_response": False},
                        completion_tokens=4,
                    ),
                    _event("TOOL_CALL", duration_ms=500),
                    _event("TOOL_RESULT", duration_ms=14, metadata={"tool_executed": True}),
                ],
            },
            {
                "passed": True,
                "operation": "tool_retry",
                "status": "COMPLETED",
                "trace_events": [
                    _event("WORKFLOW_END", duration_ms=100, metadata={"status": "COMPLETED"})
                ],
            },
        ]
    )

    assert metrics["case_pass_rate"] == 2 / 3
    assert metrics["workflow_completion_rate"] == 0.5
    assert metrics["formal_ready_case_rate"] == 1 / 3
    assert metrics["workflow_execution_p50_latency_ms"] == 30.0
    assert metrics["workflow_execution_p95_latency_ms"] == 70.0
    assert metrics["llm_p50_latency_ms"] == 10.0
    assert metrics["llm_p95_latency_ms"] == 20.0
    assert metrics["tool_p50_latency_ms"] == 7.0
    assert metrics["tool_p95_latency_ms"] == 14.0

    assert metrics["prompt_tokens"] == 3
    assert metrics["completion_tokens"] == 6
    assert metrics["total_tokens"] == 5
    assert metrics["usage_complete"] is False
    assert metrics["known_cost_usd"] == 0.25
    assert metrics["calculated_cost_usd"] is None
    assert metrics["cost_complete"] is False
    assert metrics["llm_response_count"] == 2
    assert metrics["llm_received_response_count"] == 1
    assert metrics["llm_response_rate"] == 0.5

    assert "grounded_official_claim_rate" not in metrics
    assert "actual_cost_usd" not in metrics
    assert "p50_latency_ms" not in metrics


def test_eval_metrics_report_complete_response_cost() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "passed": True,
                "operation": "workflow",
                "trace_events": [
                    _event("LLM_REQUEST"),
                    _event(
                        "LLM_RESPONSE",
                        metadata={"outcome": "success", "received_response": True},
                        prompt_tokens=4,
                        completion_tokens=6,
                        total_tokens=10,
                        cost_usd=0.125,
                    ),
                    _event("LLM_REQUEST"),
                    _event(
                        "LLM_RESPONSE",
                        metadata={"outcome": "success", "received_response": True},
                        prompt_tokens=1,
                        completion_tokens=2,
                        total_tokens=3,
                        cost_usd=0.375,
                    ),
                ],
            }
        ]
    )

    assert metrics["cost_complete"] is True
    assert metrics["known_cost_usd"] == 0.5
    assert metrics["calculated_cost_usd"] == 0.5
    assert metrics["usage_complete"] is True


def test_tool_latency_excludes_approval_gate_results() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "trace_events": [
                    _event("TOOL_RESULT", duration_ms=100, metadata={"tool_executed": False}),
                    _event("TOOL_RESULT", duration_ms=10, metadata={"tool_executed": True}),
                ]
            }
        ]
    )

    assert metrics["tool_p50_latency_ms"] == 10.0
    assert metrics["tool_p95_latency_ms"] == 10.0


def test_unmatched_llm_request_keeps_usage_and_cost_incomplete() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "trace_events": [
                    _event("LLM_REQUEST"),
                    _event(
                        "LLM_RESPONSE",
                        metadata={"received_response": True},
                        prompt_tokens=4,
                        completion_tokens=2,
                        total_tokens=6,
                        cost_usd=0.1,
                    ),
                    _event("LLM_REQUEST"),
                ]
            }
        ]
    )

    assert metrics["usage_complete"] is False
    assert metrics["cost_complete"] is False
    assert metrics["calculated_cost_usd"] is None
