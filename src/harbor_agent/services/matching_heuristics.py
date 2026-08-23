from __future__ import annotations

from harbor_agent.core.llm import LLMProvider, MockLLMProvider
from harbor_agent.core.rules import (
    check_program_eligibility,
    display_gpa,
    hard_rules_pass,
    normalized_gpa_100,
)
from harbor_agent.models import (
    AssessmentResult,
    DataStatus,
    DecisionStatus,
    NormalizedProfile,
    Program,
    ProgramMatch,
    RecommendationExplanation,
    ResolvedProgramView,
)
from harbor_agent.services.external_candidates import qs_evidence_note_for_program
from harbor_agent.services.intent import (
    IntentClassification,
    build_intent_profile,
    classify_program_intent,
)
from harbor_agent.services.matching_strategy import load_matching_strategy
from harbor_agent.services.program_urls import has_program_detail_page
from harbor_agent.services.resolved_program import materialize_decision_program
from harbor_agent.tools.constraint_tools import (
    admissions_eligibility_checks,
    admissions_status,
    financial_feasibility,
)

ELITE_INSTITUTIONS = {
    "the university of hong kong": 5.15,
    "hong kong university of science and technology": 5.1,
    "the chinese university of hong kong": 5.05,
    "national university of singapore": 5.25,
    "nanyang technological university": 5.15,
}

STRONG_INSTITUTIONS = {
    "city university of hong kong": 4.25,
    "the hong kong polytechnic university": 4.15,
    "singapore management university": 4.1,
    "singapore university of technology and design": 4.0,
}

SOLID_INSTITUTIONS = {
    "hong kong baptist university": 3.35,
    "lingnan university": 3.0,
    "the education university of hong kong": 3.0,
}


class MatchingHeuristicService:
    name = "MatchingHeuristicService"

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or MockLLMProvider()

    def run(
        self,
        profile: NormalizedProfile,
        assessment: AssessmentResult,
        programs: list[Program],
        pinned_program_ids: list[str] | None = None,
    ) -> list[ProgramMatch]:
        # Keep the legacy service entry point, but delegate the actual matching
        # calculation to the sole evidence-aware implementation.  The optional
        # LLM pass below can only refine wording; it never changes facts,
        # constraint statuses or formal readiness.
        from harbor_agent.services.deterministic_matching import calculate_applicant_fit

        matches = calculate_applicant_fit(
            profile,
            assessment,
            programs,
            pinned_program_ids=pinned_program_ids,
        )
        return self._apply_llm_consultant_pass(profile, matches)

    def _tier(self, strategy_band: str) -> str:
        if strategy_band == "blocked":
            return "not_recommended"
        if strategy_band in {"reach", "target", "safer", "candidate"}:
            return strategy_band
        return "candidate"

    def _apply_llm_consultant_pass(
        self,
        profile: NormalizedProfile,
        matches: list[ProgramMatch],
    ) -> list[ProgramMatch]:
        if self.llm.name == "mock":
            return matches
        top = sorted(matches, key=_ranking_key)[:15]
        payload = {
            "profile": {
                "school_tier": profile.education.school_tier,
                "major": profile.education.major,
                "gpa": display_gpa(profile),
                "language": profile.language.model_dump(mode="json"),
                "interests": profile.discipline_tags,
                "career_goal": profile.career_goal,
            },
            "programs": [
                {
                    "program_id": item.program.id,
                    "institution": item.program.institution_zh or item.program.institution,
                    "name": item.program.name_zh or item.program.name,
                    "strategy_band": item.strategy_band,
                    "match_category": item.match_category,
                    "data_status": item.program.data_status.value,
                    "source_warning": item.source_warning,
                    "deterministic_note": item.consultant_note,
                }
                for item in top
            ],
        }
        try:
            completion = self.llm.complete_json(
                system=(
                    "You are a cautious Hong Kong/Singapore master admissions consultant. "
                    "Do not invent official deadlines, tuition, language requirements, admissions outcomes, or school facts. "
                    "Only refine consultant notes and risk wording using the provided profile and program list. "
                    "Return JSON with notes by program_id."
                ),
                user=str(payload),
                schema_hint={
                    "notes": [
                        {
                            "program_id": "string",
                            "consultant_note": "string",
                            "risk_note": "string",
                        }
                    ]
                },
            )
        except Exception:
            return matches

        notes = completion.get("notes", [])
        if not isinstance(notes, list):
            return matches
        by_id: dict[str, dict] = {
            str(item.get("program_id")): item
            for item in notes
            if isinstance(item, dict) and item.get("program_id")
        }
        updated: list[ProgramMatch] = []
        for item in matches:
            note = by_id.get(item.program.id)
            if note:
                consultant_note = str(note.get("consultant_note") or item.consultant_note).strip()
                risk_note = str(note.get("risk_note") or item.source_warning).strip()
                if consultant_note:
                    item.consultant_note = consultant_note[:280]
                if risk_note:
                    item.source_warning = risk_note[:240]
            updated.append(item)
        return updated


