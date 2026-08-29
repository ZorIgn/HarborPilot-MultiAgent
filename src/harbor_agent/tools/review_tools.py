from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.services.claim_graph import build_claim_graph, claim_graph_passed
from harbor_agent.services.deterministic_review import run_review_gate
from harbor_agent.models import AssessmentResult, NormalizedProfile, ProgramMatch, WritingDraft
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.formal_gate import program_field_gate
from harbor_agent.services.deterministic_matching import calculate_applicant_fit
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class GateResult(BaseModel):
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


def _matches(state: AgentState) -> list[ProgramMatch]:
    return [ProgramMatch.model_validate(item) for item in (state.selected_matches or list(state.program_matches.values()))]


def _formal(state: AgentState, _: EmptyToolInput) -> GateResult:
    matches = _matches(state)
    gates = {
        item.program.id: program_field_gate(item.program)
        for item in matches
    }
    blockers = [
        f"{program_id}: {blocker}"
        for program_id, gate in gates.items()
        for blocker in gate["formal_blockers"]
    ]
    return GateResult(
        passed=bool(matches)
        and all(gate["formal_recommendation_ready"] for gate in gates.values())
        and not blockers,
        blockers=blockers,
        details={"program_gates": gates},
    )


def _recommendations(state: AgentState, _: EmptyToolInput) -> GateResult:
    matches = _matches(state)
    explicit_ids = set(state.working_memory.get("explicit_selected_program_ids", []))
    details: dict[str, object] = {
        "explicitly_selected_ineligible_program_ids": [],
        "recomputed_match_changed_program_ids": [],
        "recomputed": {},
    }
    if not matches:
        return GateResult(
            passed=False,
            blockers=["No selected programme is available for deterministic re-evaluation."],
            details=details,
        )
    if state.normalized_profile is None or state.assessment is None:
        return GateResult(
            passed=False,
            blockers=["Normalized profile and assessment are required for deterministic re-evaluation."],
            details=details,
        )
    try:
        profile = NormalizedProfile.model_validate(state.normalized_profile)
        assessment = AssessmentResult.model_validate(state.assessment)
        recomputed_matches = calculate_applicant_fit(
            profile.model_copy(update={"budget_hkd": None}),
            assessment,
            [item.program for item in matches],
            pinned_program_ids=list(
                dict.fromkeys([item.program.id for item in matches] + list(explicit_ids))
            ),
        )
    except Exception as exc:
        return GateResult(
            passed=False,
            blockers=[f"Deterministic admissions re-evaluation failed: {exc}"],
            details=details,
        )

    recomputed_by_id = {item.program.id: item for item in recomputed_matches}
    recomputed_details: dict[str, dict[str, object]] = {}
    blocked: list[str] = []
    explicit_blocked: list[str] = []
    changed: list[str] = []
    for item in matches:
        current = recomputed_by_id.get(item.program.id)
        if current is None:
            blocked.append(item.program.id)
            recomputed_details[item.program.id] = {
                "hard_rule_passed": False,
                "status": "MISSING_RECOMPUTED_MATCH",
            }
            continue
        recomputed_details[item.program.id] = {
            "cached_hard_rule_passed": item.hard_rule_passed,
            "hard_rule_passed": current.hard_rule_passed,
            "admissions_status": current.admissions_status.value,
            "formal_recommendation": current.formal_recommendation,
        }
        if current.hard_rule_passed != item.hard_rule_passed:
            changed.append(item.program.id)
        if not current.hard_rule_passed:
            blocked.append(item.program.id)
            if item.program.id in explicit_ids:
                explicit_blocked.append(item.program.id)
    details["recomputed"] = recomputed_details
    details["explicitly_selected_ineligible_program_ids"] = explicit_blocked
    details["recomputed_match_changed_program_ids"] = changed
    return GateResult(
        passed=not blocked,
        blockers=[f"{item}: admissions eligibility did not pass" for item in blocked],
        details=details,
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
    graph = build_claim_graph(
        draft,
        _matches(state),
        student_facts=state.story_cards,
    )
    grounded = claim_graph_passed(graph)
    blockers = list(graph.blockers)
    if not state.writing_ready:
        blockers.append("WritingAgent 尚未在独立 ClaimGraph 验证 turn 中把 writing_ready 设为 true。")
    blockers = list(dict.fromkeys(blockers))
    return GateResult(
        passed=grounded and state.writing_ready and not blockers,
        blockers=blockers,
        details={
            "claim_graph": graph.model_dump(mode="json"),
            "claim_grounding_ready": grounded,
            "writing_ready": state.writing_ready,
        },
    )


def _review_gate(state: AgentState, _: EmptyToolInput) -> GateResult:
    draft = WritingDraft.model_validate(state.writing_draft) if state.writing_draft else None
    result = run_review_gate(
        _matches(state),
        draft,
        writing_ready=state.writing_ready,
        writing_required=state.goal.value in {"writing", "full_application_plan"},
        student_facts=state.story_cards,
    )
    return GateResult(passed=bool(result.get("passed")), blockers=list(result.get("blockers", [])), details=result)


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("formal_gate_check", "Require current reviewed DecisionFacts for every formal recommendation field.", EmptyToolInput, GateResult, _formal),
        ToolDefinition("validate_recommendation_consistency", "Check recommendations against deterministic admissions outcomes.", EmptyToolInput, GateResult, _recommendations),
        ToolDefinition("validate_source_grounding", "Check official evidence completeness and conflicts.", EmptyToolInput, GateResult, _source),
        ToolDefinition("validate_writing_grounding", "Check writing claims against verified facts and programme evidence.", EmptyToolInput, GateResult, _writing),
        ToolDefinition("run_review_gate", "Run the deterministic review gate through the Tool Registry.", EmptyToolInput, GateResult, _review_gate),
    ]
