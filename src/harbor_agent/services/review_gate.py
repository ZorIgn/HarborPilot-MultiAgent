from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from harbor_agent.models import (
    FieldEvidenceRecord,
    FieldVerificationStatus,
    ReviewBulkPublishRequest,
    ReviewBulkPublishResponse,
    ReviewPublishRequest,
    ReviewPublishResponse,
    ReviewQueueItem,
    ReviewQueueSummary,
)
from harbor_agent.services import program_store
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.evidence_graph import build_field_evidence_records
from harbor_agent.services.field_contract import FORMAL_RECOMMENDATION_FIELDS
from harbor_agent.services.resolved_program import normalize_field_value
from harbor_agent.services.review_store import (
    load_review_decisions,
    save_published_field_record,
    save_review_decision,
)
from harbor_agent.services.source_identity import is_allowed_official_url, same_official_institution

CURRENT_CYCLE_DATE_FIELDS = {"deadline", "scholarship_deadline", "recommendation_deadline"}
REVIEWER_GATE_FIELDS = list(FORMAL_RECOMMENDATION_FIELDS)


def build_review_queue(program_id: str | None = None, limit: int = 80) -> ReviewQueueSummary:
    generated_at = datetime.now(UTC)
    rejected_ids = {review_id for review_id, decision in load_review_decisions().items() if decision == "reject"}
    items = [_queue_item_from_record(record) for record in build_field_evidence_records()]
    items = [item for item in items if item is not None]
    items = [item for item in items if item.review_id not in rejected_ids]
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
    if item is None and request.decision == "approve":
        # An operator may explicitly override a previous rejection by opening
        # the stable review id.  It remains hidden from the normal queue until
        # that deliberate action.
        historical = [_queue_item_from_record(record) for record in build_field_evidence_records()]
        item = next((candidate for candidate in historical if candidate and candidate.review_id == request.review_id), None)
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
        if request.persist:
            decision_id = save_review_decision(
                review_id=item.review_id,
                program_id=item.program_id,
                field_name=item.field_name,
                decision="reject",
                reviewer_id=request.reviewer_id,
                reviewer_note=request.reviewer_note,
            )
            item.reviewer_note = (item.reviewer_note or "") + f" [decision:{decision_id}]"
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
    validation_error = _validate_confirmed_value(item, value)
    if validation_error:
        item.status = "REJECTED"
        if request.persist:
            save_review_decision(
                review_id=item.review_id,
                program_id=item.program_id,
                field_name=item.field_name,
                decision="reject",
                reviewer_id=request.reviewer_id,
                reviewer_note=validation_error,
            )
        return ReviewPublishResponse(
            ok=False,
            item=item,
            published_record=None,
            message=validation_error,
        )
    decision_id = (
        save_review_decision(
            review_id=item.review_id,
            program_id=item.program_id,
            field_name=item.field_name,
            decision="approve",
            reviewer_id=request.reviewer_id,
            reviewer_note=request.reviewer_note,
        )
        if request.persist
        else None
    )
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
        source_scope=item.source_scope,
        page_title=item.page_title,
        final_url=item.final_url,
        binding_status=item.binding_status,
        binding_score=item.binding_score,
        reviewer_note=request.reviewer_note,
        review_decision_id=decision_id,
        execution_ref=item.execution_ref,
    )
    if request.persist:
        save_published_field_record(record)
    return ReviewPublishResponse(
        ok=True,
        item=item,
        published_record=record,
        message=(
            "Official field approved and persisted to SQLite/local publish store."
            if request.persist
            else "Official field approved in preview mode; set persist=true to write the local publish store."
        ),
    )