def _balanced_recommendation_output(
    matches: list[ProgramMatch],
    pinned_program_ids: set[str] | None = None,
) -> list[ProgramMatch]:
    pinned_program_ids = pinned_program_ids or set()
    positives = [item for item in matches if item.tier != "not_recommended"]
    strategy = load_matching_strategy()
    configured_quotas = strategy.get("recommendation_quotas", {})
    blocked = [item for item in matches if item.tier == "not_recommended"][
        : int(configured_quotas.get("not_recommended", 12))
    ]
    quotas = {
        band: int(configured_quotas.get(band, default))
        for band, default in {"reach": 14, "target": 14, "safer": 12, "candidate": 10}.items()
    }
    selected: list[ProgramMatch] = []
    seen: set[str] = set()
    for band, limit in quotas.items():
        for item in [candidate for candidate in positives if candidate.tier == band][:limit]:
            if item.program.id in seen:
                continue
            selected.append(item)
            seen.add(item.program.id)
    for item in positives:
        if len(selected) >= int(configured_quotas.get("max_total", 60)):
            break
        if item.program.id in seen:
            continue
        selected.append(item)
        seen.add(item.program.id)
    output = selected + blocked
    seen_output = {item.program.id for item in output}
    pinned_missing = [
        item
        for item in matches
        if item.program.id in pinned_program_ids and item.program.id not in seen_output
    ]
    return output + pinned_missing


def _ranking_key(item: ProgramMatch) -> tuple[int, int, float, int]:
    band_order = {"reach": 0, "target": 1, "safer": 2, "candidate": 3, "blocked": 4}
    category_order = {"core": 0, "related": 1, "general": 2, "blocked": 3}
    return (
        category_order.get(item.match_category, 9),
        band_order.get(item.strategy_band, 9),
        -_institution_level(item.program),
        -item.fit_score,
    )


def _institution_level(program: Program) -> float:
    institution = program.institution.lower()
    tiers = load_matching_strategy().get("institution_tiers", {})
    for tier in tiers.values():
        score = float(tier.get("score", 3.4))
        for alias in tier.get("aliases", []):
            if str(alias).lower() in institution:
                return score
    return 3.4


