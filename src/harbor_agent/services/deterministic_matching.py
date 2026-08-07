"""Deterministic applicant-fit and portfolio helpers for MatchingAgent tools."""

from __future__ import annotations

from harbor_agent.core.rules import check_program_eligibility, hard_rules_pass
from harbor_agent.models import (
    AssessmentResult,
    DataStatus,
    NormalizedProfile,
    Program,
    ProgramMatch,
)
from harbor_agent.services.intent import build_intent_profile, classify_program_intent


def calculate_applicant_fit(
    profile: NormalizedProfile,
    assessment: AssessmentResult,
    programs: list[Program],
    pinned_program_ids: list[str] | None = None,
) -> list[ProgramMatch]:
    """Calculate typed heuristic matches without an LLM or mutable Agent instance."""

    # The imported symbols are pure scoring primitives retained by the
    # compatibility matching module; routing and model calls stay outside this
    # deterministic service boundary.
    from harbor_agent.services.matching_heuristics import (
        _actions,
        _balanced_recommendation_output,
        _consultant_note,
        _critical_fields_verified,
        _decision_dimensions,
        _explanation,
        _institution_priority_adjustment,
        _intent_fit_adjustment,
        _ranking_key,
        _reasons,
        _risks,
        _score_breakdown,
        _source_warning_v2,
        _strategy_band,
        _weighted_fit,
    )

    matches: list[ProgramMatch] = []
    pinned_ids = set(pinned_program_ids or [])
    base = _base_score_from_level(assessment.overall_level)
    intent_profile = build_intent_profile(profile)

    for program in programs:
        intent = classify_program_intent(profile, program, intent_profile)
        checks = check_program_eligibility(profile, program)
        hard_ok = hard_rules_pass(checks)
        overlap = len(set(program.discipline_tags) & set(profile.discipline_tags))
        recommendable = hard_ok and intent.category != "blocked"
        score_breakdown = _score_breakdown(profile, assessment, program, overlap, intent)
        risk_penalty = 12 if not hard_ok else 0
        fit = (
            _weighted_fit(score_breakdown, base)
            - risk_penalty
            + _intent_fit_adjustment(intent)
            + _institution_priority_adjustment(profile, program, intent.category)
        )
        if intent.category == "blocked":
            fit = min(fit, 38)
        fit = max(10, min(96, fit))

        data_ready = _critical_fields_verified(program)
        formal = recommendable and program.data_status == DataStatus.verified
        strategy_band = _strategy_band(profile, program, fit, recommendable, intent.category)
        tier = _tier(strategy_band)
        reasons = _reasons(profile, program, intent)
        risks = _risks(profile, program, checks, score_breakdown, intent)
        actions = _actions(intent, formal, risks)
        consultant_note = _consultant_note(profile, program, strategy_band, score_breakdown, intent)
        source_warning = _source_warning_v2(program, formal)

        matches.append(
            ProgramMatch(
                program=program,
                tier=tier,
                **_decision_dimensions(profile, program, score_breakdown, fit, intent.alignment),
                fit_score=fit,
                score_breakdown=score_breakdown,
                match_category=intent.category,
                intent_alignment=intent.alignment,
                intent_reasons=intent.reasons,
                hard_rule_passed=hard_ok,
                formal_recommendation=formal,
                data_status=program.data_status,
                reasons=reasons[:5],
                risks=risks[:5],
                actions=actions[:5],
                rule_checks=checks,
                explanation=_explanation(
                    score_breakdown, recommendable, data_ready, program, reasons, risks
                ),
                strategy_band=strategy_band,
                consultant_note=consultant_note,
                source_warning=source_warning,
            )
        )

    return _balanced_recommendation_output(sorted(matches, key=_ranking_key), pinned_ids)


def _base_score_from_level(level: str) -> int:
    return {
        "A": 84,
        "A-": 78,
        "B+": 72,
        "B": 66,
        "C+": 58,
        "C": 50,
        "NEEDS_DATA": 45,
    }[level]


def _tier(strategy_band: str) -> str:
    if strategy_band == "blocked":
        return "not_recommended"
    if strategy_band in {"reach", "target", "safer", "candidate"}:
        return strategy_band
    return "candidate"
