from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from harbor_agent.models import (
    FieldEvidenceRecord,
    FieldVerificationStatus,
    ReviewPublishRequest,
    ReviewPublishResponse,
    ReviewQueueItem,
    ReviewQueueSummary,
)
from harbor_agent.services.evidence_graph import REVIEWER_GATE_FIELDS, build_field_evidence_records
from harbor_agent.services.review_store import save_published_field_record


def build_review_queue(program_id: str | None = None, limit: int = 80) -> ReviewQueueSummary:
    generated_at = datetime.now(UTC)
    items = [_queue_item_from_record(record) for record in build_field_evidence_records()]
    items = [item for item in items if item is not None]
    if program_id:
        items = [item for item in items if item.program_id == program_id]
    items = sorted(items, key=lambda item: (not item.publishable, item.program_id, item.source_priority, item.field_name))
    limited = items[:limit]
    return ReviewQueueSummary(
        generated_at=generated_at,
        pending_count=len(items),
        publishable_count=sum(1 for item in items if item.publishable),
        items=limited,
    )


def publish_review_item(request: ReviewPublishRequest) -> ReviewPublishResponse:
    queue = build_review_queue(limit=10_000)
    item = next((candidate for candidate in queue.items if candidate.review_id == request.review_id), None)
    if item is None:
        return ReviewPublishResponse(
            ok=False,
            item=ReviewQueueItem(
                review_id=request.review_id,
                program_id="unknown",
                field_name="unknown",
                source_type="unknown",
                status="REJECTED",
                publishable=False,
                reviewer_id=request.reviewer_id,
                reviewer_note=request.reviewer_note,
                reviewed_at=datetime.now(UTC),
                boundary="Review id was not found in the current queue.",
            ),
            message="Review item was not found or has already been superseded.",
        )

    reviewed_at = datetime.now(UTC)
    item.reviewer_id = request.reviewer_id
    item.reviewer_note = request.reviewer_note
    item.reviewed_at = reviewed_at

    if request.decision == "reject":
        item.status = "REJECTED"
        return ReviewPublishResponse(
            ok=True,
            item=item,
            published_record=None,
            message="Review item rejected; no official field was published.",
        )

    if not item.publishable:
        item.status = "REJECTED"
        return ReviewPublishResponse(
            ok=False,
            item=item,
            published_record=None,
            message="This item is not publishable as an official current field. Use official school sources only.",
        )

    item.status = "APPROVED"
    value = request.confirmed_value if request.confirmed_value is not None else item.proposed_value
    record = FieldEvidenceRecord(
        program_id=item.program_id,
        field_name=item.field_name,
        value=value,
        cycle=item.cycle,
        source_url=item.source_url,
        source_type=item.source_type,
        extracted_at=item.extracted_at,
        verified_at=reviewed_at,
        page_hash=item.page_hash,
        confidence="high",
        source_priority=item.source_priority,
        status=FieldVerificationStatus.official_verified_current,
        review_required=False,
        reviewer_id=request.reviewer_id,
        evidence_snippet=item.evidence_snippet,
        snapshot_url=item.snapshot_url,
        agent_chain=[*item.agent_chain, "HumanReviewGateAgent", "AuditAgent"],
    )
    if request.persist:
        save_published_field_record(record)
    return ReviewPublishResponse(
        ok=True,
        item=item,
        published_record=record,
        message=(
            "Official field approved and persisted locally."
            if request.persist
            else "Official field approved in preview mode; set persist=true to write the local publish store."
        ),
    )


def _queue_item_from_record(record: FieldEvidenceRecord) -> ReviewQueueItem | None:
    if record.field_name not in REVIEWER_GATE_FIELDS:
        return None
    if record.status == FieldVerificationStatus.official_verified_current and not record.review_required:
        return None
    if record.status in {FieldVerificationStatus.community_only, FieldVerificationStatus.model_inferred}:
        return None
    publishable = _is_publishable_official_candidate(record)
    return ReviewQueueItem(
        review_id=_review_id(record),
        program_id=record.program_id,
        field_name=record.field_name,
        proposed_value=record.value,
        cycle=record.cycle,
        source_url=record.source_url,
        source_type=record.source_type,
        evidence_snippet=record.evidence_snippet,
        page_hash=record.page_hash,
        snapshot_url=record.snapshot_url,
        extracted_at=record.extracted_at,
        confidence=record.confidence,
        source_priority=record.source_priority,
        publishable=publishable,
        boundary=(
            "Official public source candidate. Publish only after the reviewer checks the original source."
            if publishable
            else "Not publishable as an official current field; keep it as preparation/reference only."
        ),
        agent_chain=record.agent_chain,
    )


def _is_publishable_official_candidate(record: FieldEvidenceRecord) -> bool:
    if not record.source_type.startswith("official"):
        return False
    if not record.source_url:
        return False
    if not record.evidence_snippet:
        return False
    if not record.page_hash:
        return False
    if record.status in {FieldVerificationStatus.not_published, FieldVerificationStatus.conflicted}:
        return False
    return True


def _review_id(record: FieldEvidenceRecord) -> str:
    raw = "|".join(
        [
            record.program_id,
            record.field_name,
            record.cycle or "",
            str(record.source_url or ""),
            record.page_hash or "",
            str(record.value or ""),
        ]
    )
    return "rev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]