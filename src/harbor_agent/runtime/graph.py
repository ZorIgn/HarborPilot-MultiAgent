from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicEdge:
    source: str
    target: str
    reason: str


SUPERVISOR_AGENT = "SupervisorAgent"

# These are the only non-supervisor roles in the runtime graph.  Keeping the
# names here (rather than importing the agent registry) avoids a circular
# import while making the execution boundary explicit and inspectable.
SPECIALIST_AGENTS = frozenset(
    {
        "AssessmentAgent",
        "ResearchAgent",
        "MatchingAgent",
        "VerificationAgent",
        "PlanningAgent",
        "WritingAgent",
        "CriticAgent",
    }
)


def _build_execution_edges() -> set[DynamicEdge]:
    """Return the only runtime transitions that may cross agent turns.

    Every specialist turn returns control to the Supervisor.  A later
    Supervisor turn may select another specialist.  In particular, critic
    outcomes such as ``REPLAN_MATCHING``, ``REVERIFY`` and ``REWRITE`` are
    route *signals* consumed by the Supervisor; they are not peer handoffs.
    The graph intentionally contains no specialist-to-specialist edge and no
    specialist self-loop.
    """

    supervisor_routes = {
        DynamicEdge(SUPERVISOR_AGENT, target, reason)
        for target, reason in {
            "AssessmentAgent": "profile normalization or assessment incomplete",
            "ResearchAgent": "candidate recall or bounded source plan incomplete",
            "MatchingAgent": "eligibility/fit needs calculation or replan",
            "VerificationAgent": "official field verification incomplete or reverify",
            "PlanningAgent": "application timeline requested",
            "WritingAgent": "writing deliverable requested",
            "CriticAgent": "deliverables need grounded review",
        }.items()
    }
    specialist_returns = {
        DynamicEdge(
            source,
            SUPERVISOR_AGENT,
            "specialist completed its bounded turn; Supervisor evaluates the next route",
        )
        for source in SPECIALIST_AGENTS
    }
    return supervisor_routes | specialist_returns


# This is an execution-capability graph, not a fixed DAG.  Runtime state and
# specialist results choose which Supervisor route is traversed on each turn.
DYNAMIC_EDGES = _build_execution_edges()


def can_handoff(source: str, target: str) -> bool:
    """Return whether a typed handoff is legal at the executor boundary.

    Specialists may only return to the Supervisor.  Only the Supervisor may
    choose a specialist target.  For compatibility with small test or plugin
    agents that are not listed in this module, an unknown non-supervisor source
    may still return to ``SupervisorAgent``; that fallback is safe because it
    cannot bypass supervisory routing.  Unknown sources may never select a
    specialist target.
    """

    if target == SUPERVISOR_AGENT and source != SUPERVISOR_AGENT:
        return True
    return any(edge.source == source and edge.target == target for edge in DYNAMIC_EDGES)

def is_specialist(agent_name: str) -> bool:
    """Return whether a name is a registered non-supervisor runtime role."""

    return agent_name in SPECIALIST_AGENTS


def can_terminate(agent_name: str) -> bool:
    """Only the Supervisor owns the workflow terminal transition."""

    return agent_name == SUPERVISOR_AGENT
