from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput, ApplicationPlanResult, ProgramPlanResult


BASE_PROFILE = ROOT / "examples" / "sample_profile.json"
TECH_BLOCKED_TERMS = {
    "accounting",
    "business analytics",
    "economics",
    "finance",
    "management",
    "marketing",
    "communication",
}
BA_BLOCKED_TERMS = {"marketing", "economics", "applied accounting", "communication management"}


@dataclass(frozen=True)
class ScenarioCase:
    name: str
    school: str
    tier: str
    gpa: float
    major: str
    interests: list[str]
    raw_interest: str
    ielts: float
    budget_hkd: int = 420000
    expect_strict_intent: bool = False
    expect_no_reach: bool = False
    expected_mix_min: int = 6
    expected_mix_max: int = 10
    blocked_terms: set[str] | None = None


@dataclass
class ScenarioAuditResult:
    case: ScenarioCase
    plan: ProgramPlanResult
    application: ApplicationPlanResult
    failures: list[str]


def _base() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(BASE_PROFILE.read_text(encoding="utf-8"))


def build_payload(case: ScenarioCase) -> ApplicantProfileInput:
    payload = deepcopy(_base())
    payload.education.school = case.school
    payload.education.school_tier = case.tier  # type: ignore[assignment]
    payload.education.gpa = case.gpa
    payload.education.gpa_scale = "100"
    payload.education.ranking_percentile = 20
    payload.education.major = case.major
    payload.language.test = "IELTS"
    payload.language.overall = case.ielts
    payload.language.writing = 6.0 if case.ielts <= 6.5 else 6.5
    payload.language.speaking = 6.0 if case.ielts <= 6.5 else 6.5
    payload.language.reading = case.ielts
    payload.language.listening = case.ielts
    payload.discipline_interests = case.interests
    payload.raw_interest_text = case.raw_interest
    payload.budget_hkd = case.budget_hkd
    return payload


def scenario_cases() -> list[ScenarioCase]:
    return [
        ScenarioCase(
            name="985 CS / IELTS 6.5",
            school="华南理工大学",
            tier="985",
            gpa=85,
            major="计算机科学与技术",
            interests=["computer_science", "artificial_intelligence", "data_science"],
            raw_interest="CS AI machine learning 数据科学 数据结构 算法 数据库 机器学习",
            ielts=6.5,
            expect_strict_intent=True,
            blocked_terms=TECH_BLOCKED_TERMS,
        ),
        ScenarioCase(
            name="211 AI / IELTS 7.0",
            school="西南财经大学",
            tier="211",
            gpa=86,
            major="人工智能",
            interests=["computer_science", "artificial_intelligence", "data_science"],
            raw_interest="计算机 人工智能 数据科学 machine learning deep learning",
            ielts=7.0,
            expect_strict_intent=True,
            blocked_terms=TECH_BLOCKED_TERMS,
        ),
        ScenarioCase(
            name="Regular BA+Data / IELTS 6.5",
            school="广东工业大学",
            tier="regular",
            gpa=82,
            major="金融工程",
            interests=["business analytics", "data_science"],
            raw_interest="business analytics data analytics statistics SQL Python",
            ielts=6.5,
            budget_hkd=330000,
            expect_strict_intent=False,
            expect_no_reach=True,
            blocked_terms=BA_BLOCKED_TERMS,
        ),
    ]


def audit_case(orchestrator: WorkflowOrchestrator, case: ScenarioCase) -> ScenarioAuditResult:
    payload = build_payload(case)
    plan = orchestrator.run_program_plan_stage(payload)
    selected_ids = [item.program.id for item in plan.application_mix[:2]]
    application = orchestrator.run_application_plan_stage(payload, selected_ids)
    failures = _quality_failures(case, plan, application)
    return ScenarioAuditResult(case=case, plan=plan, application=application, failures=failures)


def _quality_failures(
    case: ScenarioCase,
    plan: ProgramPlanResult,
    application: ApplicationPlanResult,
) -> list[str]:
    failures: list[str] = []
    if plan.intent_profile is None:
        failures.append("missing intent profile")
    elif plan.intent_profile.strict_intent is not case.expect_strict_intent:
        failures.append(
            f"strict intent expected {case.expect_strict_intent}, got {plan.intent_profile.strict_intent}"
        )

    if not (case.expected_mix_min <= len(plan.application_mix) <= case.expected_mix_max):
        failures.append(
            f"application mix size expected {case.expected_mix_min}-{case.expected_mix_max}, "
            f"got {len(plan.application_mix)}"
        )
    if not plan.application_mix:
        failures.append("empty application mix")

    if any(item.formal_recommendation for item in plan.application_mix):
        failures.append("unverified catalog produced formal recommendations")
    if application.review.get("passed") is not False:
        failures.append("application review should remain blocked until official fields are verified")

    official_backplan = [
        task
        for task in application.timeline
        if task.date_basis == "官方截止倒推" and task.official_deadline != "NOT_PUBLISHED"
    ]
    if official_backplan:
        failures.append("unverified deadlines produced official back-planning tasks")

    if case.expect_no_reach:
        reach_count = sum(1 for item in plan.application_mix if item.strategy_band == "reach")
        if reach_count:
            failures.append(f"regular-background conservative case has {reach_count} reach items")

    if case.blocked_terms:
        names = " ".join(
            f"{item.program.name} {item.program.name_zh or ''} {' '.join(item.program.discipline_tags)}".lower()
            for item in plan.application_mix[:8]
        )
        bad_terms = sorted(term for term in case.blocked_terms if term in names)
        if bad_terms:
            failures.append(f"off-direction terms in top mix: {', '.join(bad_terms)}")

    if case.expect_strict_intent and any(item.match_category != "core" for item in plan.application_mix):
        failures.append("strict CS/AI/Data case contains non-core application mix items")

    required_trace = [
        "ProfileAgent",
        "EvidenceAgent",
        "EvaluationAgent",
        "ProgramIntelligenceAgent",
        "SchoolMatchingAgent",
    ]
    trace_nodes = [event.node for event in plan.trace]
    if trace_nodes[: len(required_trace)] != required_trace:
        failures.append(f"unexpected plan agent trace: {trace_nodes}")

    return failures


def print_result(result: ScenarioAuditResult) -> None:
    plan = result.plan
    application = result.application
    official_backplan = [
        task
        for task in application.timeline
        if task.date_basis == "官方截止倒推" and task.official_deadline != "NOT_PUBLISHED"
    ]
    print(f"\n=== {result.case.name} ===")
    print(f"profile: {plan.consultant_plan.profile_summary if plan.consultant_plan else ''}")
    print(
        "intent: "
        f"{plan.intent_profile.primary_intents if plan.intent_profile else []}; "
        f"strict={plan.intent_profile.strict_intent if plan.intent_profile else False}"
    )
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
    if result.failures:
        print("quality gate: FAILED")
        for failure in result.failures:
            print(f"  - {failure}")
    else:
        print("quality gate: passed")


def run_audit() -> list[ScenarioAuditResult]:
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    return [audit_case(orchestrator, case) for case in scenario_cases()]


def main() -> int:
    results = run_audit()
    for result in results:
        print_result(result)
    failures = [failure for result in results for failure in result.failures]
    if failures:
        print(f"\nScenario audit failed with {len(failures)} issue(s).")
        return 1
    print("\nScenario audit passed: recommendation, data-trust, and agent-trace gates are stable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())