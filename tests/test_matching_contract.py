from __future__ import annotations

import json
from pathlib import Path

from harbor_agent.models import ApplicantProfileInput, DecisionStatus
from harbor_agent.models import ConstraintCheck as CanonicalConstraintCheck
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.deterministic_assessment import calculate_profile_assessment
from harbor_agent.services.deterministic_matching import calculate_applicant_fit
from harbor_agent.services.deterministic_profile import normalize_profile
from harbor_agent.tools.constraint_tools import ConstraintCheck as ToolConstraintCheck
from harbor_agent.tools.constraint_tools import DecisionStatus as ToolDecisionStatus
from harbor_agent.tools.constraint_tools import admissions_status
from harbor_agent.tools.matching_tools import materialize_match_dimensions


def _profile() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate(
        json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    )


def test_constraint_tools_reexports_the_canonical_models() -> None:
    assert ToolConstraintCheck is CanonicalConstraintCheck
    assert ToolDecisionStatus is DecisionStatus


def test_matching_dimensions_are_materialized_from_real_tool_outputs() -> None:
    profile = normalize_profile(_profile())
    assessment = calculate_profile_assessment(profile)
    program = load_programs()[0]
    match = calculate_applicant_fit(profile, assessment, [program])[0]
    merged = materialize_match_dimensions(
        [match],
        {
            "evaluate_admissions_eligibility": {
                "checks": [
                    {
                        "check_id": "min_gpa",
                        "program_id": program.id,
                        "category": "ADMISSIONS_ELIGIBILITY",
                        "status": "PASS",
                        "severity": "BLOCKING",
                        "message": "passed",
                        "evidence_level": "SELF_REPORTED",
                    }
                ]
            },
            "evaluate_financial_feasibility": {
                "assessments": [
                    {
                        "program_id": program.id,
                        "status": "PASS",
                        "budget_hkd": 100,
                        "tuition_hkd": 100,
                        "gap_hkd": 0,
                        "budget_mode": "soft",
                        "financial_status": "WITHIN_BUDGET",
                        "blocks_user_selection": False,
                        "message": "covered",
                    }
                ]
            },
        },
    )[0]
    assert merged.admissions_status == DecisionStatus.PASS
    assert [item.check_id for item in merged.admissions_checks] == ["min_gpa"]
    assert merged.academic_fit_score == match.score_breakdown["academic"]
    assert merged.language_fit_score == match.score_breakdown["language"]
    assert merged.discipline_fit_score == match.score_breakdown["discipline_fit"]
    assert merged.experience_fit_score == match.score_breakdown["experience"]
    assert merged.applicant_fit_score == match.fit_score
    assert merged.preference_fit_score == match.intent_alignment
    assert merged.financial_fit_score == 88
    assert merged.data_confidence_score == match.score_breakdown["data_trust"]
    assert merged.strategy_score == match.fit_score


def test_known_admissions_failure_takes_precedence_over_unknown() -> None:
    checks = [
        CanonicalConstraintCheck.model_validate(
            {
                "check_id": "language",
                "program_id": "p",
                "category": "ADMISSIONS_ELIGIBILITY",
                "status": "UNKNOWN",
                "severity": "BLOCKING",
                "message": "missing",
                "evidence_level": "SELF_REPORTED",
            }
        ),
        CanonicalConstraintCheck.model_validate(
            {
                "check_id": "gpa",
                "program_id": "p",
                "category": "ADMISSIONS_ELIGIBILITY",
                "status": "FAIL",
                "severity": "BLOCKING",
                "message": "failed",
                "evidence_level": "SELF_REPORTED",
            }
        ),
    ]
    assert admissions_status(checks) == DecisionStatus.FAIL
