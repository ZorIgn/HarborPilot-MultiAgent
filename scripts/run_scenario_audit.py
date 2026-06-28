from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.agents.scenario_audit import ScenarioAuditAgent, ScenarioAuditExpectation
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import (
    AgentStatus,
    AgentTraceEvent,
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
    audit_trace: list[AgentTraceEvent]
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
    audit_report = ScenarioAuditAgent().run(
        ScenarioAuditExpectation(
            name=case.name,
            expect_strict_intent=case.expect_strict_intent,
            expect_no_reach=case.expect_no_reach,
            expected_mix_min=case.expected_mix_min,
            expected_mix_max=case.expected_mix_max,
            blocked_terms=case.blocked_terms or set(),
            target_program_ids=case.target_program_ids,
        ),
        plan=plan,
        application=application,
        crawl_queue=crawl_queue,
        data_acquisition=data_acquisition,
        review_queues=review_queues,
    )
    failures = audit_report.failures
    audit_trace = _build_audit_trace(plan, application, crawl_queue, data_acquisition, audit_report)
    return ScenarioAuditResult(
        case=case,
        plan=plan,
        application=application,
        crawl_queue=crawl_queue,
        data_acquisition=data_acquisition,
        review_queues=review_queues,
        audit_trace=audit_trace,
        failures=failures,
    )



def _build_audit_trace(
    plan: ProgramPlanResult,
    application: ApplicationPlanResult,
    crawl_queue: CrawlQueueReport,
    data_acquisition: DataAcquisitionReport,
    audit_report,
) -> list[AgentTraceEvent]:
    trace: list[AgentTraceEvent] = list(plan.trace)
    trace.append(
        _trace_event(
            "ProgramDataAcquisitionAgent",
            input_summary=f"packages={len(data_acquisition.packages)}",
            output_summary=f"source_plan={len(data_acquisition.source_plan)}; human_review_required=True",
            tool_calls=["data_package_builder", "field_coverage_gate", "community_boundary_gate"],
            needs_human_reason="Official fields require reviewer publication before formal use.",
        )
    )
    trace.append(
        _trace_event(
            "SourceCrawlQueueAgent",
            input_summary=f"selected={crawl_queue.selected_program_ids}",
            output_summary=f"jobs={crawl_queue.job_count}; official={crawl_queue.official_job_count}; community={crawl_queue.community_job_count}",
            tool_calls=["crawl_job_builder", "snapshot_policy_gate", "community_boundary_gate"],
            needs_human_reason="Crawler jobs only create review candidates.",
        )
    )
    review_event = next((event for event in reversed(application.trace) if event.node == "ReviewAgent"), None)
    if review_event:
        trace.append(review_event)
    else:
        trace.append(
            _trace_event(
                "ReviewAgent",
                input_summary="application plan",
                output_summary=str(application.review.get("passed")),
                tool_calls=["official_field_gate", "timeline_gate"],
                needs_human_reason="Application review was not present in trace.",
            )
        )
    trace.append(
        _trace_event(
            "ScenarioAuditAgent",
            input_summary=audit_report.scenario_name,
            output_summary="passed" if audit_report.passed else f"failures={len(audit_report.failures)}",
            tool_calls=["scenario_matrix", "target_program_drilldown", "data_trust_gate", "agent_trace_gate"],
            needs_human_reason=None if audit_report.passed else "Scenario audit found quality failures.",
        )
    )
    return trace


def _trace_event(
    node: str,
    input_summary: str,
    output_summary: str,
    tool_calls: list[str],
    needs_human_reason: str | None = None,
) -> AgentTraceEvent:
    now = datetime.now(UTC)
    return AgentTraceEvent(
        node=node,
        status=AgentStatus.needs_human if needs_human_reason else AgentStatus.completed,
        started_at=now,
        finished_at=now,
        input_summary=input_summary,
        output_summary=output_summary,
        tool_calls=tool_calls,
        needs_human_reason=needs_human_reason,
    )

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
    print("agents: " + " -> ".join(event.node for event in result.audit_trace))
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