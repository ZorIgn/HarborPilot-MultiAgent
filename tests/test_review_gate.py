from __future__ import annotations

from datetime import UTC, datetime

from harbor_agent.models import FieldEvidenceRecord, FieldVerificationStatus, ReviewPublishRequest
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
        agent_chain=["SourceDiscoveryAgent", "PageFetchAgent", "FieldExtractionAgent"],
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