from __future__ import annotations

from typing import Literal

from harbor_agent.core.rules import check_program_eligibility
from harbor_agent.models import (
    ConstraintCategory,
    ConstraintCheck,
    DataConfidenceAssessment,
    DecisionStatus,
    EvidenceLevel,
    FinancialFeasibility,
    FinancialFeasibilityStatus,
    NormalizedProfile,
    Program,
    ResolvedProgramView,
    RuleSeverity,
)
from harbor_agent.services.resolved_program import (
    HARD_ADMISSIONS_FIELDS,
    materialize_decision_program,
    resolve_program_view,
)

__all__ = [
    "ConstraintCategory",
    "ConstraintCheck",
    "DataConfidenceAssessment",
    "DecisionStatus",
    "FinancialFeasibility",
    "FinancialFeasibilityStatus",
    "RuleSeverity",
    "admissions_eligibility_checks",
    "admissions_status",
    "financial_feasibility",
]


def admissions_eligibility_checks(
    profile: NormalizedProfile,
    program: Program | ResolvedProgramView,
) -> list[ConstraintCheck]:
    """Return source-aware admissions checks while deliberately excluding budget.

    A seed value is not a failed or passed admissions predicate.  Every hard
    field first gets an explicit availability check from ``ResolvedProgramView``;
    only a current, reviewed decision fact enables the corresponding rule.
    """

    view = _resolved_view(program)
    decision_program = materialize_decision_program(view)
    checks: list[ConstraintCheck] = []
    for field_name in HARD_ADMISSIONS_FIELDS:
        fact = view.fact(field_name)
        checks.append(
            ConstraintCheck(
                check_id=f"fact_{field_name}",
                program_id=view.program_id,
                category=ConstraintCategory.ADMISSIONS_ELIGIBILITY,
                status=DecisionStatus.PASS
                if fact.formal_use_ready
                else DecisionStatus.UNKNOWN,
                severity=RuleSeverity.BLOCKING,
                message=(
                    f"{field_name} 已由当前申请季官方来源审核。"
                    if fact.formal_use_ready
                    else f"{field_name} 不能用于硬资格判断：{'；'.join(fact.blockers[:2])}"
                ),
                evidence_level=EvidenceLevel.evidence_verified
                if fact.formal_use_ready
                else EvidenceLevel.self_reported,
                source_url=str(fact.source_url) if fact.source_url else None,
            )
        )
    for item in check_program_eligibility(profile, decision_program):
        if item.rule_id == "tuition_budget":
            continue
        field_name = _field_for_rule(item.rule_id)
        fact = view.fact(field_name) if field_name else None
        unknown = (
            (fact is not None and not fact.formal_use_ready)
            or (item.rule_id == "language_required" and profile.language.test == "NONE")
        )
        checks.append(
            ConstraintCheck(
                check_id=item.rule_id,
                program_id=view.program_id,
                category=ConstraintCategory.ADMISSIONS_ELIGIBILITY,
                status=DecisionStatus.UNKNOWN
                if unknown
                else (DecisionStatus.PASS if item.passed else DecisionStatus.FAIL),
                severity=RuleSeverity.BLOCKING if item.severity == "hard" else RuleSeverity.WARNING,
                message=item.message,
                evidence_level=item.evidence_level,
                source_url=str(fact.source_url) if fact and fact.source_url else None,
            )
        )
    return checks


def admissions_status(checks: list[ConstraintCheck]) -> DecisionStatus:
    """Summarise blocking admissions checks without treating warnings as rejection."""

    blocking = [item for item in checks if item.severity == RuleSeverity.BLOCKING]
    if any(item.status == DecisionStatus.FAIL for item in blocking):
        return DecisionStatus.FAIL
    if not blocking or any(item.status == DecisionStatus.UNKNOWN for item in blocking):
        return DecisionStatus.UNKNOWN
    return DecisionStatus.PASS


def financial_feasibility(
    program: Program | ResolvedProgramView,
    budget_hkd: int | None,
    budget_mode: Literal["soft", "hard_cap"] = "soft",
) -> FinancialFeasibility:
    view = _resolved_view(program)
    decision_program = materialize_decision_program(view)
    if budget_hkd is None:
        return FinancialFeasibility(
            program_id=view.program_id,
            status=DecisionStatus.UNKNOWN,
            budget_mode=budget_mode,
            financial_status=FinancialFeasibilityStatus.UNKNOWN,
            message="未填写预算，不能评估费用可行性。",
        )
    tuition_fact = view.fact("tuition_hkd")
    if not tuition_fact.formal_use_ready or decision_program.tuition_hkd is None:
        return FinancialFeasibility(
            program_id=view.program_id,
            status=DecisionStatus.UNKNOWN,
            budget_hkd=budget_hkd,
            budget_mode=budget_mode,
            financial_status=FinancialFeasibilityStatus.UNKNOWN,
            message=(
                "项目学费未达到当前申请季字段级核验，不能把费用风险写成通过或失败。"
                + (f" 原因：{'；'.join(tuition_fact.blockers[:2])}" if tuition_fact.blockers else "")
            ),
        )
    gap = budget_hkd - decision_program.tuition_hkd
    slight_threshold = max(1, round(decision_program.tuition_hkd * 0.1))
    financial_status = (
        FinancialFeasibilityStatus.WITHIN_BUDGET
        if gap >= 0
        else FinancialFeasibilityStatus.SLIGHTLY_OVER
        if abs(gap) <= slight_threshold
        else FinancialFeasibilityStatus.OVER_BUDGET
    )
    return FinancialFeasibility(
            program_id=view.program_id,
        status=DecisionStatus.PASS if gap >= 0 else DecisionStatus.FAIL,
        budget_hkd=budget_hkd,
        tuition_hkd=decision_program.tuition_hkd,
        gap_hkd=gap,
        budget_mode=budget_mode,
        financial_status=financial_status,
        blocks_user_selection=budget_mode == "hard_cap" and gap < 0,
        message=(
            f"预算可覆盖已记录学费，余量约 HKD {gap:,}。"
            if gap >= 0
            else f"预算较已记录学费少约 HKD {abs(gap):,}；这不改变招生资格判断。"
        ),
    )


def _resolved_view(program: Program | ResolvedProgramView) -> ResolvedProgramView:
    return program if isinstance(program, ResolvedProgramView) else resolve_program_view(program)


def _field_for_rule(rule_id: str) -> str | None:
    if rule_id == "min_gpa":
        return "min_gpa"
    if rule_id.startswith(("ielts_", "toefl_", "pte_")) or rule_id in {
        "language_required",
        "language_test_mismatch",
        "language_subscores_signal",
    }:
        return "language_requirement"
    if rule_id == "required_background":
        return "required_backgrounds"
    if rule_id == "portfolio_required":
        return "portfolio_required"
    if rule_id == "prerequisite_signal":
        return "prerequisites"
    return None
