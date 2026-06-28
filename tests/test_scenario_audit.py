from __future__ import annotations

from scripts.run_scenario_audit import run_audit


def test_scenario_audit_quality_gates_pass() -> None:
    results = run_audit()
    assert results
    failures = [failure for result in results for failure in result.failures]
    assert failures == []
    assert all(result.plan.application_mix for result in results)
    assert all(result.application.review["passed"] is False for result in results)