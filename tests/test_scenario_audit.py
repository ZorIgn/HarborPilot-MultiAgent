from __future__ import annotations

from scripts.run_scenario_audit import run_audit


def test_scenario_audit_quality_gates_pass() -> None:
    results = run_audit()
    assert results
    failures = [failure for result in results for failure in result.failures]
    assert failures == []
    assert all(result.plan.application_mix for result in results)
    assert all(result.application.review["passed"] is False for result in results)
    assert all(result.case.target_program_ids for result in results)
    for result in results:
        recommendation_ids = {item.program.id for item in result.plan.recommendations}
        package_ids = {package.program_id for package in result.data_acquisition.packages}
        for program_id in result.case.target_program_ids:
            assert program_id in recommendation_ids
            assert program_id in package_ids
            assert result.review_queues[program_id].pending_count >= 1
