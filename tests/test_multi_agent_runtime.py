

def test_human_conflict_resolution_is_typed_and_does_not_rewait() -> None:
    from uuid import uuid4

    from harbor_agent.models import FieldEvidenceRecord, FieldVerificationStatus, SourceScope
    from harbor_agent.runtime.checkpoint import save_checkpoint
    from harbor_agent.runtime.state import WorkflowStatus
    from harbor_agent.services.agent_runtime import create_multi_agent_workflow

    workflow_id = f"human_resolution_{uuid4().hex}"
    # Human review is only meaningful for a real, durable evidence candidate.
    # A synthetic ``record_id`` with no source/binding/snapshot metadata must
    # not be enough to clear a conflict gate.
    conflict = FieldEvidenceRecord(
        evidence_id="official-record-a",
        program_id="cityu-ma-communication-and-new-media-2027",
        field_name="deadline",
        value="2027-02-28",
        cycle="2027-fall",
        source_url="https://www.cityu.edu.hk/programmes/communication-new-media",
        source_type="official_program_page",
        page_hash="sha256:conflict-record-a",
        confidence="high",
        source_priority=1,
        status=FieldVerificationStatus.conflicted,
        review_required=True,
        evidence_snippet="Application deadline: 28 February 2027.",
        snapshot_url="https://snapshots.cityu.edu.hk/conflict-record-a.html",
        source_scope=SourceScope.programme_detail,
        binding_status="matched",
        binding_score=98,
    ).model_dump(mode="json")
    conflict["record_id"] = "official-record-a"
    state = AgentState(
        workflow_id=workflow_id,
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        raw_profile={},
        normalized_profile={},
        assessment={},
        candidate_program_ids=["cityu-ma-communication-and-new-media-2027"],
        program_matches={"cityu-ma-communication-and-new-media-2027": {}},
        selected_program_ids=["cityu-ma-communication-and-new-media-2027"],
        verification_conflicts=[conflict],
        human_review_reason="Choose the authoritative deadline record.",
        working_memory={
            "verification_cursor": 1,
            "verification_complete": True,
                "critic_outcome": "PRELIMINARY_COMPLETE",
                "critic_readiness": "PRELIMINARY_COMPLETE",
            "tool_results": {
                "compare_evidence_records": {
                    "conflicts": [dict(conflict)],
                    "human_review_required": True,
                    "consistent": False,
                }
            },
        },
    )
    create_multi_agent_workflow(workflow_id, state.goal.value, state.model_dump(mode="json"))
    save_checkpoint(state)

    response = TestClient(app).post(
        f"/api/agent/workflows/{workflow_id}/resume",
        json={
            "human_resolution": {
                "action": "resolve_conflicts",
                "conflict_resolutions": [
                    {"conflict_id": "official-record-a", "action": "reject", "reviewer_note": "The record is not authoritative."}
                ]
            }
        },
    )
    assert response.status_code == 200
    resumed = AgentState.model_validate(response.json())

    assert resumed.status == WorkflowStatus.COMPLETED
    assert resumed.verification_conflicts == []
    assert resumed.human_review_reason is None
    assert resumed.resolved_conflicts[0].conflict_id == "official-record-a"
    assert resumed.resolved_conflicts[0].action == "reject"
    comparison = resumed.working_memory["tool_results"]["compare_evidence_records"]
    assert comparison["conflicts"] == []
    assert comparison["human_review_required"] is False


def test_human_resolution_requires_a_typed_conflict_selector() -> None:
    with pytest.raises(ValidationError):
        WorkflowResumeRequest(human_resolution={"conflict_resolutions": [{"action": "accept"}]})


