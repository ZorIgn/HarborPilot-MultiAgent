from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harbor_agent.models import (
    DecisionStatus,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    SourceScope,
)
from harbor_agent.runtime.state import (
    AgentState,
    ConflictResolution,
    HumanResolution,
    HumanReviewItem,
    WorkflowGoal,
    WorkflowStatus,
)
from harbor_agent.runtime.workflow import (
    _apply_human_conflict_resolution,
    _ensure_human_review_item,
)
from harbor_agent.services import program_store
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.resolved_program import resolve_program_view
from harbor_agent.tools.source_tools import SourceBindingProposal


def _member(program_id: str, evidence_id: str, value: str) -> FieldEvidenceRecord:
    return FieldEvidenceRecord(
        evidence_id=evidence_id,
        program_id=program_id,
        field_name="deadline",
        value=value,
        cycle="2027-fall",
        source_url=f"https://example.edu/programmes/{evidence_id}",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash=f"sha256:{evidence_id}",
        confidence="high",
        source_priority=1,
        status=FieldVerificationStatus.conflicted,
        review_required=True,
        evidence_snippet=f"Application deadline: {value}.",
        snapshot_url=f"snapshots/{evidence_id}.html",
        source_scope=SourceScope.programme_detail,
        final_url=f"https://example.edu/programmes/{evidence_id}",
        binding_status="matched",
        binding_score=100,
    )


def test_waiting_human_checkpoint_contains_actionable_typed_conflict_groups() -> None:
    program = load_programs()[0]
    first = _member(program.id, "record-a", "2027-03-01")
    second = _member(program.id, "record-b", "2027-03-15")
    state = AgentState(
        workflow_id="typed-human-item",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        verification_conflicts=[
            first.model_dump(mode="json"),
            second.model_dump(mode="json"),
        ],
        human_review_reason="Choose the authoritative current deadline.",
    )

    waiting = _ensure_human_review_item(state)
    item = HumanReviewItem.model_validate(waiting.human_review_item)

    assert waiting.status is WorkflowStatus.WAITING_HUMAN
    assert item.kind == "evidence_conflict"
    assert item.action == "resolve_conflicts"
    assert len(item.conflict_groups) == 1
    group = item.conflict_groups[0]
    assert set(group.member_record_ids) == {"record-a", "record-b"}
    assert group.conflict_id not in group.member_record_ids
    assert {record["record_id"] for record in group.records} == {"record-a", "record-b"}


def test_waiting_human_without_action_fails_retryably_instead_of_deadlocking() -> None:
    state = AgentState(
        workflow_id="dead-human-item",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        human_review_reason="No actual action exists.",
    )

    failed = _ensure_human_review_item(state)

    assert failed.status is WorkflowStatus.FAILED_RETRYABLE
    assert failed.human_review_item is None
    assert any("failed closed" in error for error in failed.errors)


def test_single_conflict_record_is_not_presented_as_an_actionable_group() -> None:
    program = load_programs()[0]
    state = AgentState(
        workflow_id="incomplete-human-group",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        verification_conflicts=[
            _member(program.id, "record-only", "2027-03-01").model_dump(mode="json")
        ],
        human_review_reason="The conflicting sibling is missing.",
    )

    failed = _ensure_human_review_item(state)

    assert failed.status is WorkflowStatus.FAILED_RETRYABLE
    assert failed.human_review_item is None


def test_conflict_resume_requires_the_stable_group_id_not_a_member_alias() -> None:
    program = load_programs()[0]
    state = AgentState(
        workflow_id="strict-conflict-group-id",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        status=WorkflowStatus.WAITING_HUMAN,
        verification_conflicts=[
            _member(program.id, "record-a", "2027-03-01").model_dump(mode="json"),
            _member(program.id, "record-b", "2027-03-15").model_dump(mode="json"),
        ],
        human_review_reason="Choose the authoritative current deadline.",
    )
    resolution = HumanResolution(
        action="resolve_conflicts",
        conflict_resolutions=[
            ConflictResolution(conflict_id="record-a", action="reject")
        ],
    )

    with pytest.raises(ValueError, match="unknown conflict_id"):
        _apply_human_conflict_resolution(
            state,
            {},
            resolution,
            reviewer_id="independent-reviewer",
        )


def test_conflict_accept_is_atomic_and_canonical_resolver_converges(tmp_path) -> None:
    db_path = tmp_path / "evidence.sqlite3"
    program = load_programs()[0]
    selected = _member(program.id, "record-selected", "2027-03-01")
    sibling = _member(program.id, "record-sibling", "2027-03-15")

    persisted, decision_id = program_store.persist_conflict_resolution(
        [selected, sibling],
        action="accept",
        conflict_id="conflict-group-deadline",
        selected_record_id=selected.evidence_id,
        reviewer_id="independent-reviewer",
        reviewer_note="Official programme page is authoritative.",
        db_path=db_path,
    )

    assert persisted is not None
    assert persisted.evidence_id == selected.evidence_id
    records = program_store.load_field_evidence_records([program.id], db_path=db_path)
    by_id = {record.evidence_id: record for record in records}
    assert by_id["record-selected"].status is FieldVerificationStatus.official_verified_current
    assert by_id["record-sibling"].status is FieldVerificationStatus.not_published
    assert by_id["record-selected"].review_decision_id == decision_id
    assert by_id["record-sibling"].review_decision_id == decision_id
    assert by_id["record-selected"].reviewer_id == "independent-reviewer"

    with sqlite3.connect(db_path) as conn:
        decisions = conn.execute(
            "SELECT review_id, decision, reviewer_id FROM review_decisions"
        ).fetchall()
    assert decisions == [
        ("conflict-group-deadline", "accept", "independent-reviewer")
    ]

    view = resolve_program_view(program, evidence_records=records)
    deadline = view.fact("deadline")
    assert deadline.decision_status is DecisionStatus.PASS
    assert deadline.normalized_value == "2027-03-01"
    assert deadline.conflict_id is None


def test_reject_cannot_select_one_member_or_mix_conflict_groups(tmp_path) -> None:
    program = load_programs()[0]
    first = _member(program.id, "record-a", "2027-03-01")
    second = _member(program.id, "record-b", "2027-03-15")

    with pytest.raises(ValueError, match="whole conflict group"):
        ConflictResolution(
            conflict_id="conflict-group",
            action="reject",
            selected_record_id="record-a",
        )

    mixed = second.model_copy(update={"field_name": "tuition_hkd", "value": "120000"})
    with pytest.raises(ValueError, match="same program field and cycle"):
        program_store.persist_conflict_resolution(
            [first, mixed],
            action="accept",
            conflict_id="mixed-conflict",
            selected_record_id=first.evidence_id,
            reviewer_id="independent-reviewer",
            db_path=tmp_path / "mixed.sqlite3",
        )


def test_source_binding_rejects_field_names_that_normalize_to_empty() -> None:
    with pytest.raises(ValidationError):
        SourceBindingProposal(
            program_id="demo-program",
            source_url="https://example.edu/programme",
            field_names=["   ", ""],
            snapshot_id="snapshots/demo.html",
            page_hash="sha256:demo",
        )
