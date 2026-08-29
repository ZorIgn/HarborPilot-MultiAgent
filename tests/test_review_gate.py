from __future__ import annotations

import json
from datetime import UTC, datetime

from harbor_agent.models import (
    FieldEvidenceRecord,
    FieldVerificationStatus,
    ReviewPublishRequest,
    SourceScope,
)
from harbor_agent.services import review_gate


def test_review_gate_blocks_not_published_official_candidate(monkeypatch) -> None:
    record = FieldEvidenceRecord(
        program_id="demo-program",
        field_name="deadline",
        value=None,
        cycle="2027-fall",
        source_url="https://example.edu/programme",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash="sha256:notpublished",
        confidence="low",
        source_priority=2,
        status=FieldVerificationStatus.not_published,
        review_required=True,
        evidence_snippet="The application deadline has not been published yet.",
        execution_ref=None,
    )
    monkeypatch.setattr(review_gate, "build_field_evidence_records", lambda: [record])

    queue = review_gate.build_review_queue()
    assert queue.pending_count == 1
    assert queue.publishable_count == 0
    assert queue.items[0].publishable is False

    response = review_gate.publish_review_item(
        ReviewPublishRequest(
            review_id=queue.items[0].review_id,
            decision="approve",
            reviewer_id="qa_reviewer",
            reviewer_note="cannot approve unpublished deadline",
        )
    )

    assert response.ok is False
    assert response.item.status == "REJECTED"
    assert response.published_record is None
    assert "not publishable" in response.message.lower()

def test_review_store_persists_published_record_to_sqlite(monkeypatch, tmp_path) -> None:
    from harbor_agent.services import review_store

    monkeypatch.setattr(review_store, "DB_PATH", tmp_path / "evidence.sqlite3")
    monkeypatch.setattr(review_store, "STORE_PATH", tmp_path / "published.json")

    record = FieldEvidenceRecord(
        program_id="demo-program",
        field_name="deadline",
        value="2027-03-20",
        cycle="2027-fall",
        source_url="https://example.edu/programme",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
        page_hash="sha256:published",
        confidence="high",
        source_priority=2,
        status=FieldVerificationStatus.official_verified_current,
        review_required=False,
        reviewer_id="qa_reviewer",
        evidence_snippet="Application deadline: 2027-03-20.",
        execution_ref=None,
    )

    review_store.save_published_field_record(record)

    stored = review_store.load_published_field_records()
    assert len(stored) == 1
    assert stored[0].program_id == "demo-program"
    assert stored[0].status == FieldVerificationStatus.official_verified_current
    assert stored[0].field_name == "deadline"
    assert stored[0].value == "2027-03-20"


def test_review_store_never_revives_a_stale_json_export(monkeypatch, tmp_path) -> None:
    from harbor_agent.services import review_store

    monkeypatch.setattr(review_store, "DB_PATH", tmp_path / "empty-evidence.sqlite3")
    export_path = tmp_path / "published.json"
    monkeypatch.setattr(review_store, "STORE_PATH", export_path)
    stale = FieldEvidenceRecord(
        program_id="demo-program",
        field_name="deadline",
        value="2027-03-20",
        cycle="2027-fall",
        source_type="official_program_page",
        status=FieldVerificationStatus.official_verified_current,
        review_required=False,
        reviewer_id="stale-reviewer",
    )
    export_path.write_text(
        json.dumps([stale.model_dump(mode="json")]),
        encoding="utf-8",
    )

    assert review_store.load_published_field_records() == []


def _deadline_candidate(source_url: str, value: str, snippet: str) -> FieldEvidenceRecord:
    return FieldEvidenceRecord(
        program_id="demo-program",
        field_name="deadline",
        value=value,
        cycle="2027-fall",
        source_url=source_url,
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash="sha256:candidate",
        confidence="medium",
        source_priority=2,
        status=FieldVerificationStatus.official_previous_cycle,
        review_required=True,
        evidence_snippet=snippet,
        snapshot_url="snapshots/review-gate-deadline.html",
        execution_ref=None,
    )


def test_review_gate_requires_allowlisted_school_domain(monkeypatch) -> None:
    record = _deadline_candidate("https://admissions-example.com/hku", "2027-03-20", "2027 Fall deadline: 20 March 2027")
    monkeypatch.setattr(review_gate, "build_field_evidence_records", lambda: [record])

    queue = review_gate.build_review_queue()

    assert queue.publishable_count == 0
    assert queue.items[0].publishable is False


def test_review_gate_requires_target_cycle_year_in_date_evidence(monkeypatch) -> None:
    record = _deadline_candidate("https://www.hku.hk/programme", "20 March", "Application deadline: 20 March")
    monkeypatch.setattr(review_gate, "build_field_evidence_records", lambda: [record])

    queue = review_gate.build_review_queue()

    assert queue.publishable_count == 0


def test_review_gate_accepts_current_cycle_evidence_on_school_domain(monkeypatch) -> None:
    record = _deadline_candidate("https://www.hku.hk/programme", "2027-03-20", "2027 Fall application deadline: 20 March 2027")
    record.program_id = "hku-master-of-science-in-computer-science-2027"
    record.source_scope = SourceScope.programme_detail
    record.final_url = "https://www.hku.hk/programme"
    record.page_title = "Master of Science in Computer Science"
    record.binding_status = "matched"
    record.binding_score = 90
    monkeypatch.setattr(review_gate, "build_field_evidence_records", lambda: [record])

    queue = review_gate.build_review_queue()

    assert queue.publishable_count == 1
    assert queue.items[0].publishable is True


def test_review_preview_has_no_persistent_decision_and_preserves_provenance(monkeypatch) -> None:
    record = _deadline_candidate(
        "https://www.hku.hk/programme/computer-science",
        "2027-03-20",
        "2027 Fall application deadline: 20 March 2027",
    )
    record.program_id = "hku-master-of-science-in-computer-science-2027"
    record.source_scope = SourceScope.programme_detail
    record.final_url = "https://www.hku.hk/programme/computer-science"
    record.page_title = "Master of Science in Computer Science"
    record.binding_status = "matched"
    record.binding_score = 92
    record.page_hash = "sha256:preview-provenance"
    decisions: list[dict] = []
    monkeypatch.setattr(review_gate, "build_field_evidence_records", lambda: [record])
    monkeypatch.setattr(
        review_gate,
        "save_review_decision",
        lambda **kwargs: decisions.append(kwargs) or "should-not-be-created",
    )

    queue = review_gate.build_review_queue()
    response = review_gate.publish_review_item(
        ReviewPublishRequest(
            review_id=queue.items[0].review_id,
            decision="approve",
            reviewer_id="preview-reviewer",
            persist=False,
        )
    )

    assert response.ok is True
    assert decisions == []
    assert response.published_record is not None
    assert response.published_record.source_scope == SourceScope.programme_detail
    assert response.published_record.final_url == record.final_url
    assert response.published_record.binding_status == "matched"
    assert response.published_record.binding_score == 92
    assert response.published_record.review_decision_id is None
