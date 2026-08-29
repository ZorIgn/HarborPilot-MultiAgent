from __future__ import annotations

from pathlib import Path

import pytest

from harbor_agent.agents.orchestrator import WorkflowDeliveryBlockedError, WorkflowOrchestrator
from harbor_agent.services.deterministic_profile import normalize_profile
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput


def load_sample() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )


def test_profile_agent_uses_structured_courses_and_skills_for_direction() -> None:
    payload = load_sample()
    payload.discipline_interests = []
    payload.raw_interest_text = ""
    payload.education.major = "Interdisciplinary Studies"
    payload.additional_background.core_courses = ["Machine Learning", "Database Systems"]
    payload.additional_background.skills = ["Python", "SQL"]

    profile = normalize_profile(payload)

    assert {"artificial_intelligence", "data_science", "computer_science"} & set(profile.discipline_tags)
    assert "core courses or prerequisites" not in profile.missing_fields


def test_full_assessment_is_retryably_blocked_without_current_formal_sources() -> None:
    with pytest.raises(WorkflowDeliveryBlockedError) as exc_info:
        WorkflowOrchestrator(MockLLMProvider()).run_assessment(load_sample())

    state = exc_info.value.state
    assert state.status.value == "FAILED_RETRYABLE"
    assert state.working_memory["critic_readiness"] == "BLOCKED"
    assert state.working_memory["critic_blockers"]
    assert state.human_review_item is None
    assert state.human_review_reason is None
    assert state.assessment is not None
    assert state.program_matches
    assert state.writing_ready is False
    assert {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "CriticAgent"} <= set(state.visited_agents)


def test_recommended_programs_do_not_violate_hard_rules() -> None:
    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(load_sample())
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
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    program_plan = orchestrator.run_program_plan_stage(payload)
    selected_ids = [
        item.program.id
        for item in program_plan.recommendations
        if item.tier != "not_recommended"
    ][:2]
    assert selected_ids
    result = orchestrator.run_application_plan_stage(payload, selected_ids)

    uncertain_ids = result.review["programs_requiring_data_review"]
    assert uncertain_ids
    assert result.review["passed"] is False
    assert any(item.program.data_status.value != "VERIFIED" for item in result.selected_programs)
    assert result.selected_programs[0].program.id in uncertain_ids
