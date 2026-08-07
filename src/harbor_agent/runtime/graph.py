from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicEdge:
    source: str
    target: str
    reason: str


# This is a capability graph, not an execution plan. Runtime state and critic
# results choose which valid edge is traversed on each supervisor turn.
DYNAMIC_EDGES = {
    DynamicEdge("SupervisorAgent", "AssessmentAgent", "profile normalization or assessment incomplete"),
    DynamicEdge("SupervisorAgent", "ResearchAgent", "candidate research incomplete"),
    DynamicEdge("SupervisorAgent", "MatchingAgent", "eligibility/fit needs calculation or replan"),
    DynamicEdge("SupervisorAgent", "VerificationAgent", "official field verification incomplete or reverify"),
    DynamicEdge("SupervisorAgent", "PlanningAgent", "application timeline requested"),
    DynamicEdge("SupervisorAgent", "WritingAgent", "writing deliverable requested"),
    DynamicEdge("SupervisorAgent", "CriticAgent", "deliverables need grounded review"),
    DynamicEdge("CriticAgent", "MatchingAgent", "REPLAN_MATCHING"),
    DynamicEdge("CriticAgent", "VerificationAgent", "REVERIFY"),
    DynamicEdge("CriticAgent", "WritingAgent", "REWRITE"),
    DynamicEdge("MatchingAgent", "ResearchAgent", "research can expand after matching"),
    DynamicEdge("VerificationAgent", "VerificationAgent", "multi-program verification loop"),
}


def can_handoff(source: str, target: str) -> bool:
    return any(edge.source == source and edge.target == target for edge in DYNAMIC_EDGES) or target == "SupervisorAgent"
