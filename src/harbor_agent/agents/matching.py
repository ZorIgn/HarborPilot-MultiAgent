from __future__ import annotations

from harbor_agent.core.rules import check_program_eligibility, display_gpa, hard_rules_pass, normalized_gpa_100
from harbor_agent.core.llm import LLMProvider, MockLLMProvider
from harbor_agent.models import (
    AssessmentResult,
    DataStatus,
    NormalizedProfile,
    Program,
    ProgramMatch,
    RecommendationExplanation,
)
from harbor_agent.services.intent import IntentClassification, build_intent_profile, classify_program_intent
from harbor_agent.services.external_candidates import qs_evidence_note_for_program


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


class SchoolMatchingAgent:
    name = "SchoolMatchingAgent"

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or MockLLMProvider()

    def run(
        self,
        profile: NormalizedProfile,
        assessment: AssessmentResult,
        programs: list[Program],
    ) -> list[ProgramMatch]:
        matches: list[ProgramMatch] = []
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
            tier = self._tier(fit, recommendable, data_ready, intent.category)
            formal = recommendable and program.data_status == DataStatus.verified
            strategy_band = _strategy_band(profile, program, fit, recommendable, intent.category)

            reasons = _reasons(profile, program, intent)
            risks = _risks(profile, program, checks, score_breakdown, intent)
            actions = _actions(intent, formal, risks)
            consultant_note = _consultant_note(profile, program, strategy_band, score_breakdown, intent)
            source_warning = _source_warning_v2(program, formal)

            matches.append(
                ProgramMatch(
                    program=program,
                    tier=tier,
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
                    explanation=_explanation(score_breakdown, recommendable, data_ready, program, reasons, risks),
                    strategy_band=strategy_band,
                    consultant_note=consultant_note,
                    source_warning=source_warning,
                )
            )

        matches = self._apply_llm_consultant_pass(profile, matches)
        ranked = sorted(matches, key=_ranking_key)
        positive = [item for item in ranked if item.tier != "not_recommended"][:50]
        blocked = [item for item in ranked if item.tier == "not_recommended"][:12]
        return positive + blocked

    def _tier(self, fit: int, recommendable: bool, data_ready: bool, match_category: str) -> str:
        if not recommendable or match_category == "blocked":
            return "not_recommended"
        if not data_ready:
            return "insufficient_info"
        if fit >= 86:
            return "reach"
        if fit >= 72:
            return "match"
        return "safer"

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
                    "Do not invent official deadlines, tuition, language requirements, admission odds, or school facts. "
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


def _ranking_key(item: ProgramMatch) -> tuple[int, int, float, int]:
    band_order = {"reach": 0, "target": 1, "safe": 2, "candidate": 3, "blocked": 4}
    category_order = {"core": 0, "related": 1, "general": 2, "blocked": 3}
    return (
        category_order.get(item.match_category, 9),
        band_order.get(item.strategy_band, 9),
        -_institution_level(item.program),
        -item.fit_score,
    )


def _institution_level(program: Program) -> float:
    institution = program.institution.lower()
    for name, level in ELITE_INSTITUTIONS.items():
        if name in institution:
            return level
    for name, level in STRONG_INSTITUTIONS.items():
        if name in institution:
            return level
    for name, level in SOLID_INSTITUTIONS.items():
        if name in institution:
            return level
    return 3.4


def _profile_competitiveness(profile: NormalizedProfile) -> float:
    tier = profile.education.school_tier
    base = {
        "C9": 4.75,
        "985": 4.45,
        "211": 4.05,
        "double_first_class": 3.85,
        "overseas": 4.1,
        "regular": 3.15,
        "unknown": 3.25,
    }.get(tier, 3.25)
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
    if set(profile.discipline_tags) & {"computer_science", "data_science", "artificial_intelligence"}:
        major_text = profile.education.major.lower()
        if any(keyword in major_text for keyword in ["computer", "software", "人工智能", "计算机", "软件", "ai", "data"]):
            base += 0.12
    return max(2.2, min(5.2, base))


def _institution_challenge(profile: NormalizedProfile, program: Program) -> float:
    return _institution_level(program) - _profile_competitiveness(profile)


def _institution_priority_adjustment(profile: NormalizedProfile, program: Program, match_category: str) -> int:
    if match_category == "blocked":
        return -20
    level = _institution_level(program)
    if match_category == "core":
        return round((level - 3.2) * 5)
    if match_category == "related":
        return round((level - 3.8) * 2)
    return 0



