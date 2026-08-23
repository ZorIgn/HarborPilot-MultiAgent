from __future__ import annotations

from harbor_agent.agents.critic import CriticAgent
from harbor_agent.models import CriticReadiness
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.state import AgentState, WorkflowGoal


def _state(
    *,
    goal: WorkflowGoal = WorkflowGoal.PROGRAM_RECOMMENDATION,
    source_passed: bool = True,
    source_blockers: list[str] | None = None,
    reverify_attempts: int = 0,
    verification_complete: bool = True,
    missing_fields: dict[str, list[str]] | None = None,
    writing_passed: bool | None = None,
    writing_ready: bool | None = None,
    formal_passed: bool | None = None,
) -> AgentState:
    results: dict[str, dict] = {
        "validate_recommendation_consistency": {"passed": True},
        "validate_source_grounding": {
            "passed": source_passed,
            "blockers": list(source_blockers or []),
        },
    }
    if writing_passed is not None:
        results["validate_writing_grounding"] = {
            "passed": writing_passed,
            "details": {"claim_grounding_ready": writing_passed},
        }
    # Programme recommendation and planning goals always include the formal
    # gate.  These tests target the source/critic outcome after that gate has
    # completed successfully, rather than accidentally asserting behaviour
    # from the earlier "schedule missing tools" turn.
    requires_formal = goal in {
        WorkflowGoal.PROGRAM_RECOMMENDATION,
        WorkflowGoal.APPLICATION_PLANNING,
        WorkflowGoal.FULL_APPLICATION_PLAN,
    }
    if requires_formal:
        results["formal_gate_check"] = {"passed": True if formal_passed is None else formal_passed}
    return AgentState(
        workflow_id="critic-outcome-test",
        goal=goal,
        selected_program_ids=["program-a"],
        writing_ready=(writing_passed is True if writing_ready is None else writing_ready),
        fields_needing_verification=missing_fields or {},
        working_memory={
            "reverify_attempts": reverify_attempts,
            "verification_complete": verification_complete,
            "tool_results": results,
        },
    )


def _patched_memory(state: AgentState, decision) -> dict:
    assert decision.state_patch is not None
    return decision.state_patch["working_memory"]


def test_source_failure_requests_one_bounded_reverify() -> None:
    state = _state(
        source_passed=False,
        source_blockers=["deadline has no current-cycle official evidence"],
        reverify_attempts=0,
        verification_complete=False,
        missing_fields={"program-a": ["deadline"]},
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert decision.decision == DecisionType.HANDOFF
    assert memory["critic_outcome"] == "REVERIFY"
    assert memory["reverify_attempts"] == 1
    assert memory["reverify_target_program_id"] == "program-a"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value
    assert "deadline has no current-cycle official evidence" in memory["critic_blockers"]


def test_exhausted_reverify_is_explicitly_preliminary_and_never_passes() -> None:
    state = _state(
        source_passed=False,
        source_blockers=["official source fetch did not produce a publishable record"],
        reverify_attempts=1,
        verification_complete=True,
        missing_fields={"program-a": ["deadline"]},
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert decision.decision == DecisionType.HANDOFF
    assert memory["critic_outcome"] == "PRELIMINARY_COMPLETE"
    assert memory["critic_outcome"] != "PASS"
    assert memory["critic_readiness"] == CriticReadiness.PRELIMINARY_COMPLETE.value
    assert memory["readiness_level"] == CriticReadiness.PRELIMINARY_COMPLETE.value
    assert memory["critic_blockers"]


def test_source_failure_with_empty_field_state_still_cannot_be_formal_pass() -> None:
    state = _state(
        source_passed=False,
        source_blockers=[],
        reverify_attempts=1,
        verification_complete=True,
        missing_fields={},
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert memory["critic_outcome"] == "PRELIMINARY_COMPLETE"
    assert memory["critic_readiness"] == CriticReadiness.PRELIMINARY_COMPLETE.value
    assert memory["critic_outcome"] != "PASS"
    assert any("validate_source_grounding" in item for item in memory["critic_blockers"])


def test_formal_pass_requires_all_required_gates_to_be_green() -> None:
    state = _state(
        goal=WorkflowGoal.FULL_APPLICATION_PLAN,
        source_passed=True,
        writing_passed=True,
        formal_passed=True,
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert memory["critic_outcome"] == "PASS"
    assert memory["critic_readiness"] == CriticReadiness.FORMAL_PASS.value
    assert memory["critic_blockers"] == []


def test_writing_grounding_failure_cannot_formal_pass() -> None:
    state = _state(
        goal=WorkflowGoal.WRITING,
        source_passed=True,
        writing_passed=False,
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert memory["critic_outcome"] == "REWRITE"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value
    assert memory["critic_outcome"] != "PASS"


def test_critic_cannot_formally_pass_when_writing_ready_was_not_set_by_a_separate_turn() -> None:
    state = _state(
        goal=WorkflowGoal.WRITING,
        source_passed=True,
        writing_passed=True,
        writing_ready=False,
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert memory["critic_outcome"] == "REWRITE"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value


def test_missing_sources_still_block_full_application_delivery_after_reverify() -> None:
    state = _state(
        goal=WorkflowGoal.FULL_APPLICATION_PLAN,
        source_passed=False,
        source_blockers=["deadline has no current-cycle official evidence"],
        reverify_attempts=1,
        verification_complete=True,
        missing_fields={"program-a": ["deadline"]},
        writing_passed=True,
        formal_passed=True,
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert decision.decision == DecisionType.HANDOFF
    assert memory["critic_outcome"] == "BLOCKED"
    assert memory["critic_readiness"] == CriticReadiness.BLOCKED.value
    assert memory["critic_outcome"] != "PASS"


def test_background_assessment_is_preliminary_complete_not_formal_pass() -> None:
    state = AgentState(
        workflow_id="critic-background-test",
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        assessment={"overall_level": "B"},
    )

    decision = CriticAgent().step(state)
    memory = _patched_memory(state, decision)

    assert memory["critic_outcome"] == "PASS"
    assert memory["critic_readiness"] == CriticReadiness.PRELIMINARY_COMPLETE.value
    assert memory["critic_readiness"] != CriticReadiness.FORMAL_PASS.value
