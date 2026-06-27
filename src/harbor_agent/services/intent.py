from __future__ import annotations

from dataclasses import dataclass

from harbor_agent.models import NormalizedProfile, Program, ProgramIntentProfile


TECH_STRICT_INTENTS = {
    "artificial_intelligence",
    "computer_science",
    "data_science",
    "software_engineering",
    "cyber_security",
}

INTENT_KEYWORDS: dict[str, list[str]] = {
    "artificial_intelligence": [
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "ai",
        " ai/",
        "ai product",
        "large language model",
        "llm",
        "nlp",
        "computer vision",
        "人工智能",
        "机器学习",
        "深度学习",
        "大模型",
    ],
    "computer_science": [
        "computer science",
        "computing",
        "programming",
        "algorithm",
        "database",
        "information technology",
        "information engineering",
        "computer",
        "计算机",
        "计算",
        "信息工程",
        "信息技术",
        "数据库",
        "算法",
    ],
    "data_science": [
        "data science",
        "data analytics",
        "big data",
        "statistics",
        "statistical",
        "data",
        "数据科学",
        "数据分析",
        "大数据",
        "统计",
    ],
    "business_analytics": [
        "business analytics",
        "product analytics",
        "information systems",
        "commercial analytics",
        "商业分析",
        "商务分析",
        "产品数据",
        "信息系统",
    ],
    "fintech": ["fintech", "financial technology", "金融科技"],
    "software_engineering": ["software", "software engineering", "软件", "软件工程"],
    "cyber_security": ["cyber security", "cybersecurity", "security", "网络安全", "安全"],
    "finance": ["finance", "financial", "quantitative finance", "金融", "定量金融"],
    "management": ["management", "marketing", "accounting", "economics", "管理", "市场", "会计", "经济"],
    "education_language": ["education", "teaching", "tesol", "english", "language", "教育", "英语", "语言"],
}

PROGRAM_CORE_KEYWORDS = [
    "artificial intelligence",
    "machine learning",
    "computer science",
    "computing",
    "data science",
    "big data",
    "information technology",
    "information engineering",
    "software",
    "cyber security",
    "cybersecurity",
    "security by design",
    "人工智能",
    "机器学习",
    "计算机科学",
    "计算硕士",
    "数据科学",
    "大数据",
    "资讯科技",
    "信息技术",
    "信息工程",
    "网络安全",
]

PROGRAM_BA_CORE_KEYWORDS = [
    "business analytics",
    "business and data analytics",
    "data analytics",
    "business statistics",
    "information systems",
    "it in business",
    "information technology management",
    "statistics",
    "statistical",
    "商业分析",
    "商务及数据分析",
    "商业统计",
    "信息系统",
    "统计",
]

PROGRAM_RELATED_TECH_BUSINESS_KEYWORDS = [
    "business analytics",
    "business and data analytics",
    "business statistics",
    "information systems",
    "financial technology",
    "fintech",
    "statistics",
    "statistical",
    "quantitative finance",
    "financial engineering",
    "it in business",
    "information technology management",
    "urban informatics",
    "商业分析",
    "商务及数据分析",
    "商业统计",
    "信息系统",
    "金融科技",
    "统计",
    "定量金融",
    "金融工程",
    "城市信息学",
]

PROGRAM_BLOCKED_FOR_TECH_KEYWORDS = [
    "accounting",
    "economics",
    "finance",
    "global management",
    "management",
    "marketing",
    "english",
    "linguistics",
    "tesol",
    "education",
    "public policy",
    "law",
    "会计",
    "经济",
    "金融学",
    "全球管理",
    "管理",
    "市场营销",
    "英语",
    "语言学",
    "教育",
    "公共政策",
    "法学",
]


@dataclass(frozen=True)
class IntentClassification:
    category: str
    alignment: int
    reasons: list[str]


