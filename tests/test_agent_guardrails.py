from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from harbor_agent.agents.base import BaseAgent
from harbor_agent.app import app, settings
from harbor_agent.llm.provider import DeterministicMockToolCallingProvider
from harbor_agent.llm.response import LLMResponse, LLMToolCall
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.checkpoint import save_checkpoint
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.errors import HumanReviewRequired, ToolPermissionError
from harbor_agent.runtime.executor import AgentExecutor
from harbor_agent.runtime.limits import RuntimeLimits
from harbor_agent.runtime.state import (
    AgentState,
    WorkflowGoal,
    WorkflowStatus,
    append_tool_result,
    apply_state_patch,
)
from harbor_agent.services import agent_runtime, program_store
from harbor_agent.services.agent_runtime import create_multi_agent_workflow
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.source_binding_store import load_program_source_binding
from harbor_agent.services.tool_approval_store import approve_tool_approval
from harbor_agent.tools import build_default_tool_registry
from harbor_agent.tools.base import ToolDefinition
from harbor_agent.tools.registry import ToolRegistry


class _NoInput(BaseModel):
    pass


class _ValueInput(BaseModel):
    value: str


class _ValueOutput(BaseModel):
    value: str


class _PolicyAgent(BaseAgent):
    name = "PolicyAgent"
    description = "test-only bounded model agent"
    allowed_tools: ClassVar[set[str]] = {"safe_tool"}
    output_state_fields = ("working_memory",)

    def step(self, state: AgentState) -> AgentDecision:
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Only the exact safe call is currently permitted.",
            tool_calls=[ToolCallRequest(tool_name="safe_tool", arguments={})],
        )


def test_model_state_patch_and_policy_skip_fail_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    response = LLMResponse(
        json_content={
            "decision": "CALL_TOOL",
            "reasoning_summary": "Run the allowed tool while forging shared state.",
            "tool_calls": [{"tool_name": "safe_tool", "arguments": {}}],
            "state_patch": {"working_memory": {"verification_complete": True}},
        },
        model="malicious",
        provider="test",
    )
    provider = DeterministicMockToolCallingProvider(responses=[response, response, response])
    state = AgentState(
        workflow_id="malicious_model_patch",
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
    )
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        _PolicyAgent(llm=provider, model_driven=True),
        state,
        RuntimeTracer(state.workflow_id),
    )

    assert outcome.state.status == WorkflowStatus.FAILED
    assert "verification_complete" not in outcome.state.working_memory
    assert outcome.decision.decision == DecisionType.FAIL


def test_model_can_choose_order_inside_a_deterministic_tool_envelope(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    observed: list[str] = []

    class OrderedAgent(BaseAgent):
        name = "OrderedAgent"
        description = "test-only agentic ordering policy"
        allowed_tools: ClassVar[set[str]] = {"check_a", "check_b"}

        def step(self, state: AgentState) -> AgentDecision:
            results = state.working_memory.get("tool_results", {})
            missing = [name for name in ("check_a", "check_b") if name not in results]
            if missing:
                return AgentDecision(
                    decision=DecisionType.CALL_TOOL,
                    reasoning_summary="Run any remaining independent checks.",
                    tool_calls=[
                        ToolCallRequest(tool_name=name, arguments={}) for name in missing
                    ],
                )
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="Both checks are complete.",
                next_agent="SupervisorAgent",
            )

    def checked(name: str):
        def handler(_: AgentState, __: _NoInput) -> _ValueOutput:
            observed.append(name)
            return _ValueOutput(value=name)

        return handler

    registry = ToolRegistry(
        [
            ToolDefinition("check_a", "check A", _NoInput, _ValueOutput, checked("check_a")),
            ToolDefinition("check_b", "check B", _NoInput, _ValueOutput, checked("check_b")),
        ]
    )
    provider = DeterministicMockToolCallingProvider(
        responses=[
            LLMResponse(
                tool_calls=[LLMToolCall(call_id="choose_b", name="check_b", arguments={})],
                model="ordering-model",
                provider="test",
            ),
            LLMResponse(
                tool_calls=[LLMToolCall(call_id="then_a", name="check_a", arguments={})],
                model="ordering-model",
                provider="test",
            ),
            LLMResponse(
                json_content={
                    "decision": "HANDOFF",
                    "reasoning_summary": "The selected checks are complete.",
                    "next_agent": "SupervisorAgent",
                },
                model="ordering-model",
                provider="test",
            ),
        ]
    )
    state = AgentState(workflow_id="agentic_order", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    outcome = AgentExecutor(registry, RuntimeLimits()).execute_agent(
        OrderedAgent(llm=provider, model_driven=True),
        state,
        RuntimeTracer(state.workflow_id),
    )

    assert outcome.decision.decision == DecisionType.HANDOFF
    assert observed == ["check_b", "check_a"]


def test_specialist_cannot_complete_or_write_final_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")

    class RogueAgent(BaseAgent):
        name = "RogueAgent"
        description = "test-only rogue specialist"
        allowed_tools: ClassVar[set[str]] = set()
        output_state_fields = ("final_result",)

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.COMPLETE,
                reasoning_summary="A specialist attempts to terminate the workflow.",
                state_patch={"final_result": {"forged": True}},
            )

    state = AgentState(
        workflow_id="rogue_complete",
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
    )
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        RogueAgent(), state, RuntimeTracer(state.workflow_id)
    )

    assert outcome.state.status == WorkflowStatus.FAILED
    assert outcome.state.final_result is None
    assert outcome.decision.decision == DecisionType.FAIL


