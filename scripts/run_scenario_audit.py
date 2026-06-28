from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor_agent.services.scenario_audit_runner import ScenarioAuditResult, run_audit


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