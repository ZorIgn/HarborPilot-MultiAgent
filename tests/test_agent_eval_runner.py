from __future__ import annotations

from harbor_agent.evals.metrics import aggregate_eval_metrics
from harbor_agent.evals.runner import AgentEvalRunner


def test_agent_eval_cases_cover_documented_runtime_boundaries() -> None:
    cases = AgentEvalRunner().load_cases()
    ids = {case.case_id for case in cases}

    assert len(cases) >= 22
    assert {
        "profile_missing_language",
        "cross_major",
        "eligibility_failure",
        "budget_hard_cap",
        "previous_cycle_evidence",
        "deadline_conflict",
        "source_fetch_failure",
        "tool_validation_failure",
        "llm_malformed_output",
        "llm_timeout",
        "tool_retry",
        "human_escalation",
        "critic_replan",
        "community_source_leakage",
        "prompt_injection_source",
        "resume_after_user",
        "resume_after_human",
        "workflow_max_step",
    } <= ids


def test_source_fetch_eval_records_a_safe_rejection() -> None:
    runner = AgentEvalRunner()
    case = next(item for item in runner.load_cases() if item.case_id == "source_fetch_failure")

    result = runner.run_case(case)

    assert result["passed"] is True
    assert result["operation_data"]["ok"] is False
    assert result["operation_data"]["error_type"] == "ToolExecutionError"


def test_previous_cycle_eval_is_self_contained() -> None:
    runner = AgentEvalRunner()
    case = next(item for item in runner.load_cases() if item.case_id == "previous_cycle_evidence")

    result = runner.run_case(case)

    assert result["passed"] is True
    assert "scholarship_deadline" in result["operation_data"]["previous_cycle_fields"]


def test_high_risk_tool_proposal_is_traced_before_human_gate() -> None:
    runner = AgentEvalRunner()
    case = next(item for item in runner.load_cases() if item.case_id == "human_escalation")

    result = runner.run_case(case)

    assert result["passed"] is True
    assert any(
        item.get("event_type") == "TOOL_CALL"
        and item.get("tool_name") == "bind_source_to_program"
        for item in result["trace_events"]
    )



def test_blocked_community_source_is_not_counted_as_leakage() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "passed": True,
                "status": "WAITING_HUMAN",
                "operation": "community_source_leakage",
                "expectations": {"expect_human_review": True},
                "operation_data": {
                    "community_blocked": True,
                    "community_leakage": False,
                    "published": False,
                },
                "trace_events": [],
            }
        ]
    )

    assert metrics["community_leakage_rate"] == 0.0