def _profile_competitiveness(profile: NormalizedProfile) -> float:
    tier = profile.education.school_tier
    tier_base = load_matching_strategy().get("profile_tier_base", {})
    base = float(tier_base.get(tier, 3.25))
    gpa = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)
    if gpa >= 90:
        base += 0.45
    elif gpa >= 86:
        base += 0.25
    elif gpa >= 82:
        base += 0.05
    elif gpa < 78:
        base -= 0.35
    language = profile.language.overall or 0
    if profile.language.test == "IELTS":
        if language >= 7.5:
            base += 0.15
        elif language >= 7.0:
            base += 0.08
        elif 0 < language < 6.5:
            base -= 0.25
    elif profile.language.test == "TOEFL":
        if language >= 105:
            base += 0.15
        elif language >= 100:
            base += 0.08
        elif 0 < language < 90:
            base -= 0.25
    if profile.experiences:
        months = sum(exp.months for exp in profile.experiences)
        if months >= 12:
            base += 0.18
        elif months >= 4:
            base += 0.08
    if set(profile.discipline_tags) & {
        "computer_science",
        "data_science",
        "artificial_intelligence",
    }:
        major_text = profile.education.major.lower()
        if any(
            keyword in major_text
            for keyword in ["computer", "software", "人工智能", "计算机", "软件", "ai", "data"]
        ):
            base += 0.12
    return max(2.2, min(5.2, base))


def _institution_challenge(profile: NormalizedProfile, program: Program) -> float:
    return _institution_level(program) - _profile_competitiveness(profile)


def _institution_priority_adjustment(
    profile: NormalizedProfile, program: Program, match_category: str
) -> int:
    if match_category == "blocked":
        return -20
    level = _institution_level(program)
    if match_category == "core":
        return round((level - 3.2) * 5)
    if match_category == "related":
        return round((level - 3.8) * 2)
    return 0


def _reasons(
    profile: NormalizedProfile, program: Program, intent: IntentClassification
) -> list[str]:
    reasons = list(intent.reasons)
    if intent.category == "core":
        reasons.append("该项目进入核心匹配区，优先放入 AI/CS/Data 项目清单比较。")
    elif intent.category == "related":
        reasons.append("该项目进入相关候选区，可作为交叉方向备选，但不替代核心项目。")
    elif intent.category == "blocked":
        reasons.append("该项目已被专业意向过滤，不建议加入当前项目清单。")
    else:
        reasons.append("项目方向证据不足，仅可作为普通候选。")

    reasons.append("申请季数据已版本化，但正式信息仍按来源状态决定能否用于最终结论。")
    if profile.experiences:
        reasons.append("已填写经历可复用到文书、CV 和面试素材。")
    if profile.education.school_tier != "unknown":
        reasons.append(f"本科层级已纳入分档：{profile.education.school_tier}。")
    if program.community_signals:
        reasons.append("社区资料只作为线索，仍需回到学校官网确认。")
    return reasons


def _strategy_band(
    profile: NormalizedProfile,
    program: Program,
    fit: int,
    recommendable: bool,
    match_category: str,
) -> str:
    if not recommendable or match_category == "blocked":
        return "blocked"
    if match_category == "general":
        return "candidate"
    if match_category == "related" and fit < 78:
        return "candidate"
    if not has_program_detail_page(program):
        return "candidate"
    challenge = _institution_challenge(profile, program)
    if challenge >= 0.35:
        return _conservative_reach_band(profile, program, fit, match_category)
    if challenge >= -0.75:
        if _should_downgrade_target(profile, program, fit, match_category):
            return "safer"
        return "target"
    if challenge >= -1.9:
        return "safer"
    if fit >= 58:
        return "candidate"
    return "candidate"


def _conservative_reach_band(
    profile: NormalizedProfile,
    program: Program,
    fit: int,
    match_category: str,
) -> str:
    profile_level = _profile_competitiveness(profile)
    institution_level = _institution_level(program)
    language = profile.language.overall or 0

    if match_category != "core":
        return "target" if fit >= 76 else "safer"
    if profile.education.school_tier == "regular":
        if institution_level >= 4.0:
            return "target" if fit >= 80 else "safer"
        return "safer" if fit >= 70 else "candidate"
    if profile.education.school_tier in {"211", "double_first_class"} and institution_level >= 5.0:
        return "reach"
    if profile.education.school_tier == "985" and institution_level >= 5.0:
        return "reach"
    if profile.education.school_tier in {"C9", "overseas"} and institution_level >= 5.0:
        return "reach"
    return "target"


