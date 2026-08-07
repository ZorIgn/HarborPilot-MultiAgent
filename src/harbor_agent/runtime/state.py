from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from harbor_agent.runtime.errors import AgentDecisionValidationError
from harbor_agent.runtime.sanitizer import sanitize_runtime_payload


class WorkflowGoal(str, Enum):
    BACKGROUND_ASSESSMENT = "background_assessment"
    PROGRAM_RECOMMENDATION = "program_recommendation"
    APPLICATION_PLANNING = "application_planning"
    WRITING = "writing"
    FULL_APPLICATION_PLAN = "full_application_plan"

    @classmethod
    def _missing_(cls, value: object):  # type: ignore[override]
        """Accept the documented upper-case API spelling as an input alias."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if normalized in {member.value, member.name.lower()}:
                    return member
        return None


class WorkflowStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"


class WorkflowTaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class WorkflowTask(BaseModel):
    """A visible, resumable unit of work owned by one specialized agent."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    description: str
    assigned_agent: str | None = None
    status: WorkflowTaskStatus = WorkflowTaskStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)
    result_ref: str | None = None
    blocker: str | None = None


class ConflictResolution(BaseModel):
    """A typed reviewer decision for one evidence conflict."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str | None = None
    program_id: str | None = None
    field_name: str | None = None
    action: Literal["accept", "reject", "dismiss", "resolve"] = "resolve"
    selected_record_id: str | None = None
    reviewer_note: str | None = None
    all_conflicts: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        aliases = {
            "conflict_id": ("id", "conflictId"),
            "program_id": ("programId",),
            "field_name": ("field", "fieldName"),
            "selected_record_id": ("record_id", "recordId", "selectedRecordId"),
            "reviewer_note": ("note", "reviewerNote"),
            "all_conflicts": ("all", "resolve_all", "resolveAll"),
        }
        for canonical, alternatives in aliases.items():
            if canonical not in data:
                for alternative in alternatives:
                    if alternative in data:
                        data[canonical] = data[alternative]
                        break
            for alternative in alternatives:
                data.pop(alternative, None)
        if "action" not in data:
            for alternative in ("decision", "resolution"):
                if alternative in data and isinstance(data[alternative], str):
                    data["action"] = data[alternative]
                    break
        for alternative in ("decision", "resolution"):
            data.pop(alternative, None)
        action = str(data.get("action", "resolve")).lower()
        if action in {"approve", "accepted", "approved"}:
            data["action"] = "accept"
        elif action in {"deny", "rejected", "decline"}:
            data["action"] = "reject"
        elif action in {"resolved", "resolve_conflict", "resolve-conflict"}:
            data["action"] = "resolve"
        return data

    @model_validator(mode="after")
    def _require_selector(self) -> "ConflictResolution":
        if not (self.all_conflicts or self.conflict_id or self.selected_record_id or self.program_id or self.field_name):
            raise ValueError("a conflict resolution must identify a conflict, programme, field, or all_conflicts")
        return self


class HumanResolution(BaseModel):
    """Typed payload accepted by the workflow human-review resume endpoint."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["resume", "resolve_conflicts", "resolve", "approve", "accept", "reject", "complete", "fail"] = "resume"
    approved_tools: list[str] = Field(default_factory=list, max_length=40)
    conflict_resolutions: list[ConflictResolution] = Field(default_factory=list, max_length=200)
    resolve_conflicts: bool = False
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value: object) -> object:
        if isinstance(value, str):
            return {"action": "resolve_conflicts", "resolve_conflicts": True, "note": value}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        # The legacy resolution key may carry either an action string or a
        # compact list/object of typed conflict decisions.
        if "conflict_resolutions" not in data and isinstance(data.get("resolution"), (dict, list)):
            data["conflict_resolutions"] = data.pop("resolution")
        direct_aliases = {
            "conflict_id": ("id", "conflictId"),
            "program_id": ("programId",),
            "field_name": ("field", "fieldName"),
            "selected_record_id": ("record_id", "recordId", "selectedRecordId"),
            "all_conflicts": ("all", "resolveAll"),
        }
        for canonical, alternatives in direct_aliases.items():
            if canonical not in data:
                for alternative in alternatives:
                    if alternative in data:
                        data[canonical] = data.pop(alternative)
                        break
        aliases = {
            "approved_tools": ("approvedTools", "approved_tool", "approvedTool"),
            "conflict_resolutions": ("resolutions", "resolved_conflicts", "resolvedConflicts", "conflicts", "conflict_resolution"),
            "note": ("message", "comment", "reviewer_note", "reviewerNote"),
        }
        for canonical, alternatives in aliases.items():
            if canonical not in data:
                for alternative in alternatives:
                    if alternative in data:
                        data[canonical] = data[alternative]
                        break
            for alternative in alternatives:
                data.pop(alternative, None)
        if "approved_tools" in data and isinstance(data["approved_tools"], str):
            data["approved_tools"] = [data["approved_tools"]]
        if "conflict_resolutions" in data:
            raw_resolutions = data["conflict_resolutions"]
            if isinstance(raw_resolutions, (str, dict)):
                raw_resolutions = [raw_resolutions]
            if isinstance(raw_resolutions, list):
                data["conflict_resolutions"] = [
                    {"conflict_id": item} if isinstance(item, str) else item
                    for item in raw_resolutions
                ]
        selector_keys = {"conflict_id", "id", "conflictId", "program_id", "field_name", "field", "selected_record_id", "record_id", "all_conflicts", "all"}
        if "conflict_resolutions" not in data and selector_keys.intersection(data):
            resolution = {key: data.pop(key) for key in list(data) if key in selector_keys}
            if "action" in data and data["action"] in {"accept", "approve", "reject", "dismiss", "resolve"}:
                resolution["action"] = data["action"]
                data["action"] = "resolve_conflicts"
            data["conflict_resolutions"] = [resolution]
        if "action" not in data:
            for alternative in ("decision", "resolution"):
                if alternative in data and isinstance(data[alternative], str):
                    data["action"] = data[alternative]
                    break
        for alternative in ("decision", "resolution"):
            data.pop(alternative, None)
        if data.get("resolve_conflicts"):
            data["action"] = "resolve_conflicts"
        action = str(data.get("action", "resume")).lower()
        if action in {"resolve_conflict", "resolve-conflict", "resolved"}:
            data["action"] = "resolve_conflicts"
        return data

    @model_validator(mode="after")
    def _normalize_action(self) -> "HumanResolution":
        if self.resolve_conflicts or self.conflict_resolutions:
            if self.action == "resume":
                self.action = "resolve_conflicts"
        return self
