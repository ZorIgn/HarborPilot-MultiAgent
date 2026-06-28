from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import (
    ApplicantProfileInput,
    ApplicationPlanResult,
    DataAcquisitionReport,
    DataAcquisitionRequest,
    CrawlQueueReport,
    CrawlQueueRequest,
    ProgramPlanResult,
    ReviewQueueSummary,
)
from harbor_agent.services.review_gate import build_review_queue


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
    target_program_ids: tuple[str, ...] = ()


@dataclass
class ScenarioAuditResult:
    case: ScenarioCase
    plan: ProgramPlanResult
    application: ApplicationPlanResult
    crawl_queue: CrawlQueueReport
    data_acquisition: DataAcquisitionReport
    review_queues: dict[str, ReviewQueueSummary]
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
            target_program_ids=(
                "nus-msc-data-science-and-machine-learning-2027",
                "ntu-msc-artificial-intelligence-2027",
                "hku-master-of-science-in-computer-science-2027",
            ),
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
            target_program_ids=(
                "nus-msc-data-science-and-machine-learning-2027",
                "ntu-msc-artificial-intelligence-2027",
                "hku-master-of-science-in-computer-science-2027",
            ),
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
            target_program_ids=(
                "cityu-msc-business-and-data-analytics-2027",
                "polyu-msc-business-analytics-2027",
                "smu-master-of-it-in-business-2027",
            ),
        ),
    ]


def audit_case(orchestrator: WorkflowOrchestrator, case: ScenarioCase) -> ScenarioAuditResult:
    payload = build_payload(case)
    plan = orchestrator.run_program_plan_stage(payload)
    selected_ids = [item.program.id for item in plan.application_mix[:2]]
    application = orchestrator.run_application_plan_stage(payload, selected_ids)
    crawl_queue = orchestrator.run_crawl_queue_stage(
        CrawlQueueRequest(selected_program_ids=selected_ids, include_community=True, max_sources_per_program=8)
    )
    target_ids = list(case.target_program_ids)
    data_acquisition = orchestrator.run_data_acquisition_stage(
        DataAcquisitionRequest(
            selected_program_ids=target_ids,
            include_community=True,
            dry_run=True,
            max_sources_per_program=8,
        )
    )
    review_queues = {program_id: build_review_queue(program_id=program_id, limit=20) for program_id in target_ids}
    failures = _quality_failures(case, plan, application, crawl_queue, data_acquisition, review_queues)
    return ScenarioAuditResult(
        case=case,
        plan=plan,
        application=application,
        crawl_queue=crawl_queue,
        data_acquisition=data_acquisition,
        review_queues=review_queues,
        failures=failures,
    )


