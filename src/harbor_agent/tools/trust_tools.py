from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from harbor_agent.models import (
    ExecutionReference,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    SourceScope,
)
from harbor_agent.runtime.state import AgentState
from harbor_agent.services import program_store
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.formal_gate import program_field_gate
from harbor_agent.services.review_gate import review_id_for_record
from harbor_agent.services.resolved_program import normalize_field_value
from harbor_agent.services.source_binding_store import load_program_source_binding
from harbor_agent.services.source_identity import (
    is_allowed_official_url,
    same_official_institution,
)
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
    program_id: str
    consistent: bool
    conflicts: list[dict] = Field(default_factory=list)
    preferred_record_id: str | None = None
    human_review_required: bool = False


class ReviewCandidate(BaseModel):
    program_id: str
    field_name: str
    proposed_value: str | None = None
    reason: str
    snapshot_id: str = Field(min_length=1, max_length=512)
    page_hash: str = Field(min_length=1, max_length=256)


class SavedReviewCandidate(BaseModel):
    record_id: str
    review_id: str
    program_id: str
    field_name: str
    persisted: bool
    record: FieldEvidenceRecord


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
    # The resolver can detect a conflict even when the ingestion layer has not
    # stamped every member row as CONFLICTED yet.  Build the review payload from
    # durable SQLite record IDs so a reviewer can select an actual row.
    persisted = program_store.load_field_evidence_records([args.program_id])
    conflicts = _current_conflict_members(persisted, args.program_id)
    conflicts.extend(
        _conflict_payload(record, conflict_id=str(record.get("conflict_id") or ""))
        for record in (
            item.model_dump(mode="json")
            for item in trust.field_records
            if str(item.status.value) == "CONFLICTED"
        )
        if not any(
            str(existing.get("record_id") or existing.get("evidence_id") or "")
            == str(record.get("record_id") or record.get("evidence_id") or "")
            and str(existing.get("field_name")) == str(record.get("field_name"))
            for existing in conflicts
        )
    )
    state_conflicts = [item for item in state.verification_conflicts if item.get("program_id") == args.program_id]
    conflicts.extend(_conflict_payload(item, conflict_id=str(item.get("conflict_id") or "")) for item in state_conflicts)
    deduped: dict[tuple[str, str], dict] = {}
    for item in conflicts:
        conflict_id = str(item.get("conflict_id") or "")
        record_id = str(item.get("record_id") or item.get("evidence_id") or "")
        deduped[(conflict_id, record_id)] = item
    conflicts = list(deduped.values())
    return EvidenceComparison(
        program_id=args.program_id,
        consistent=not conflicts,
        conflicts=conflicts,
        human_review_required=bool(conflicts),
    )


def _review_candidate(state: AgentState, args: ReviewCandidate) -> SavedReviewCandidate:
    approval = state.active_tool_approval
    if approval is None or approval.tool_name != "save_review_candidate" or not approval.reviewer_id:
        raise ValueError("review candidate persistence requires an active exact approval")
    if approval.arguments != args.model_dump(mode="json"):
        raise PermissionError("review candidate approval does not match the exact snapshot-bound arguments")
    program = _program(args.program_id)
    sessions = state.working_memory.get("verification_sources", {})
    session = sessions.get(args.program_id, {}) if isinstance(sessions, dict) else {}
    source_url = str(session.get("source_url") or "") if isinstance(session, dict) else ""
    tool_results = state.working_memory.get("tool_results", {})
    extraction = tool_results.get("extract_program_fields", {}) if isinstance(tool_results, dict) else {}
    if (
        not isinstance(extraction, dict)
        or extraction.get("program_id") != args.program_id
        or extraction.get("source_url") != source_url
    ):
        raise ValueError("review candidate requires the current extraction result")
    candidates = extraction.get("fields", [])
    candidate = next(
        (
            item for item in candidates
            if isinstance(item, dict)
            and str(item.get("field_name")) == args.field_name
            and (
                args.proposed_value is None
                or str(item.get("value")) == str(args.proposed_value)
            )
        ),
        None,
    )
    if not source_url or candidate is None:
        raise ValueError("review candidate must match the current extraction session")
    expected_url = str(program.official_program_url or program.source.url or "")
    if not is_allowed_official_url(source_url) or not same_official_institution(source_url, expected_url):
        raise ValueError("review candidate source must be the programme institution's official domain")
    binding = load_program_source_binding(
        workflow_id=state.workflow_id,
        program_id=args.program_id,
        source_url=source_url,
    )
    if binding is None or args.field_name not in set(binding.get("field_names", [])):
        raise ValueError("review candidate requires a persisted binding for this exact field")
    snapshot = tool_results.get("snapshot_official_source", {}) if isinstance(tool_results, dict) else {}
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("program_id") != args.program_id
        or snapshot.get("url") != source_url
        or not snapshot.get("ok")
    ):
        raise ValueError("review candidate requires the current source snapshot")
    current_snapshot_id = snapshot.get("snapshot_id")
    current_page_hash = snapshot.get("page_hash")
    if not current_snapshot_id or not current_page_hash:
        raise ValueError("review candidate requires a successful snapshot id and page hash")
    if str(binding.get("snapshot_id") or "") != str(current_snapshot_id) or str(binding.get("page_hash") or "") != str(current_page_hash):
        raise ValueError("review candidate binding is stale for the current source snapshot")
    if str(args.snapshot_id) != str(current_snapshot_id) or str(args.page_hash) != str(current_page_hash):
        raise ValueError("review candidate snapshot_id/page_hash do not match the current source snapshot")
    final_url = str(snapshot.get("final_url") or source_url)
    application_url = str(program.application_url or "")
    programme_url = str(program.official_program_url or "")
    is_application_portal = bool(application_url) and (
        source_url == application_url or final_url == application_url
    )
    is_programme_detail = bool(programme_url) and (
        source_url == programme_url or final_url == programme_url
    )
    source_type = (
        "official_application_system"
        if is_application_portal
        else "official_program_page"
        if is_programme_detail
        else "official_program_index"
    )
    source_scope = (
        SourceScope.application_portal
        if is_application_portal
        else SourceScope.programme_detail
        if is_programme_detail
        else SourceScope.institution_index
    )
    raw_status = str(candidate.get("status") or "")
    status = (
        FieldVerificationStatus.official_previous_cycle
        if raw_status == FieldVerificationStatus.official_previous_cycle.value
        else FieldVerificationStatus.model_inferred
    )
    confidence = str(candidate.get("confidence") or "low")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    record = FieldEvidenceRecord(
        program_id=args.program_id,
        field_name=args.field_name,
        value=str(candidate.get("value")) if candidate.get("value") is not None else None,
        cycle=str(getattr(program, "cycle", "") or "") or None,
        source_url=source_url,
        source_type=source_type,
        extracted_at=datetime.now(UTC),
        page_hash=str(current_page_hash),
        confidence=confidence,
        source_priority=1,
        status=status,
        review_required=True,
        evidence_snippet=str(candidate.get("evidence_snippet") or "") or None,
        snapshot_url=str(current_snapshot_id),
        source_scope=source_scope,
        final_url=final_url,
        binding_status="matched" if source_scope != SourceScope.institution_index else "index_only",
        binding_score=100 if source_scope != SourceScope.institution_index else 0,
        reviewer_note=args.reason,
        execution_ref=ExecutionReference(
            workflow_id=state.workflow_id,
            produced_by_agent="VerificationAgent",
            produced_by_tool="save_review_candidate",
            tool_call_id=approval.tool_call_id,
        ),
    )
    record = record.model_copy(update={"evidence_id": program_store.field_evidence_id(record)})
    program_store.upsert_field_evidence_records(
        [record],
        db_path=program_store.DB_PATH,
    )
    review_id = review_id_for_record(record)
    return SavedReviewCandidate(
        record_id=str(record.evidence_id),
        review_id=review_id,
        program_id=args.program_id,
        field_name=args.field_name,
        persisted=True,
        record=record,
    )