def build_intent_profile(profile: NormalizedProfile) -> ProgramIntentProfile:
    selected_text = _selected_direction_text(profile)
    context_text = _profile_text(profile)
    primary = [
        intent
        for intent, keywords in INTENT_KEYWORDS.items()
        if _contains_any(selected_text, keywords)
    ]

    for tag in profile.discipline_tags:
        if tag == "artificial_intelligence":
            _append_unique(primary, "artificial_intelligence")
        if tag == "computer_science":
            _append_unique(primary, "computer_science")
        if tag == "data_science":
            _append_unique(primary, "data_science")
        if tag == "business":
            _append_unique(primary, "business_analytics")
        if tag == "education_language":
            _append_unique(primary, "education_language")

    explicit_cross_business = bool({"business_analytics", "fintech", "finance"} & set(primary))
    strict = bool(TECH_STRICT_INTENTS & set(primary)) and not explicit_cross_business
    if strict:
        primary = [
            item
            for item in primary
            if item not in {"business_analytics", "finance", "management", "education_language"}
        ]

    if not primary:
        primary = ["interdisciplinary"]

    return ProgramIntentProfile(
        primary_intents=primary[:6],
        strict_intent=strict,
        user_terms=_compact_terms(context_text),
        core_program_keywords=PROGRAM_CORE_KEYWORDS[:10] if strict else [],
        related_program_keywords=PROGRAM_RELATED_TECH_BUSINESS_KEYWORDS[:10],
        blocked_program_keywords=PROGRAM_BLOCKED_FOR_TECH_KEYWORDS[:10] if strict else [],
        explanation=(
            "系统会先匹配 AI/计算机/数据科学等强相关项目，再把 BA、FinTech、统计等放入相关候选；"
            "纯经济、金融、管理、英语、教育不会进入核心推荐。"
            if strict
            else "系统按用户填写的方向和项目名称做宽召回，再用数据可信度与硬条件过滤。"
        ),
    )


