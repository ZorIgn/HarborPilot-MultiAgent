from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from harbor_agent.agents import build_agent_registry
from harbor_agent.agents.base import BaseAgent
from harbor_agent.agents.supervisor import SupervisorAgent, SupervisorRoute
from harbor_agent.llm.provider import RuntimeLLMProvider
from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.checkpoint import CheckpointPolicy, load_checkpoint, save_checkpoint
from harbor_agent.runtime.decision import AgentDecision, DecisionType
from harbor_agent.runtime.errors import WorkflowLimitExceeded
from harbor_agent.runtime.executor import AgentExecutor
from harbor_agent.runtime.limits import RuntimeLimits, enforce_workflow_limits
from harbor_agent.runtime.sanitizer import sanitize_runtime_payload
from harbor_agent.runtime.state import (
    AgentState,
    ConflictResolution,
    HumanResolution,
    WorkflowGoal,
    WorkflowStatus,
    apply_state_patch,
)
from harbor_agent.services.agent_runtime import (
    create_multi_agent_workflow,
    get_multi_agent_workflow,
    list_multi_agent_workflows,
)
from harbor_agent.tools import build_default_tool_registry
from harbor_agent.tools.registry import ToolRegistry


class WorkflowStartRequest(BaseModel):
    goal: WorkflowGoal
    profile: dict[str, Any]
    user_request: str = ""
    questionnaire: dict[str, Any] | None = None
    selected_program_ids: list[str] = Field(default_factory=list, max_length=20)
    document_type: str = "PS"
    refresh_official_sources: bool = False


class WorkflowResumeRequest(BaseModel):
    user_message: str | None = None
    human_resolution: HumanResolution | None = None