def _reasons(profile: NormalizedProfile, program: Program, intent: IntentClassification) -> list[str]:
    reasons = list(intent.reasons)
    if intent.category == "core":
        reasons.append("该项目进入核心匹配区，优先用于构建 AI/CS/Data 申请组合。")
    elif intent.category == "related":
        reasons.append("该项目进入相关候选区，可作为交叉方向备选，但不替代核心项目。")
    elif intent.category == "blocked":
        reasons.append("该项目已被专业意向过滤，不建议加入当前申请方案。")
    else:
        reasons.append("项目方向证据不足，仅可作为普通候选。")

    reasons.append("申请季数据已版本化，但正式字段仍按来源状态决定能否用于最终结论。")
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
    challenge = _institution_challenge(profile, program)
    if challenge >= 0.35:
        return "reach"
    if challenge >= -0.75:
        return "target"
    if challenge >= -1.9:
        return "safe"
    if fit >= 58:
        return "candidate"
    return "candidate"


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
        "safe": "保底",
        "candidate": "候选",
        "blocked": "暂不建议",
    }[strategy_band]
    academic = _band(score_breakdown["academic"])
    language = _band(score_breakdown["language"])
    experience = _band(score_breakdown["experience"])
    institution_level = _institution_level(program)
    profile_level = _profile_competitiveness(profile)
    direction = "、".join(profile.discipline_tags[:3]) or "目标方向待确认"
    if strategy_band == "blocked":
        return (
            f"暂不建议加入本轮方案：项目方向与 {direction} 的匹配度不足，"
            "除非学生主动改变申请方向，否则不应占用申请名额。"
        )
    return (
        f"顾问分档：{band_label}。依据：本科层级 {profile.education.school_tier}、"
        f"GPA {display_gpa(profile)}、语言匹配 {language}、学术背景 {academic}、"
        f"经历匹配 {experience}、方向匹配 {intent.category}、"
        f"院校挑战度 {institution_level:.1f} vs 背景竞争力 {profile_level:.1f}。"
        f"适合放入 {program.institution_zh or program.institution} 的同层级项目对比池，"
        "最终投递前仍需逐项确认学校官网。"
    )


def _source_warning(program: Program, formal: bool) -> str:
    if formal:
        return "关键字段已达到当前系统的正式推荐门槛；递交前仍建议再次打开官网确认。"
    if program.deadline == "NOT_PUBLISHED":
        return "学校暂未确认当前申请季截止日期；系统先帮你安排材料准备，不把它当成正式提交时间。"
    if program.source.field_coverage != "complete":
        return "目前只确认到项目入口，学费、语言、材料和截止日期还需要打开学校官网逐项确认。"
    return "这条信息可用于初筛和方案草案，递交前还需要再次确认学校官网原文。"


def _source_warning_v2(program: Program, formal: bool) -> str:
    external_note = qs_evidence_note_for_program(program)
    if formal:
        return external_note or "关键字段已达到当前系统的正式推荐门槛；递交前仍建议再次打开官网确认。"
    if program.deadline == "NOT_PUBLISHED":
        return external_note or "学校暂未发布当前申请季截止日期；系统先安排材料准备，不把它当成正式提交时间。"
    if program.source.field_coverage != "complete":
        return external_note or "目前只确认到项目入口，学费、语言、材料和截止日期还需要打开学校官网逐项确认。"
    return external_note or "这条信息可用于初筛和方案草稿；递交前还需要再次确认学校官网原文。"


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
        risks.insert(0, "项目主方向与当前专业意向不匹配，已由择校 Agent 拦截，不进入申请组合。")
    elif intent.category == "related":
        risks.append("该项目属于交叉/弱相关候选，需要进一步核对课程、先修课和职业目标匹配。")
    elif intent.category == "general":
        risks.append("项目方向证据不足，不能作为核心推荐。")

    if program.deadline == "NOT_PUBLISHED":
        risks.append("学校暂未确认当前申请季截止日期，时间线只能先做准备清单。")
    if program.data_status != DataStatus.verified:
        risks.append(
            "截止日期、学费、材料清单、语言要求还没有完成学校官网确认，不能当作最终递交依据。"
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
        actions.insert(0, "除非用户主动改选该方向，否则不要把该项目加入申请方案。")
    elif intent.category == "related":
        actions.insert(0, "将该项目放在相关候选区，与核心 AI/CS/Data 项目分开比较。")
    if not formal:
        actions.insert(0, "打开学校项目页、申请系统或 PDF/FAQ，确认截止日期、学费、语言和材料要求。")
    if risks:
        actions.insert(0, "先处理未满足或不确定要求，再进入最终排序。")
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
    if any(tag in profile.discipline_tags for tag in {"business", "computer_science", "data_science"}):
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
    if program.data_status == DataStatus.verified:
        return 92
    if program.data_status in {DataStatus.pending_review, DataStatus.extracted, DataStatus.discovered}:
        return 42 if program.source.field_coverage != "complete" else 56
    if program.data_status in {DataStatus.stale, DataStatus.changed, DataStatus.not_published}:
        return 25
    return 35


def _critical_fields_verified(program: Program) -> bool:
    return program.data_status == DataStatus.verified and program.last_verified_at is not None


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
        hard_condition="通过" if recommendable and data_ready else "待确认" if recommendable else "未通过",
        academic_match=_band(score_breakdown["academic"]),
        course_match=_band(score_breakdown["discipline_fit"]) if data_ready else "待学校确认",
        experience_match=_band(score_breakdown["experience"]),
        budget_match=_band(score_breakdown["budget_fit"]),
        timeline_feasibility="可规划" if deadline_known else "准备建议" if program.deadline != "NOT_PUBLISHED" else "未知",
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
