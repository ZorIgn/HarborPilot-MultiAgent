from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC

from harbor_agent.models import DataStatus, EvidenceGraphSummary, FieldEvidenceRecord, FieldVerificationStatus, Program, ProgramTrustDetail
from harbor_agent.services.data_loader import load_programs, load_source_registry
from harbor_agent.services.program_store import load_field_evidence_records
from harbor_agent.services.program_urls import has_program_detail_page, student_application_url, student_program_url
from harbor_agent.services.review_store import load_published_field_records


PRODUCTION_FIELDS = [
    "program_name",
    "official_program_url",
    "deadline",
    "tuition_hkd",
    "materials",
    "language_requirement",
    "application_url",
    "scholarship_deadline",
    "recommendation_deadline",
    "essay_prompts",
]

REVIEWER_GATE_FIELDS = [
    "deadline",
    "official_program_url",
    "tuition_hkd",
    "materials",
    "language_requirement",
    "application_url",
    "scholarship_deadline",
    "essay_prompts",
]

STUDENT_TIMELINE_GATE_FIELDS = [
    "official_program_url",
    "deadline",
    "application_url",
    "language_requirement",
    "materials",
    "tuition_hkd",
]

OFFICIAL_PRIORITY = [
    "official_application_system",
    "official_program_page",
    "official_pdf_or_faq",
    "official_program_index",
    "ranking_or_directory",
    "community_result",
]


def build_evidence_graph_summary(limit: int = 12) -> EvidenceGraphSummary:
    programs = load_programs()
    registry = load_source_registry()
    records = build_field_evidence_records(programs)
    status_counts = Counter(record.status.value for record in records)
    field_counts = Counter(record.field_name for record in records)
    review_required_count = sum(1 for record in records if record.review_required)

    return EvidenceGraphSummary(
        program_count=len(programs),
        field_record_count=len(records),
        verified_field_count=status_counts[FieldVerificationStatus.official_verified_current.value],
        extracted_field_count=(
            status_counts[FieldVerificationStatus.official_previous_cycle.value]
            + status_counts[FieldVerificationStatus.model_inferred.value]
        ),
        pending_review_field_count=review_required_count,
        official_source_count=sum(1 for source in registry.sources if source.trust_level.value == "official"),
        community_source_count=sum(1 for source in registry.sources if source.trust_level.value == "community"),
        status_breakdown=dict(status_counts),
        field_breakdown=dict(field_counts),
        official_priority=OFFICIAL_PRIORITY,
        production_schema=PRODUCTION_FIELDS,
        reviewer_gate_fields=REVIEWER_GATE_FIELDS,
        sample_records=records[:limit],
    )


def build_field_evidence_records(programs: list[Program] | None = None) -> list[FieldEvidenceRecord]:
    programs = programs or load_programs()
    program_ids = {program.id for program in programs}
    records: list[FieldEvidenceRecord] = []
    for program in programs:
        records.extend(_records_from_existing_evidence(program))
        records.extend(_synthetic_review_records(program))
    records.extend(load_field_evidence_records(program_ids))
    records.extend(
        record for record in load_published_field_records()
        if record.program_id in program_ids
    )
    deduped: dict[tuple[str, str, str, str, str, str], FieldEvidenceRecord] = {}
    for record in records:
        key = (
            record.program_id,
            record.field_name,
            record.cycle or "",
            str(record.source_url or ""),
            record.page_hash or "",
            str(record.value or ""),
        )
        deduped[key] = record
    return list(deduped.values())


