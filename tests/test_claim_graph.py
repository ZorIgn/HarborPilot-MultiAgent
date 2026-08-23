from __future__ import annotations

from harbor_agent.agents.writing_agent import WritingWorkflowAgent
from harbor_agent.models import (
    DecisionFact,
    DecisionStatus,
    ProgramMatch,
    ResolvedProgramView,
    WritingDraft,
)
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.state import AgentState, WorkflowGoal
from harbor_agent.services.claim_graph import build_claim_graph, claim_graph_passed
from harbor_agent.services.data_loader import load_programs
from harbor_agent.tools.base import EmptyToolInput
from harbor_agent.tools.review_tools import _writing


def _program_and_match() -> tuple[object, ProgramMatch]:
    program = load_programs()[0]
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=70,
        hard_rule_passed=True,
        reasons=["fixture"],
        risks=[],
        actions=[],
        rule_checks=[],
    )
    return program, match


def _draft(program_id: str, text: str) -> WritingDraft:
    return WritingDraft.model_construct(
        document_type="PS",
        title="fixture",
        outline=[],
        draft=text,
        draft_zh="",
        draft_en=text,
        material_gaps=[],
        paragraph_drafts=[],
        fact_bindings=[],
        target_program_ids=[program_id],
        school_customization=[],
        prompt_requirements=[],
        cv_bullets=[],
        reference_package=[],
        risk_controls=[],
        review_flags=[],
    )


def _view(program, *, tuition: int | None) -> ResolvedProgramView:
    facts = {}
    if tuition is not None:
        facts["tuition_hkd"] = DecisionFact(
            fact_id="decision:tuition:current",
            program_id=program.id,
            field_name="tuition_hkd",
            cycle=program.cycle,
            raw_value=str(tuition),
            normalized_value=tuition,
            decision_status=DecisionStatus.PASS,
            formal_use_ready=True,
            evidence_id="published:tuition:current",
        )
    return ResolvedProgramView(
        program_id=program.id,
        cycle=program.cycle,
        catalog=program,
        facts=facts,
    )


def test_program_claim_stays_blocked_when_review_flags_are_removed() -> None:
    program, _ = _program_and_match()
    draft = _draft(program.id, "The programme tuition is HK$88,000.")

    graph = build_claim_graph(draft, [program], resolved_views={program.id: _view(program, tuition=None)})

    assert graph.nodes
    assert any(node.status.value == "BLOCKED" for node in graph.nodes)
    assert graph.blockers
    assert graph.formal_status is DecisionStatus.UNKNOWN
    assert not claim_graph_passed(graph)


def test_current_reviewed_decision_fact_supports_program_claim() -> None:
    program, _ = _program_and_match()
    draft = _draft(program.id, "The programme tuition is HK$88,000.")

    graph = build_claim_graph(draft, [program], resolved_views={program.id: _view(program, tuition=88000)})

    assert claim_graph_passed(graph)
    assert graph.formal_status is DecisionStatus.PASS
    node = next(node for node in graph.nodes if node.claim_type == "program_fact")
    assert node.status.value == "SUPPORTED"
    assert node.decision_fact_ids == ["decision:tuition:current"]
    assert node.evidence_ids == ["published:tuition:current"]


def test_writing_agent_cannot_mark_ready_on_validation_call_same_turn() -> None:
    program, match = _program_and_match()
    draft = _draft(program.id, "A grounded student story.")
    state = AgentState(
        workflow_id="claim-graph-test",
        goal=WorkflowGoal.WRITING,
        selected_matches=[match.model_dump(mode="json")],
        story_cards=[{"id": "story-1", "title": "story"}],
        writing_ready=False,
        working_memory={
            "tool_results": {
                "build_writing_draft": {"draft": draft.model_dump(mode="json")},
            }
        },
    )
    agent = WritingWorkflowAgent()

    first = agent.step(state)

    assert first.decision is DecisionType.CALL_TOOL
    assert first.tool_calls[0].tool_name == "validate_writing_claims"
    assert first.state_patch["writing_ready"] is False

    failed_state = state.model_copy(
        update={
            "working_memory": {
                "tool_results": {
                    "build_writing_draft": {"draft": draft.model_dump(mode="json")},
                    "validate_writing_claims": {
                        "grounded": False,
                        "passed": False,
                        "unsupported_claims": ["unsupported tuition claim"],
                        "blockers": ["missing current DecisionFact"],
                    },
                }
            }
        }
    )
    failed = agent.step(failed_state)
    assert failed.decision is DecisionType.HANDOFF
    assert failed.next_agent == "SupervisorAgent"
    assert failed.state_patch["writing_ready"] is False

    passed_state = failed_state.model_copy(
        update={
            "working_memory": {
                "tool_results": {
                    "build_writing_draft": {"draft": draft.model_dump(mode="json")},
                    "validate_writing_claims": {
                        "grounded": True,
                        "passed": True,
                        "unsupported_claims": [],
                        "blockers": [],
                    },
                }
            }
        }
    )
    passed = agent.step(passed_state)
    assert passed.decision is DecisionType.HANDOFF
    assert passed.state_patch["writing_ready"] is True


def test_critic_writing_gate_uses_claim_graph_not_empty_review_flags() -> None:
    program, match = _program_and_match()
    draft = _draft(program.id, "The programme tuition is HK$88,000.")
    state = AgentState(
        workflow_id="claim-graph-review-tool",
        goal=WorkflowGoal.WRITING,
        selected_matches=[match.model_dump(mode="json")],
        writing_draft=draft.model_dump(mode="json"),
        # This simulates a stale or malicious legacy state where a caller
        # cleared review prose but has not supplied a published DecisionFact.
        writing_ready=True,
    )

    result = _writing(state, EmptyToolInput())

    assert result.passed is False
    assert result.details["claim_grounding_ready"] is False
    assert result.blockers
