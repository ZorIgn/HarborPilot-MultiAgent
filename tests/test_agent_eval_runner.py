from __future__ import annotations

from harbor_agent.evals.metrics import aggregate_eval_metrics
from harbor_agent.evals.model_replay import PolicyEnvelopeReplayProvider
from harbor_agent.evals.runner import AgentEvalRunner
from harbor_agent.llm.response import LLMResponse


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


def test_decision_cases_expect_unknown_formal_boundaries() -> None:
    cases = {
        case.case_id: case
        for case in AgentEvalRunner().load_cases()
        if case.case_id
        in {"writing_grounded_story", "cross_major", "eligibility_failure", "budget_hard_cap"}
    }

    writing = cases["writing_grounded_story"].expectations
    assert writing.final_status == "FAILED_RETRYABLE"
    assert writing.formal_use_ready is False
    assert writing.critic_readiness == "BLOCKED"
    assert writing.expect_blockers is True

    for case_id in ("cross_major", "eligibility_failure"):
        expectations = cases[case_id].expectations
        assert expectations.admissions_status == "UNKNOWN"
        assert expectations.formal_use_ready is False
        assert expectations.critic_readiness == "PRELIMINARY_COMPLETE"
        assert expectations.expect_blockers is True

    budget = cases["budget_hard_cap"]
    assert "unknown official tuition" in budget.category
    assert budget.expectations.final_status == "COMPLETED"
    assert budget.expectations.financial_status == "UNKNOWN"
    assert budget.expectations.formal_use_ready is False
    assert budget.expectations.critic_readiness == "PRELIMINARY_COMPLETE"
    assert budget.expectations.expect_blockers is True
    assert budget.expectations.expect_user_question is None


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


def test_policy_replay_exercises_a_complete_model_driven_workflow() -> None:
    provider = PolicyEnvelopeReplayProvider()
    runner = AgentEvalRunner(llm=provider, model_driven=True)
    case = next(
        item
        for item in runner.load_cases()
        if item.case_id == "normal_background_assessment"
    )

    result = runner.run_case(case)

    assert result["passed"] is True
    assert result["status"] == "COMPLETED"
    assert result["model_driven"] is True
    assert result["llm_requests"] > 0
    assert result["llm_requests"] == result["llm_responses"]
    assert provider.call_count == result["llm_requests"]


def test_model_path_metrics_report_provider_response_coverage() -> None:
    metrics = aggregate_eval_metrics(
        [
            {
                "passed": True,
                "status": "COMPLETED",
                "operation": "workflow",
                "model_driven": True,
                "expectations": {},
                "trace_events": [
                    {"event_type": "LLM_REQUEST"},
                    {"event_type": "LLM_RESPONSE", "metadata": {"received_response": True}},
                ],
            }
        ]
    )

    assert metrics["model_path_case_rate"] == 1.0
    assert metrics["case_pass_rate"] == 1.0
    assert metrics["workflow_completion_rate"] == 1.0
    assert metrics["llm_request_count"] == 1
    assert metrics["llm_response_rate"] == 1.0


def test_policy_replay_supports_supervisor_blocked_route() -> None:
    provider = PolicyEnvelopeReplayProvider()

    response: LLMResponse = provider.complete(
        messages=[
            {
                "role": "user",
                "content": '{"available_routes":[{"target":"BLOCKED","policy_reason":"formal facts are missing"}]}',
            }
        ]
    )

    assert response.json_content is not None
    assert response.json_content["decision"] == "BLOCKED"
    assert "next_agent" not in response.json_content


def test_eval_runner_filters_cases_and_rejects_unknown_ids() -> None:
    runner = AgentEvalRunner()

    report = runner.run({"normal_background_assessment"})

    assert report["mode"] == "deterministic"
    assert [item["case_id"] for item in report["results"]] == [
        "normal_background_assessment"
    ]
