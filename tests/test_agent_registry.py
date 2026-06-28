from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbor_agent.app import app
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.services.agent_registry import build_agent_system_report, validate_trace


def _sample() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )


def test_agent_system_registry_contracts_are_complete() -> None:
    report = build_agent_system_report()
    agent_names = {agent.agent_name for agent in report.agents}

    assert {check.check_id: check.passed for check in report.checks}
    assert all(check.passed for check in report.checks)
    assert "ProfileAgent" in agent_names
    assert "ProgramIntelligenceAgent" in agent_names
    assert "ProgramDataAcquisitionAgent" in agent_names
    assert "SourceCrawlQueueAgent" in agent_names
    assert "ScenarioAuditAgent" in agent_names
    assert "ProgramResearchAgent" not in agent_names
    assert any(workflow.workflow_name == "assessment" for workflow in report.workflows)
    assert any(workflow.workflow_name == "crawl_queue" for workflow in report.workflows)
    assert any(workflow.workflow_name == "scenario_audit" for workflow in report.workflows)
    assert any("Unverified" in guardrail or "unverified" in guardrail for guardrail in report.deterministic_guardrails)
    assert len(report.human_gates) >= 5


def test_agent_system_api_exposes_contracts() -> None:
    client = TestClient(app)
    response = client.get("/api/agent-system")

    assert response.status_code == 200
    data = response.json()
    assert data["agents"]
    assert data["workflows"]
    assert all(check["passed"] for check in data["checks"])
    assert any(agent["agent_name"] == "ReviewAgent" for agent in data["agents"])
    assert any(agent["agent_name"] == "ScenarioAuditAgent" for agent in data["agents"])


def test_runtime_traces_satisfy_registered_workflow_contracts() -> None:
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    assessment = orchestrator.run_assessment(_sample())
    program_plan = orchestrator.run_program_plan_stage(_sample())
    selected_ids = [item.program.id for item in program_plan.application_mix[:2]]
    application_plan = orchestrator.run_application_plan_stage(_sample(), selected_ids)

    for workflow_name, trace in [
        ("assessment", assessment.trace),
        ("program_plan", program_plan.trace),
        ("application_plan", application_plan.trace),
    ]:
        checks = validate_trace(workflow_name, trace)
        assert all(check.passed for check in checks), [check.model_dump() for check in checks]