def build_program_trust_detail(program: Program) -> ProgramTrustDetail:
    field_records = _primary_records_by_field(build_field_evidence_records([program]))
    gate_fields = list(REVIEWER_GATE_FIELDS)
    official_fields = [
        record.field_name
        for record in field_records
        if record.status == FieldVerificationStatus.official_verified_current
    ]
    review_fields = [
        field
        for field in gate_fields
        if _record_for_field(field_records, field) is None
        or _record_for_field(field_records, field).review_required
        or _record_for_field(field_records, field).status != FieldVerificationStatus.official_verified_current
    ]
    reference_fields = [
        record.field_name
        for record in field_records
        if record.status == FieldVerificationStatus.official_previous_cycle
    ]
    production_ready = not review_fields
    reference_ready = not production_ready and set(STUDENT_TIMELINE_GATE_FIELDS).issubset(set(reference_fields))
    previous_label = _previous_cycle_label(program.cycle)
    if production_ready:
        status_label = "官网当前季已核验"
        source_warning = "关键申请字段均有本申请季学校官方来源，可作为正式申请计划依据。"
    elif reference_ready:
        status_label = previous_label
        source_warning = (
            f"关键申请字段已有 {previous_label} 字段级来源，可用于安排材料和核对窗口；"
            "正式提交日期仍需等待当前申请季官网页面发布。"
        )
    else:
        status_label = "缺少关键项目字段"
        source_warning = (
            f"{len(review_fields)} 个关键字段缺少当前季官网核验或明确往届字段；"
            "补齐前只能展示项目清单，不能生成正式申请时间线。"
        )

    return ProgramTrustDetail(
        program_id=program.id,
        cycle=program.cycle,
        production_ready=production_ready,
        reference_ready=reference_ready,
        status_label=status_label,
        source_warning=source_warning,
        official_current_fields=official_fields,
        fields_requiring_review=review_fields,
        stale_or_reference_fields=reference_fields,
        reviewer_gate_fields=gate_fields,
        last_official_verified_at=program.last_verified_at,
        field_records=field_records,
    )


def _previous_cycle_label(cycle: str | None) -> str:
    raw = str(cycle or "").lower()
    year = 2027
    for token in raw.replace("_", "-").split("-"):
        if token.isdigit() and len(token) == 4:
            year = int(token)
            break
    term = "Spring" if "spring" in raw else "Fall"
    return f"{year - 1} {term} 往届参考"


def _primary_records_by_field(records: list[FieldEvidenceRecord]) -> list[FieldEvidenceRecord]:
    grouped: dict[str, list[FieldEvidenceRecord]] = {}
    for record in records:
        grouped.setdefault(record.field_name, []).append(record)
    by_field: dict[str, FieldEvidenceRecord] = {}
    for field_name, candidates in grouped.items():
        verified = [record for record in candidates if record.status == FieldVerificationStatus.official_verified_current]
        conflicts = [record for record in candidates if record.status == FieldVerificationStatus.conflicted]
        latest_verified = max(verified, key=_record_timestamp, default=None)
        latest_conflict = max(conflicts, key=_record_timestamp, default=None)
        if latest_conflict is not None and (
            latest_verified is None or _record_timestamp(latest_conflict) > _record_timestamp(latest_verified)
        ):
            by_field[field_name] = latest_conflict
        else:
            by_field[field_name] = min(candidates, key=_record_sort_key)
    return sorted(by_field.values(), key=lambda record: (record.source_priority, record.field_name))


def _record_for_field(records: list[FieldEvidenceRecord], field_name: str) -> FieldEvidenceRecord | None:
    return next((record for record in records if record.field_name == field_name), None)


def _record_sort_key(record: FieldEvidenceRecord) -> tuple[int, int, int, float, str]:
    status_rank = {
        FieldVerificationStatus.official_verified_current: 0,
        FieldVerificationStatus.conflicted: 1,
        FieldVerificationStatus.not_published: 2,
        FieldVerificationStatus.official_previous_cycle: 3,
        FieldVerificationStatus.community_only: 4,
        FieldVerificationStatus.model_inferred: 5,
    }.get(record.status, 9)
    review_rank = 1 if record.review_required else 0
    return (status_rank, record.source_priority, review_rank, -_record_timestamp(record), record.page_hash or "")


def _record_timestamp(record: FieldEvidenceRecord) -> float:
    value = record.verified_at or record.extracted_at
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _records_from_existing_evidence(program: Program) -> list[FieldEvidenceRecord]:
    records: list[FieldEvidenceRecord] = []
    for field_name, evidence in program.field_evidence.items():
        records.append(
            FieldEvidenceRecord(
                program_id=program.id,
                field_name=field_name,
                value=evidence.value,
                cycle=evidence.cycle,
                source_url=evidence.official_url,
                source_type=evidence.source_type,
                extracted_at=evidence.captured_at,
                verified_at=evidence.verified_at,
                page_hash=_stable_hash(f"{program.id}:{field_name}:{evidence.value}:{evidence.official_url}"),
                confidence=evidence.confidence,
                source_priority=_source_priority(evidence.source_type),
                status=_status_from_legacy(evidence.status, evidence.source_type),
                review_required=_status_from_legacy(evidence.status, evidence.source_type)
                != FieldVerificationStatus.official_verified_current,
                evidence_snippet=evidence.excerpt,
                snapshot_url=evidence.official_url,
                execution_ref=None,
            )
        )
    return records


