from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.services.deterministic_assessment import calculate_profile_assessment
from harbor_agent.models import AssessmentResult, NormalizedProfile
from harbor_agent.runtime.state import AgentState
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class BackgroundGapResult(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    highest_risk: str | None = None


def _assessment(state: AgentState, _: EmptyToolInput) -> AssessmentResult:
    if state.normalized_profile is None:
        raise ValueError("normalize_profile must run first")
    return calculate_profile_assessment(NormalizedProfile.model_validate(state.normalized_profile))


def _background_gap(state: AgentState, _: EmptyToolInput) -> BackgroundGapResult:
    assessment = state.assessment or {}
    gaps = [str(item) for item in assessment.get("weaknesses", [])] + [str(item) for item in assessment.get("risks", [])]
    return BackgroundGapResult(gaps=gaps[:10], highest_risk=gaps[0] if gaps else None)


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("calculate_profile_assessment", "Calculate deterministic academic, language, experience and readiness assessment.", EmptyToolInput, AssessmentResult, _assessment),
        ToolDefinition("detect_background_gap", "Summarize the most important evidence-backed background gaps.", EmptyToolInput, BackgroundGapResult, _background_gap),
    ]
