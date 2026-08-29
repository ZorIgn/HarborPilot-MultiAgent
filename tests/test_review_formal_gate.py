from __future__ import annotations

from pathlib import Path

import pytest

from harbor_agent.agents.critic import CriticAgent
from harbor_agent.models import ApplicantProfileInput, CriticReadiness, ProgramMatch
from harbor_agent.services import data_loader, program_store
from harbor_agent.services.deterministic_assessment import calculate_profile_assessment
from harbor_agent.services.deterministic_profile import normalize_profile
from harbor_agent.runtime.state import AgentState, WorkflowGoal
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.deterministic_review import run_review_gate
from harbor_agent.tools import review_tools
from harbor_agent.tools.base import EmptyToolInput

from test_decision_facts import _upsert, _valid_record


@pytest.fixture
def stored_program():
    data_loader.clear_data_loader_caches()
    program = next(
        item
        for item in data_loader.load_programs()
        if item.id == "cuhk-msc-in-computer-science-2027"
    )
    program_store.seed_program_store(
        [program],
        db_path=program_store.DB_PATH,
        replace=True,
    )
    data_loader.clear_data_loader_caches()
    return program


def _profile_and_assessment() -> tuple[dict, dict]:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    profile = normalize_profile(payload)
    assessment = calculate_profile_assessment(profile)
    return profile.model_dump(mode="json"), assessment.model_dump(mode="json")


def _recommendation_state(
    program,
    *,
    explicit_program_ids: list[str] | None = None,
    cached_hard_rule_passed: bool = True,
) -> AgentState:
    profile, assessment = _profile_and_assessment()
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=82,
        hard_rule_passed=cached_hard_rule_passed,
        reasons=["cached matching result"],
        risks=[],
        actions=[],
        rule_checks=[],
    )
    explicit_ids = explicit_program_ids or []
    return AgentState(
        workflow_id="recommendation-formal-gate-test",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        normalized_profile=profile,
        assessment=assessment,
        selected_program_ids=[program.id],
        selected_matches=[match.model_dump(mode="json")],
        working_memory={"explicit_selected_program_ids": explicit_ids},
    )


def _critic_state(
    program,
    recommendation: object,
    *,
    goal: WorkflowGoal = WorkflowGoal.PROGRAM_RECOMMENDATION,
    explicit_program_ids: list[str] | None = None,
    cached_hard_rule_passed: bool = True,
) -> AgentState:
    state = _recommendation_state(
        program,
        explicit_program_ids=explicit_program_ids,
        cached_hard_rule_passed=cached_hard_rule_passed,
    )
    state.goal = goal
    state.working_memory["tool_results"] = {
        "validate_recommendation_consistency": recommendation.model_dump(mode="json"),
        "validate_source_grounding": {"passed": True},
        "formal_gate_check": {"passed": True},
        "validate_writing_grounding": {"passed": True},
    }
    return state


def _match() -> ProgramMatch:
    program = load_programs()[0]
    return ProgramMatch(
        program=program,
        tier="candidate",
        fit_score=50,
        hard_rule_passed=True,
        reasons=[],
        risks=[],
        actions=[],
        rule_checks=[],
    )


def _formal_blocked_gate(program):
    return {
        "production_ready": True,
        "reference_ready": False,
        "current_fields": ["official_program_url", "application_url", "deadline"],
        "previous_cycle_fields": [],
        "missing_or_blocked_fields": [],
        "field_status": {},
        "formal_recommendation_ready": False,
        "formal_use_ready": False,
        "canonical_formal_readiness": False,
        "formal_current_fields": [],
        "formal_missing_or_blocked_fields": ["materials"],
        "formal_blockers": ["materials: current reviewed DecisionFact is missing"],
    }


def test_critic_formal_tool_does_not_pass_on_timeline_fields_alone(
    monkeypatch,
) -> None:
    match = _match()
    state = AgentState(
        workflow_id="formal-tool-test",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        selected_matches=[match.model_dump(mode="json")],
    )
    monkeypatch.setattr(review_tools, "program_field_gate", _formal_blocked_gate)

    result = review_tools._formal(state, EmptyToolInput())

    assert result.passed is False
    assert any("materials" in blocker for blocker in result.blockers)
    assert result.details["program_gates"][match.program.id][
        "formal_recommendation_ready"
    ] is False


