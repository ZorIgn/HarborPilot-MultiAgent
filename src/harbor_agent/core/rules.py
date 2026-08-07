from __future__ import annotations

from harbor_agent.models import (
    AssessmentResult,
    DimensionFinding,
    EvidenceLevel,
    NormalizedProfile,
    Program,
    RuleCheck,
)


def evaluate_general_profile(profile: NormalizedProfile) -> AssessmentResult:
    gpa_100 = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)
    academic = _score_gpa(gpa_100)
    academic = max(45, min(96, academic + _school_tier_bonus(profile.education.school_tier)))
    language = _score_language(profile)
    experience = _score_experience(profile)
    readiness = _score_readiness(profile)
    average = round((academic * 0.34) + (language * 0.22) + (experience * 0.28) + (readiness * 0.16))

    strengths: list[str] = []
    weaknesses: list[str] = []
    actions: list[str] = []
    risks: list[str] = []

    if academic >= 82:
        strengths.append("学术成绩和学校层级可支撑港新硕士初步分档。")
    else:
        weaknesses.append("学术成绩可能限制顶尖项目的冲刺空间。")
        actions.append("补充排名、核心课程成绩和成绩趋势证据。")

    if language >= 78:
        strengths.append("语言成绩接近或达到多数项目的常见递交状态。")
    else:
        weaknesses.append("语言成绩缺失或低于港新常见要求。")
        actions.append("补充语言单项，逐项目确认 IELTS/TOEFL/PTE 要求。")

    if experience >= 76:
        strengths.append("经历素材具备转化为文书故事卡的基础。")
    else:
        weaknesses.append("经历部分需要更多量化结果、角色边界和技术细节。")
        actions.append("按问题、行动、工具、结果、反思重写每段关键经历。")

    if profile.profile_completeness < 75:
        risks.append("仍有重要自填信息缺失，当前结论只能用于初步探索。")
    if profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0) == 0:
        risks.append("当前还没有上传材料验证过的事实，不适合包装成正式申请结论。")

    decision_field_coverage = _decision_field_coverage(profile)
    minimum_data_ready = _minimum_decision_data_ready(profile, decision_field_coverage)
    level = _overall_level(average) if minimum_data_ready else "NEEDS_DATA"
    confidence = "high" if profile.profile_completeness >= 88 else "medium"
    if profile.profile_completeness < 70 or not minimum_data_ready:
        confidence = "low"
    evidence_coverage = _evidence_coverage(profile)
    competitiveness_level = _competitiveness_level(average) if minimum_data_ready else "弱"

    return AssessmentResult(
        assessment_type="VERIFIED"
        if profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0) > 0
        else "PRELIMINARY",
        overall_level=level,
        competitiveness_level=competitiveness_level,
        competitiveness_summary=(
            _competitiveness_summary(profile, average, competitiveness_level)
            if minimum_data_ready
            else "关键决策信息不足，暂不输出竞争力等级。请先补齐本科专业与成绩、目标方向，以及语言或备考状态后重新评估。"
        ),
        application_positioning=_application_positioning(competitiveness_level),
        hard_thresholds=_hard_thresholds(profile),
        strengthening_actions=_strengthening_actions(profile, academic, language, experience),
        confidence=confidence,
        data_completeness=profile.profile_completeness,
        dimension_scores={
            "academic": academic,
            "language": language,
            "experience": experience,
            "readiness": readiness,
        },
        strengths=strengths,
        weaknesses=weaknesses,
        risks=risks,
        actions=actions[:5],
        rule_checks=[],
        template_confidence="medium" if profile.discipline_tags else "low",
        qualification_status=_qualification_status(profile),
        decision_field_coverage=decision_field_coverage,
        evidence_coverage=evidence_coverage,
        dimension_findings=_dimension_findings(profile, academic, language, experience, readiness),
        scope_note=_scope_note(decision_field_coverage, evidence_coverage),
    )


def check_program_eligibility(profile: NormalizedProfile, program: Program) -> list[RuleCheck]:
    checks: list[RuleCheck] = []
    req = program.requirements
    gpa_100 = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)

    if req.min_gpa is not None:
        checks.append(
            RuleCheck(
                rule_id="min_gpa",
                program_id=program.id,
                passed=gpa_100 >= req.min_gpa,
                severity="hard",
                message=(
                    f"GPA {profile.education.gpa:g}/{profile.education.gpa_scale}，"
                    f"折算约 {gpa_100:.1f}/100；项目最低要求 {req.min_gpa:.1f}/100。"
                ),
                evidence_level=profile.education.evidence_level,
            )
        )

    if req.language:
        if profile.language.test == "NONE" or profile.language.overall is None:
            checks.append(
                RuleCheck(
                    rule_id="language_required",
                    program_id=program.id,
                    passed=False,
                    severity="hard",
                    message=f"尚未提供语言成绩；项目语言要求为 {_language_requirement_text(req.language)}。",
                    evidence_level=profile.language.evidence_level,
                )
            )
        elif profile.language.test in req.language:
            required = req.language[profile.language.test]
            actual = profile.language.overall
            checks.append(
                RuleCheck(
                    rule_id=f"{profile.language.test.lower()}_overall",
                    program_id=program.id,
                    passed=actual >= required,
                    severity="hard",
                    message=f"{profile.language.test} {actual:g}，项目最低要求 {profile.language.test} {required:g}。",
                    evidence_level=profile.language.evidence_level,
                )
            )
            subscore_check = _language_subscore_check(profile, program.id, required)
            if subscore_check:
                checks.append(subscore_check)
        else:
            checks.append(
                RuleCheck(
                    rule_id="language_test_mismatch",
                    program_id=program.id,
                    passed=False,
                    severity="soft",
                    message=(
                        f"你填写的是 {profile.language.test} {profile.language.overall:g}；"
                        f"当前项目库只记录到 {_language_requirement_text(req.language)}，"
                        "需打开学校官网确认是否接受该考试及对应分数。"
                    ),
                    evidence_level=profile.language.evidence_level,
                )
            )

    if req.required_backgrounds:
        known_text = _background_known_text(profile)
        missing = [background for background in req.required_backgrounds if not _background_requirement_satisfied(background, known_text)]
        checks.append(
            RuleCheck(
                rule_id="required_background",
                program_id=program.id,
                passed=len(missing) == 0,
                severity="hard",
                message=(
                    "专业背景要求：已在专业、核心课程、技能或经历中找到相关证据。"
                    if not missing
                    else "专业背景要求：缺少 " + ", ".join(_background_label(item) for item in missing) + " 的明确证据。"
                ),
                evidence_level=EvidenceLevel.self_reported,
            )
        )

    if req.preferred_backgrounds:
        known_text = _background_known_text(profile)
        missing_preferred = [background for background in req.preferred_backgrounds if not _background_requirement_satisfied(background, known_text)]
        if missing_preferred:
            checks.append(
                RuleCheck(
                    rule_id="preferred_background_signal",
                    program_id=program.id,
                    passed=False,
                    severity="soft",
                    message="偏好背景：还缺少 " + ", ".join(_background_label(item) for item in missing_preferred[:4]) + " 的材料证据；会影响竞争力但不直接判定不能申请。",
                    evidence_level=EvidenceLevel.self_reported,
                )
            )

    if req.portfolio_required:
        has_portfolio = any("portfolio" in item.lower() or "作品集" in item for item in profile.raw_interest_text.split())
        checks.append(
            RuleCheck(
                rule_id="portfolio_required",
                program_id=program.id,
                passed=has_portfolio,
                severity="hard",
                message="该项目需要作品集或作品证明。",
                evidence_level=EvidenceLevel.self_reported,
            )
        )

    if req.prerequisites:
        known_text = _prerequisite_known_text(profile)
        missing = [course for course in req.prerequisites if not _prerequisite_satisfied(course, known_text)]
        missing_labels = [_prerequisite_label(course) for course in missing]
        checks.append(
            RuleCheck(
                rule_id="prerequisite_signal",
                program_id=program.id,
                passed=len(missing) == 0,
                severity="soft",
                message=(
                    "先修课/背景关键词已在用户资料中找到。"
                    if not missing
                    else f"缺少先修课或背景证据：{', '.join(missing_labels)}。"
                ),
                evidence_level=EvidenceLevel.self_reported,
            )
        )

    if profile.budget_hkd is not None and program.tuition_hkd is not None:
        checks.append(
            RuleCheck(
                rule_id="tuition_budget",
                program_id=program.id,
                passed=profile.budget_hkd >= program.tuition_hkd,
                severity="hard",
                message=(
                    f"预算 HKD {profile.budget_hkd:,}；项目学费约 HKD {program.tuition_hkd:,}。"
                    "预算还需另外覆盖生活费、签证、保险和交通。"
                ),
                evidence_level=EvidenceLevel.self_reported,
            )
        )

    return checks



def _background_known_text(profile: NormalizedProfile) -> str:
    background = profile.additional_background
    parts: list[str] = [
        profile.education.major,
        *background.core_courses,
        *background.skills,
        *background.research_outputs,
        *background.exchange_experiences,
        *background.activities,
        *background.awards,
    ]
    for exp in profile.experiences:
        parts.extend([exp.title, exp.organization, exp.role])
        parts.extend(exp.tools)
        parts.extend(exp.outcomes)
    return " ".join(part for part in parts if part).lower()


_BACKGROUND_REQUIREMENT_KEYWORDS: dict[str, list[str]] = {
    "computing": ["computer science", "computing", "information technology", "software", "programming", "coding", "python", "java", "c++", "sql", "data structures", "algorithms", "database", "operating systems", "computer networks", "计算机", "软件", "信息技术", "程序设计", "编程", "代码", "数据结构", "算法", "数据库", "操作系统", "计算机网络"],
    "business": ["business", "management", "finance", "accounting", "marketing", "商业", "管理", "金融", "会计", "市场"],
    "statistics": ["statistics", "probability", "statistical", "统计", "概率"],
    "engineering": ["engineering", "mechanical", "electrical", "civil", "工程", "机械", "电气", "土木"],
}

def _background_requirement_satisfied(requirement: str, known_text: str) -> bool:
    normalized = requirement.lower().replace("_", " ").strip()
    keywords = _BACKGROUND_REQUIREMENT_KEYWORDS.get(normalized, [normalized])
    text_match = any(keyword.lower() in known_text for keyword in keywords)
    # Intention tags and career goals are deliberately excluded here. Wanting
    # to study AI is not evidence of an existing computing background.
    return text_match


def _background_label(requirement: str) -> str:
    labels = {
        "computing": "计算机/编程背景",
        "business": "商科背景",
        "statistics": "统计背景",
        "engineering": "工程背景",
    }
    return labels.get(requirement.lower(), requirement)


def _prerequisite_known_text(profile: NormalizedProfile) -> str:
    background = profile.additional_background
    parts: list[str] = [
        profile.education.major,
        *background.core_courses,
        *background.skills,
        *background.research_outputs,
        *background.exchange_experiences,
        *background.activities,
        *background.awards,
    ]
    for exp in profile.experiences:
        parts.extend([exp.title, exp.organization, exp.role])
        parts.extend(exp.tools)
        parts.extend(exp.outcomes)
    return " ".join(part for part in parts if part).lower()

_PREREQUISITE_KEYWORDS: dict[str, list[str]] = {
    "programming": ["programming", "programming ability", "program design", "coding", "python", "java", "c++", "程序设计", "编程", "代码", "计算机程序", "软件开发"],
    "statistics": ["statistics", "statistical", "probability", "概率", "统计", "数理统计", "应用统计"],
    "linear algebra": ["linear algebra", "matrix", "矩阵", "线性代数", "线代"],
    "calculus": ["calculus", "advanced mathematics", "mathematical analysis", "微积分", "高等数学", "数学分析"],
    "database": ["database", "sql", "dbms", "数据库", "数据仓库", "关系型数据库"],
    "algorithms": ["algorithm", "algorithms", "算法", "算法设计"],
    "data structures": ["data structure", "data structures", "数据结构"],
    "machine learning": ["machine learning", "deep learning", "ml", "机器学习", "深度学习"],
    "computer networks": ["computer network", "computer networks", "networking", "计算机网络", "网络协议"],
    "operating systems": ["operating system", "operating systems", "os", "操作系统"],
}


def _prerequisite_satisfied(course: str, known_text: str) -> bool:
    normalized = course.lower().replace("_", " ").strip()
    keywords = _PREREQUISITE_KEYWORDS.get(normalized, [normalized])
    return any(keyword.lower() in known_text for keyword in keywords)


