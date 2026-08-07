from __future__ import annotations

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class PlanningAgent(BaseAgent):
    name = "PlanningAgent"
    description = "Builds preparation and formally gated application timelines from verified programme data."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    input_state_fields = ("selected_matches", "verified_program_fields")
    output_state_fields = ("timeline", "timeline_ready")
    deterministic_boundaries = ("unverified official deadlines cannot enter a formal timeline",)

    def step(self, state: AgentState) -> AgentDecision:
        results = state.working_memory.get("tool_results", {})
        readiness = results.get("inspect_timeline_readiness")
        if not readiness:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Check the formal timeline gate before generating tasks.",
                tool_calls=[ToolCallRequest(tool_name="inspect_timeline_readiness", arguments={})],
            )
        selected_tool = "build_official_timeline" if readiness.get("ready") else "build_preparation_timeline"
        timeline = results.get(selected_tool)
        if not timeline:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Build the appropriate timeline based on official evidence readiness.",
                tool_calls=[ToolCallRequest(tool_name=selected_tool, arguments={})],
            )
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary="Timeline tasks were generated through the formal-evidence gate.",
            state_patch={"timeline": list(timeline.get("tasks", [])), "timeline_ready": bool(readiness.get("ready"))},
            next_agent="SupervisorAgent",
        )
