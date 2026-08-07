from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.models import AssessmentResult, NormalizedProfile, Program, ProgramMatch
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.deterministic_matching import calculate_applicant_fit
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition
from harbor_agent.tools.constraint_tools import (
    ConstraintCategory,
    ConstraintCheck,
    DecisionStatus,
    FinancialFeasibility,
    RuleSeverity,
    admissions_eligibility_checks,
    admissions_status,
    financial_feasibility,
)


class ProgramIdsInput(BaseModel):
    program_ids: list[str] = Field(default_factory=list, max_length=80)


class EligibilityResult(BaseModel):
    checks: list[ConstraintCheck] = Field(default_factory=list)


class FinancialResult(BaseModel):
    assessments: list[FinancialFeasibility] = Field(default_factory=list)


class PreferenceResult(BaseModel):
    checks: list[ConstraintCheck] = Field(default_factory=list)


def materialize_match_dimensions(
    matches: list[ProgramMatch],
    tool_results: dict[str, object],
) -> list[ProgramMatch]:
    """Attach the preceding typed decision-tool outputs to each match."""

    admissions_payload = tool_results.get("evaluate_admissions_eligibility", {})
    financial_payload = tool_results.get("evaluate_financial_feasibility", {})
    admissions_available = isinstance(admissions_payload, dict) and "checks" in admissions_payload
    financial_available = isinstance(financial_payload, dict) and "assessments" in financial_payload
    admissions_by_program: dict[str, list[ConstraintCheck]] = {}
    if admissions_available:
        for raw in admissions_payload.get("checks", []):
            if isinstance(raw, dict):
                check = ConstraintCheck.model_validate(raw)
                if check.program_id:
                    admissions_by_program.setdefault(check.program_id, []).append(check)
    financial_by_program: dict[str, FinancialFeasibility] = {}
    if financial_available:
        for raw in financial_payload.get("assessments", []):
            if isinstance(raw, dict):
                assessment = FinancialFeasibility.model_validate(raw)
                financial_by_program[assessment.program_id] = assessment

    output: list[ProgramMatch] = []
    for match in matches:
        admission_checks = admissions_by_program.get(match.program.id, [])
        has_admission_result = bool(admission_checks)
        financial = financial_by_program.get(match.program.id)
        has_financial_result = financial is not None
        updates = {
            "admissions_status": admissions_status(admission_checks)
            if admissions_available and has_admission_result
            else match.admissions_status,
            "admissions_checks": admission_checks
            if admissions_available and has_admission_result
            else match.admissions_checks,
            "academic_fit_score": match.score_breakdown.get("academic", match.academic_fit_score),
            "language_fit_score": match.score_breakdown.get("language", match.language_fit_score),
            "discipline_fit_score": match.score_breakdown.get(
                "discipline_fit", match.discipline_fit_score
            ),
            "experience_fit_score": match.score_breakdown.get(
                "experience", match.experience_fit_score
            ),
            "applicant_fit_score": match.fit_score,
            "preference_fit_score": match.intent_alignment,
            "financial_fit_score": _financial_fit_score(financial)
            if financial_available and has_financial_result
            else match.financial_fit_score,
            "data_confidence_score": match.score_breakdown.get(
                "data_trust", match.data_confidence_score
            ),
            "strategy_score": match.fit_score,
        }
        output.append(match.model_copy(update=updates))
    return output


def _financial_fit_score(assessment: FinancialFeasibility | None) -> int | None:
    if assessment is None or assessment.status == DecisionStatus.UNKNOWN:
        return None
    if assessment.budget_hkd is None or assessment.tuition_hkd is None:
        return None
    if assessment.budget_hkd >= assessment.tuition_hkd:
        return 88
    ratio = assessment.budget_hkd / assessment.tuition_hkd
    if ratio >= 0.85:
        return 72
    if ratio >= 0.7:
        return 58
    return 42


class MatchResult(BaseModel):
    matches: list[dict] = Field(default_factory=list)


