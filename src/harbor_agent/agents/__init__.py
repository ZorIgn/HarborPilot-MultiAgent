"""The eight real HarborPilot multi-agent runtime roles."""

from __future__ import annotations

from harbor_agent.agents.assessment import AssessmentAgent
from harbor_agent.agents.critic import CriticAgent
from harbor_agent.agents.matching_agent import MatchingAgent
from harbor_agent.agents.planning import PlanningAgent
from harbor_agent.agents.research import ResearchAgent
from harbor_agent.agents.supervisor import SupervisorAgent
from harbor_agent.agents.verification import VerificationAgent
from harbor_agent.agents.writing_agent import WritingWorkflowAgent
from harbor_agent.llm.provider import RuntimeLLMProvider


def build_agent_registry(*, llm: RuntimeLLMProvider | None = None, model_driven: bool = False) -> dict[str, object]:
    """Instantiate every real agent; names in traces always exist here."""

    return {
        "SupervisorAgent": SupervisorAgent(llm=llm, model_driven=model_driven),
        "AssessmentAgent": AssessmentAgent(llm=llm, model_driven=model_driven),
        "ResearchAgent": ResearchAgent(llm=llm, model_driven=model_driven),
        "MatchingAgent": MatchingAgent(llm=llm, model_driven=model_driven),
        "VerificationAgent": VerificationAgent(llm=llm, model_driven=model_driven),
        "PlanningAgent": PlanningAgent(llm=llm, model_driven=model_driven),
        "WritingAgent": WritingWorkflowAgent(llm=llm, model_driven=model_driven),
        "CriticAgent": CriticAgent(llm=llm, model_driven=model_driven),
    }


__all__ = [
    "AssessmentAgent",
    "CriticAgent",
    "MatchingAgent",
    "PlanningAgent",
    "ResearchAgent",
    "SupervisorAgent",
    "VerificationAgent",
    "WritingWorkflowAgent",
    "build_agent_registry",
]
