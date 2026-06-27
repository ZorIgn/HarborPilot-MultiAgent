from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput


BASE_PROFILE = Path("examples/sample_profile.json")


def _base() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(BASE_PROFILE.read_text(encoding="utf-8"))


def _case(
    name: str,
    school: str,
    tier: str,
    gpa: float,
    major: str,
    interests: list[str],
    raw_interest: str,
    ielts: float,
    budget_hkd: int = 420000,
) -> tuple[str, ApplicantProfileInput]:
    payload = deepcopy(_base())
    payload.education.school = school
    payload.education.school_tier = tier  # type: ignore[assignment]
    payload.education.gpa = gpa
    payload.education.gpa_scale = "100"
    payload.education.ranking_percentile = 20
    payload.education.major = major
    payload.language.test = "IELTS"
    payload.language.overall = ielts
    payload.language.writing = 6.0 if ielts <= 6.5 else 6.5
    payload.language.speaking = 6.0 if ielts <= 6.5 else 6.5
    payload.language.reading = ielts
    payload.language.listening = ielts
    payload.discipline_interests = interests
    payload.raw_interest_text = raw_interest
    payload.budget_hkd = budget_hkd
    return name, payload


def main() -> None:
    cases = [
        _case(
            "985 CS / IELTS 6.5",
            "华南理工大学",
            "985",
            85,
            "计算机科学与技术",
            ["computer_science", "artificial_intelligence", "data_science"],
            "CS AI machine learning 数据科学 数据结构 算法 数据库 机器学习",
            6.5,
        ),
        _case(
            "211 AI / IELTS 7.0",
            "西南财经大学",
            "211",
            86,
            "人工智能",
            ["computer_science", "artificial_intelligence", "data_science"],
            "计算机 人工智能 数据科学 machine learning deep learning",
            7.0,
        ),
        _case(
            "Regular BA+Data / IELTS 6.5",
            "广东工业大学",
            "regular",
            82,
            "金融工程",
            ["business analytics", "data_science"],
            "business analytics data analytics statistics SQL Python",
            6.5,
            330000,
        ),
    ]

    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    for name, payload in cases:
        plan = orchestrator.run_program_plan_stage(payload)
        selected_ids = [item.program.id for item in plan.application_mix[:2]]
        application = orchestrator.run_application_plan_stage(payload, selected_ids)
        official_backplan = [
            task
            for task in application.timeline
            if task.date_basis == "官方截止倒推" and task.official_deadline != "NOT_PUBLISHED"
        ]
        print(f"\n=== {name} ===")
        print(f"profile: {plan.consultant_plan.profile_summary if plan.consultant_plan else ''}")
        print(f"intent: {plan.intent_profile.primary_intents if plan.intent_profile else []}; strict={plan.intent_profile.strict_intent if plan.intent_profile else False}")
        print(f"assessment: {plan.assessment.overall_level}; {plan.assessment.dimension_scores}")
        print(f"bands: {plan.consultant_plan.band_counts if plan.consultant_plan else {}}")
        for item in plan.application_mix:
            print(
                "- "
                f"{item.strategy_band}/{item.match_category} "
                f"score={item.fit_score} "
                f"formal={item.formal_recommendation} "
                f"{item.program.institution_zh or item.program.institution} "
                f"{item.program.name_zh or item.program.name}"
            )
        print(
            "timeline: "
            f"tasks={len(application.timeline)}; "
            f"official_backplan={len(official_backplan)}; "
            f"review_passed={application.review.get('passed')}"
        )
        print("agents: " + " -> ".join(event.node for event in plan.trace))


if __name__ == "__main__":
    main()