class PortfolioResult(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    blocked_program_ids: list[str] = Field(default_factory=list)
    portfolio: list[dict] = Field(default_factory=list)


def _programs(ids: list[str]) -> list[Program]:
    selected = set(ids)
    values = load_programs()
    return [item for item in values if not selected or item.id in selected]


def _profile(state: AgentState) -> NormalizedProfile:
    if state.normalized_profile is None:
        raise ValueError("normalized profile is required")
    return NormalizedProfile.model_validate(state.normalized_profile)


def _admissions(state: AgentState, args: ProgramIdsInput) -> EligibilityResult:
    profile = _profile(state)
    checks: list[ConstraintCheck] = []
    for program in _programs(args.program_ids or state.candidate_program_ids):
        checks.extend(admissions_eligibility_checks(profile, program))
    return EligibilityResult(checks=checks)


def _financial(state: AgentState, args: ProgramIdsInput) -> FinancialResult:
    profile = _profile(state)
    return FinancialResult(
        assessments=[
            financial_feasibility(item, profile.budget_hkd, profile.budget_mode)
            for item in _programs(args.program_ids or state.candidate_program_ids)
        ]
    )


def _preferences(state: AgentState, args: ProgramIdsInput) -> PreferenceResult:
    profile = _profile(state)
    tags = set(profile.discipline_tags)
    checks: list[ConstraintCheck] = []
    for program in _programs(args.program_ids or state.candidate_program_ids):
        overlap = tags & set(program.discipline_tags)
        checks.append(
            ConstraintCheck(
                check_id="discipline_preference",
                program_id=program.id,
                category=ConstraintCategory.USER_PREFERENCE,
                status=DecisionStatus.PASS if overlap else DecisionStatus.UNKNOWN,
                severity=RuleSeverity.INFO,
                message="与明确方向存在标签交集。"
                if overlap
                else "与明确方向的标签交集有限，应作为探索候选而非资格结论。",
                evidence_level=profile.education.evidence_level,
            )
        )
    return PreferenceResult(checks=checks)


def _fit(state: AgentState, args: ProgramIdsInput) -> MatchResult:
    profile = _profile(state)
    if state.assessment is None:
        raise ValueError("profile assessment is required")
    assessment = AssessmentResult.model_validate(state.assessment)
    # Applicant fit excludes budget; financial feasibility is emitted by its
    # separate deterministic tool.
    scoring_profile = profile.model_copy(update={"budget_hkd": None})
    pinned_program_ids = list(
        state.working_memory.get("explicit_selected_program_ids", state.selected_program_ids)
    )
    matches = calculate_applicant_fit(
        scoring_profile,
        assessment,
        _programs(args.program_ids or state.candidate_program_ids),
        pinned_program_ids=pinned_program_ids,
    )
    matches = materialize_match_dimensions(matches, state.working_memory.get("tool_results", {}))
    return MatchResult(matches=[item.model_dump(mode="json") for item in matches])


def _portfolio(state: AgentState, _: EmptyToolInput) -> PortfolioResult:
    matches = [ProgramMatch.model_validate(item) for item in state.program_matches.values()]
    financial = state.working_memory.get("tool_results", {}).get(
        "evaluate_financial_feasibility", {}
    )
    hard_blocked = {
        str(item.get("program_id"))
        for item in financial.get("assessments", [])
        if item.get("blocks_user_selection")
    }
    viable = [
        item
        for item in matches
        if item.tier != "not_recommended" and item.program.id not in hard_blocked
    ]
    explicit_ids = [
        str(program_id)
        for program_id in state.working_memory.get(
            "explicit_selected_program_ids", state.selected_program_ids
        )
    ]
    by_id = {item.program.id: item for item in matches}
    # Keep an explicit selection even when its eligibility fails. It remains
    # review-gated and cannot become a formal recommendation, but the student
    # still receives a preparation timeline and the concrete blocker.
    selected = (
        [
            by_id[program_id]
            for program_id in explicit_ids
            if program_id in by_id and program_id not in hard_blocked
        ]
        if explicit_ids
        else viable[:8]
    )
    return PortfolioResult(
        selected_program_ids=[item.program.id for item in selected],
        blocked_program_ids=[
            item.program.id
            for item in matches
            if item.tier == "not_recommended" or item.program.id in hard_blocked
        ],
        portfolio=[item.model_dump(mode="json") for item in selected],
    )


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            "evaluate_admissions_eligibility",
            "Evaluate GPA, language and background admission conditions only; excludes budget and preference.",
            ProgramIdsInput,
            EligibilityResult,
            _admissions,
        ),
        ToolDefinition(
            "evaluate_financial_feasibility",
            "Evaluate tuition against the stated budget as a separate financial decision.",
            ProgramIdsInput,
            FinancialResult,
            _financial,
        ),
        ToolDefinition(
            "evaluate_user_preference",
            "Evaluate explicit preferences without treating them as admissions evidence.",
            ProgramIdsInput,
            PreferenceResult,
            _preferences,
        ),
        ToolDefinition(
            "calculate_applicant_fit",
            "Calculate heuristic applicant fit without changing official requirements.",
            ProgramIdsInput,
            MatchResult,
            _fit,
        ),
        ToolDefinition(
            "build_program_portfolio",
            "Build a diversified programme portfolio from previous matching results.",
            EmptyToolInput,
            PortfolioResult,
            _portfolio,
        ),
    ]
