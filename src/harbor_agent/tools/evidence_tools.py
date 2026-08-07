from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.models import EvidenceReview
from harbor_agent.runtime.state import AgentState
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class EvidenceCountResult(BaseModel):
    verified_fact_ratio: int = Field(ge=0, le=100)
    pending_confirmations: list[str] = Field(default_factory=list)


class EvidenceListResult(BaseModel):
    required_evidence: list[str] = Field(default_factory=list)


class EvidenceConflictResult(BaseModel):
    conflicts: list[str] = Field(default_factory=list)


def _review(state: AgentState) -> EvidenceReview:
    if state.evidence_review is None:
        raise ValueError("inspect_evidence_readiness must run first")
    return EvidenceReview.model_validate(state.evidence_review)


def _count(state: AgentState, _: EmptyToolInput) -> EvidenceCountResult:
    review = _review(state)
    return EvidenceCountResult(verified_fact_ratio=review.verified_fact_ratio, pending_confirmations=review.pending_confirmations)


def _required(state: AgentState, _: EmptyToolInput) -> EvidenceListResult:
    return EvidenceListResult(required_evidence=_review(state).recommended_uploads)


def _conflicts(state: AgentState, _: EmptyToolInput) -> EvidenceConflictResult:
    return EvidenceConflictResult(conflicts=_review(state).conflicts)


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("count_verified_facts", "Count evidence-confirmed facts in the current profile.", EmptyToolInput, EvidenceCountResult, _count),
        ToolDefinition("list_required_evidence", "List documents and facts the student should confirm or upload.", EmptyToolInput, EvidenceListResult, _required),
        ToolDefinition("detect_fact_conflicts", "Return known profile evidence conflicts.", EmptyToolInput, EvidenceConflictResult, _conflicts),
    ]