def _quality_failures(
    case: ScenarioCase,
    plan: ProgramPlanResult,
    application: ApplicationPlanResult,
    crawl_queue: CrawlQueueReport,
    data_acquisition: DataAcquisitionReport,
    review_queues: dict[str, ReviewQueueSummary],
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

    _target_program_failures(case, plan, data_acquisition, review_queues, failures)

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

    if crawl_queue.job_count == 0:
        failures.append("crawl queue is empty for selected programs")
    if crawl_queue.official_job_count == 0:
        failures.append("crawl queue has no official-source jobs")
    if crawl_queue.community_job_count == 0:
        failures.append("crawl queue has no community-reference jobs")
    if not all(item.snapshot_required and item.human_review_required for item in crawl_queue.items):
        failures.append("crawl queue contains jobs without snapshot or human-review gates")

    official_only = {"deadline", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"}
    community_leaks = [
        item.source_id
        for item in crawl_queue.items
        if item.trust_level == "community" and official_only & set(item.allowed_fields)
    ]
    if community_leaks:
        failures.append(f"community crawl jobs can emit official fields: {community_leaks}")

    if "SourceCrawlQueueAgent" not in crawl_queue.agent_chain:
        failures.append(f"crawl queue agent chain missing SourceCrawlQueueAgent: {crawl_queue.agent_chain}")

    return failures


def _target_program_failures(
    case: ScenarioCase,
    plan: ProgramPlanResult,
    data_acquisition: DataAcquisitionReport,
    review_queues: dict[str, ReviewQueueSummary],
    failures: list[str],
) -> None:
    if not case.target_program_ids:
        failures.append("scenario has no target program drilldown ids")
        return

    by_program_id = {item.program.id: item for item in plan.recommendations}
    package_by_id = {package.program_id: package for package in data_acquisition.packages}
    official_fields = {"deadline", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"}

    for program_id in case.target_program_ids:
        match = by_program_id.get(program_id)
        if match is None:
            failures.append(f"target program missing from recommendations: {program_id}")
            continue
        if match.formal_recommendation:
            failures.append(f"target program became formal without verified data: {program_id}")
        if not match.reasons or not match.risks or not match.actions:
            failures.append(f"target program lacks reasons/risks/actions: {program_id}")
        if not match.source_warning:
            failures.append(f"target program lacks source warning: {program_id}")
        if match.program.source.field_coverage == "complete" and match.program.data_status.value != "VERIFIED":
            failures.append(f"target program claims complete coverage without VERIFIED status: {program_id}")
        if case.expect_strict_intent and match.match_category != "core":
            failures.append(f"strict-intent target is not core: {program_id} -> {match.match_category}")

        package = package_by_id.get(program_id)
        if package is None:
            failures.append(f"missing data package for target program: {program_id}")
            continue
        if package.production_ready:
            failures.append(f"unreviewed target package is production_ready: {program_id}")
        if not package.human_review_required:
            failures.append(f"target package does not require human review: {program_id}")
        coverage_fields = {item.field_name for item in package.coverage_items}
        missing_fields = sorted(official_fields - coverage_fields)
        if missing_fields:
            failures.append(f"target package missing coverage fields for {program_id}: {missing_fields}")
        if any(not item.blocks_formal_use for item in package.coverage_items if item.field_name in official_fields):
            failures.append(f"target package allows formal use before official verification: {program_id}")
        if not any(plan.trust_level == "official" for plan in package.acquisition_plan):
            failures.append(f"target package lacks official acquisition source: {program_id}")
        if not any(plan.trust_level == "community" for plan in package.acquisition_plan):
            failures.append(f"target package lacks public community/reference source: {program_id}")
        for plan_item in package.acquisition_plan:
            if plan_item.trust_level == "community" and official_fields & set(plan_item.allowed_fields):
                failures.append(f"target community acquisition leaks official fields: {program_id}/{plan_item.source_id}")

        queue = review_queues.get(program_id)
        if queue is None:
            failures.append(f"missing review queue for target program: {program_id}")
            continue
        if queue.pending_count == 0:
            failures.append(f"review queue is empty for target program: {program_id}")
        for item in queue.items:
            if item.publishable:
                if not item.source_type.startswith("official"):
                    failures.append(f"publishable review item is not official: {program_id}/{item.field_name}")
                if not item.source_url or not item.evidence_snippet or not item.page_hash:
                    failures.append(f"publishable review item lacks source/snippet/hash: {program_id}/{item.field_name}")


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
    print(
        "crawl_queue: "
        f"jobs={result.crawl_queue.job_count}; "
        f"official={result.crawl_queue.official_job_count}; "
        f"community={result.crawl_queue.community_job_count}"
    )
    package_by_id = {package.program_id: package for package in result.data_acquisition.packages}
    for program_id in result.case.target_program_ids:
        match = next((item for item in plan.recommendations if item.program.id == program_id), None)
        package = package_by_id.get(program_id)
        queue = result.review_queues.get(program_id)
        print(
            "target: "
            f"{program_id}; "
            f"fit={match.fit_score if match else 'missing'}; "
            f"category={match.match_category if match else 'missing'}; "
            f"formal={match.formal_recommendation if match else 'missing'}; "
            f"coverage={len(package.coverage_items) if package else 0}; "
            f"review_pending={queue.pending_count if queue else 'missing'}; "
            f"publishable={queue.publishable_count if queue else 'missing'}"
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