def test_runtime_state_checkpoint_and_trace_redact_camel_kebab_snake_and_nested_secrets() -> None:
    from uuid import uuid4

    from harbor_agent.observability.events import TraceEventType
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.checkpoint import save_checkpoint
    from harbor_agent.services.agent_runtime import (
        create_multi_agent_workflow,
        get_multi_agent_workflow,
        list_runtime_trace_events,
        load_workflow_checkpoint,
    )

    workflow_id = f"runtime_redaction_{uuid4().hex}"
    secrets_payload = {
        "apiKey": "camel-value-should-never-persist",
        "access-token": "kebab-value-should-never-persist",
        "refresh_token": "snake-value-should-never-persist",
        "nested": {"clientSecret": "nested-value-should-never-persist"},
    }
    state = AgentState(
        workflow_id=workflow_id,
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        raw_profile=secrets_payload,
        working_memory={"provider": secrets_payload},
    )
    serialized_state = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    for value in ("camel-value-should-never-persist", "kebab-value-should-never-persist", "snake-value-should-never-persist", "nested-value-should-never-persist"):
        assert value not in serialized_state

    create_multi_agent_workflow(workflow_id, state.goal.value, state.model_dump(mode="json"))
    save_checkpoint(state)
    tracer = RuntimeTracer(workflow_id)
    tracer.emit(
        TraceEventType.ERROR,
        input_summary="apiKey=trace-api-key-should-never-persist",
        output_summary="accessToken=trace-access-token-should-never-persist",
        error=RuntimeError("nestedSecret=trace-nested-secret-should-never-persist"),
    )

    persisted = [
        get_multi_agent_workflow(workflow_id)["state"],
        load_workflow_checkpoint(workflow_id)["state"],
        list_runtime_trace_events(workflow_id),
    ]
    serialized_persisted = json.dumps(persisted, ensure_ascii=False)
    for value in (
        "camel-value-should-never-persist",
        "kebab-value-should-never-persist",
        "snake-value-should-never-persist",
        "nested-value-should-never-persist",
        "trace-api-key-should-never-persist",
        "trace-access-token-should-never-persist",
        "trace-nested-secret-should-never-persist",
    ):
        assert value not in serialized_persisted

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from harbor_agent.app import app
from harbor_agent.runtime.decision import AgentDecision, DecisionType
from harbor_agent.runtime.errors import ToolExecutionError, ToolPermissionError
from harbor_agent.runtime.state import AgentState, WorkflowGoal, apply_state_patch
from harbor_agent.runtime.workflow import (
    MultiAgentRuntime,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from harbor_agent.tools import build_default_tool_registry


def _profile() -> dict:
    return json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))