class MultiAgentRuntime:
    """Supervisor-driven runtime with typed state, checkpoint/resume and real tool traces."""

    def __init__(
        self,
        *,
        llm: RuntimeLLMProvider | None = None,
        model_driven: bool = False,
        tool_registry: ToolRegistry | None = None,
        limits: RuntimeLimits | None = None,
    ) -> None:
        self.limits = limits or RuntimeLimits()
        self.tools = tool_registry or build_default_tool_registry()
        self.agents = build_agent_registry(llm=llm, model_driven=model_driven)
        # A Supervisor turn surrounds each specialist turn. Keep its per-agent cap
        # bounded by the workflow cap so long verification/replan paths can finish.
        supervisor_limits = self.limits.model_copy(update={"max_agent_turns_per_agent": max(self.limits.max_agent_turns_per_agent, self.limits.max_workflow_steps)})
        self.supervisor_executor = AgentExecutor(self.tools, supervisor_limits)
        self.executor = AgentExecutor(self.tools, self.limits)
        self.checkpoint_policy = CheckpointPolicy()

    def _save_checkpoint(self, state: AgentState, *, force: bool = False) -> str | None:
        """Persist only policy-approved snapshots; forced boundaries always save."""

        return save_checkpoint(state, force=force, policy=self.checkpoint_policy)

    def start(self, request: WorkflowStartRequest, *, owner_id: str | None = None) -> AgentState:
        workflow_id = f"maf_{uuid4().hex[:16]}"
        safe_profile = sanitize_runtime_payload(request.profile)
        safe_questionnaire = sanitize_runtime_payload(request.questionnaire)
        safe_user_request = sanitize_runtime_payload(request.user_request) or ""
        state = AgentState(
            workflow_id=workflow_id,
            goal=request.goal,
            user_request=safe_user_request,
            raw_profile=safe_profile if isinstance(safe_profile, dict) else {},
            questionnaire=safe_questionnaire if isinstance(safe_questionnaire, dict) else None,
            selected_program_ids=request.selected_program_ids,
            document_type=request.document_type,
            max_steps=self.limits.max_workflow_steps,
            working_memory={
                "explicit_selected_program_ids": list(request.selected_program_ids),
                "verification_source_fetch_enabled": bool(request.refresh_official_sources),
            },
        )
        create_multi_agent_workflow(workflow_id, state.goal.value, state.model_dump(mode="json"), owner_id=owner_id)
        tracer = RuntimeTracer(workflow_id)
        tracer.emit(TraceEventType.WORKFLOW_STARTED, output_summary=f"goal={state.goal.value}")
        tracer.emit(TraceEventType.WORKFLOW_START, output_summary=f"goal={state.goal.value}")
        self._save_checkpoint(state, force=True)
        return self._run(state, tracer)

    def resume(
        self,
        workflow_id: str,
        request: WorkflowResumeRequest,
        *,
        reviewer_id: str | None = None,
    ) -> AgentState:
        state = load_checkpoint(workflow_id)
        if state is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        if state.status not in {WorkflowStatus.WAITING_USER, WorkflowStatus.WAITING_HUMAN, WorkflowStatus.FAILED_RETRYABLE}:
            raise ValueError(f"workflow cannot resume from status {state.status.value}")
        if request.user_message and request.human_resolution is not None:
            raise ValueError("user input and human review must be submitted separately")
        if state.status == WorkflowStatus.WAITING_HUMAN:
            if request.user_message:
                raise ValueError("user messages cannot release a human-review gate")
            if request.human_resolution is None:
                raise ValueError("WAITING_HUMAN requires an explicit typed reviewer decision")
            if not reviewer_id:
                raise PermissionError("human review requires an authenticated administrator")
        if state.status == WorkflowStatus.WAITING_USER and request.human_resolution is not None:
            raise ValueError("WAITING_USER accepts only a user_message")
        memory = deepcopy(state.working_memory)
        user_messages = list(state.user_messages)
        raw_profile = deepcopy(state.raw_profile)
        if request.user_message:
            safe_user_message = sanitize_runtime_payload(request.user_message) or ""
            user_messages.append({"role": "user", "content": safe_user_message})
            memory["latest_user_message"] = safe_user_message
            raw_profile = _apply_json_profile_supplement(raw_profile, safe_user_message)
        resolution: HumanResolution | None = None
        human_patch: dict[str, Any] = {}
        if request.human_resolution is not None:
            resolution = _coerce_human_resolution(request.human_resolution)
            assert reviewer_id is not None
            if state.pending_tool_approval is not None:
                if resolution.action not in {"approve_tool", "reject_tool"}:
                    raise ValueError("the current gate requires a decision for the pending tool call")
                if resolution.approval_id != state.pending_tool_approval.approval_id:
                    raise ValueError("approval_id does not match the pending tool call")
                if resolution.action == "approve_tool":
                    from harbor_agent.services.tool_approval_store import approve_tool_approval

                    approved = approve_tool_approval(
                        resolution.approval_id,
                        workflow_id=workflow_id,
                        reviewer_id=reviewer_id,
                        reviewer_note=resolution.note,
                    )
                    human_patch = {
                        "pending_tool_approval": None,
                        "active_tool_approval": approved,
                        "human_resolution": resolution,
                    }
                else:
                    from harbor_agent.services.tool_approval_store import reject_tool_approval

                    rejected = reject_tool_approval(
                        resolution.approval_id,
                        workflow_id=workflow_id,
                        reviewer_id=reviewer_id,
                        reviewer_note=resolution.note,
                    )
                    state = apply_state_patch(
                        state,
                        {
                            "status": WorkflowStatus.FAILED.value,
                            "pending_tool_approval": None,
                            "active_tool_approval": None,
                            "human_resolution": resolution,
                            "human_review_reason": None,
                            "errors": [
                                *state.errors,
                                f"Reviewer rejected {rejected.tool_name} approval {rejected.approval_id}.",
                            ],
                        },
                    )
                    self._save_checkpoint(state, force=True)
                    return state
            elif state.verification_conflicts:
                if resolution.action != "resolve_conflicts":
                    raise ValueError("the current gate requires exact conflict decisions")
                memory, human_patch = _apply_human_conflict_resolution(
                    state,
                    memory,
                    resolution,
                    reviewer_id=reviewer_id,
                )
            else:
                raise ValueError("workflow has no pending tool approval or evidence conflict")
            memory["human_resolution"] = resolution.model_dump(mode="json")
        resume_patch: dict[str, Any] = {}
        if request.user_message:
            # New profile information invalidates every derived decision. This
            # makes resuming a genuine reassessment, not a stale continuation.
            memory["tool_results"] = {}
            memory.pop("critic_outcome", None)
            memory.pop("verification_complete", None)
            memory.pop("verification_cursor", None)
            resume_patch = {
                "normalized_profile": None,
                "assessment": None,
                "evidence_review": None,
                "missing_profile_fields": [],
                "candidate_program_ids": [],
                "researched_program_ids": [],
                "program_matches": {},
                "selected_matches": [],
                "fields_needing_verification": {},
                "verified_program_fields": {},
                "verification_conflicts": [],
            }
        resolved_state_patch = {"human_resolution": resolution} if resolution is not None else {}
        unresolved_conflicts = bool(human_patch.get("verification_conflicts"))
        state = apply_state_patch(
            state,
            {
                "status": (
                    WorkflowStatus.WAITING_HUMAN.value
                    if unresolved_conflicts
                    else WorkflowStatus.RUNNING.value
                ),
                "user_question": None,
                "human_review_reason": (
                    "Evidence conflicts remain; submit an exact decision for every remaining conflict."
                    if unresolved_conflicts
                    else None
                ),
                "user_messages": user_messages,
                "raw_profile": raw_profile,
                "working_memory": memory,
                **human_patch,
                **resolved_state_patch,
                **resume_patch,
            },
        )
        tracer = RuntimeTracer(workflow_id)
        tracer.emit(TraceEventType.RETRY, output_summary="workflow resumed after user or human input")
        self._save_checkpoint(state, force=True)
        if state.status == WorkflowStatus.WAITING_HUMAN:
            return state
        return self._run(state, tracer)

    def get_state(self, workflow_id: str) -> AgentState | None:
        return load_checkpoint(workflow_id)

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return get_multi_agent_workflow(workflow_id)

    def list_workflows(self, limit: int = 80) -> list[dict[str, Any]]:
        return list_multi_agent_workflows(limit)

    def _supervisor_turn(
        self,
        state: AgentState,
        tracer: RuntimeTracer,
        supervisor: SupervisorAgent,
    ) -> tuple[AgentState, SupervisorRoute | None, bool]:
        """Execute a model-driven Supervisor turn or use the deterministic fallback."""

        model_driven = bool(supervisor.llm and supervisor.model_driven)
        if not model_driven:
            route = supervisor.route(state)
            if route.state_patch:
                state = apply_state_patch(state, route.state_patch)
            return state, route, False

        outcome = self.supervisor_executor.execute_agent(supervisor, state, tracer)
        state = outcome.state
        decision = outcome.decision
        if decision.decision == DecisionType.FAIL or state.status == WorkflowStatus.FAILED:
            self._save_checkpoint(state, force=True)
            tracer.emit(
                TraceEventType.ERROR,
                agent_name=supervisor.name,
                output_summary=decision.reasoning_summary,
            )
            return state, None, True

        route = _supervisor_route_from_decision(decision)
        if route is None:
            error = ValueError("Supervisor returned an unregistered route.")
            state = apply_state_patch(
                state,
                {"status": WorkflowStatus.FAILED.value, "errors": [*state.errors, str(error)]},
            )
            self._save_checkpoint(state, force=True)
            tracer.emit(TraceEventType.ERROR, agent_name=supervisor.name, error=error)
            return state, None, True

        tracer.emit(
            TraceEventType.SUPERVISOR_ROUTE,
            agent_name=supervisor.name,
            output_summary=f"selected={route.next_agent}; reason={route.reason}",
        )
        if self._save_checkpoint(state):
            tracer.emit(
                TraceEventType.CHECKPOINT,
                agent_name=supervisor.name,
                output_summary=f"status={state.status.value}",
            )
        return state, route, True

    def _run(self, state: AgentState, tracer: RuntimeTracer) -> AgentState:
        supervisor = self.agents["SupervisorAgent"]
        assert isinstance(supervisor, SupervisorAgent)
        while state.status == WorkflowStatus.RUNNING:
            try:
                enforce_workflow_limits(state, self.limits)
                state, route, model_supervisor = self._supervisor_turn(state, tracer, supervisor)
                if route is None:
                    return state
                if not model_supervisor:
                    tracer.emit(
                        TraceEventType.SUPERVISOR_ROUTE,
                        agent_name=supervisor.name,
                        output_summary=f"selected={route.next_agent}; reason={route.reason}",
                    )
                if route.next_agent == "END":
                    if state.status == WorkflowStatus.RUNNING:
                        state = apply_state_patch(state, {"status": WorkflowStatus.COMPLETED.value})
                    self._save_checkpoint(state, force=True)
                    tracer.emit(
                        TraceEventType.CHECKPOINT,
                        agent_name=supervisor.name,
                        output_summary="terminal checkpoint",
                    )
                    tracer.emit(TraceEventType.WORKFLOW_COMPLETED, agent_name=supervisor.name, output_summary=route.reason)
                    tracer.emit(TraceEventType.WORKFLOW_END, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                if route.next_agent == "ASK_USER":
                    if state.status == WorkflowStatus.RUNNING:
                        state = apply_state_patch(state, {"status": WorkflowStatus.WAITING_USER.value})
                    self._save_checkpoint(state, force=True)
                    tracer.emit(TraceEventType.USER_WAIT, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                if route.next_agent == "HUMAN_REVIEW":
                    if state.status == WorkflowStatus.RUNNING:
                        state = apply_state_patch(state, {"status": WorkflowStatus.WAITING_HUMAN.value})
                    self._save_checkpoint(state, force=True)
                    tracer.emit(TraceEventType.HUMAN_WAIT, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                agent = self.agents[route.next_agent]
                assert isinstance(agent, BaseAgent)
                outcome = self.executor.execute_agent(agent, state, tracer)
                state = outcome.state
                if self._save_checkpoint(state, force=state.status != WorkflowStatus.RUNNING):
                    tracer.emit(
                        TraceEventType.CHECKPOINT,
                        agent_name=agent.name,
                        output_summary=f"status={state.status.value}",
                    )
                if state.status == WorkflowStatus.WAITING_USER:
                    tracer.emit(TraceEventType.USER_WAIT, agent_name=agent.name, output_summary=state.user_question)
                    return state
                if state.status == WorkflowStatus.WAITING_HUMAN:
                    tracer.emit(TraceEventType.HUMAN_WAIT, agent_name=agent.name, output_summary=state.human_review_reason)
                    return state
                if state.status in {WorkflowStatus.FAILED, WorkflowStatus.COMPLETED}:
                    tracer.emit(TraceEventType.WORKFLOW_COMPLETED if state.status == WorkflowStatus.COMPLETED else TraceEventType.ERROR, agent_name=agent.name, output_summary="agent returned terminal state")
                    tracer.emit(TraceEventType.WORKFLOW_END, agent_name=agent.name, output_summary="agent returned terminal state")
                    return state
            except WorkflowLimitExceeded as exc:
                state = apply_state_patch(state, {"status": WorkflowStatus.FAILED.value, "errors": [*state.errors, str(exc)]})
                self._save_checkpoint(state, force=True)
                tracer.emit(TraceEventType.ERROR, agent_name=supervisor.name, error=exc)
                return state
        return state


def _supervisor_route_from_decision(decision: AgentDecision) -> SupervisorRoute | None:
    """Translate an Executor decision into a validated visible route event."""

    if decision.decision == DecisionType.COMPLETE:
        target = "END"
    elif decision.decision == DecisionType.ASK_USER:
        target = "ASK_USER"
    elif decision.decision == DecisionType.HUMAN_REVIEW:
        target = "HUMAN_REVIEW"
    elif decision.decision == DecisionType.HANDOFF:
        target = decision.next_agent
    else:
        return None
    if target not in {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "PlanningAgent", "WritingAgent", "CriticAgent", "ASK_USER", "HUMAN_REVIEW", "END"}:
        return None
    return SupervisorRoute(next_agent=target, reason=decision.reasoning_summary, state_patch=decision.state_patch)

def _coerce_human_resolution(value: HumanResolution | dict[str, Any]) -> HumanResolution:
    """Accept only the strict typed reviewer contract."""

    return value if isinstance(value, HumanResolution) else HumanResolution.model_validate(value)


def _apply_human_conflict_resolution(
    state: AgentState,
    memory: dict[str, Any],
    resolution: HumanResolution,
    *,
    reviewer_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist exact decisions, then remove only those conflicts from state."""

    from harbor_agent.runtime.state import annotate_conflict
    from harbor_agent.services.review_gate import persist_conflict_decision

    active = [annotate_conflict(item) for item in state.verification_conflicts]
    decisions = list(resolution.conflict_resolutions)
    by_id = {str(item["conflict_id"]): item for item in active}
    decision_ids = [item.conflict_id for item in decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("duplicate conflict decisions are not allowed")
    unknown = set(decision_ids) - set(by_id)
    if unknown:
        raise ValueError(f"unknown conflict_id values: {sorted(unknown)}")
    remaining: list[dict[str, Any]] = []
    resolved: list[ConflictResolution] = []
    for conflict in active:
        conflict_id = str(conflict["conflict_id"])
        decision = next((item for item in decisions if item.conflict_id == conflict_id), None)
        if decision is None:
            remaining.append(conflict)
            continue
        if decision.action == "accept" and decision.selected_record_id != conflict_id:
            raise ValueError(
                "selected_record_id must identify the exact record represented by conflict_id"
            )
        persist_conflict_decision(
            conflict,
            action=decision.action,
            conflict_id=conflict_id,
            reviewer_id=reviewer_id,
            reviewer_note=decision.reviewer_note or resolution.note,
        )
        resolved.append(decision)

    # A cached comparison is a snapshot from before the reviewer decision.  Do
    # not feed its old conflict list back to VerificationAgent on resume.
    updated_memory = deepcopy(memory)
    tool_results = dict(updated_memory.get("tool_results", {}))
    comparison = tool_results.get("compare_evidence_records")
    if isinstance(comparison, dict) and decisions:
        filtered = []
        for item in comparison.get("conflicts", []) or []:
            conflict = annotate_conflict(item)
            if str(conflict["conflict_id"]) not in set(decision_ids):
                filtered.append(conflict)
        comparison = {
            **comparison,
            "conflicts": filtered,
            "consistent": not filtered,
            "human_review_required": bool(filtered),
        }
        tool_results["compare_evidence_records"] = comparison
        updated_memory["tool_results"] = tool_results

    resolved_ids = list(updated_memory.get("resolved_conflict_ids", []))
    resolved_ids.extend(item.conflict_id for item in resolved)
    updated_memory["resolved_conflict_ids"] = list(dict.fromkeys(str(item) for item in resolved_ids))
    cursor = int(updated_memory.get("verification_cursor", 0) or 0)
    if not remaining and cursor >= len(state.selected_program_ids):
        updated_memory["verification_complete"] = True
    elif remaining:
        updated_memory["verification_complete"] = False

    audit = list(state.resolved_conflicts)
    seen = {item.conflict_id for item in audit}
    audit.extend(item for item in resolved if item.conflict_id not in seen)
    return updated_memory, {
        "verification_conflicts": remaining,
        "resolved_conflicts": audit,
        "human_resolution": resolution,
    }


def _apply_json_profile_supplement(raw_profile: dict[str, Any] | None, message: str) -> dict[str, Any] | None:
    """Allow a UI resume form to send a small JSON profile patch without storing secrets."""

    if raw_profile is None:
        return raw_profile
    try:
        patch = json.loads(message)
    except json.JSONDecodeError:
        return raw_profile
    if not isinstance(patch, dict):
        return raw_profile
    merged = deepcopy(raw_profile)
    for key, value in patch.items():
        if key in {"language", "education", "additional_background", "discipline_interests", "raw_interest_text", "budget_hkd", "career_goal", "experiences"}:
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged
