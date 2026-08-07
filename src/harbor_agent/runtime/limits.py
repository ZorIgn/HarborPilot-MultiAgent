from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.runtime.errors import WorkflowLimitExceeded
from harbor_agent.runtime.state import AgentState, apply_state_patch


class RuntimeLimits(BaseModel):
    """Hard caps that prevent a routing or tool-call loop from running forever."""

    max_workflow_steps: int = Field(default=40, ge=1)
    max_agent_turns_per_agent: int = Field(default=8, ge=1)
    max_tool_rounds_per_agent_turn: int = Field(default=6, ge=1)
    max_total_tool_calls: int = Field(default=80, ge=1)
    max_tool_retries: int = Field(default=3, ge=0)
    max_supervisor_replans: int = Field(default=8, ge=0)


def enforce_workflow_limits(state: AgentState, limits: RuntimeLimits) -> None:
    if state.step_count >= min(state.max_steps, limits.max_workflow_steps):
        raise WorkflowLimitExceeded("maximum workflow steps reached")
    if state.tool_call_count > limits.max_total_tool_calls:
        raise WorkflowLimitExceeded("maximum total tool calls reached")
    if state.supervisor_replans > limits.max_supervisor_replans:
        raise WorkflowLimitExceeded("maximum supervisor replans reached")


def record_agent_turn(state: AgentState, agent_name: str, limits: RuntimeLimits) -> AgentState:
    turns = dict(state.agent_turn_counts)
    turns[agent_name] = turns.get(agent_name, 0) + 1
    if turns[agent_name] > limits.max_agent_turns_per_agent:
        raise WorkflowLimitExceeded(f"{agent_name} exceeded maximum turns")
    return apply_state_patch(
        state,
        {
            "agent_turn_counts": turns,
            "step_count": state.step_count + 1,
            "previous_agent": state.current_agent,
            "current_agent": agent_name,
            "visited_agents": [*state.visited_agents, agent_name],
        },
    )