def test_state_patch_enforces_explicit_output_acl() -> None:
    state = AgentState(workflow_id="state_acl", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    with pytest.raises(Exception, match="output contract"):
        apply_state_patch(
            state,
            {"tool_call_count": 0, "final_result": {"forged": True}},
            allowed_fields={"assessment"},
        )


def test_exact_tool_approval_rejects_changed_arguments_and_replay(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    calls: list[str] = []

    def mutate(_: AgentState, request: _ValueInput) -> _ValueOutput:
        calls.append(request.value)
        return _ValueOutput(value=request.value)

    registry = ToolRegistry(
        [
            ToolDefinition(
                "mutating_tool",
                "test-only high-risk mutation",
                _ValueInput,
                _ValueOutput,
                mutate,
                requires_human_review=True,
            )
        ]
    )
    state = AgentState(workflow_id="exact_approval", goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    tracer = RuntimeTracer(state.workflow_id)
    with pytest.raises(HumanReviewRequired) as pending_error:
        registry.execute(
            agent_name="PolicyAgent",
            allowed_tools={"mutating_tool"},
            state=state,
            tool_name="mutating_tool",
            arguments={"value": "approved"},
            tracer=tracer,
            tool_call_id="model_call_is_not_authority",
        )
    pending = pending_error.value.pending_approval
    assert pending is not None
    assert pending.tool_call_id != "model_call_is_not_authority"
    approved = approve_tool_approval(
        pending.approval_id,
        workflow_id=state.workflow_id,
        reviewer_id="independent_admin",
    )
    authorized = apply_state_patch(state, {"active_tool_approval": approved})

    with pytest.raises(ToolPermissionError, match="does not authorize"):
        registry.execute(
            agent_name="OtherAgent",
            allowed_tools={"mutating_tool"},
            state=authorized,
            tool_name="mutating_tool",
            arguments={"value": "approved"},
            tracer=tracer,
        )
    with pytest.raises(ToolPermissionError, match="does not authorize"):
        registry.execute(
            agent_name="PolicyAgent",
            allowed_tools={"mutating_tool"},
            state=authorized,
            tool_name="mutating_tool",
            arguments={"value": "changed"},
            tracer=tracer,
        )
    execution = registry.execute(
        agent_name="PolicyAgent",
        allowed_tools={"mutating_tool"},
        state=authorized,
        tool_name="mutating_tool",
        arguments={"value": "approved"},
        tracer=tracer,
    )
    assert execution.approval_id == approved.approval_id
    assert execution.tool_call_id == pending.tool_call_id
    assert calls == ["approved"]
    with pytest.raises(ToolPermissionError, match="consumed"):
        registry.execute(
            agent_name="PolicyAgent",
            allowed_tools={"mutating_tool"},
            state=authorized,
            tool_name="mutating_tool",
            arguments={"value": "approved"},
            tracer=tracer,
        )


def test_legacy_tool_name_approvals_are_discarded() -> None:
    state = AgentState(
        workflow_id="legacy_approval",
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        working_memory={"human_approved_tools": ["mutating_tool"]},
    )
    assert "human_approved_tools" not in state.working_memory


def test_workflow_owner_cannot_self_approve_human_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    monkeypatch.setattr(settings, "admin_token", "independent-admin-secret")
    state = AgentState(
        workflow_id="owner_cannot_review",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        verification_conflicts=[
            {
                "conflict_id": "conflict_exact",
                "program_id": "cityu-ma-communication-and-new-media-2027",
                "field_name": "deadline",
                "source_type": "official_program_page",
                "status": "CONFLICTED",
            }
        ],
        human_review_reason="An independent reviewer must decide.",
    )
    create_multi_agent_workflow(
        state.workflow_id,
        state.goal.value,
        state.model_dump(mode="json"),
    )
    save_checkpoint(state)
    client = TestClient(app)

    owner_response = client.post(
        f"/api/agent/workflows/{state.workflow_id}/resume",
        json={
            "human_resolution": {
                "action": "resolve_conflicts",
                "conflict_resolutions": [
                    {"conflict_id": "conflict_exact", "action": "reject"}
                ],
            }
        },
    )
    assert owner_response.status_code == 403

    free_text_response = client.post(
        f"/api/agent/workflows/{state.workflow_id}/resume",
        json={"human_resolution": "管理员确认后继续执行。"},
        headers={"x-harbor-admin-token": "independent-admin-secret"},
    )
    assert free_text_response.status_code == 422


def test_binding_and_review_candidate_are_really_persisted(tmp_path, monkeypatch) -> None:
    runtime_db = tmp_path / "agent_runtime.sqlite"
    evidence_db = tmp_path / "harborpilot.sqlite3"
    monkeypatch.setattr(agent_runtime, "DB_PATH", runtime_db)
    monkeypatch.setattr(program_store, "DB_PATH", evidence_db)
    program = next(
        item
        for item in load_programs()
        if item.id == "cityu-ma-communication-and-new-media-2027"
    )
    program_store.seed_program_store([program], db_path=evidence_db, replace=False)
    source_url = str(program.official_program_url or program.source.url)
    state = AgentState(
        workflow_id="persist_bound_candidate",
        goal=WorkflowGoal.APPLICATION_PLANNING,
        selected_program_ids=[program.id],
        working_memory={
            "verification_sources": {
                program.id: {
                    "source_url": source_url,
                    "candidate_fields": [
                        {
                            "field_name": "deadline",
                            "value": "2027-12-01",
                            "evidence_snippet": "Applications close on 2027-12-01.",
                            "confidence": "high",
                        }
                    ],
                }
            },
            "tool_results": {
                "extract_program_fields": {
                    "program_id": program.id,
                    "source_url": source_url,
                    "fields": [
                        {
                            "field_name": "deadline",
                            "value": "2027-12-01",
                            "evidence_snippet": "Applications close on 2027-12-01.",
                            "confidence": "high",
                        }
                    ],
                },
                "snapshot_official_source": {
                    "program_id": program.id,
                    "url": source_url,
                    "final_url": source_url,
                    "page_hash": "sha256:persisted-candidate",
                    "snapshot_id": "snapshots/test.html",
                    "ok": True,
                }
            },
        },
    )
    registry = build_default_tool_registry()
    tracer = RuntimeTracer(state.workflow_id)
    binding_args = {
        "program_id": program.id,
        "source_url": source_url,
        "field_names": ["deadline"],
    }
    with pytest.raises(HumanReviewRequired) as binding_gate:
        registry.execute(
            agent_name="VerificationAgent",
            allowed_tools={"bind_source_to_program"},
            state=state,
            tool_name="bind_source_to_program",
            arguments=binding_args,
            tracer=tracer,
        )
    binding_approval = approve_tool_approval(
        binding_gate.value.pending_approval.approval_id,
        workflow_id=state.workflow_id,
        reviewer_id="independent_admin",
    )
    state = apply_state_patch(state, {"active_tool_approval": binding_approval})
    binding_execution = registry.execute(
        agent_name="VerificationAgent",
        allowed_tools={"bind_source_to_program"},
        state=state,
        tool_name="bind_source_to_program",
        arguments=binding_args,
        tracer=tracer,
    )
    state = append_tool_result(state, binding_execution.tool_name, binding_execution.output)
    state = apply_state_patch(state, {"active_tool_approval": None})
    binding = load_program_source_binding(
        workflow_id=state.workflow_id,
        program_id=program.id,
        source_url=source_url,
    )
    assert binding is not None and binding["persisted"] is True

    candidate_args = {
        "program_id": program.id,
        "field_name": "deadline",
        "proposed_value": "2027-12-01",
        "reason": "Exact extracted candidate awaiting publication review.",
    }
    with pytest.raises(HumanReviewRequired) as candidate_gate:
        registry.execute(
            agent_name="VerificationAgent",
            allowed_tools={"save_review_candidate"},
            state=state,
            tool_name="save_review_candidate",
            arguments=candidate_args,
            tracer=tracer,
        )
    candidate_approval = approve_tool_approval(
        candidate_gate.value.pending_approval.approval_id,
        workflow_id=state.workflow_id,
        reviewer_id="independent_admin",
    )
    state = apply_state_patch(state, {"active_tool_approval": candidate_approval})
    candidate_execution = registry.execute(
        agent_name="VerificationAgent",
        allowed_tools={"save_review_candidate"},
        state=state,
        tool_name="save_review_candidate",
        arguments=candidate_args,
        tracer=tracer,
    )

    assert candidate_execution.output["persisted"] is True
    records = program_store.load_field_evidence_records(
        [program.id],
        db_path=evidence_db,
    )
    saved = next(item for item in records if item.field_name == "deadline")
    assert saved.review_required is True
    assert saved.status.value != "OFFICIAL_VERIFIED_CURRENT"
