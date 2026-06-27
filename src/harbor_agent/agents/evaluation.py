from __future__ import annotations

from harbor_agent.core.llm import LLMProvider
from harbor_agent.core.rules import evaluate_general_profile
from harbor_agent.models import AssessmentResult, NormalizedProfile


class EvaluationAgent:
    name = "EvaluationAgent"

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, profile: NormalizedProfile) -> AssessmentResult:
        result = evaluate_general_profile(profile)
        # Keep the deterministic score as source of truth; the LLM only sharpens explanation text.
        if self.llm.name != "mock":
            completion = self.llm.complete_json(
                system=(
                    "You are an admissions evaluation agent. You may explain but must not invent "
                    "requirements, probabilities, or facts."
                ),
                user=result.model_dump_json(),
                schema_hint={"strengths": ["string"], "weaknesses": ["string"], "actions": ["string"]},
            )
            result.strengths = completion.get("strengths", result.strengths)[:5]
            result.weaknesses = completion.get("weaknesses", result.weaknesses)[:5]
            result.actions = completion.get("actions", result.actions)[:5]
        return result