def _should_downgrade_target(
    profile: NormalizedProfile,
    program: Program,
    fit: int,
    match_category: str,
) -> bool:
    if match_category != "core":
        return fit < 78
    if profile.education.school_tier == "regular":
        if _institution_level(program) < 4.0:
            return True
        return fit < 80
    return False


def _challenge_readable_label(institution_level: float, profile_level: float) -> str:
    gap = institution_level - profile_level
    if gap >= 0.9:
        return "项目层级明显高于当前背景，应作为冲刺项，需要用高 GPA、语言和经历补强"
    if gap >= 0.25:
        return "项目层级略高于当前背景，适合放在主申或冲刺对比池"
    if gap >= -0.5:
        return "项目层级与当前背景基本匹配"
    return "项目层级低于当前背景，更适合作为稳妥备选"


def _consultant_note(
    profile: NormalizedProfile,
    program: Program,
    strategy_band: str,
    score_breakdown: dict[str, int],
    intent: IntentClassification,
) -> str:
    band_label = {
        "reach": "冲刺",
        "target": "主申",
        "safer": "相对稳妥",
        "candidate": "候选",
        "blocked": "暂不建议",
    }[strategy_band]
    academic = _band(score_breakdown["academic"])
    language = _band(score_breakdown["language"])
    experience = _band(score_breakdown["experience"])
    challenge_label = _challenge_readable_label(
        _institution_level(program), _profile_competitiveness(profile)
    )
    direction = "、".join(profile.discipline_tags[:3]) or "目标方向待补充"
    if strategy_band == "blocked":
        return (
            f"暂不建议加入本轮项目清单：项目方向与 {direction} 的匹配度不足，"
            "除非学生主动改变申请方向，否则不应占用申请名额。"
        )
    return (
        f"顾问分档：{band_label}。依据：本科层级 {profile.education.school_tier}、"
        f"GPA {display_gpa(profile)}、语言匹配 {language}、学术背景 {academic}、"
        f"经历匹配 {experience}、方向匹配 {intent.category}。"
        f"{challenge_label}。"
        f"适合放入 {program.institution_zh or program.institution} 的同层级项目对比池，"
        "最终投递前仍需逐项打开项目官网页面和申请入口确认。"
    )


def _source_warning(program: Program, formal: bool) -> str:
    if formal:
        return "关键信息已达到当前系统的正式推荐门槛；递交前仍建议再次打开官网确认。"
    if program.deadline == "NOT_PUBLISHED":
        return "官网当前季截止日期未发布；先给出材料准备动作，不把它当成正式提交时间。"
    if program.source.field_coverage != "complete":
        return "目前只定位到项目入口；学费、语言、材料和截止日期还需要打开学校官网逐项核对。"
    return "这条信息可用于初筛和项目清单草稿；递交前还需要再次核对项目官网页面和申请入口。"


def _source_warning_v2(program: Program, formal: bool) -> str:
    external_note = qs_evidence_note_for_program(program)
    if not has_program_detail_page(program):
        missing_detail = "未找到项目详情页；当前只能进入候选或准备参考，不能生成正式申请时间线。"
        return f"{missing_detail} {external_note}" if external_note else missing_detail
    if formal:
        return (
            external_note or "关键信息已达到当前系统的正式推荐门槛；递交前仍建议再次打开官网确认。"
        )
    if program.deadline == "NOT_PUBLISHED":
        return (
            external_note
            or "官网当前季截止日期未发布；先给出材料准备动作，不把它当成正式提交时间。"
        )
    if program.source.field_coverage != "complete":
        return (
            external_note
            or "目前只定位到项目入口；学费、语言、材料和截止日期还需要打开学校官网逐项核对。"
        )
    return (
        external_note
        or "这条信息可用于初筛和项目清单草稿；递交前还需要再次核对项目官网页面和申请入口。"
    )