def _language_subscore_check(profile: NormalizedProfile, program_id: str, required_overall: float) -> RuleCheck | None:
    if profile.language.test not in {"IELTS", "TOEFL", "PTE"}:
        return None
    subscores = {
        "writing": profile.language.writing,
        "reading": profile.language.reading,
        "listening": profile.language.listening,
        "speaking": profile.language.speaking,
    }
    provided = {name: value for name, value in subscores.items() if value is not None}
    if not provided:
        return RuleCheck(
            rule_id="language_subscores_missing",
            program_id=program_id,
            passed=False,
            severity="soft",
            message="尚未填写语言单项；部分港新项目会设置写作、口语或各单项最低要求，正式递交前需逐项目核对。",
            evidence_level=profile.language.evidence_level,
        )
    if profile.language.test == "IELTS":
        floor = 6.0 if required_overall <= 6.5 else 6.5
    elif profile.language.test == "TOEFL":
        floor = 20 if required_overall <= 90 else 22
    else:
        floor = 59 if required_overall <= 62 else 62
    low = {name: value for name, value in provided.items() if value < floor}
    if not low:
        return None
    low_text = ", ".join(f"{name} {value:g}" for name, value in low.items())
    return RuleCheck(
        rule_id="language_subscores_signal",
        program_id=program_id,
        passed=False,
        severity="soft",
        message=f"语言总分可能达标，但单项存在风险：{low_text}；请核对目标项目是否有单项最低要求。",
        evidence_level=profile.language.evidence_level,
    )
def hard_rules_pass(checks: list[RuleCheck]) -> bool:
    return all(check.passed for check in checks if check.severity == "hard")


def normalized_gpa_100(gpa: float, scale: str) -> float:
    if scale == "4.0":
        bounded = max(0.0, min(4.0, gpa))
        anchors = [
            (3.85, 95.0),
            (3.70, 90.0),
            (3.30, 85.0),
            (3.00, 80.0),
            (2.70, 75.0),
            (2.30, 70.0),
            (2.00, 65.0),
            (0.00, 50.0),
        ]
        for cutoff, score in anchors:
            if bounded >= cutoff:
                return score
    if scale == "5.0":
        return round(max(0.0, min(5.0, gpa)) / 5.0 * 100, 1)
    return round(max(0.0, min(100.0, gpa)), 1)


def display_gpa(profile: NormalizedProfile) -> str:
    gpa_100 = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)
    if profile.education.gpa_scale == "100":
        return f"{gpa_100:.1f}/100"
    return f"{profile.education.gpa:g}/{profile.education.gpa_scale}（约 {gpa_100:.1f}/100）"


def _language_requirement_text(language: dict[str, float]) -> str:
    if not language:
        return "学校官网需核验"
    return " / ".join(f"{test} {score:g}" for test, score in language.items())


def _prerequisite_label(course: str) -> str:
    labels = {
        "programming": "编程能力/程序设计",
        "statistics": "统计学",
        "linear algebra": "线性代数",
        "calculus": "微积分",
        "database": "数据库",
        "algorithms": "算法",
        "data structures": "数据结构",
        "machine learning": "机器学习",
        "computer networks": "计算机网络",
        "operating systems": "操作系统",
    }
    return labels.get(course.lower(), course)


def _score_gpa(gpa_100: float) -> int:
    if gpa_100 >= 88:
        return 92
    if gpa_100 >= 84:
        return 84
    if gpa_100 >= 80:
        return 76
    if gpa_100 >= 75:
        return 66
    return 52


def _school_tier_bonus(tier: str) -> int:
    return {
        "C9": 8,
        "985": 6,
        "211": 3,
        "double_first_class": 4,
        "overseas": 4,
        "regular": 0,
        "unknown": -2,
    }.get(tier, 0)


def _score_language(profile: NormalizedProfile) -> int:
    if profile.language.test == "NONE" or profile.language.overall is None:
        return 45
    score = profile.language.overall
    if profile.language.test == "IELTS":
        if score >= 7.5:
            return 92
        if score >= 7.0:
            return 84
        if score >= 6.5:
            return 73
        return 58
    if profile.language.test == "TOEFL":
        if score >= 105:
            return 92
        if score >= 100:
            return 84
        if score >= 90:
            return 73
        return 58
    if profile.language.test == "PTE":
        if score >= 76:
            return 92
        if score >= 69:
            return 84
        if score >= 62:
            return 73
        return 58
    return 65


def _score_experience(profile: NormalizedProfile) -> int:
    if not profile.experiences:
        return 40
    base = min(82, 45 + len(profile.experiences) * 12)
    quantified = sum(1 for exp in profile.experiences if exp.outcomes)
    return min(95, base + quantified * 5)