def test_state_patch_is_typed_and_rejects_unknown_fields() -> None:
    state = AgentState(workflow_id="state_test", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    updated = apply_state_patch(state, {"step_count": 2})
    assert updated.step_count == 2
    with pytest.raises(Exception):
        apply_state_patch(state, {"not_a_state_field": True})


def test_decision_contract_requires_control_fields() -> None:
    with pytest.raises(ValidationError):
        AgentDecision(decision=DecisionType.CALL_TOOL, reasoning_summary="missing calls")
    with pytest.raises(ValidationError):
        AgentDecision(decision=DecisionType.ASK_USER, reasoning_summary="missing question")


def test_registry_enforces_agent_tool_permission() -> None:
    from harbor_agent.observability.trace import RuntimeTracer

    state = AgentState(workflow_id="tool_permission", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    with pytest.raises(ToolPermissionError):
        build_default_tool_registry().execute(
            agent_name="WritingAgent",
            allowed_tools={"build_story_cards"},
            state=state,
            tool_name="snapshot_official_source",
            arguments={"url": "https://example.com", "dry_run": True},
            tracer=RuntimeTracer(state.workflow_id),
        )


def test_live_snapshot_requires_runtime_source_fetch_capability() -> None:
    from harbor_agent.observability.trace import RuntimeTracer

    state = AgentState(workflow_id="source_capability", goal=WorkflowGoal.PROGRAM_RECOMMENDATION)
    with pytest.raises(ToolExecutionError, match="snapshot_official_source failed: PermissionError") as exc_info:
        build_default_tool_registry().execute(
            agent_name="VerificationAgent",
            allowed_tools={"snapshot_official_source"},
            state=state,
            tool_name="snapshot_official_source",
            arguments={
                "program_id": "hku-master-of-science-in-computer-science-2027",
                "url": "https://example.com",
                "dry_run": False,
            },
            tracer=RuntimeTracer(state.workflow_id),
        )
    assert exc_info.value.__cause__ is not None
    assert "server-issued operator authorization" in str(exc_info.value.__cause__)


def test_background_runtime_uses_real_agent_and_tool_events() -> None:
    state = MultiAgentRuntime().start(
        WorkflowStartRequest(goal=WorkflowGoal.BACKGROUND_ASSESSMENT, profile=_profile())
    )
    assert state.status.value == "COMPLETED"
    assert state.visited_agents == ["AssessmentAgent", "CriticAgent"]
    assert state.tool_call_count >= 4


def test_ask_user_resume_reassesses_profile() -> None:
    profile = _profile()
    profile["language"] = {"test": "NONE", "overall": None}
    runtime = MultiAgentRuntime()
    paused = runtime.start(WorkflowStartRequest(goal=WorkflowGoal.PROGRAM_RECOMMENDATION, profile=profile))
    assert paused.status.value == "WAITING_USER"
    resumed = runtime.resume(
        paused.workflow_id,
        WorkflowResumeRequest(
            user_message=json.dumps(
                {"language": {"test": "IELTS", "overall": 7.0, "writing": 6.5, "speaking": 6.5, "reading": 7.0, "listening": 7.0}}
            )
        ),
    )
    assert resumed.status.value == "COMPLETED"
    assert resumed.agent_turn_counts["AssessmentAgent"] >= 2


def test_runtime_api_accepts_sparse_profile_and_pauses_for_required_fields() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/workflows",
        json={"goal": "PROGRAM_RECOMMENDATION", "profile": {"apiKey": "api-response-secret", "nested": {"accessToken": "access-response-secret"}}},
    )
    assert response.status_code == 200
    state = response.json()
    assert state["status"] == "WAITING_USER"
    assert "本科专业" in state["user_question"]
    assert "GPA" in state["user_question"]
    assert "api-response-secret" not in json.dumps(state, ensure_ascii=False)
    assert "access-response-secret" not in json.dumps(state, ensure_ascii=False)


def test_runtime_api_exposes_owned_state_and_real_trace() -> None:
    client = TestClient(app)
    create = client.post(
        "/api/agent/workflows",
        json={"goal": "BACKGROUND_ASSESSMENT", "profile": _profile(), "user_request": "test"},
    )
    assert create.status_code == 200
    workflow_id = create.json()["workflow_id"]
    trace = client.get(f"/api/agent/workflows/{workflow_id}/trace")
    assert trace.status_code == 200
    assert any(event["event_type"] == "TOOL_CALL" for event in trace.json())
    state = client.get(f"/api/agent/workflows/{workflow_id}/state")
    assert state.status_code == 200
    assert state.json()["status"] == "COMPLETED"


def test_budget_is_not_admissions_eligibility() -> None:
    profile = _profile()
    profile["budget_hkd"] = 1
    state = MultiAgentRuntime().start(
        WorkflowStartRequest(goal=WorkflowGoal.PROGRAM_RECOMMENDATION, profile=profile)
    )
    tools = state.working_memory["tool_results"]
    financial = tools["evaluate_financial_feasibility"]["assessments"]
    admissions = tools["evaluate_admissions_eligibility"]["checks"]
    # No current reviewed tuition exists in the default catalogue, so a hard
    # budget cannot be fabricated from a seed price.  This is deliberately an
    # UNKNOWN financial result, while admissions remains separate.
    assert financial
    assert all(item["status"] == "UNKNOWN" for item in financial)
    assert all(item["blocks_user_selection"] is False for item in financial)
    assert all(item["check_id"] != "tuition_budget" for item in admissions)



def test_hard_cap_budget_choice_precedes_research_fallback() -> None:
    from harbor_agent.agents.supervisor import SupervisorAgent

    state = AgentState(
        workflow_id="hard_cap_budget_choice",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        raw_profile={"budget_mode": "hard_cap"},
        normalized_profile={"budget_mode": "hard_cap"},
        assessment={},
        candidate_program_ids=["program-a"],
        program_matches={"program-a": {"tier": "target"}},
        working_memory={
            "financial_hard_cap_blocked": True,
            "routing_hint": {"target": "ResearchAgent", "reason": "stale fallback hint"},
        },
    )

    route = SupervisorAgent().route(state)

    assert route.next_agent == "ASK_USER"
    assert "提高预算" in route.state_patch["user_question"]
    assert "soft" in route.state_patch["user_question"]


def test_matching_marks_only_financial_hard_cap_portfolios_for_budget_choice() -> None:
    from harbor_agent.agents.matching_agent import MatchingAgent

    state = AgentState(
        workflow_id="hard_cap_only",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        program_matches={
            "program-a": {"tier": "target"},
            "program-b": {"tier": "not_recommended"},
        },
        working_memory={
            "tool_results": {
                "calculate_applicant_fit": {"matches": []},
                "evaluate_admissions_eligibility": {"assessments": []},
                "evaluate_user_preference": {"assessments": []},
                "build_program_portfolio": {"selected_program_ids": [], "blocked_program_ids": [], "portfolio": []},
                "evaluate_financial_feasibility": {
                    "assessments": [
                        {"program_id": "program-a", "blocks_user_selection": True},
                        {"program_id": "program-b", "blocks_user_selection": True},
                    ]
                },
            }
        },
    )

    decision = MatchingAgent().step(state)

    assert decision.state_patch["working_memory"]["financial_hard_cap_blocked"] is True
    assert "routing_hint" not in decision.state_patch["working_memory"]

    nonfinancial_state = state.model_copy(deep=True)
    nonfinancial_state.program_matches["program-b"]["tier"] = "target"
    nonfinancial_state.working_memory["tool_results"]["evaluate_financial_feasibility"]["assessments"][1][
        "blocks_user_selection"
    ] = False

    nonfinancial_decision = MatchingAgent().step(nonfinancial_state)
    nonfinancial_memory = nonfinancial_decision.state_patch["working_memory"]

    assert "financial_hard_cap_blocked" not in nonfinancial_memory
    assert nonfinancial_memory["routing_hint"]["target"] == "ResearchAgent"


def test_financial_results_keep_all_candidates_for_hard_cap_portfolio() -> None:
    from harbor_agent.runtime.state import append_tool_result

    assessments = [
        {"program_id": f"program-{index}", "blocks_user_selection": True}
        for index in range(13)
    ]
    state = append_tool_result(
        AgentState(workflow_id="financial_result_limit", goal=WorkflowGoal.PROGRAM_RECOMMENDATION),
        "evaluate_financial_feasibility",
        {"assessments": assessments},
    )

    retained = state.working_memory["tool_results"]["evaluate_financial_feasibility"]["assessments"]
    assert len(retained) == len(assessments)

def test_model_decision_trace_uses_provider_tokens_and_retries_structured_output() -> None:
    from uuid import uuid4

    from harbor_agent.agents.base import BaseAgent
    from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
    from harbor_agent.llm.response import LLMResponse, LLMUsage
    from harbor_agent.observability.events import TraceEventType
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.executor import AgentExecutor
    from harbor_agent.runtime.limits import RuntimeLimits
    from harbor_agent.services.agent_runtime import list_runtime_trace_events
    from harbor_agent.tools.registry import ToolRegistry

    class ModelDecisionAgent(BaseAgent):
        name = "ModelDecisionAgent"
        description = "Test-only model driven agent."
        allowed_tools: set[str] = set()

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="The deterministic policy permits only a Supervisor handoff.",
                next_agent="SupervisorAgent",
            )

    workflow_id = f"model_trace_{uuid4().hex}"
    state = AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    provider = DeterministicMockToolCallingProvider(
        responses=[
            LLMResponse(content="{invalid", usage=LLMUsage(prompt_tokens=3, completion_tokens=1), model="mock", provider="mock"),
            LLMResponse(
                json_content={
                    "decision": "HANDOFF",
                    "reasoning_summary": "The retry returned a valid typed decision.",
                    "next_agent": "SupervisorAgent",
                },
                usage=LLMUsage(prompt_tokens=11, completion_tokens=7),
                model="mock",
                provider="mock",
            ),
        ]
    )
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        ModelDecisionAgent(llm=provider, model_driven=True),
        state,
        RuntimeTracer(workflow_id),
    )

    assert outcome.decision.decision == DecisionType.HANDOFF
    events = list_runtime_trace_events(workflow_id)
    event_types = [item["event_type"] for item in events]
    assert event_types.count(TraceEventType.LLM_REQUEST.value) == 2
    assert TraceEventType.RETRY.value in event_types
    response = next(item for item in events if item["event_type"] == TraceEventType.LLM_RESPONSE.value)
    assert response["prompt_tokens"] == 11
    assert response["completion_tokens"] == 7
    assert response["total_tokens"] == 18
    assert response["cost_usd"] is None