class AgentState(BaseModel):
    """Typed shared state exchanged by every real agent through the runtime."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = "agent-state-v1"
    workflow_id: str
    goal: WorkflowGoal
    status: WorkflowStatus = WorkflowStatus.RUNNING

    user_request: str = ""
    user_messages: list[dict[str, Any]] = Field(default_factory=list)
    raw_profile: dict[str, Any] | None = None
    normalized_profile: dict[str, Any] | None = None
    questionnaire: dict[str, Any] | None = None
    selected_program_ids: list[str] = Field(default_factory=list)
    document_type: str = "PS"

    assessment: dict[str, Any] | None = None
    evidence_review: dict[str, Any] | None = None
    missing_profile_fields: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)

    candidate_program_ids: list[str] = Field(default_factory=list)
    researched_program_ids: list[str] = Field(default_factory=list)
    program_matches: dict[str, dict[str, Any]] = Field(default_factory=dict)
    selected_matches: list[dict[str, Any]] = Field(default_factory=list)
    blocked_program_ids: list[str] = Field(default_factory=list)

    fields_needing_verification: dict[str, list[str]] = Field(default_factory=dict)
    verified_program_fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verification_conflicts: list[dict[str, Any]] = Field(default_factory=list)

    timeline: list[dict[str, Any]] = Field(default_factory=list)
    timeline_ready: bool = False
    story_cards: list[dict[str, Any]] = Field(default_factory=list)
    writing_draft: dict[str, Any] | None = None
    writing_ready: bool = False

    tasks: list[WorkflowTask] = Field(default_factory=list)
    current_agent: str | None = None
    previous_agent: str | None = None
    visited_agents: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0, ge=0)
    max_steps: int = Field(default=40, ge=1, le=200)
    agent_turn_counts: dict[str, int] = Field(default_factory=dict)
    tool_call_count: int = Field(default=0, ge=0)
    supervisor_replans: int = Field(default=0, ge=0)

    # Tool results are intentionally compact summaries only. Full source pages and
    # full database records remain in their stores rather than inflating prompts.
    working_memory: dict[str, Any] = Field(default_factory=dict)
    user_question: str | None = None
    human_review_reason: str | None = None
    human_resolution: HumanResolution | None = None
    resolved_conflicts: list[ConflictResolution] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_result: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _sanitize_runtime_state(cls, value: object, info: ValidationInfo) -> object:
        """Ensure direct AgentState construction is as safe as checkpoint writes."""

        if info.context and info.context.get("trusted_runtime_state") is True:
            return value
        return sanitize_runtime_payload(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if not value.startswith("agent-state-v"):
            raise ValueError("schema_version must use the agent-state-vN format")
        return value


_IMMUTABLE_STATE_FIELDS = {"workflow_id", "schema_version"}


def apply_state_patch(state: AgentState, patch: dict[str, Any], *, trusted_patch: bool = False) -> AgentState:
    """Validate and atomically merge a top-level state patch.

    Agents never mutate ``state.__dict__``. A full Pydantic validation after
    the merge protects later agents from malformed model or tool output.
    """

    unknown = set(patch) - set(AgentState.model_fields)
    if unknown:
        raise AgentDecisionValidationError(f"state patch contains unknown fields: {sorted(unknown)}")
    immutable = _IMMUTABLE_STATE_FIELDS & set(patch)
    if immutable:
        raise AgentDecisionValidationError(f"state patch cannot modify: {sorted(immutable)}")

    safe_patch = patch if trusted_patch else sanitize_runtime_payload(patch)
    merged = state.model_dump(mode="json")
    for key, value in patch.items():
        merged[key] = deepcopy(safe_patch[key])
    try:
        return AgentState.model_validate(merged, context={"trusted_runtime_state": True})
    except Exception as exc:  # Pydantic produces useful detail for the caller.
        raise AgentDecisionValidationError(f"invalid state patch: {exc}") from exc


def compact_value(value: Any, *, max_items: int = 12, max_chars: int = 1200) -> Any:
    """Keep tool output useful for the next decision without retaining blobs."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        # Preserve all top-level typed fields; cap only nested collections/blobs.
        return {str(key): compact_value(item, max_items=max_items, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [compact_value(item, max_items=max_items, max_chars=max_chars) for item in list(value)[:max_items]]
    if isinstance(value, str):
        return value[:max_chars]
    return value


_DECISION_RESULT_LIST_LIMITS = {
    # These results are not merely display context: later deterministic agents
    # turn the complete candidate/match sets into durable state. Truncating
    # them here silently changed portfolio decisions to the first 12 rows.
    "search_program_catalog": 80,
    "calculate_applicant_fit": 80,
    "evaluate_admissions_eligibility": 80,
    "evaluate_financial_feasibility": 80,
    "evaluate_user_preference": 80,
    "build_program_portfolio": 80,
}


def append_tool_result(state: AgentState, tool_name: str, result: Any) -> AgentState:
    """Store a bounded, serializable latest result for the calling agent.

    Most tool output remains compact. Decision-producing catalogue and
    matching tools retain their schema-bounded full result so the next agent
    does not lose viable or user-selected programmes before it can persist
    them into typed state.
    """

    memory = deepcopy(state.working_memory)
    results = dict(memory.get("tool_results", {}))
    results[tool_name] = sanitize_runtime_payload(
        compact_value(
            result,
            max_items=_DECISION_RESULT_LIST_LIMITS.get(tool_name, 12),
        )
    )
    memory["tool_results"] = results
    return apply_state_patch(state, {"working_memory": memory}, trusted_patch=True)
