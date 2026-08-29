from __future__ import annotations

import pytest

from harbor_agent.agents import build_agent_registry
from harbor_agent.runtime.errors import AgentDecisionValidationError
from harbor_agent.runtime.executor import AgentExecutor
from harbor_agent.runtime.graph import (
    DYNAMIC_EDGES,
    SPECIALIST_AGENTS,
    SUPERVISOR_AGENT,
    can_handoff,
    can_terminate,
)


def test_execution_graph_has_only_supervisor_routes_or_specialist_returns() -> None:
    """The graph must expose Supervisor-mediated execution, never peer handoff."""

    assert DYNAMIC_EDGES
    assert all(
        edge.source == SUPERVISOR_AGENT or edge.target == SUPERVISOR_AGENT
        for edge in DYNAMIC_EDGES
    )
    assert not any(
        edge.source in SPECIALIST_AGENTS and edge.target in SPECIALIST_AGENTS
        for edge in DYNAMIC_EDGES
    )
    assert not any(edge.source == edge.target for edge in DYNAMIC_EDGES)

    for specialist in SPECIALIST_AGENTS:
        assert can_handoff(specialist, SUPERVISOR_AGENT)
        for other_specialist in SPECIALIST_AGENTS:
            assert not can_handoff(specialist, other_specialist)

    for specialist in SPECIALIST_AGENTS:
        assert can_handoff(SUPERVISOR_AGENT, specialist)
    assert not can_handoff(SUPERVISOR_AGENT, SUPERVISOR_AGENT)
    assert can_terminate(SUPERVISOR_AGENT)
    assert all(not can_terminate(name) for name in SPECIALIST_AGENTS)


def test_executor_rejects_specialist_peer_handoff_even_if_called_directly() -> None:
    """The compatibility validation API cannot bypass the Supervisor."""

    registry = build_agent_registry()
    critic = registry["CriticAgent"]

    with pytest.raises(AgentDecisionValidationError, match="cannot hand off|not registered"):
        AgentExecutor._validate_handoff(critic, "MatchingAgent")

    # The actual specialist return path remains legal.
    AgentExecutor._validate_handoff(critic, SUPERVISOR_AGENT)
