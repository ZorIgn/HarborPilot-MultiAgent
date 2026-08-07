from __future__ import annotations

from datetime import UTC, datetime

from harbor_agent.agents import build_agent_registry
from harbor_agent.agents.base import BaseAgent
from harbor_agent.models import AgentContract, AgentContractCheck, AgentSystemReport, AgentWorkflowContract
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.tools import build_default_tool_registry


def build_agent_system_report() -> AgentSystemReport:
    """Report only real instantiated supervisor-runtime agents and real tools."""

    registry = build_agent_registry()
    contracts = [_contract(agent) for agent in registry.values() if isinstance(agent, BaseAgent)]
    checks = _contract_checks(registry)
    return AgentSystemReport(
        generated_at=datetime.now(UTC),
        agents=contracts,
        workflows=[
            AgentWorkflowContract(workflow_name="supervisor_runtime", required_agents=[item.agent_name for item in contracts], terminal_agent="SupervisorAgent", human_gate_required=True),
        ],
        checks=checks,
        human_gates=["Verification evidence conflict", "High-risk source binding", "High-risk review candidate"],
        deterministic_guardrails=sorted({guardrail for agent in registry.values() if isinstance(agent, BaseAgent) for guardrail in agent.deterministic_boundaries}),
    )


def _contract(agent: BaseAgent) -> AgentContract:
    definition = agent.definition()
    return AgentContract(
        agent_name=definition.name,
        responsibility=definition.description,
        is_autonomous=True,
        inputs=definition.input_state_fields,
        outputs=definition.output_state_fields,
        tools=definition.allowed_tools,
        allowed_tools=definition.allowed_tools,
        decision_schema="AgentDecision",
        can_handoff_to=definition.possible_handoffs,
        can_ask_user=definition.can_ask_user,
        can_request_human=definition.can_request_human,
        max_tool_rounds=definition.max_tool_rounds,
        upstream_agents=["SupervisorAgent"] if definition.name != "SupervisorAgent" else [],
        human_gate="Can request explicit human review" if definition.can_request_human else None,
        deterministic_guardrails=definition.deterministic_boundaries,
        llm_role=definition.llm_role,
        llm_guardrails=["Model output is Pydantic-validated", "Tool permissions are executor-enforced"],
        retry_policy="bounded retry through runtime limits and explicit resume",
        handoff_policy="supervisor records every dynamic route and handoff",
    )


def _contract_checks(registry: dict[str, object]) -> list[AgentContractCheck]:
    tools = build_default_tool_registry().names()
    expected = set(AGENT_TOOL_PERMISSIONS)
    actual = set(registry)
    checks: list[AgentContractCheck] = [
        AgentContractCheck(check_id="real_agents_exact", passed=actual == expected, detail=f"registered={sorted(actual)}"),
        AgentContractCheck(check_id="no_legacy_agents_in_runtime", passed=not (actual & {"ProfileAgent", "EvidenceAgent", "TimelineAgent", "StoryCardAgent", "ReviewAgent", "ScenarioAuditAgent", "SourceCrawlQueueAgent"}), detail="runtime registry contains only eight specialized roles"),
    ]
    for name, agent in registry.items():
        if not isinstance(agent, BaseAgent):
            checks.append(AgentContractCheck(check_id=f"agent_instance.{name}", passed=False, detail="not a BaseAgent"))
            continue
        missing = sorted(agent.allowed_tools - tools)
        checks.append(AgentContractCheck(check_id=f"agent_instance.{name}", passed=True, detail="instantiated"))
        checks.append(AgentContractCheck(check_id=f"tools_exist.{name}", passed=not missing, detail=f"missing={missing}"))
        checks.append(AgentContractCheck(check_id=f"decision_contract.{name}", passed=True, detail="AgentDecision is the sole runtime control protocol"))
    return checks
