"""Deterministic applicant-fit and portfolio helpers for MatchingAgent tools."""

from __future__ import annotations

from harbor_agent.core.rules import check_program_eligibility
from harbor_agent.models import (
    AssessmentResult,
    DataStatus,
    DecisionStatus,
    NormalizedProfile,
    Program,
    ProgramMatch,
    RuleCheck,
)
from harbor_agent.services.intent import build_intent_profile, classify_program_intent
from harbor_agent.services.resolved_program import (
    materialize_decision_program,
    resolve_program_views,
)
from harbor_agent.tools.constraint_tools import admissions_eligibility_checks, admissions_status


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
    views = resolve_program_views(programs)

    for program in programs:
        view = views[program.id]
        decision_program = materialize_decision_program(view)
        intent = classify_program_intent(profile, program, intent_profile)
        admission_checks = admissions_eligibility_checks(profile, view)
        admission_status = admissions_status(admission_checks)
        checks = _rule_checks_for_compatibility(profile, decision_program, admission_checks)
        # ``UNKNOWN`` is deliberately not a hard rejection.  It remains an
        # exploration candidate with explicit blockers, while only a verified
        # predicate may produce a hard FAIL.
        hard_ok = admission_status != DecisionStatus.FAIL
        overlap = len(set(program.discipline_tags) & set(profile.discipline_tags))
        recommendable = hard_ok and intent.category != "blocked"
        score_breakdown = _score_breakdown(profile, assessment, decision_program, overlap, intent)
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

        data_ready = view.formal_readiness == DecisionStatus.PASS
        formal = recommendable and admission_status == DecisionStatus.PASS and data_ready
        # Candidate identity/detail URLs can guide exploratory banding, while
        # all hard admission and budget predicates above use ``decision_program``.
        strategy_band = _strategy_band(profile, program, fit, recommendable, intent.category)
        tier = _tier(strategy_band)
        reasons = _reasons(profile, decision_program, intent)
        risks = [*view.formal_blockers, *_risks(profile, decision_program, checks, score_breakdown, intent)]
        actions = _actions(intent, formal, risks)
        consultant_note = _consultant_note(profile, program, strategy_band, score_breakdown, intent)
        source_warning = _source_warning_v2(program, formal)

        matches.append(
            ProgramMatch(
                program=program,
                tier=tier,
                **_decision_dimensions(profile, view, score_breakdown, fit, intent.alignment),
                fit_score=fit,
                score_breakdown=score_breakdown,
                match_category=intent.category,
                intent_alignment=intent.alignment,
                intent_reasons=intent.reasons,
                hard_rule_passed=hard_ok,
                formal_recommendation=formal,
                decision_facts=view.facts,
                formal_gate_status=view.formal_readiness,
                formal_blockers=view.formal_blockers,
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


def _rule_checks_for_compatibility(
    profile: NormalizedProfile,
    decision_program: Program,
    admission_checks,
) -> list[RuleCheck]:
    """Expose legacy ``RuleCheck`` output without letting UNKNOWN hard-fail.

    The typed ``ConstraintCheck`` objects remain the decision authority.  This
    adapter preserves API fields used by existing UI code while making every
    unresolved source an informational, visible rule rather than a fake pass.
    """

    checks: list[RuleCheck] = []
    for item in admission_checks:
        if item.check_id.startswith("fact_"):
            checks.append(
                RuleCheck(
                    rule_id=item.check_id,
                    program_id=item.program_id,
                    passed=item.status == DecisionStatus.PASS,
                    severity="info" if item.status == DecisionStatus.UNKNOWN else "soft",
                    message=item.message,
                    evidence_level=item.evidence_level,
                )
            )
    checks.extend(check_program_eligibility(profile, decision_program))
    return checks


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