def test_review_gate_reports_formal_blockers_without_a_writing_false_positive(
    monkeypatch,
) -> None:
    match = _match()
    monkeypatch.setattr(
        "harbor_agent.services.deterministic_review.program_field_gate",
        _formal_blocked_gate,
    )

    result = run_review_gate(
        [match],
        None,
        writing_ready=False,
        writing_required=False,
    )

    assert result["passed"] is False
    assert result["programs_with_formal_blockers"] == [match.program.id]
    assert any("materials" in blocker for blocker in result["blockers"])
    assert all("writing draft" not in blocker for blocker in result["blockers"])


def test_recommendation_gate_recomputes_current_decision_facts(stored_program) -> None:
    # The cached match deliberately says PASS.  The current SQLite fact raises
    # the minimum GPA above the applicant's GPA, so the gate must ignore that
    # stale flag and fail on the fresh deterministic result.
    _upsert([_valid_record(stored_program.id, "min_gpa", "90")])
    state = _recommendation_state(stored_program)

    result = review_tools._recommendations(state, EmptyToolInput())

    assert result.passed is False
    assert result.details["recomputed"][stored_program.id]["hard_rule_passed"] is False
    assert result.details["recomputed_match_changed_program_ids"] == [stored_program.id]
    assert result.details["explicitly_selected_ineligible_program_ids"] == []
    assert any(stored_program.id in blocker for blocker in result.blockers)


def test_critic_replans_matching_for_non_explicit_current_ineligibility(stored_program) -> None:
    _upsert([_valid_record(stored_program.id, "min_gpa", "90")])
    state = _recommendation_state(stored_program)
    recommendation = review_tools._recommendations(state, EmptyToolInput())
    state = _critic_state(stored_program, recommendation)

    decision = CriticAgent().step(state)

    assert decision.decision == DecisionType.HANDOFF
    assert decision.state_patch["working_memory"]["critic_outcome"] == "REPLAN_MATCHING"
    assert decision.state_patch["working_memory"]["critic_readiness"] == CriticReadiness.BLOCKED.value


def test_critic_keeps_explicit_ineligible_selection_preliminary_for_exploration(
    stored_program,
) -> None:
    _upsert([_valid_record(stored_program.id, "min_gpa", "90")])
    state = _recommendation_state(
        stored_program,
        explicit_program_ids=[stored_program.id],
        cached_hard_rule_passed=False,
    )
    recommendation = review_tools._recommendations(state, EmptyToolInput())
    assert recommendation.passed is False
    assert recommendation.details["explicitly_selected_ineligible_program_ids"] == [stored_program.id]
    state = _critic_state(
        stored_program,
        recommendation,
        explicit_program_ids=[stored_program.id],
        cached_hard_rule_passed=False,
    )

    decision = CriticAgent().step(state)
    memory = decision.state_patch["working_memory"]

    assert decision.decision == DecisionType.HANDOFF
    assert memory["critic_outcome"] == "PRELIMINARY_COMPLETE"
    assert memory["critic_readiness"] == CriticReadiness.PRELIMINARY_COMPLETE.value
    assert memory["critic_readiness"] != CriticReadiness.FORMAL_PASS.value
    assert memory["critic_blockers"]


def test_critic_refreshes_a_stale_explicit_selection_before_preliminary_delivery(
    stored_program,
) -> None:
    _upsert([_valid_record(stored_program.id, "min_gpa", "90")])
    state = _recommendation_state(
        stored_program,
        explicit_program_ids=[stored_program.id],
    )
    recommendation = review_tools._recommendations(state, EmptyToolInput())
    state = _critic_state(
        stored_program,
        recommendation,
        explicit_program_ids=[stored_program.id],
    )

    decision = CriticAgent().step(state)
    memory = decision.state_patch["working_memory"]

    assert memory["critic_outcome"] == "REPLAN_MATCHING"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value


@pytest.mark.parametrize(
    "goal",
    [WorkflowGoal.FULL_APPLICATION_PLAN, WorkflowGoal.WRITING],
)
def test_critic_blocks_formal_or_writing_delivery_for_explicit_ineligibility(
    stored_program,
    goal: WorkflowGoal,
) -> None:
    _upsert([_valid_record(stored_program.id, "min_gpa", "90")])
    state = _recommendation_state(
        stored_program,
        explicit_program_ids=[stored_program.id],
        cached_hard_rule_passed=False,
    )
    recommendation = review_tools._recommendations(state, EmptyToolInput())
    state = _critic_state(
        stored_program,
        recommendation,
        goal=goal,
        explicit_program_ids=[stored_program.id],
        cached_hard_rule_passed=False,
    )

    decision = CriticAgent().step(state)
    memory = decision.state_patch["working_memory"]

    assert decision.decision == DecisionType.HANDOFF
    assert memory["critic_outcome"] == "BLOCKED"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value