def _risks(
    profile: NormalizedProfile,
    program: Program,
    checks,
    score_breakdown: dict[str, int],
    intent: IntentClassification,
) -> list[str]:
    del profile
    risks = [check.message for check in checks if not check.passed]
    if intent.category == "blocked":
        risks.insert(0, "项目主方向与当前专业意向不匹配，暂不进入项目清单。")
    elif intent.category == "related":
        risks.append("该项目属于交叉/弱相关候选，需要进一步核对课程、先修课和职业目标匹配。")
    elif intent.category == "general":
        risks.append("项目方向证据不足，不能作为核心推荐。")

    if not has_program_detail_page(program):
        risks.append(
            "未找到该项目的官方详情页；需要补齐项目页、PDF/FAQ 或网申系统来源后再进入正式时间线。"
        )
    if program.deadline == "NOT_PUBLISHED":
        risks.append(
            "官网当前季截止日期未发布或未核验；时间线会标注往届参考，并给出可执行准备动作。"
        )
    if program.data_status != DataStatus.verified:
        risks.append(
            "截止日期、学费、材料清单、语言要求尚未完成项目详情页信息确认，不能作为最终递交依据。"
        )
    if score_breakdown["language"] < 72:
        risks.append("语言成绩接近港新常见最低线，建议优先确认项目语言要求并准备重考/送分。")
    if score_breakdown["budget_fit"] < 65:
        risks.append("预算与学费匹配度偏低，需要确认币种、全日制学费和生活费。")
    if program.community_signals:
        risks.append("存在社区资料线索，但不能替代官方要求。")
    return risks


def _actions(intent: IntentClassification, formal: bool, risks: list[str]) -> list[str]:
    actions = [
        "递交前逐项复核硬性条件。",
        "所有文书主张都绑定到已确认事实。",
    ]
    if intent.category == "blocked":
        actions.insert(0, "除非学生主动改选该方向，否则不要把该项目加入最终项目清单。")
    elif intent.category == "related":
        actions.insert(0, "将该项目放在相关候选区，与核心 AI/CS/Data 项目分开比较。")
    if not formal:
        actions.insert(
            0, "打开项目详情页、申请系统或 PDF/FAQ，确认截止日期、学费、语言和材料要求。"
        )
    if risks:
        actions.insert(0, "先处理未满足或需核验要求，再进入最终排序。")
    return actions


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


def _score_breakdown(
    profile: NormalizedProfile,
    assessment: AssessmentResult,
    program: Program,
    overlap: int,
    intent: IntentClassification,
) -> dict[str, int]:
    academic = assessment.dimension_scores.get("academic", 65)
    language = assessment.dimension_scores.get("language", 55)
    experience = assessment.dimension_scores.get("experience", 50)
    discipline_fit = _discipline_fit(overlap, profile, program, intent)
    budget_fit = _budget_fit(profile, program)
    data_trust = _data_trust(program)
    return {
        "academic": academic,
        "language": language,
        "experience": experience,
        "discipline_fit": discipline_fit,
        "budget_fit": budget_fit,
        "data_trust": data_trust,
    }


def _decision_dimensions(
    profile: NormalizedProfile,
    program: Program | ResolvedProgramView,
    score_breakdown: dict[str, int],
    fit: int,
    intent_alignment: int,
) -> dict[str, object]:
    admissions = admissions_eligibility_checks(profile, program)
    financial = financial_feasibility(program, profile.budget_hkd, profile.budget_mode)
    decision_program = (
        materialize_decision_program(program)
        if isinstance(program, ResolvedProgramView)
        else program
    )
    financial_score = None
    if financial.status != DecisionStatus.UNKNOWN:
        financial_score = _budget_fit(profile, decision_program)
    return {
        "admissions_status": admissions_status(admissions),
        "admissions_checks": admissions,
        "academic_fit_score": score_breakdown["academic"],
        "language_fit_score": score_breakdown["language"],
        "discipline_fit_score": score_breakdown["discipline_fit"],
        "experience_fit_score": score_breakdown["experience"],
        "applicant_fit_score": fit,
        "preference_fit_score": intent_alignment,
        "financial_fit_score": financial_score,
        "data_confidence_score": score_breakdown["data_trust"],
        "strategy_score": fit,
    }


