from __future__ import annotations

from copy import deepcopy

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class ResearchAgent(BaseAgent):
    name = "ResearchAgent"
    description = "Recalls catalogue programmes and creates a bounded official-source research plan for Verification."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    input_state_fields = ("normalized_profile", "assessment", "candidate_program_ids")
    output_state_fields = ("candidate_program_ids", "researched_program_ids", "working_memory")
    deterministic_boundaries = ("catalogue search is deterministic", "does not claim official facts without evidence")

    def step(self, state: AgentState) -> AgentDecision:
        results = state.working_memory.get("tool_results", {})
        catalogue = results.get("search_program_catalog")
        if not catalogue:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Search the programme catalogue for the normalized applicant profile.",
                tool_calls=[ToolCallRequest(tool_name="search_program_catalog", arguments={})],
            )
        source_plan = results.get("build_source_research_plan")
        if not source_plan:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="The catalogue candidates are ready; build a bounded official-source plan before handoff.",
                tool_calls=[ToolCallRequest(tool_name="build_source_research_plan", arguments={})],
            )
        memory = deepcopy(state.working_memory)
        memory["candidate_programs"] = catalogue.get("programs", [])
        memory["source_research_plan"] = source_plan
        ids = list(catalogue.get("program_ids", []))
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary=f"Research recalled {len(ids)} catalogue candidates and prepared a bounded official-source plan for Verification.",
            state_patch={"candidate_program_ids": ids, "researched_program_ids": ids, "working_memory": memory},
            next_agent="SupervisorAgent",
        )