def _score_readiness(profile: NormalizedProfile) -> int:
    score = 50
    if profile.budget_hkd:
        score += 15
    if profile.career_goal:
        score += 15
    if not profile.risk_flags:
        score += 10
    if profile.target_cycle:
        score += 10
    return min(score, 95)


def _overall_level(score: int) -> str:
    if score >= 88:
        return "A"
    if score >= 82:
        return "A-"
    if score >= 76:
        return "B+"
    if score >= 68:
        return "B"
    if score >= 60:
        return "C+"
    return "C"


def _minimum_decision_data_ready(profile: NormalizedProfile, decision_field_coverage: int) -> bool:
    major = profile.education.major.strip().lower()
    has_major = bool(major and major not in {"未填写", "unknown", "n/a"})
    has_academic_record = profile.education.gpa > 0
    has_direction = bool(profile.discipline_tags)
    return decision_field_coverage >= 50 and has_major and has_academic_record and has_direction


def _competitiveness_level(score: int) -> str:
    if score >= 84:
        return "强"
    if score >= 76:
        return "中强"
    if score >= 64:
        return "中"
    return "弱"


def _competitiveness_summary(profile: NormalizedProfile, score: int, level: str) -> str:
    gpa_text = display_gpa(profile)
    language = (
        f"{profile.language.test} {profile.language.overall:g}"
        if profile.language.test != "NONE" and profile.language.overall is not None
        else "语言未出分"
    )
    direction = "、".join(profile.discipline_tags[:3]) or "方向待明确"
    positioning = _application_positioning(level)
    return (
        f"当前竞争力为{level}（规则分 {score}/100）：{profile.education.school_tier} 背景，"
        f"{profile.education.major}，GPA {gpa_text}，{language}，目标方向 {direction}。"
        f"择校可先按冲刺、主申、相对稳妥三层筛选：{positioning['冲刺']}{positioning['主申']}{positioning['相对稳妥']}"
    )

def _application_positioning(level: str) -> dict[str, str]:
    if level == "强":
        return {
            "冲刺": "港三、新二高选择性项目可进入冲刺池，但仍要核对先修课、语言单项和项目详情页。",
            "主申": "港三/城大/理工/SMU 等方向强匹配项目应作为主申核心。",
            "相对稳妥": "选择 1-2 个方向一致、硬门槛明确通过且信息可核验的项目作为补充。",
        }
    if level == "中强":
        return {
            "冲刺": "可保留少量港三/新二项目冲刺，优先选与经历和课程高度相关的项目。",
            "主申": "城大、理工、浸会、SMU、SUTD 等匹配项目应作为主申主体。",
            "相对稳妥": "需要配置 2-3 个方向匹配、材料要求清晰且信息可核验的项目。",
        }
    if level == "中":
        return {
            "冲刺": "高选择性项目只保留极少数强相关方向，不建议堆数量。",
            "主申": "以方向匹配、硬门槛通过、学费预算可承受的项目为主申。",
            "相对稳妥": "相对稳妥项目要优先确保语言、先修课、材料和申请入口清晰。",
        }
    return {
        "冲刺": "暂不建议把高选择性项目作为本轮重点，除非补强后重新评估。",
        "主申": "先选择硬门槛明确通过、方向宽容度较高的项目。",
        "相对稳妥": "相对稳妥项目应以语言、GPA、专业背景和申请信息清晰为第一条件。",
    }


def _hard_thresholds(profile: NormalizedProfile) -> list[str]:
    thresholds: list[str] = []
    gpa_100 = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)
    thresholds.append(f"GPA：当前 {display_gpa(profile)}；低于 75/100 时需要逐项目核对最低成绩要求。")
    if profile.language.test == "NONE" or profile.language.overall is None:
        thresholds.append("语言：暂未提供有效总分；多数港新项目需要 IELTS/TOEFL/PTE 达标后递交或后补。")
    else:
        thresholds.append(f"语言：当前 {profile.language.test} {profile.language.overall:g}；仍需核对每个项目的总分和单项要求。")
    thresholds.append(
        "专业背景：需核对项目是否限制本科专业，跨专业项目也可能要求数学、统计、编程或作品集。"
    )
    thresholds.append(
        "先修课：需要把核心课程和成绩结构化，重点检查统计、线代、编程、数据库、算法、机器学习等要求。"
    )
    if profile.budget_hkd:
        thresholds.append(f"预算：当前预算 HKD {profile.budget_hkd:,}；超预算项目应进入风险清单。")
    else:
        thresholds.append("预算：未填写预算上限；无法判断学费和生活成本是否可承受。")
    if gpa_100 < 75:
        thresholds.append("成绩风险：当前 GPA 低于常见安全线，必须优先确认项目最低分和补充成绩趋势说明。")
    return thresholds


