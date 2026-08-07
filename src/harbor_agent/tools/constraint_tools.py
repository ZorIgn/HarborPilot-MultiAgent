from __future__ import annotations

from typing import Literal

from harbor_agent.core.rules import check_program_eligibility
from harbor_agent.models import (
    ConstraintCategory,
    ConstraintCheck,
    DataConfidenceAssessment,
    DecisionStatus,
    FinancialFeasibility,
    FinancialFeasibilityStatus,
    NormalizedProfile,
    Program,
    RuleSeverity,
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
    program: Program,
) -> list[ConstraintCheck]:
    """Return typed admissions checks while deliberately excluding budget."""

    checks: list[ConstraintCheck] = []
    for item in check_program_eligibility(profile, program):
        if item.rule_id == "tuition_budget":
            continue
        unknown = item.rule_id == "language_required" and profile.language.test == "NONE"
        checks.append(
            ConstraintCheck(
                check_id=item.rule_id,
                program_id=program.id,
                category=ConstraintCategory.ADMISSIONS_ELIGIBILITY,
                status=DecisionStatus.UNKNOWN
                if unknown
                else (DecisionStatus.PASS if item.passed else DecisionStatus.FAIL),
                severity=RuleSeverity.BLOCKING if item.severity == "hard" else RuleSeverity.WARNING,
                message=item.message,
                evidence_level=item.evidence_level,
                source_url=str(program.official_program_url)
                if program.official_program_url
                else None,
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
    program: Program,
    budget_hkd: int | None,
    budget_mode: Literal["soft", "hard_cap"] = "soft",
) -> FinancialFeasibility:
    if budget_hkd is None:
        return FinancialFeasibility(
            program_id=program.id,
            status=DecisionStatus.UNKNOWN,
            budget_mode=budget_mode,
            financial_status=FinancialFeasibilityStatus.UNKNOWN,
            message="未填写预算，不能评估费用可行性。",
        )
    if program.tuition_hkd is None:
        return FinancialFeasibility(
            program_id=program.id,
            status=DecisionStatus.UNKNOWN,
            budget_hkd=budget_hkd,
            budget_mode=budget_mode,
            financial_status=FinancialFeasibilityStatus.UNKNOWN,
            message="项目学费未核验，不能把费用风险写成通过或失败。",
        )
    gap = budget_hkd - program.tuition_hkd
    slight_threshold = max(1, round(program.tuition_hkd * 0.1))
    financial_status = (
        FinancialFeasibilityStatus.WITHIN_BUDGET
        if gap >= 0
        else FinancialFeasibilityStatus.SLIGHTLY_OVER
        if abs(gap) <= slight_threshold
        else FinancialFeasibilityStatus.OVER_BUDGET
    )
    return FinancialFeasibility(
        program_id=program.id,
        status=DecisionStatus.PASS if gap >= 0 else DecisionStatus.FAIL,
        budget_hkd=budget_hkd,
        tuition_hkd=program.tuition_hkd,
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
