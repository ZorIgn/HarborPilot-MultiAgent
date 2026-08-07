from __future__ import annotations

from math import ceil
from typing import Any, Iterable


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def aggregate_eval_metrics(results: Iterable[dict[str, Any]]) -> dict[str, float | int | None]:
    """Derive runtime-quality metrics from real deterministic traces.

    These values describe deterministic fixtures, not general model quality:
    no missing token/cost value is estimated or inferred.
    """

    items = list(results)
    total = len(items)
    passed = sum(bool(item.get("passed")) for item in items)
    agent_turns = [int(item.get("agent_turns", 0)) for item in items]
    tool_calls = [int(item.get("tool_calls", 0)) for item in items]
    traces = [list(item.get("trace_events", [])) for item in items]
    events = [event for trace in traces for event in trace]
    grounded = sum(item.get("formal_use_ready") is True for item in items)
    human_waits = [item for item in items if item.get("status") == "WAITING_HUMAN"]

    expected_tool_cases = [item for item in items if item.get("expectations", {}).get("expected_tools")]
    correct_tool_cases = 0
    routing_cases = [item for item in items if item.get("expectations", {}).get("must_visit_agents") or item.get("expectations", {}).get("expected_handoffs")]
    correct_routes = 0
    expected_human_cases = [item for item in items if item.get("expectations", {}).get("expect_human_review") is True]
    correct_human = 0
    human_predicted_cases = 0
    recovery_cases = [item for item in items if item.get("operation") in {"llm_malformed_output", "human_resume"} or item.get("resume_user_message")]
    recovered = 0
    replan_cases = [item for item in items if item.get("operation") == "critic_replan"]
    replan_successes = 0
    resume_cases = [item for item in items if item.get("operation") == "human_resume" or item.get("resume_user_message")]
    resume_successes = 0
    unsupported = 0
    community_leaks = 0

    for item in items:
        trace = item.get("trace_events", [])
        observed_tools = {event.get("tool_name") for event in trace if event.get("event_type") == "TOOL_CALL"}
        expectations = item.get("expectations", {})
        expected_tools = set(expectations.get("expected_tools", []))
        if expected_tools and expected_tools.issubset(observed_tools):
            correct_tool_cases += 1
        expected_agents = set(expectations.get("must_visit_agents", []))
        expected_handoffs = set(expectations.get("expected_handoffs", []))
        handoffs = {str(event.get("output_summary") or "") for event in trace if event.get("event_type") == "HANDOFF"}
        if (not expected_agents or expected_agents.issubset(set(item.get("visited_agents", [])))) and (not expected_handoffs or all(any(target in handoff for handoff in handoffs) for target in expected_handoffs)):
            if expected_agents or expected_handoffs:
                correct_routes += 1
        wanted_human = expectations.get("expect_human_review") is True
        actual_human = item.get("status") == "WAITING_HUMAN"
        if wanted_human and actual_human:
            correct_human += 1
        if actual_human:
            human_predicted_cases += 1
        operation_data = item.get("operation_data", {}) or {}
        if operation_data.get("recovered") is True or (item.get("operation") == "human_resume" and item.get("status") == "COMPLETED") or (item.get("resume_user_message") and item.get("status") == "COMPLETED"):
            recovered += 1
        if item.get("operation") == "critic_replan" and operation_data.get("critic_outcome") == "REPLAN_MATCHING":
            replan_successes += 1
        if (item.get("operation") == "human_resume" or item.get("resume_user_message")) and item.get("status") == "COMPLETED":
            resume_successes += 1
        if operation_data.get("published") is True:
            unsupported += 1
        if operation_data.get("community_leakage") is True:
            community_leaks += 1

    tool_events = [event for event in events if event.get("event_type") == "TOOL_CALL"]
    validation_errors = [event for event in events if str(event.get("error_type") or "") == "ToolArgumentValidationError"]
    permission_errors = [event for event in events if str(event.get("error_type") or "") == "ToolPermissionError"]
    durations = [int(event.get("duration_ms")) for event in events if event.get("duration_ms") is not None]
    prompt_tokens = sum(int(event.get("prompt_tokens") or 0) for event in events)
    completion_tokens = sum(int(event.get("completion_tokens") or 0) for event in events)
    known_costs = [float(event["cost_usd"]) for event in events if event.get("cost_usd") is not None]

    return {
        "case_count": total,
        "task_completion_rate": _rate(passed, total),
        "routing_accuracy": _rate(correct_routes, len(routing_cases)),
        "tool_selection_accuracy": _rate(correct_tool_cases, len(expected_tool_cases)),
        "tool_argument_validity": _rate(max(0, len(tool_events) - len(validation_errors)), len(tool_events)),
        "tool_permission_violation_rate": _rate(len(permission_errors), len(tool_events)),
        "recovery_success_rate": _rate(recovered, len(recovery_cases)),
        "human_escalation_precision": _rate(correct_human, human_predicted_cases),
        "human_escalation_recall": _rate(correct_human, len(expected_human_cases)),
        "grounded_official_claim_rate": _rate(grounded, total),
        "unsupported_official_claim_rate": _rate(unsupported, total),
        "community_leakage_rate": _rate(community_leaks, total),
        "critic_replan_success_rate": _rate(replan_successes, len(replan_cases)),
        "checkpoint_resume_success_rate": _rate(resume_successes, len(resume_cases)),
        "human_escalation_rate": _rate(len(human_waits), total),
        "average_agent_turns": _rate(sum(agent_turns), total),
        "average_tool_calls": _rate(sum(tool_calls), total),
        "p50_latency_ms": _percentile(durations, 0.50),
        "p95_latency_ms": _percentile(durations, 0.95),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "trace_event_count": len(events),
        "actual_cost_usd": sum(known_costs) if known_costs else None,
    }
