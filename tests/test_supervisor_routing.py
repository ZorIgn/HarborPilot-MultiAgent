from __future__ import annotations

import json

from harbor_agent.agents.supervisor import SupervisorAgent
from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
from harbor_agent.llm.response import LLMResponse, LLMUsage
from harbor_agent.models import ProgramMatch, WritingDraft
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.state import AgentState, WorkflowGoal
from harbor_agent.services.data_loader import load_programs


def _ready_full_plan_state(*, verification_complete: bool = True) -> AgentState:
    return AgentState(
        workflow_id="supervisor_route_options",
        goal=WorkflowGoal.FULL_APPLICATION_PLAN,
        raw_profile={},
        normalized_profile={},
        assessment={},
        candidate_program_ids=["program-a"],
        program_matches={"program-a": {}},
        selected_program_ids=["program-a"],
        working_memory={"verification_complete": verification_complete},
    )


def _model_response(next_agent: str) -> LLMResponse:
    return LLMResponse(
        json_content={
            "decision": "HANDOFF",
            "reasoning_summary": "Both independently gated workstreams are ready; begin with writing.",
            "next_agent": next_agent,
        },
        usage=LLMUsage(prompt_tokens=5, completion_tokens=3),
        model="mock",
        provider="mock",
    )


def test_model_supervisor_can_choose_an_independent_ready_workstream() -> None:
    state = _ready_full_plan_state()
    agent = SupervisorAgent(
        llm=DeterministicMockToolCallingProvider(responses=[_model_response("WritingAgent")]),
        model_driven=True,
    )

    context = json.loads(agent.build_model_messages(state)[1]["content"])
    assert [item["target"] for item in context["available_routes"]] == [
        "PlanningAgent",
        "WritingAgent",
    ]

    decision = agent.model_decision(state, [])

    assert decision is not None
    assert decision.decision == DecisionType.HANDOFF
    assert decision.next_agent == "WritingAgent"
    assert decision.state_patch["tasks"][-1]["assigned_agent"] == "WritingAgent"


def test_model_supervisor_can_choose_only_a_safe_preparation_route_before_verification() -> None:
    state = _ready_full_plan_state(verification_complete=False)
    agent = SupervisorAgent(
        llm=DeterministicMockToolCallingProvider(responses=[_model_response("WritingAgent")]),
        model_driven=True,
    )

    # Verification remains the only path that can make programme facts
    # formal, but the Supervisor deliberately exposes two bounded preparatory
    # workstreams: an official-source plan and student-story preparation.  A
    # model may choose their order without gaining a way to mark verification
    # or writing as ready.
    assert [route.next_agent for route in agent.route_options(state)] == [
        "VerificationAgent",
        "ResearchAgent",
        "WritingAgent",
    ]

    decision = agent.model_decision(state, [])

    assert decision is not None
    assert decision.decision == DecisionType.HANDOFF
    assert decision.next_agent == "WritingAgent"
    assert decision.state_patch["tasks"][-1]["assigned_agent"] == "WritingAgent"
    assert "verification_complete" not in decision.state_patch
    assert decision.state_patch.get("writing_ready") is not True


def test_supervisor_cannot_complete_writing_when_separate_claim_validation_is_missing() -> None:
    program = load_programs()[0]
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=70,
        hard_rule_passed=True,
        reasons=[],
        risks=[],
        actions=[],
        rule_checks=[],
    )
    draft = WritingDraft.model_construct(
        document_type="PS",
        title="fixture",
        outline=[],
        draft="Student story only.",
        fact_bindings=[],
        review_flags=[],
    )
    state = AgentState(
        workflow_id="supervisor-writing-ready",
        goal=WorkflowGoal.WRITING,
        raw_profile={},
        normalized_profile={},
        assessment={},
        candidate_program_ids=[program.id],
        program_matches={program.id: match.model_dump(mode="json")},
        selected_matches=[match.model_dump(mode="json")],
        selected_program_ids=[program.id],
        writing_draft=draft.model_dump(mode="json"),
        writing_ready=False,
        working_memory={
            "verification_complete": True,
            "critic_outcome": "PASS",
            "critic_readiness": "FORMAL_PASS",
            "tool_results": {"validate_writing_grounding": {"passed": True}},
        },
    )

    route = SupervisorAgent().route(state)

    assert route.next_agent == "CriticAgent"
    assert route.state_patch["working_memory"].get("critic_outcome") is None
