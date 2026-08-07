from __future__ import annotations

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from harbor_agent.app import app
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.runtime.state import WorkflowGoal
from harbor_agent.services.agent_registry import build_agent_system_report


def _sample() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )


def test_workflow_orchestrator_is_runtime_only_compatibility_facade() -> None:
    class RuntimeStub:
        def __init__(self) -> None:
            self.requests = []

        def start(self, request):
            self.requests.append(request)
            return sentinel

    sentinel = object()
    runtime = RuntimeStub()
    payload = _sample()
    orchestrator = WorkflowOrchestrator(MockLLMProvider(), runtime=runtime)

    result = orchestrator._start(
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        payload=payload,
        user_request="compatibility test",
        selected_program_ids=["program-a"],
    )

    assert result is sentinel
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.goal == WorkflowGoal.PROGRAM_RECOMMENDATION
    assert request.profile == payload.model_dump(mode="json")
    assert request.selected_program_ids == ["program-a"]
    assert not hasattr(orchestrator, "run_data_acquisition_stage")
    assert not hasattr(orchestrator, "run_crawl_queue_stage")

    source = inspect.getsource(WorkflowOrchestrator)
    assert "MultiAgentRuntime" in source
    for legacy_symbol in (
        "ProfileAgent",
        "EvidenceAgent",
        "EvaluationAgent",
        "ProgramIntelligenceAgent",
        "SchoolMatchingAgent",
        "TimelineAgent",
        "WritingAgent",
        "StoryCardAgent",
        "ReviewAgent",
    ):
        assert legacy_symbol not in source
def test_agent_system_registry_contracts_are_runtime_backed() -> None:
    report = build_agent_system_report()
    agent_names = {agent.agent_name for agent in report.agents}
    expected_agents = {
        "SupervisorAgent",
        "AssessmentAgent",
        "ResearchAgent",
        "MatchingAgent",
        "VerificationAgent",
        "PlanningAgent",
        "WritingAgent",
        "CriticAgent",
    }
    legacy_agents = {
        "ProfileAgent",
        "EvidenceAgent",
        "TimelineAgent",
        "StoryCardAgent",
        "ReviewAgent",
        "ScenarioAuditAgent",
        "SourceCrawlQueueAgent",
        "ProgramDataAcquisitionAgent",
    }

    assert agent_names == expected_agents
    assert not (agent_names & legacy_agents)
    assert all(check.passed for check in report.checks)
    assert [workflow.workflow_name for workflow in report.workflows] == ["supervisor_runtime"]
    runtime_workflow = report.workflows[0]
    assert set(runtime_workflow.required_agents) == expected_agents
    assert runtime_workflow.terminal_agent == "SupervisorAgent"
def test_agent_system_api_exposes_contracts() -> None:
    client = TestClient(app)
    response = client.get("/api/agent-system")

    assert response.status_code == 200
    data = response.json()
    assert data["agents"]
    assert data["workflows"]
    assert all(check["passed"] for check in data["checks"])
    assert any(agent["agent_name"] == "SupervisorAgent" for agent in data["agents"])
    assert any(agent["agent_name"] == "CriticAgent" for agent in data["agents"])
    assert not any(agent["agent_name"] == "ReviewAgent" for agent in data["agents"])


def test_runtime_traces_expose_dynamic_runtime_contracts() -> None:
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    assessment = orchestrator.run_assessment(_sample())
    program_plan = orchestrator.run_program_plan_stage(_sample())
    selected_ids = [item.program.id for item in program_plan.application_mix[:2]]
    application_plan = orchestrator.run_application_plan_stage(_sample(), selected_ids)

    expected_by_workflow = {
        "assessment": {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "PlanningAgent", "WritingAgent", "CriticAgent"},
        "program_plan": {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "CriticAgent"},
        "application_plan": {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "PlanningAgent", "CriticAgent"},
    }
    runtime_agents = {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "PlanningAgent", "WritingAgent", "CriticAgent"}
    for workflow_name, trace in [
        ("assessment", assessment.trace),
        ("program_plan", program_plan.trace),
        ("application_plan", application_plan.trace),
    ]:
        nodes = {event.node for event in trace}
        assert expected_by_workflow[workflow_name] <= nodes
        assert nodes <= runtime_agents
        assert all(event.tool_calls for event in trace)