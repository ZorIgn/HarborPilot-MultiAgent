from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.runtime.state import AgentState
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.formal_gate import program_field_gate
from harbor_agent.services.data_loader import load_programs
from harbor_agent.tools.base import ToolDefinition


class ProgramTrustInput(BaseModel):
    program_id: str


class ProgramTrustResult(BaseModel):
    program_id: str
    trust: dict = Field(default_factory=dict)


class MissingOfficialFields(BaseModel):
    program_id: str
    missing_fields: list[str] = Field(default_factory=list)
    formal_use_ready: bool = False


class EvidenceComparison(BaseModel):
    consistent: bool
    conflicts: list[dict] = Field(default_factory=list)
    preferred_record_id: str | None = None
    human_review_required: bool = False


class ReviewCandidate(BaseModel):
    program_id: str
    field_name: str
    proposed_value: str | None = None
    reason: str


def _program(program_id: str):
    item = next((program for program in load_programs() if program.id == program_id), None)
    if item is None:
        raise ValueError(f"unknown program_id: {program_id}")
    return item


def _trust(_: AgentState, args: ProgramTrustInput) -> ProgramTrustResult:
    return ProgramTrustResult(program_id=args.program_id, trust=build_program_trust_detail(_program(args.program_id)).model_dump(mode="json"))


def _missing(_: AgentState, args: ProgramTrustInput) -> MissingOfficialFields:
    gate = program_field_gate(_program(args.program_id))
    return MissingOfficialFields(program_id=args.program_id, missing_fields=list(gate["missing_or_blocked_fields"]), formal_use_ready=bool(gate["production_ready"]))


def _compare(state: AgentState, args: ProgramTrustInput) -> EvidenceComparison:
    trust = build_program_trust_detail(_program(args.program_id))
    conflicts = [record.model_dump(mode="json") for record in trust.field_records if str(record.status.value) == "CONFLICTED"]
    state_conflicts = [item for item in state.verification_conflicts if item.get("program_id") == args.program_id]
    conflicts.extend(state_conflicts)
    return EvidenceComparison(consistent=not conflicts, conflicts=conflicts, human_review_required=bool(conflicts))


def _review_candidate(_: AgentState, args: ReviewCandidate) -> ReviewCandidate:
    return args


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("get_program_trust_detail", "Read structured programme evidence and trust details.", ProgramTrustInput, ProgramTrustResult, _trust),
        ToolDefinition("list_missing_official_fields", "List official fields that block formal use.", ProgramTrustInput, MissingOfficialFields, _missing),
        ToolDefinition("compare_evidence_records", "Compare evidence records and surface unresolved conflicts.", ProgramTrustInput, EvidenceComparison, _compare),
        ToolDefinition("save_review_candidate", "Save a proposed evidence-review item only after human approval.", ReviewCandidate, ReviewCandidate, _review_candidate, requires_human_review=True),
    ]