def test_model_driven_supervisor_executes_via_executor_and_records_llm_trace() -> None:
    from uuid import uuid4

    from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
    from harbor_agent.llm.response import LLMResponse, LLMUsage
    from harbor_agent.observability.events import TraceEventType
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.services.agent_runtime import list_runtime_trace_events

    workflow_id = f"supervisor_model_{uuid4().hex}"
    state = AgentState(
        workflow_id=workflow_id,
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        raw_profile={},
        normalized_profile={},
        assessment={},
        working_memory={"critic_outcome": "PASS", "critic_readiness": "PRELIMINARY_COMPLETE"},
    )
    provider = DeterministicMockToolCallingProvider(
        responses=[
            LLMResponse(
                json_content={"decision": "COMPLETE", "reasoning_summary": "The completed assessment is ready to close."},
                usage=LLMUsage(prompt_tokens=13, completion_tokens=5),
                model="mock",
                provider="mock",
            )
        ]
    )

    result = MultiAgentRuntime(llm=provider, model_driven=True)._run(state, RuntimeTracer(workflow_id))

    assert result.status.value == "COMPLETED"
    assert result.agent_turn_counts == {"SupervisorAgent": 1}
    events = list_runtime_trace_events(workflow_id)
    event_types = [event["event_type"] for event in events if event["agent_name"] == "SupervisorAgent"]
    assert TraceEventType.AGENT_STARTED.value in event_types
    assert TraceEventType.AGENT_END.value in event_types
    assert TraceEventType.AGENT_DECISION.value in event_types
    assert TraceEventType.LLM_REQUEST.value in event_types
    assert TraceEventType.LLM_RESPONSE.value in event_types
    assert TraceEventType.SUPERVISOR_ROUTE.value in event_types
    response = next(event for event in events if event["event_type"] == TraceEventType.LLM_RESPONSE.value)
    assert response["prompt_tokens"] == 13
    assert response["completion_tokens"] == 5

