from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.services.deterministic_review import run_review_gate
from harbor_agent.models import ProgramMatch, WritingDraft
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.formal_gate import formal_timeline_blockers, formal_timeline_ready
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class GateResult(BaseModel):
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


def _matches(state: AgentState) -> list[ProgramMatch]:
    return [ProgramMatch.model_validate(item) for item in (state.selected_matches or list(state.program_matches.values()))]


def _formal(state: AgentState, _: EmptyToolInput) -> GateResult:
    matches = _matches(state)
    blockers = [f"{item.program.id}: {', '.join(formal_timeline_blockers(item))}" for item in matches if not formal_timeline_ready(item)]
    return GateResult(passed=bool(matches) and not blockers, blockers=blockers)


def _recommendations(state: AgentState, _: EmptyToolInput) -> GateResult:
    explicit_ids = set(state.working_memory.get("explicit_selected_program_ids", []))
    blocked = [
        item.program.id
        for item in _matches(state)
        if not item.hard_rule_passed and item.program.id not in explicit_ids
    ]
    explicit_blocked = [
        item.program.id
        for item in _matches(state)
        if not item.hard_rule_passed and item.program.id in explicit_ids
    ]
    return GateResult(
        passed=not blocked,
        blockers=[f"{item}: admissions eligibility did not pass" for item in blocked],
        details={"explicitly_selected_ineligible_program_ids": explicit_blocked},
    )


def _source(state: AgentState, _: EmptyToolInput) -> GateResult:
    missing = [program_id for program_id, fields in state.fields_needing_verification.items() if fields]
    conflicts = state.verification_conflicts
    blockers = [f"{item}: official fields missing" for item in missing]
    blockers.extend(f"evidence conflict: {item}" for item in conflicts[:5])
    return GateResult(passed=not blockers, blockers=blockers)


def _writing(state: AgentState, _: EmptyToolInput) -> GateResult:
    if state.writing_draft is None:
        return GateResult(passed=False, blockers=["writing draft is missing"])
    draft = WritingDraft.model_validate(state.writing_draft)
    blockers = [item for item in draft.review_flags if "不能" in item or "缺少" in item]
    return GateResult(passed=not blockers, blockers=blockers)


def _review_gate(state: AgentState, _: EmptyToolInput) -> GateResult:
    draft = WritingDraft.model_validate(state.writing_draft) if state.writing_draft else WritingDraft.model_construct()
    result = run_review_gate(_matches(state), draft)
    return GateResult(passed=bool(result.get("passed")), blockers=list(result.get("blockers", [])), details=result)


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("formal_gate_check", "Apply deterministic formal-use requirements to timeline evidence.", EmptyToolInput, GateResult, _formal),
        ToolDefinition("validate_recommendation_consistency", "Check recommendations against deterministic admissions outcomes.", EmptyToolInput, GateResult, _recommendations),
        ToolDefinition("validate_source_grounding", "Check official evidence completeness and conflicts.", EmptyToolInput, GateResult, _source),
        ToolDefinition("validate_writing_grounding", "Check writing claims against verified facts and programme evidence.", EmptyToolInput, GateResult, _writing),
        ToolDefinition("run_review_gate", "Run the deterministic review gate through the Tool Registry.", EmptyToolInput, GateResult, _review_gate),
    ]