def _record_id(record: FieldEvidenceRecord | dict) -> str:
    if isinstance(record, FieldEvidenceRecord):
        if record.evidence_id:
            return str(record.evidence_id)
        return program_store.field_evidence_id(record)
    for key in ("evidence_id", "record_id"):
        if record.get(key):
            return str(record[key])
    payload = "|".join(
        str(record.get(key) or "")
        for key in ("program_id", "field_name", "cycle", "source_url", "page_hash", "value")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _conflict_group_id(program_id: str, field_name: str, cycle: str | None, records: list[FieldEvidenceRecord]) -> str:
    members = sorted(
        f"{_record_id(record)}:{normalize_field_value(field_name, record.value)!r}"
        for record in records
    )
    raw = "|".join([program_id, field_name, cycle or "", *members])
    return "conflict_group_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _conflict_payload(record: FieldEvidenceRecord | dict, *, conflict_id: str) -> dict:
    payload = record.model_dump(mode="json") if isinstance(record, FieldEvidenceRecord) else dict(record)
    record_id = _record_id(record)
    payload["evidence_id"] = payload.get("evidence_id") or record_id
    payload["record_id"] = record_id
    if conflict_id:
        payload["conflict_id"] = conflict_id
    return payload


def _current_conflict_members(records: list[FieldEvidenceRecord], program_id: str) -> list[dict]:
    by_field: dict[tuple[str, str | None], list[FieldEvidenceRecord]] = {}
    for record in records:
        if record.program_id != program_id:
            continue
        if record.status not in {FieldVerificationStatus.official_verified_current, FieldVerificationStatus.conflicted}:
            continue
        if record.review_required or normalize_field_value(record.field_name, record.value) is None:
            continue
        by_field.setdefault((record.field_name, record.cycle), []).append(record)
    output: list[dict] = []
    for (field_name, cycle), members in by_field.items():
        values = {json.dumps(normalize_field_value(field_name, record.value), sort_keys=True, default=str) for record in members}
        if len(values) <= 1:
            continue
        conflict_id = _conflict_group_id(program_id, field_name, cycle, members)
        member_ids = [_record_id(record) for record in members]
        for record in members:
            payload = _conflict_payload(record, conflict_id=conflict_id)
            payload["member_record_ids"] = member_ids
            output.append(payload)
    return output


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("get_program_trust_detail", "Read structured programme evidence and trust details.", ProgramTrustInput, ProgramTrustResult, _trust),
        ToolDefinition("list_missing_official_fields", "List official fields that block formal use.", ProgramTrustInput, MissingOfficialFields, _missing),
        ToolDefinition("compare_evidence_records", "Compare evidence records and surface unresolved conflicts.", ProgramTrustInput, EvidenceComparison, _compare),
        ToolDefinition("save_review_candidate", "Persist one bound evidence candidate in the human review queue.", ReviewCandidate, SavedReviewCandidate, _review_candidate, requires_human_review=True),
    ]
