from __future__ import annotations

from pathlib import Path

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput


def load_sample() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )


def test_assessment_workflow_runs_all_agents() -> None:
    result = WorkflowOrchestrator(MockLLMProvider()).run_assessment(load_sample())

    assert result.assessment.overall_level in {"A", "A-", "B+", "B", "C+", "C"}
    assert result.evidence.recommended_uploads
    assert result.recommendations
    assert result.timeline
    assert result.writing.outline
    assert [event.node for event in result.trace] == [
        "ProfileAgent",
        "EvidenceAgent",
        "EvaluationAgent",
        "ProgramIntelligenceAgent",
        "SchoolMatchingAgent",
        "TimelineAgent",
        "WritingAgent",
        "ReviewAgent",
    ]


def test_recommended_programs_do_not_violate_hard_rules() -> None:
    result = WorkflowOrchestrator(MockLLMProvider()).run_assessment(load_sample())
    selected = [item for item in result.recommendations if item.tier != "not_recommended"]

    assert selected
    assert all(item.hard_rule_passed for item in selected)
    assert all(item.score_breakdown for item in selected[:5])
    assert all(item.formal_recommendation is False for item in selected[:5])
    assert all(item.score_breakdown["data_trust"] < 60 for item in selected[:5])
    assert all(
        check.passed
        for item in selected
        for check in item.rule_checks
        if check.severity == "hard"
    )


def test_partial_program_source_requires_data_review() -> None:
    payload = load_sample()
    payload.discipline_interests = ["design"]
    payload.raw_interest_text = "design portfolio urban design architecture portfolio"
    result = WorkflowOrchestrator(MockLLMProvider()).run_assessment(payload)

    uncertain_ids = result.review["programs_requiring_data_review"]
    assert uncertain_ids
    assert result.review["passed"] is False
    assert any(item.program.data_status.value != "VERIFIED" for item in result.recommendations)
    assert result.recommendations[0].program.id in uncertain_ids