def test_model_driven_supervisor_rejects_unvalidated_route() -> None:
    from harbor_agent.agents.supervisor import SupervisorAgent
    from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
    from harbor_agent.llm.response import LLMResponse, LLMUsage
    from harbor_agent.runtime.errors import LLMStructuredOutputError

    state = AgentState(
        workflow_id="supervisor_policy_reject",
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        raw_profile={},
        normalized_profile={},
        assessment={},
        working_memory={"critic_outcome": "PASS"},
    )
    provider = DeterministicMockToolCallingProvider(
        responses=[
            LLMResponse(
                json_content={"decision": "HANDOFF", "reasoning_summary": "Skip the final review.", "next_agent": "ResearchAgent"},
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
                model="mock",
                provider="mock",
            )
        ]
    )

    with pytest.raises(LLMStructuredOutputError):
        SupervisorAgent(llm=provider, model_driven=True).model_decision(state, [])

def test_explicit_ineligible_program_is_retained_as_review_gated_preparation_plan() -> None:

    profile = _profile()
    profile["education"]["gpa"] = 1
    program_id = "hku-master-of-science-in-computer-science-2027"

    state = MultiAgentRuntime().start(
        WorkflowStartRequest(
            goal=WorkflowGoal.APPLICATION_PLANNING,
            profile=profile,
            selected_program_ids=[program_id],
        )
    )

    assert state.status.value == "COMPLETED"
    assert state.selected_program_ids == [program_id]
    assert state.selected_matches[0]["program"]["id"] == program_id
    # The catalogue's GPA threshold is not a published DecisionFact, so this
    # low GPA cannot be labelled a confirmed hard failure.  The explicit
    # programme remains a preparation-only, non-formal plan instead.
    assert state.selected_matches[0]["hard_rule_passed"] is True
    assert state.timeline
    assert state.final_result is not None
    assert state.final_result["formal_use_ready"] is False


def test_retryable_tool_retries_only_transient_execution_failures() -> None:
    from uuid import uuid4

    from pydantic import BaseModel

    from harbor_agent.agents.base import BaseAgent
    from harbor_agent.observability.events import TraceEventType
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.decision import ToolCallRequest
    from harbor_agent.runtime.executor import AgentExecutor
    from harbor_agent.runtime.limits import RuntimeLimits
    from harbor_agent.services.agent_runtime import list_runtime_trace_events
    from harbor_agent.tools.base import ToolDefinition
    from harbor_agent.tools.registry import ToolRegistry

    class RetryInput(BaseModel):
        pass

    class RetryOutput(BaseModel):
        ok: bool

    class RetryAgent(BaseAgent):
        name = "RetryAgent"
        description = "Test-only retry agent."
        allowed_tools = {"flaky_tool"}

        def step(self, state: AgentState) -> AgentDecision:
            raise AssertionError("not used")

    attempts = {"count": 0}

    def flaky_handler(_: AgentState, __: RetryInput) -> RetryOutput:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("temporary network failure")
        return RetryOutput(ok=True)

    workflow_id = f"tool_retry_{uuid4().hex}"
    state = AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    registry = ToolRegistry(
        [
            ToolDefinition(
                "flaky_tool",
                "Fails once then succeeds.",
                RetryInput,
                RetryOutput,
                flaky_handler,
                max_retries=3,
                retryable=True,
            )
        ]
    )
    tracer = RuntimeTracer(workflow_id)
    result = AgentExecutor(registry, RuntimeLimits())._execute_tool(
        agent=RetryAgent(),
        state=state,
        call=ToolCallRequest(tool_name="flaky_tool", arguments={}),
        tracer=tracer,
    )

    assert result.output == {"ok": True}
    assert attempts["count"] == 2
    events = list_runtime_trace_events(workflow_id)
    assert [item["event_type"] for item in events].count(TraceEventType.TOOL_CALL.value) == 2
    assert TraceEventType.RETRY.value in [item["event_type"] for item in events]

