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
        risks.append("仍有重要自填字段缺失，当前结论只能用于初步探索。")
    if profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0) == 0:
        risks.append("当前还没有上传材料验证过的事实，不适合包装成正式申请结论。")

    level = _overall_level(average)
    confidence = "high" if profile.profile_completeness >= 88 else "medium"
    if profile.profile_completeness < 70:
        confidence = "low"
    evidence_coverage = _evidence_coverage(profile)
    decision_field_coverage = _decision_field_coverage(profile)

    return AssessmentResult(
        assessment_type="VERIFIED"
        if profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0) > 0
        else "PRELIMINARY",
        overall_level=level,
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
        known_text = " ".join(
            [profile.education.major, profile.raw_interest_text]
            + [tool for exp in profile.experiences for tool in exp.tools]
        ).lower()
        missing = [course for course in req.prerequisites if course.lower() not in known_text]
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

    return checks


def hard_rules_pass(checks: list[RuleCheck]) -> bool:
    return all(check.passed for check in checks if check.severity == "hard")


def normalized_gpa_100(gpa: float, scale: str) -> float:
    if scale == "4.0":
        return round(max(0.0, min(4.0, gpa)) / 4.0 * 100, 1)
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
        return "学校官网待确认"
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
    if gpa_100 < 75:
        blockers.append("GPA 低于港新授课型硕士常见安全线，需要逐项目核对最低要求。")
    if not profile.discipline_tags:
        blockers.append("目标方向尚未明确，无法做项目级资格判断。")
    if blockers:
        return "发现需要优先处理的硬门槛或方向信息：" + " ".join(blockers)
    return "暂未发现明显硬门槛问题；但仍需成绩单、核心课程和项目级官网要求后才能完成正式资格判断。"


def _scope_note(decision_field_coverage: int, evidence_coverage: int) -> str:
    if decision_field_coverage >= 75 and evidence_coverage >= 50:
        return "可进入候选池和重点项目比较；正式择校仍需逐项确认学校官网。"
    if decision_field_coverage >= 50:
        return "适用于方向探索和候选池召回，暂不适合直接生成正式申请组合。"
    return "仅用于初步方向探索；关键决策字段不足，不能作为最终择校依据。"


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
    course_unknown = not profile.raw_interest_text and not any(exp.tools for exp in profile.experiences)
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
            uncertainties=["线性代数、数据库、算法、统计等关键课程是否满足仍待确认"],
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
            applicable_to=["申请组合", "时间线", "材料清单"],
            uncertainties=["推荐人、材料上传、官方截止日期仍需核对"],
            actions=["确认预算上限", "确定推荐人", "只使用学校官网已确认信息生成正式时间线"],
        ),
    ]
