from __future__ import annotations

import json

import pytest

from harbor_agent.agents.supervisor import SupervisorAgent
from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
from harbor_agent.llm.response import LLMResponse, LLMUsage
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.errors import LLMStructuredOutputError
from harbor_agent.runtime.state import AgentState, WorkflowGoal


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


def test_model_supervisor_cannot_bypass_a_prerequisite_route() -> None:
    state = _ready_full_plan_state(verification_complete=False)
    agent = SupervisorAgent(
        llm=DeterministicMockToolCallingProvider(responses=[_model_response("WritingAgent")]),
        model_driven=True,
    )

    assert [route.next_agent for route in agent.route_options(state)] == ["VerificationAgent"]
    with pytest.raises(LLMStructuredOutputError):
        agent.model_decision(state, [])
