from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from harbor_agent.runtime.decision import AgentDecision, DecisionType
from harbor_agent.agents import build_agent_registry
from harbor_agent.agents.base import BaseAgent
from harbor_agent.agents.supervisor import SupervisorAgent, SupervisorRoute
from harbor_agent.llm.provider import RuntimeLLMProvider
from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.checkpoint import load_checkpoint, save_checkpoint
from harbor_agent.runtime.errors import WorkflowLimitExceeded
from harbor_agent.runtime.executor import AgentExecutor
from harbor_agent.runtime.limits import RuntimeLimits, enforce_workflow_limits
from harbor_agent.runtime.sanitizer import sanitize_runtime_payload
from harbor_agent.runtime.state import AgentState, ConflictResolution, HumanResolution, WorkflowGoal, WorkflowStatus, apply_state_patch
from harbor_agent.services.agent_runtime import (
    create_multi_agent_workflow,
    get_multi_agent_workflow,
    list_multi_agent_workflows,
    update_multi_agent_workflow,
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
    human_resolution: HumanResolution | str | None = None


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
        save_checkpoint(state)
        return self._run(state, tracer)

    def resume(self, workflow_id: str, request: WorkflowResumeRequest) -> AgentState:
        state = load_checkpoint(workflow_id)
        if state is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        if state.status not in {WorkflowStatus.WAITING_USER, WorkflowStatus.WAITING_HUMAN, WorkflowStatus.FAILED_RETRYABLE}:
            raise ValueError(f"workflow cannot resume from status {state.status.value}")
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
        unresolved_conflicts = bool(state.verification_conflicts)
        if request.human_resolution is not None:
            resolution = _coerce_human_resolution(
                request.human_resolution,
                active_conflicts=bool(state.verification_conflicts),
            )
            if state.verification_conflicts:
                memory, human_patch = _apply_human_conflict_resolution(state, memory, resolution)
                unresolved_conflicts = bool(human_patch.get("verification_conflicts"))
            approved = list(memory.get("human_approved_tools", []))
            approved.extend(str(item) for item in resolution.approved_tools if item)
            memory["human_approved_tools"] = list(dict.fromkeys(approved))
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
        resume_human_reason = state.human_review_reason if unresolved_conflicts and not request.user_message else None
        resolved_state_patch = {"human_resolution": resolution} if resolution is not None else {}
        state = apply_state_patch(
            state,
            {
                "status": WorkflowStatus.RUNNING.value,
                "user_question": None,
                "human_review_reason": resume_human_reason,
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
        save_checkpoint(state)
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
            update_multi_agent_workflow(state.model_dump(mode="json"))
            save_checkpoint(state)
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
            update_multi_agent_workflow(state.model_dump(mode="json"))
            save_checkpoint(state)
            tracer.emit(TraceEventType.ERROR, agent_name=supervisor.name, error=error)
            return state, None, True

        tracer.emit(
            TraceEventType.SUPERVISOR_ROUTE,
            agent_name=supervisor.name,
            output_summary=f"selected={route.next_agent}; reason={route.reason}",
        )
        update_multi_agent_workflow(state.model_dump(mode="json"))
        save_checkpoint(state)
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
                    if not model_supervisor:
                        state = apply_state_patch(state, {"status": WorkflowStatus.COMPLETED.value})
                        update_multi_agent_workflow(state.model_dump(mode="json"))
                        save_checkpoint(state)
                        tracer.emit(TraceEventType.CHECKPOINT, agent_name=supervisor.name, output_summary="terminal checkpoint")
                    tracer.emit(TraceEventType.WORKFLOW_COMPLETED, agent_name=supervisor.name, output_summary=route.reason)
                    tracer.emit(TraceEventType.WORKFLOW_END, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                if route.next_agent == "ASK_USER":
                    if not model_supervisor:
                        state = apply_state_patch(state, {"status": WorkflowStatus.WAITING_USER.value})
                        update_multi_agent_workflow(state.model_dump(mode="json"))
                        save_checkpoint(state)
                    tracer.emit(TraceEventType.USER_WAIT, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                if route.next_agent == "HUMAN_REVIEW":
                    if not model_supervisor:
                        state = apply_state_patch(state, {"status": WorkflowStatus.WAITING_HUMAN.value})
                        update_multi_agent_workflow(state.model_dump(mode="json"))
                        save_checkpoint(state)
                    tracer.emit(TraceEventType.HUMAN_WAIT, agent_name=supervisor.name, output_summary=route.reason)
                    return state
                agent = self.agents[route.next_agent]
                assert isinstance(agent, BaseAgent)
                outcome = self.executor.execute_agent(agent, state, tracer)
                state = outcome.state
                update_multi_agent_workflow(state.model_dump(mode="json"))
                save_checkpoint(state)
                tracer.emit(TraceEventType.CHECKPOINT, agent_name=agent.name, output_summary=f"status={state.status.value}")
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
                update_multi_agent_workflow(state.model_dump(mode="json"))
                save_checkpoint(state)
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

def _coerce_human_resolution(value: HumanResolution | str | dict[str, Any], *, active_conflicts: bool) -> HumanResolution:
    """Normalize legacy free text and dict payloads to one typed decision."""

    if isinstance(value, HumanResolution):
        resolution = value
    else:
        resolution = HumanResolution.model_validate(value)
    # Older clients submit a plain reviewer note.  The HumanResolution
    # validator marks it as resolve_conflicts; retain that explicit intent.
    if active_conflicts and isinstance(value, str) and not resolution.conflict_resolutions:
        resolution.resolve_conflicts = True
        resolution.action = "resolve_conflicts"
    return resolution


def _conflict_fingerprint(conflict: dict[str, Any]) -> str:
    """Build a stable ID for evidence records that have no persisted ID."""

    for key in ("conflict_id", "id", "record_id", "review_decision_id"):
        value = conflict.get(key)
        if value:
            return str(value)
    identity = {
        key: conflict.get(key)
        for key in ("program_id", "field_name", "source_url", "official_url", "page_hash", "value", "evidence_snippet")
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)
    return "conflict_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _annotate_conflict(conflict: Any) -> dict[str, Any]:
    item = dict(conflict) if isinstance(conflict, dict) else {"value": str(conflict)}
    item.setdefault("conflict_id", _conflict_fingerprint(item))
    return item


def _resolution_matches(conflict: dict[str, Any], resolution: ConflictResolution) -> bool:
    if resolution.all_conflicts:
        return True
    conflict_id = _conflict_fingerprint(conflict)
    candidate_ids = {
        str(conflict_id),
        *(str(conflict.get(key)) for key in ("conflict_id", "id", "record_id", "review_decision_id") if conflict.get(key)),
    }
    if resolution.conflict_id and str(resolution.conflict_id) in candidate_ids:
        return True
    if resolution.selected_record_id and str(resolution.selected_record_id) in candidate_ids:
        return True
    if resolution.program_id and str(conflict.get("program_id")) != str(resolution.program_id):
        return False
    if resolution.field_name and str(conflict.get("field_name")) != str(resolution.field_name):
        return False
    return bool(resolution.program_id or resolution.field_name)


def _apply_human_conflict_resolution(
    state: AgentState,
    memory: dict[str, Any],
    resolution: HumanResolution,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove resolved conflicts and invalidate stale comparison tool output."""

    active = [_annotate_conflict(item) for item in state.verification_conflicts]
    decisions = list(resolution.conflict_resolutions)
    if not decisions and (resolution.resolve_conflicts or resolution.action in {"resolve_conflicts", "resolve"}):
        decisions = [
            ConflictResolution(
                action="resolve",
                all_conflicts=True,
                reviewer_note=resolution.note,
            )
        ]
    remaining: list[dict[str, Any]] = []
    resolved: list[ConflictResolution] = []
    for conflict in active:
        decision = next((item for item in decisions if _resolution_matches(conflict, item)), None)
        if decision is None:
            remaining.append(conflict)
            continue
        resolved.append(
            decision.model_copy(
                update={
                    "conflict_id": conflict["conflict_id"],
                    "program_id": decision.program_id or conflict.get("program_id"),
                    "field_name": decision.field_name or conflict.get("field_name"),
                    "all_conflicts": False,
                }
            )
        )

    # A cached comparison is a snapshot from before the reviewer decision.  Do
    # not feed its old conflict list back to VerificationAgent on resume.
    updated_memory = deepcopy(memory)
    tool_results = dict(updated_memory.get("tool_results", {}))
    comparison = tool_results.get("compare_evidence_records")
    if isinstance(comparison, dict) and decisions:
        filtered = []
        for item in comparison.get("conflicts", []) or []:
            conflict = _annotate_conflict(item)
            if not any(_resolution_matches(conflict, decision) for decision in decisions):
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
    resolved_ids.extend(item.conflict_id for item in resolved if item.conflict_id)
    updated_memory["resolved_conflict_ids"] = list(dict.fromkeys(str(item) for item in resolved_ids))
    cursor = int(updated_memory.get("verification_cursor", 0) or 0)
    if not remaining and cursor >= len(state.selected_program_ids):
        updated_memory["verification_complete"] = True
    elif remaining:
        updated_memory["verification_complete"] = False

    audit = list(state.resolved_conflicts)
    seen = {item.conflict_id for item in audit if item.conflict_id}
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
