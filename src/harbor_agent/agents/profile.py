from __future__ import annotations

import hashlib
from collections import Counter

from harbor_agent.models import ApplicantProfileInput, EvidenceLevel, NormalizedProfile


DISCIPLINE_KEYWORDS = {
    "artificial_intelligence": [
        "artificial_intelligence",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "ai",
        "人工智能",
        "机器学习",
        "深度学习",
    ],
    "computer_science": [
        "computer_science",
        "computer science",
        "computing",
        "computer",
        "software",
        "information technology",
        "计算机",
        "软件",
        "信息技术",
    ],
    "data_science": [
        "data_science",
        "data science",
        "big data",
        "data analytics",
        "statistics",
        "数据科学",
        "大数据",
        "数据分析",
        "统计",
    ],
    "business": ["business", "finance", "management", "marketing", "accounting", "商科", "金融", "管理"],
    "engineering": ["engineering", "mechanical", "electrical", "civil", "机械", "电气", "电子工程", "土木"],
    "social_science": ["policy", "psychology", "sociology", "social", "公共政策", "心理", "社会"],
    "communication": ["media", "communication", "journalism", "传媒", "传播", "新闻"],
    "law_policy": ["law", "legal", "policy", "法律", "法学", "政策"],
    "life_health": ["health", "biomedical", "public health", "biology", "健康", "生物", "医学"],
    "design_built_environment": ["architecture", "design", "urban", "portfolio", "建筑", "设计", "城市"],
    "education_language": ["education", "teaching", "language", "tesol", "教育", "语言"],
}


class ProfileAgent:
    name = "ProfileAgent"

    def run(self, payload: ApplicantProfileInput) -> NormalizedProfile:
        tags = self._map_disciplines(payload)
        missing = self._missing_fields(payload)
        completeness = max(30, 100 - len(missing) * 8)
        facts = Counter()

        facts[payload.education.evidence_level.value] += 1
        facts[payload.language.evidence_level.value] += 1
        for exp in payload.experiences:
            facts[exp.evidence_level.value] += 1

        profile_id = hashlib.sha1(
            (
                f"{payload.education.school}:{payload.education.school_tier}:"
                f"{payload.education.major}:{payload.target_cycle}"
            ).encode()
        ).hexdigest()[:12]

        return NormalizedProfile(
            profile_id=f"profile_{profile_id}",
            target_cycle=payload.target_cycle,
            target_regions=payload.target_regions,
            discipline_tags=tags or ["interdisciplinary"],
            raw_interest_text=payload.raw_interest_text,
            education=payload.education,
            language=payload.language,
            experiences=payload.experiences,
            budget_hkd=payload.budget_hkd,
            career_goal=payload.career_goal,
            risk_flags=payload.risk_flags,
            profile_completeness=completeness,
            missing_fields=missing,
            conflicts=[],
            fact_summary=dict(facts),
        )

    def _map_disciplines(self, payload: ApplicantProfileInput) -> list[str]:
        # Only the user's selected direction, free-form interest text, and major decide
        # primary discipline tags. Career goals and experience descriptions may inform
        # matching later, but must not silently turn a CS/AI/Data applicant into BA.
        text = " ".join(payload.discipline_interests + [payload.raw_interest_text, payload.education.major])
        lowered = text.lower()
        tags = [
            tag
            for tag, keywords in DISCIPLINE_KEYWORDS.items()
            if any(keyword.lower() in lowered for keyword in keywords)
        ]
        return tags[:4]

    def _missing_fields(self, payload: ApplicantProfileInput) -> list[str]:
        missing: list[str] = []
        if not payload.discipline_interests and not payload.raw_interest_text:
            missing.append("target discipline direction")
        if payload.language.test == "NONE" or payload.language.overall is None:
            missing.append("language test score")
        if not payload.experiences:
            missing.append("experience portfolio")
        if payload.education.ranking_percentile is None and payload.education.school_tier == "unknown":
            missing.append("school tier or ranking percentile")
        if not payload.career_goal:
            missing.append("career goal")
        if payload.budget_hkd is None:
            missing.append("budget")
        for index, exp in enumerate(payload.experiences):
            if not exp.outcomes:
                missing.append(f"experience #{index + 1} measurable outcome")
        return missing
