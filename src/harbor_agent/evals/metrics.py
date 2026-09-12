from __future__ import annotations

from collections.abc import Iterable
from math import ceil, isfinite
from typing import Any


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def _event_type(event: dict[str, Any]) -> str | None:
    """Return an event type for both serialized and enum-backed trace rows."""

    value = event.get("event_type")
    value = getattr(value, "value", value)
    return str(value) if value is not None else None


def _metadata(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("metadata")
    return value if isinstance(value, dict) else {}


def _duration_ms(event: dict[str, Any]) -> int | None:
    """Read a recorded duration without deriving one from instantaneous events."""

    value = event.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _end_event_durations(events: Iterable[dict[str, Any]], event_type: str) -> list[int]:
    return [
        duration
        for event in events
        if _event_type(event) == event_type and (duration := _duration_ms(event)) is not None
    ]


def _known_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) and number >= 0 else None


def _known_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _known_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _actual_tool_result(event: dict[str, Any]) -> bool:
    """Recognize handler execution without treating an approval gate as one."""

    if _event_type(event) != "TOOL_RESULT":
        return False
    value = _metadata(event).get("tool_executed")
    marker = _known_bool(value)
    return marker is True


def _received_response(event: dict[str, Any]) -> bool:
    value = _metadata(event).get("received_response")
    return value is True


def _known_token_sum(events: Iterable[dict[str, Any]], field: str) -> int | None:
    values: list[int] = []
    for event in events:
        value = event.get(field)
        number = _known_integer(value)
        if number is not None:
            values.append(number)
    return sum(values) if values else None


def _workflow_status(item: dict[str, Any], trace: Iterable[dict[str, Any]]) -> str | None:
    """Use the final workflow segment status when the trace records one."""

    end_events = [event for event in trace if _event_type(event) == "WORKFLOW_END"]
    if end_events:
        status = _metadata(end_events[-1]).get("status")
        if status is not None:
            status = getattr(status, "value", status)
            return str(status).rsplit(".", 1)[-1].upper()
    status = item.get("status")
    if status is None:
        return None
    status = getattr(status, "value", status)
    return str(status).rsplit(".", 1)[-1].upper()