def _strengthening_actions(profile: NormalizedProfile, academic: int, language: int, experience: int) -> list[str]:
    grade_action = (
        "成绩：补充排名、核心课程成绩、成绩趋势；如有后续成绩提升，更新后重新评估。"
        if academic < 82 or profile.education.ranking_percentile is None
        else "成绩：保留当前 GPA、排名和成绩单证据，重点标出与目标方向相关的高分课程。"
    )
    course_action = (
        "课程：填写 6-10 门核心课程、成绩和项目作业，给先修课判断提供证据。"
        if not profile.additional_background.core_courses and not profile.raw_interest_text
        else "课程：把已填写课程映射到统计、线代、编程、数据库、研究方法等常见先修课标签。"
    )
    language_action = (
        "语言：补齐阅读、听力、口语、写作单项；按目标项目最低要求安排下一次考试。"
        if language < 78
        else "语言：保留总分和单项截图，逐项目核对是否有写作、口语或送分周期要求。"
    )
    experience_action = (
        "经历：把实习/科研/项目写成问题、行动、工具、结果、反思五段事实。"
        if experience < 76
        else "经历：把已有实习、科研和项目压缩成可量化故事卡，突出个人角色和方法细节。"
    )
    writing_action = (
        "文书素材：每段经历至少补一个可验证结果，例如指标、报告、代码、展示、推荐人可证明事实。"
        if not any(exp.outcomes for exp in profile.experiences)
        else "文书素材：把结果、工具、推荐人可证明事实绑定到故事卡，避免写成泛泛自我评价。"
    )
    goal_action = (
        "目标：补充毕业后的行业、岗位和地区偏好，避免择校只按排名排序。"
        if not profile.career_goal
        else "目标：把职业目标拆成短期岗位、长期方向和目标地区，用于筛选项目培养重点。"
    )
    return [grade_action, course_action, language_action, experience_action, writing_action, goal_action]

def _evidence_coverage(profile: NormalizedProfile) -> int:
    verified = profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0)
    confirmed = profile.fact_summary.get(EvidenceLevel.user_confirmed.value, 0)
    total = sum(profile.fact_summary.values()) or 1
    return min(100, round((verified * 1.0 + confirmed * 0.5) / total * 100))


def _decision_field_coverage(profile: NormalizedProfile) -> int:
    checks = [
        bool(profile.education.school_tier and profile.education.school_tier != "unknown"),
        bool(profile.education.major),
        bool(profile.education.gpa),
        profile.education.ranking_percentile is not None,
        bool(profile.discipline_tags),
        profile.language.test != "NONE" and profile.language.overall is not None,
        profile.language.writing is not None,
        profile.language.reading is not None,
        profile.language.listening is not None,
        profile.language.speaking is not None,
        bool(profile.experiences),
        any(exp.outcomes for exp in profile.experiences),
        any(exp.tools for exp in profile.experiences),
        bool(profile.budget_hkd),
        bool(profile.career_goal),
    ]
    return round(sum(1 for item in checks if item) / len(checks) * 100)


def _qualification_status(profile: NormalizedProfile) -> str:
    blockers: list[str] = []
    gpa_100 = normalized_gpa_100(profile.education.gpa, profile.education.gpa_scale)
    if profile.language.test == "NONE" or profile.language.overall is None:
        blockers.append("缺少语言成绩，无法判断多数项目的硬门槛。")
    elif (
        (profile.language.test == "IELTS" and profile.language.overall < 6.0)
        or (profile.language.test == "TOEFL" and profile.language.overall < 80)
        or (profile.language.test == "PTE" and profile.language.overall < 58)
    ):
        blockers.append(
            f"{profile.language.test} {profile.language.overall:g} 低于多数港新授课型硕士的常见递交区间，"
            "需要先制定重考计划并逐项目核对最低分。"
        )
    if gpa_100 < 75:
        blockers.append("GPA 低于港新授课型硕士常见安全线，需要逐项目核对最低要求。")
    if not profile.discipline_tags:
        blockers.append("目标方向尚未明确，无法做项目级资格判断。")
    if blockers:
        return "发现需要优先处理的硬门槛或方向信息：" + " ".join(blockers)
    return "暂未发现明显硬门槛问题；但仍需成绩单、核心课程和项目级官网要求后才能完成正式资格判断。"