def publish_review_batch(request: ReviewBulkPublishRequest) -> ReviewBulkPublishResponse:
    if request.persist:
        return ReviewBulkPublishResponse(
            ok=False,
            published_count=0,
            preview_count=0,
            skipped_count=0,
            queue_before=build_review_queue(program_id=request.program_id, limit=1).pending_count,
            queue_after=None,
            responses=[],
            message="批量操作只允许预览。当前季官方字段必须逐条打开原文并单独发布。",
        )
    queue = build_review_queue(program_id=request.program_id, limit=10_000)
    candidates = [item for item in queue.items if item.publishable][: request.limit]
    responses: list[ReviewPublishResponse] = []
    note = request.reviewer_note or "Batch approved after checking official public source evidence."
    for item in candidates:
        responses.append(
            publish_review_item(
                ReviewPublishRequest(
                    review_id=item.review_id,
                    decision="approve",
                    reviewer_id=request.reviewer_id,
                    reviewer_note=note,
                    persist=request.persist,
                )
            )
        )
    published_count = sum(1 for item in responses if item.ok and item.published_record is not None and request.persist)
    preview_count = sum(1 for item in responses if item.ok and item.published_record is not None and not request.persist)
    queue_after = build_review_queue(program_id=request.program_id, limit=1).pending_count if request.persist else None
    skipped_count = max(queue.pending_count - len(candidates), 0)
    return ReviewBulkPublishResponse(
        ok=all(item.ok for item in responses) if responses else True,
        published_count=published_count,
        preview_count=preview_count,
        skipped_count=skipped_count,
        queue_before=queue.pending_count,
        queue_after=queue_after,
        responses=responses,
        message=(
            f"Published {published_count} official fields; {skipped_count} queue items still need review or were outside the batch limit."
            if request.persist
            else f"Previewed {preview_count} official fields; set persist=true to publish them."
        ),
    )


def _queue_item_from_record(record: FieldEvidenceRecord) -> ReviewQueueItem | None:
    if record.field_name not in REVIEWER_GATE_FIELDS:
        return None
    if record.status == FieldVerificationStatus.official_verified_current and not record.review_required:
        return None
    if record.status == FieldVerificationStatus.community_only:
        return None
    if record.status == FieldVerificationStatus.model_inferred and not record.source_type.startswith("official"):
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
        source_scope=record.source_scope,
        page_title=record.page_title,
        final_url=record.final_url,
        binding_status=record.binding_status,
        binding_score=record.binding_score,
        extracted_at=record.extracted_at,
        confidence=record.confidence,
        source_priority=record.source_priority,
        publishable=publishable,
        boundary=(
            "Official public source candidate. Publish only after the reviewer checks the original source."
            if publishable
            else "Not publishable as an official current field; keep it as preparation/reference only."
        ),
        execution_ref=record.execution_ref,
    )


def _is_publishable_official_candidate(record: FieldEvidenceRecord) -> bool:
    if not record.source_type.startswith("official"):
        return False
    if record.source_type == "official_program_index":
        return False
    if record.source_scope is None:
        return False
    scope = record.source_scope.value
    if scope == "programme_detail":
        if record.binding_status != "matched" or record.binding_score < 60:
            return False
    elif scope == "application_portal":
        if record.field_name != "application_url":
            return False
        if record.binding_status != "matched" or record.binding_score < 60:
            return False
    else:
        return False
    if not record.source_url:
        return False
    if not _is_allowed_official_url(str(record.source_url)):
        return False
    if not record.evidence_snippet:
        return False
    if not record.page_hash:
        return False
    if record.status in {FieldVerificationStatus.not_published, FieldVerificationStatus.conflicted}:
        return False
    if record.field_name in CURRENT_CYCLE_DATE_FIELDS and not _has_current_cycle_evidence(record):
        return False
    if record.field_name in {"official_program_url", "application_url"}:
        if not record.value or not _is_allowed_official_url(str(record.value)):
            return False
    if record.final_url and not _is_allowed_official_url(str(record.final_url)):
        return False
    program = next((item for item in load_programs() if item.id == record.program_id), None)
    if program is None:
        return False
    expected_url = str(program.official_program_url or program.source.url or "")
    actual_url = str(record.final_url or record.source_url or "")
    if not same_official_institution(actual_url, expected_url):
        return False
    return True


def _is_allowed_official_url(value: str) -> bool:
    return is_allowed_official_url(value)