def _synthetic_review_records(program: Program) -> list[FieldEvidenceRecord]:
    source_url = student_program_url(program) or program.source.url
    extracted_at = program.source.captured_at
    values = {
        "official_program_url": str(program.official_program_url) if has_program_detail_page(program) else None,
        "deadline": str(program.deadline),
        "tuition_hkd": str(program.tuition_hkd) if program.tuition_hkd is not None else None,
        "materials": ", ".join(program.materials),
        "language_requirement": ", ".join(
            f"{name} {score}" for name, score in program.requirements.language.items()
        ),
        "application_url": student_application_url(program),
    }
    records: list[FieldEvidenceRecord] = []
    for field_name, value in values.items():
        records.append(
            FieldEvidenceRecord(
                program_id=program.id,
                field_name=field_name,
                value=value,
                cycle=program.cycle,
                source_url=source_url,
                source_type="official_program_index",
                extracted_at=extracted_at,
                verified_at=program.last_verified_at,
                page_hash=_stable_hash(f"{program.id}:{field_name}:{value}:{source_url}"),
                confidence="medium" if value else "low",
                source_priority=_source_priority("official_program_index"),
                status=_field_status(program, field_name, value),
                review_required=_field_status(program, field_name, value)
                != FieldVerificationStatus.official_verified_current,
                evidence_snippet=_synthetic_evidence_snippet(program, field_name),
                snapshot_url=source_url,
                execution_ref=None,
            )
        )
    return records


def _synthetic_evidence_snippet(program: Program, field_name: str) -> str:
    if field_name == "official_program_url" and not has_program_detail_page(program):
        return "当前只找到学校招生索引页，未找到该项目的官方详情页；正式时间线和项目定制内容需要先补齐详情页来源。"
    if field_name == "application_url" and not student_application_url(program):
        return "当前未找到明确网申系统或提交入口；项目详情页不能当作申请入口，正式时间线需要补齐网申来源。"
    return "当前信息来自项目库抽取或规则推断，正式展示前需要回到项目详情页、PDF/FAQ 或申请系统确认。"

def _field_status(program: Program, field_name: str, value: str | None) -> FieldVerificationStatus:
    if field_name == "official_program_url" and not has_program_detail_page(program):
        return FieldVerificationStatus.model_inferred
    if not value or value == "NOT_PUBLISHED":
        return FieldVerificationStatus.not_published
    if program.last_verified_at and program.data_status == DataStatus.verified:
        return FieldVerificationStatus.official_verified_current
    if program.data_status == DataStatus.stale and field_name in {"deadline", "tuition_hkd", "materials", "language_requirement", "application_url", "official_program_url"}:
        return FieldVerificationStatus.official_previous_cycle
    return FieldVerificationStatus.model_inferred


def _status_from_legacy(status: DataStatus, source_type: str) -> FieldVerificationStatus:
    if "community" in source_type:
        return FieldVerificationStatus.community_only
    if status == DataStatus.verified:
        return FieldVerificationStatus.official_verified_current
    if status == DataStatus.not_published:
        return FieldVerificationStatus.not_published
    if status == DataStatus.changed:
        return FieldVerificationStatus.conflicted
    if status == DataStatus.stale:
        return FieldVerificationStatus.official_previous_cycle
    if status in {DataStatus.extracted, DataStatus.pending_review, DataStatus.discovered}:
        return FieldVerificationStatus.model_inferred
    return FieldVerificationStatus.model_inferred


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _source_priority(source_type: str) -> int:
    priority = {
        "official_application_system": 1,
        "official_admissions_page": 1,
        "official_program_page": 2,
        "official_pdf": 3,
        "official_faq": 3,
        "official_pdf_or_faq": 3,
        "official_program_index": 4,
        "ranking_or_directory": 5,
        "community_signal": 6,
        "community_result": 6,
    }
    return priority.get(source_type, 99)