def _scope_note(decision_field_coverage: int, evidence_coverage: int) -> str:
    if decision_field_coverage >= 75 and evidence_coverage >= 50:
        return "可生成项目分档和学生选择清单；正式投递时间线仍需通过项目官网信息确认。"
    if decision_field_coverage >= 50:
        return "可生成方向探索版项目分档，学生确认项目前需补齐语言单项、核心课程、经历结果或预算等关键信息。"
    return "仅用于初步方向探索；关键决策信息不足，不能作为正式择校依据。"

def _level(score: int, unknown: bool = False) -> str:
    if unknown:
        return "信息不足"
    if score >= 78:
        return "高"
    if score >= 62:
        return "中"
    return "低"


def _dimension_findings(
    profile: NormalizedProfile,
    academic: int,
    language: int,
    experience: int,
    readiness: int,
) -> list[DimensionFinding]:
    course_unknown = not profile.additional_background.core_courses and not profile.raw_interest_text and not any(exp.tools for exp in profile.experiences)
    gpa_text = display_gpa(profile)
    return [
        DimensionFinding(
            dimension="学术成绩",
            level=_level(academic),
            conclusion="当前 GPA 和学校层级可用于初步分档，但项目级判断仍依赖成绩单与排名。",
            basis=f"{profile.education.school_tier}，GPA {gpa_text}。",
            applicable_to=profile.discipline_tags or ["通用授课型硕士"],
            uncertainties=["缺少正式成绩单", "核心课程和成绩尚未结构化"] if course_unknown else ["需核对项目先修课"],
            actions=["上传成绩单后重新判断课程匹配", "补充年级排名或专业排名"],
        ),
        DimensionFinding(
            dimension="课程匹配",
            level=_level(70, course_unknown),
            conclusion="课程匹配暂不能下最终结论，需要看到核心课程、工具和项目技术深度。",
            basis="系统只读取到专业、方向和经历关键词，尚未读取完整课程表。",
            applicable_to=profile.discipline_tags or ["待定方向"],
            uncertainties=["线性代数、数据库、算法、统计等关键课程是否满足仍需核验"],
            actions=["补充 6-10 门相关课程及成绩", "标注每段项目使用的方法、代码和数据规模"],
        ),
        DimensionFinding(
            dimension="语言能力",
            level=_level(language, profile.language.test == "NONE"),
            conclusion="语言成绩可用于初步判断是否接近递交状态。",
            basis=(
                "尚未提供语言成绩"
                if profile.language.test == "NONE"
                else f"{profile.language.test} 总分 {profile.language.overall}，写作 {profile.language.writing or '未填'}。"
            ),
            applicable_to=["港新授课型硕士"],
            uncertainties=["不同项目可能有单项要求", "部分项目接受后补或官方送分周期不同"],
            actions=["补充语言单项成绩", "逐项目确认 IELTS/TOEFL/PTE 要求"],
        ),
        DimensionFinding(
            dimension="相关经历",
            level=_level(experience, not profile.experiences),
            conclusion="经历素材需要从描述转成可验证故事卡，才能支撑文书和面试。",
            basis=f"已填写 {len(profile.experiences)} 段经历，其中 {sum(1 for exp in profile.experiences if exp.outcomes)} 段包含结果。",
            applicable_to=profile.discipline_tags or ["待定方向"],
            uncertainties=["角色边界、量化结果、技术贡献是否清晰"],
            actions=["按问题、行动、结果、反思补全每段经历", "把 BA 经历转译为 CS/DS 能力证据时补技术细节"],
        ),
        DimensionFinding(
            dimension="申请准备度",
            level=_level(readiness),
            conclusion="预算、目标和材料证据会影响正式方案能否落地。",
            basis=f"预算 {'已填写' if profile.budget_hkd else '未填写'}，职业目标 {'已填写' if profile.career_goal else '未填写'}。",
            applicable_to=["项目清单", "时间线", "材料清单"],
            uncertainties=["推荐人、材料上传、官方截止日期仍需核对"],
            actions=["确认预算上限", "确定推荐人", "只使用学校官网已确认信息生成正式时间线"],
        ),
    ]