def _discipline_fit(
    overlap: int,
    profile: NormalizedProfile,
    program: Program,
    intent: IntentClassification,
) -> int:
    if intent.category == "core":
        return min(96, max(82, intent.alignment))
    if intent.category == "related":
        return min(76, max(58, intent.alignment))
    if intent.category == "blocked":
        return min(35, intent.alignment)
    if overlap:
        return min(88, 58 + overlap * 12)
    if any(
        tag in profile.discipline_tags for tag in {"business", "computer_science", "data_science"}
    ):
        if set(program.discipline_tags) & {"business", "computer_science", "data_science"}:
            return 54
    return 42


def _budget_fit(profile: NormalizedProfile, program: Program) -> int:
    if not profile.budget_hkd or not program.tuition_hkd:
        return 60
    if profile.budget_hkd >= program.tuition_hkd:
        return 88
    ratio = profile.budget_hkd / program.tuition_hkd
    if ratio >= 0.85:
        return 72
    if ratio >= 0.7:
        return 58
    return 42


def _data_trust(program: Program) -> int:
    if not has_program_detail_page(program):
        return 18
    if program.data_status == DataStatus.verified:
        return 92
    if program.data_status in {
        DataStatus.pending_review,
        DataStatus.extracted,
        DataStatus.discovered,
    }:
        return 42 if program.source.field_coverage != "complete" else 56
    if program.data_status in {DataStatus.stale, DataStatus.changed, DataStatus.not_published}:
        return 25
    return 35


def _critical_fields_verified(program: Program) -> bool:
    return (
        has_program_detail_page(program)
        and program.data_status == DataStatus.verified
        and program.last_verified_at is not None
    )


def _band(score: int) -> str:
    if score >= 78:
        return "高"
    if score >= 62:
        return "中"
    return "低"


def _explanation(
    score_breakdown: dict[str, int],
    recommendable: bool,
    data_ready: bool,
    program: Program,
    reasons: list[str],
    risks: list[str],
) -> RecommendationExplanation:
    deadline_known = program.deadline != "NOT_PUBLISHED" and data_ready
    confidence = "中" if recommendable and score_breakdown["data_trust"] >= 55 else "低"
    return RecommendationExplanation(
        hard_condition="通过"
        if recommendable and data_ready
        else "需核验"
        if recommendable
        else "未通过",
        academic_match=_band(score_breakdown["academic"]),
        course_match=_band(score_breakdown["discipline_fit"]) if data_ready else "官网信息需补充",
        experience_match=_band(score_breakdown["experience"]),
        budget_match=_band(score_breakdown["budget_fit"]),
        timeline_feasibility="可规划"
        if deadline_known
        else "准备动作"
        if program.deadline != "NOT_PUBLISHED"
        else "待补充",
        confidence=confidence,
        decision_basis=reasons[:3],
        uncertainties=(risks or ["关键信息还需要回到学校官网逐项确认"])[:4],
    )


def _intent_fit_adjustment(intent: IntentClassification) -> int:
    if intent.category == "core":
        return 4
    if intent.category == "related":
        return -5
    if intent.category == "general":
        return -10
    return -28


def _weighted_fit(score_breakdown: dict[str, int], base: int) -> int:
    weighted = round(
        score_breakdown["academic"] * 0.22
        + score_breakdown["language"] * 0.16
        + score_breakdown["experience"] * 0.18
        + score_breakdown["discipline_fit"] * 0.24
        + score_breakdown["budget_fit"] * 0.08
        + score_breakdown["data_trust"] * 0.12
    )
    return round(weighted * 0.78 + base * 0.22)