def classify_program_intent(
    profile: NormalizedProfile,
    program: Program,
    intent_profile: ProgramIntentProfile | None = None,
) -> IntentClassification:
    intent_profile = intent_profile or build_intent_profile(profile)
    title_text = _program_title_text(program)
    full_text = _program_full_text(program)
    profile_intents = set(intent_profile.primary_intents)
    overlap = len(set(program.discipline_tags) & set(profile.discipline_tags))

    core_hit = _matched_keywords(title_text, PROGRAM_CORE_KEYWORDS)
    related_hit = _matched_keywords(title_text, PROGRAM_RELATED_TECH_BUSINESS_KEYWORDS)
    ba_core_hit = _matched_keywords(title_text, PROGRAM_BA_CORE_KEYWORDS)
    blocked_hit = _matched_keywords(title_text, PROGRAM_BLOCKED_FOR_TECH_KEYWORDS)

    if intent_profile.strict_intent:
        if core_hit:
            return IntentClassification(
                category="core",
                alignment=min(96, 82 + min(10, len(core_hit) * 4) + overlap * 2),
                reasons=[f"项目名称/方向命中核心技术关键词：{', '.join(core_hit[:3])}"],
            )
        if related_hit:
            return IntentClassification(
                category="related",
                alignment=min(78, 58 + min(12, len(related_hit) * 4) + overlap * 2),
                reasons=[f"项目与技术申请方向弱相关，但更偏交叉方向：{', '.join(related_hit[:3])}"],
            )
        if blocked_hit:
            return IntentClassification(
                category="blocked",
                alignment=18,
                reasons=[f"项目主方向与 AI/CS 目标不匹配：{', '.join(blocked_hit[:3])}"],
            )
        if "computer_science" in program.discipline_tags:
            return IntentClassification(
                category="related",
                alignment=60,
                reasons=["项目标签含计算机/数据方向，但名称未命中核心技术项目关键词，需要人工确认课程匹配。"],
            )
        if overlap:
            return IntentClassification(
                category="general",
                alignment=48,
                reasons=["项目标签存在弱重合，但无法证明与 AI/CS 核心目标直接匹配。"],
            )
        return IntentClassification(
            category="blocked",
            alignment=12,
            reasons=["项目名称和标签均未显示与 AI/CS/Data 目标相关。"],
        )

    if "business_analytics" in profile_intents and ba_core_hit:
        return IntentClassification(
            category="core",
            alignment=min(90, 74 + overlap * 4 + len(ba_core_hit) * 3),
            reasons=[f"项目命中商业分析/信息系统相关关键词：{', '.join(ba_core_hit[:3])}"],
        )
    if (
        "business_analytics" in profile_intents
        and not (profile_intents & {"finance", "management"})
        and blocked_hit
    ):
        return IntentClassification(
            category="blocked",
            alignment=24,
            reasons=[f"项目偏泛商科/金融/管理，不是商业分析核心方向：{', '.join(blocked_hit[:3])}"],
        )
    if profile_intents & {"finance", "fintech"} and (
        _contains_any(full_text, ["fintech", "financial technology", "quantitative finance", "financial engineering", "金融科技", "定量金融", "金融工程"])
    ):
        return IntentClassification(
            category="core",
            alignment=82,
            reasons=["项目与金融科技/量化金融方向匹配。"],
        )
    if overlap:
        if "business_analytics" in profile_intents and not (profile_intents & {"finance", "management"}):
            return IntentClassification(
                category="general",
                alignment=46,
                reasons=["项目只有泛商科标签重合，尚不能证明属于商业分析核心方向。"],
            )
        return IntentClassification(
            category="core",
            alignment=min(86, 66 + overlap * 8),
            reasons=["项目 discipline tag 与用户意向存在明确重合。"],
        )
    if related_hit or core_hit:
        return IntentClassification(
            category="related",
            alignment=60,
            reasons=["项目可作为跨方向候选，但需要进一步核对课程和申请要求。"],
        )
    return IntentClassification(
        category="general",
        alignment=42,
        reasons=["项目没有明显不匹配，但缺少足够方向证据。"],
    )


def _profile_text(profile: NormalizedProfile) -> str:
    parts = [
        " ".join(profile.discipline_tags),
        profile.raw_interest_text,
        profile.education.major,
        profile.career_goal,
    ]
    for exp in profile.experiences:
        parts.extend([exp.title, exp.role, " ".join(exp.outcomes), " ".join(exp.tools)])
    return _normalize_text(" ".join(parts))


def _selected_direction_text(profile: NormalizedProfile) -> str:
    return _normalize_text(
        " ".join(
            [
                " ".join(profile.discipline_tags),
                profile.raw_interest_text,
                profile.education.major,
            ]
        )
    )


def _program_title_text(program: Program) -> str:
    return _normalize_text(" ".join([program.id, program.name, program.name_zh or ""]))


def _program_full_text(program: Program) -> str:
    return _normalize_text(
        " ".join(
            [
                program.id,
                program.name,
                program.name_zh or "",
                program.category_zh or "",
                " ".join(program.discipline_tags),
                " ".join(program.requirements.required_backgrounds),
                " ".join(program.requirements.preferred_backgrounds),
            ]
        )
    )


def _normalize_text(value: str) -> str:
    return f" {value.lower().replace('-', ' ').replace('_', ' ').replace('/', ' / ')} "


def _contains_any(text: str, keywords: list[str]) -> bool:
    return bool(_matched_keywords(text, keywords))


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    matched: list[str] = []
    for keyword in keywords:
        normalized = _normalize_text(keyword)
        if not normalized.strip():
            continue
        if normalized in text:
            matched.append(keyword)
    return matched


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _compact_terms(text: str) -> list[str]:
    terms = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if _contains_any(text, keywords):
            terms.append(intent)
    return terms[:8]