def _validate_confirmed_value(item: ReviewQueueItem, value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return "审核发布需要一个非空的确认值。"
    text = str(value).strip()
    if len(text) > 2000:
        return "确认值过长，请保留学校原文中的字段内容和必要上下文。"
    if item.field_name in CURRENT_CYCLE_DATE_FIELDS:
        year = re.search(r"20\d{2}", item.cycle or "")
        if not year or year.group(0) not in text:
            return "截止日期必须包含目标申请季年份，不能把旧季日期覆盖为当前季事实。"
        if not re.search(r"20\d{2}[-/.年]\s*[01]?\d[-/.月]\s*[0-3]?\d?", text):
            return "截止日期格式无法核验，请保留官网中的完整日期或轮次原文。"
    if item.field_name == "tuition_hkd":
        if not re.search(r"(HK\$|HKD)\s*[0-9][0-9,]{3,}", text, re.IGNORECASE):
            return "tuition_hkd 只能确认 HKD/HK$ 金额；其他币种必须保留为原币，不能直接混写为港币。"
    if item.field_name == "min_gpa" and normalize_field_value("min_gpa", text) is None:
        return (
            "min_gpa 必须是可审计的 100 分制值（例如 82 或 {\"value\": 82, \"scale\": \"100\"}）；"
            "3.6/4.0、5 分制或未声明尺度的原文可保留为候选，但不能直接发布为硬门槛。"
        )
    if item.field_name == "required_backgrounds" and normalize_field_value("required_backgrounds", text) is None:
        return (
            "required_backgrounds 必须确认成受支持的结构化标签列表（computing、business、statistics、engineering）；"
            "原始官网文字可保留在 evidence snippet，不能直接转成硬背景限制。"
        )
    if item.field_name == "portfolio_required" and normalize_field_value("portfolio_required", text) is None:
        return "portfolio_required 必须确认成 true/false，不能用模糊网页片段发布为硬门槛。"
    if item.field_name in {"official_program_url", "application_url"}:
        if not _is_allowed_official_url(text):
            return "项目页和申请入口只能发布 HTTPS 学校官方域名。"
    return None


def _has_current_cycle_evidence(record: FieldEvidenceRecord) -> bool:
    match = re.search(r"20\d{2}", record.cycle or "")
    if not match:
        return False
    target_year = match.group(0)
    evidence = " ".join([str(record.value or ""), str(record.evidence_snippet or "")])
    return target_year in evidence


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


def review_id_for_record(record: FieldEvidenceRecord) -> str:
    """Public stable identity for tools that persist a pending review record."""

    return _review_id(record)


def persist_conflict_decision(
    conflict: dict,
    *,
    action: str,
    conflict_id: str,
    reviewer_id: str,
    reviewer_note: str | None = None,
) -> FieldEvidenceRecord:
    """Persist an exact conflict decision before checkpoint state is cleared."""

    payload = {
        key: value
        for key, value in conflict.items()
        if key in FieldEvidenceRecord.model_fields
    }
    try:
        record = FieldEvidenceRecord.model_validate(payload)
    except Exception as exc:
        raise ValueError(
            "conflict is not a complete evidence record and cannot be resolved"
        ) from exc
    if action == "reject":
        decision_id = save_review_decision(
            review_id=conflict_id,
            program_id=record.program_id,
            field_name=record.field_name,
            decision="reject",
            reviewer_id=reviewer_id,
            reviewer_note=reviewer_note,
        )
        rejected = record.model_copy(
            update={
                "status": FieldVerificationStatus.not_published,
                "review_required": False,
                "reviewer_id": reviewer_id,
                "reviewer_note": reviewer_note,
                "review_decision_id": decision_id,
                "verified_at": datetime.now(UTC),
            }
        )
        program_store.upsert_field_evidence_records(
            [rejected],
            db_path=program_store.DB_PATH,
        )
        return rejected
    if action != "accept":
        raise ValueError(f"unsupported conflict decision: {action}")

    candidate = record.model_copy(
        update={
            "status": FieldVerificationStatus.model_inferred,
            "review_required": True,
            "reviewer_id": None,
            "review_decision_id": None,
        }
    )
    if not _is_publishable_official_candidate(candidate):
        raise ValueError(
            "selected conflict record is not publishable official current evidence"
        )
    item = _queue_item_from_record(candidate)
    if item is None:
        raise ValueError("selected conflict field is outside the reviewer gate")
    validation_error = _validate_confirmed_value(item, candidate.value)
    if validation_error:
        raise ValueError(validation_error)
    decision_id = save_review_decision(
        review_id=conflict_id,
        program_id=record.program_id,
        field_name=record.field_name,
        decision="approve",
        reviewer_id=reviewer_id,
        reviewer_note=reviewer_note,
    )
    approved = candidate.model_copy(
        update={
            "status": FieldVerificationStatus.official_verified_current,
            "review_required": False,
            "reviewer_id": reviewer_id,
            "reviewer_note": reviewer_note,
            "review_decision_id": decision_id,
            "verified_at": datetime.now(UTC),
            "confidence": "high",
        }
    )
    save_published_field_record(approved)
    return approved