def aggregate_eval_metrics(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Derive runtime-quality metrics from recorded evaluation traces.

    Deterministic and model-driven modes remain explicitly labelled; no
    missing token, cost, or model-quality value is estimated or inferred.
    """

    items = list(results)
    total = len(items)
    passed = sum(bool(item.get("passed")) for item in items)
    agent_turns = [int(item.get("agent_turns", 0)) for item in items]
    tool_calls = [int(item.get("tool_calls", 0)) for item in items]
    traces = [list(item.get("trace_events", [])) for item in items]
    events = [event for trace in traces for event in trace]
    formal_ready = sum(item.get("formal_use_ready") is True for item in items)
    human_waits = [item for item in items if item.get("status") == "WAITING_HUMAN"]
    workflow_cases = [item for item in items if item.get("operation", "workflow") == "workflow"]

    expected_tool_cases = [
        item for item in items if item.get("expectations", {}).get("expected_tools")
    ]
    correct_tool_cases = 0
    routing_cases = [
        item
        for item in items
        if item.get("expectations", {}).get("must_visit_agents")
        or item.get("expectations", {}).get("expected_handoffs")
    ]
    correct_routes = 0
    expected_human_cases = [
        item for item in items if item.get("expectations", {}).get("expect_human_review") is True
    ]
    correct_human = 0
    human_predicted_cases = 0
    recovery_cases = [
        item
        for item in items
        if item.get("operation") in {"llm_malformed_output", "human_resume"}
        or item.get("resume_user_message")
    ]
    recovered = 0
    replan_cases = [item for item in items if item.get("operation") == "critic_replan"]
    replan_successes = 0
    resume_cases = [
        item
        for item in items
        if item.get("operation") == "human_resume" or item.get("resume_user_message")
    ]
    resume_successes = 0
    unsupported = 0
    community_leaks = 0
    model_path_cases = 0

    for item in items:
        trace = item.get("trace_events", [])
        observed_tools = {
            event.get("tool_name") for event in trace if _event_type(event) == "TOOL_CALL"
        }
        expectations = item.get("expectations", {})
        expected_tools = set(expectations.get("expected_tools", []))
        if expected_tools and expected_tools.issubset(observed_tools):
            correct_tool_cases += 1
        expected_agents = set(expectations.get("must_visit_agents", []))
        expected_handoffs = set(expectations.get("expected_handoffs", []))
        handoffs = {
            str(event.get("output_summary") or "")
            for event in trace
            if _event_type(event) == "HANDOFF"
        }
        if (
            (not expected_agents or expected_agents.issubset(set(item.get("visited_agents", []))))
            and (
                not expected_handoffs
                or all(
                    any(target in handoff for handoff in handoffs) for target in expected_handoffs
                )
            )
            and (expected_agents or expected_handoffs)
        ):
            correct_routes += 1
        wanted_human = expectations.get("expect_human_review") is True
        actual_human = item.get("status") == "WAITING_HUMAN"
        if wanted_human and actual_human:
            correct_human += 1
        if actual_human:
            human_predicted_cases += 1
        operation_data = item.get("operation_data", {}) or {}
        if (
            operation_data.get("recovered") is True
            or (item.get("operation") == "human_resume" and item.get("status") == "COMPLETED")
            or (item.get("resume_user_message") and item.get("status") == "COMPLETED")
        ):
            recovered += 1
        if (
            item.get("operation") == "critic_replan"
            and operation_data.get("critic_outcome") == "REPLAN_MATCHING"
        ):
            replan_successes += 1
        if (
            item.get("operation") == "human_resume" or item.get("resume_user_message")
        ) and item.get("status") == "COMPLETED":
            resume_successes += 1
        if operation_data.get("published") is True:
            unsupported += 1
        if operation_data.get("community_leakage") is True:
            community_leaks += 1
        if item.get("model_driven") is True:
            model_path_cases += 1

    tool_events = [event for event in events if _event_type(event) == "TOOL_RESULT"]
    validation_errors = [
        event
        for event in tool_events
        if str(event.get("error_type") or "") == "ToolArgumentValidationError"
    ]
    permission_errors = [
        event
        for event in tool_events
        if str(event.get("error_type") or "") == "ToolPermissionError"
    ]
    workflow_events = [event for item in workflow_cases for event in item.get("trace_events", [])]
    workflow_end_durations = _end_event_durations(workflow_events, "WORKFLOW_END")
    llm_response_events = [event for event in events if _event_type(event) == "LLM_RESPONSE"]
    tool_result_durations = [
        duration
        for event in events
        if _actual_tool_result(event) and (duration := _duration_ms(event)) is not None
    ]
    llm_response_durations = _end_event_durations(events, "LLM_RESPONSE")
    prompt_tokens = _known_token_sum(llm_response_events, "prompt_tokens")
    completion_tokens = _known_token_sum(llm_response_events, "completion_tokens")
    response_total_tokens = []
    for event in llm_response_events:
        value = event.get("total_tokens")
        number = _known_integer(value)
        if number is not None:
            response_total_tokens.append(number)
    total_tokens = sum(response_total_tokens) if response_total_tokens else None
    llm_requests = sum(_event_type(event) == "LLM_REQUEST" for event in events)
    llm_responses = len(llm_response_events)
    response_coverage_complete = llm_responses == llm_requests
    usage_complete = (
        bool(llm_response_events)
        and response_coverage_complete
        and all(
            _known_integer(event.get("prompt_tokens")) is not None
            and _known_integer(event.get("completion_tokens")) is not None
            for event in llm_response_events
        )
    )
    known_costs = [
        cost
        for event in llm_response_events
        if (cost := _known_number(event.get("cost_usd"))) is not None
    ]
    known_cost_usd = sum(known_costs) if known_costs else None
    cost_complete = (
        bool(llm_response_events)
        and response_coverage_complete
        and len(known_costs) == len(llm_response_events)
    )
    calculated_cost_usd = known_cost_usd if cost_complete else None
    received_responses = sum(_received_response(event) for event in llm_response_events)
    workflow_completed = sum(
        _workflow_status(item, item.get("trace_events", [])) == "COMPLETED"
        for item in workflow_cases
    )

    return {
        "case_count": total,
        "case_pass_rate": _rate(passed, total),
        "workflow_completion_rate": _rate(workflow_completed, len(workflow_cases)),
        "routing_accuracy": _rate(correct_routes, len(routing_cases)),
        "tool_selection_accuracy": _rate(correct_tool_cases, len(expected_tool_cases)),
        "tool_argument_validity": _rate(
            max(0, len(tool_events) - len(validation_errors)), len(tool_events)
        ),
        "tool_permission_violation_rate": _rate(len(permission_errors), len(tool_events)),
        "recovery_success_rate": _rate(recovered, len(recovery_cases)),
        "human_escalation_precision": _rate(correct_human, human_predicted_cases),
        "human_escalation_recall": _rate(correct_human, len(expected_human_cases)),
        "formal_ready_case_rate": _rate(formal_ready, total),
        "unsupported_official_claim_rate": _rate(unsupported, total),
        "community_leakage_rate": _rate(community_leaks, total),
        "critic_replan_success_rate": _rate(replan_successes, len(replan_cases)),
        "checkpoint_resume_success_rate": _rate(resume_successes, len(resume_cases)),
        "human_escalation_rate": _rate(len(human_waits), total),
        "average_agent_turns": _rate(sum(agent_turns), total),
        "average_tool_calls": _rate(sum(tool_calls), total),
        "workflow_execution_p50_latency_ms": _percentile(workflow_end_durations, 0.50),
        "workflow_execution_p95_latency_ms": _percentile(workflow_end_durations, 0.95),
        "llm_p50_latency_ms": _percentile(llm_response_durations, 0.50),
        "llm_p95_latency_ms": _percentile(llm_response_durations, 0.95),
        "tool_p50_latency_ms": _percentile(tool_result_durations, 0.50),
        "tool_p95_latency_ms": _percentile(tool_result_durations, 0.95),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "usage_complete": usage_complete,
        "trace_event_count": len(events),
        "known_cost_usd": known_cost_usd,
        "calculated_cost_usd": calculated_cost_usd,
        "cost_complete": cost_complete,
        "model_path_case_rate": _rate(model_path_cases, total),
        "llm_request_count": llm_requests,
        "llm_response_count": llm_responses,
        "llm_received_response_count": received_responses,
        "llm_response_rate": _rate(received_responses, llm_requests),
    }