def test_model_driven_specialist_rejects_reordered_policy_tools_at_executor_boundary():
    from harbor_agent.agents.base import BaseAgent
    from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
    from harbor_agent.llm.response import LLMResponse, LLMUsage
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.errors import LLMStructuredOutputError
    from harbor_agent.runtime.executor import AgentExecutor
    from harbor_agent.runtime.limits import RuntimeLimits
    from harbor_agent.tools.registry import ToolRegistry

    class OrderedPolicyAgent(BaseAgent):
        name = "OrderedPolicyAgent"
        description = "Test-only ordered policy agent."
        allowed_tools = {"first_tool", "second_tool"}
        output_state_fields = ("working_memory",)

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="The policy requires first_tool before second_tool.",
                tool_calls=[
                    {"tool_name": "first_tool", "arguments": {}},
                    {"tool_name": "second_tool", "arguments": {}},
                ],
                state_patch={"working_memory": {"policy_marker": "safe"}},
            )

    response = LLMResponse(
        json_content={
            "decision": "CALL_TOOL",
            "reasoning_summary": "Try to skip the required tool order.",
            "tool_calls": [
                {"tool_name": "second_tool", "arguments": {}},
                {"tool_name": "first_tool", "arguments": {}},
            ],
        },
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        model="mock",
        provider="mock",
    )
    provider = DeterministicMockToolCallingProvider(responses=[response, response, response])
    workflow_id = "model_order_policy"
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        OrderedPolicyAgent(llm=provider, model_driven=True),
        AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT),
        RuntimeTracer(workflow_id),
    )

    assert outcome.decision.decision == DecisionType.FAIL
    assert outcome.state.status.value == "FAILED"
    assert any("ordered policy subsequence" in item for item in outcome.state.errors)


def test_model_driven_specialist_cannot_write_state_or_complete_workflow():
    from harbor_agent.agents.base import BaseAgent
    from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
    from harbor_agent.llm.response import LLMResponse, LLMUsage
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.executor import AgentExecutor
    from harbor_agent.runtime.limits import RuntimeLimits
    from harbor_agent.tools.registry import ToolRegistry

    class UnsafeSpecialist(BaseAgent):
        name = "UnsafeSpecialist"
        description = "Test-only unsafe specialist."
        allowed_tools = set()
        output_state_fields = ()

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="Return to Supervisor.",
                next_agent="SupervisorAgent",
            )

    response = LLMResponse(
        json_content={
            "decision": "HANDOFF",
            "reasoning_summary": "Attempt a privileged patch.",
            "next_agent": "SupervisorAgent",
            "state_patch": {"status": "COMPLETED"},
        },
        usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        model="mock",
        provider="mock",
    )
    provider = DeterministicMockToolCallingProvider(responses=[response, response, response])
    workflow_id = "model_state_acl"
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        UnsafeSpecialist(llm=provider, model_driven=True),
        AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT),
        RuntimeTracer(workflow_id),
    )

    assert outcome.decision.decision == DecisionType.FAIL
    assert outcome.state.status.value == "FAILED"
    assert outcome.state.final_result is None
    assert any("may not write shared state" in item for item in outcome.state.errors)


def test_executor_allows_workflow_completion_only_for_supervisor():
    from harbor_agent.agents.base import BaseAgent
    from harbor_agent.observability.trace import RuntimeTracer
    from harbor_agent.runtime.errors import AgentDecisionValidationError
    from harbor_agent.runtime.executor import AgentExecutor

    class CompletingSpecialist(BaseAgent):
        name = "CompletingSpecialist"
        description = "Test-only specialist."
        allowed_tools = set()

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.COMPLETE,
                reasoning_summary="Attempt to terminate the workflow.",
            )

    with pytest.raises(AgentDecisionValidationError, match="only SupervisorAgent"):
        AgentExecutor._validate_decision_contract(
            CompletingSpecialist(),
            CompletingSpecialist().step(AgentState(workflow_id="specialist_complete", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)),
        )
