from __future__ import annotations

import hashlib
from collections import Counter

from harbor_agent.models import DataStatus, EvidenceGraphSummary, FieldEvidenceRecord, FieldVerificationStatus, Program, ProgramTrustDetail
from harbor_agent.services.data_loader import load_programs, load_source_registry
from harbor_agent.services.review_store import load_published_field_records


PRODUCTION_FIELDS = [
    "program_name",
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
    "tuition_hkd",
    "materials",
    "language_requirement",
    "application_url",
    "scholarship_deadline",
    "essay_prompts",
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
    records.extend(
        record for record in load_published_field_records()
        if record.program_id in program_ids
    )
    return records


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
    status_label = "学校官网本季已确认" if production_ready else "仍需学校官网确认"
    if production_ready:
        source_warning = "关键申请字段均有本申请季学校官方来源，可作为正式申请计划依据。"
    else:
        source_warning = (
            f"{len(review_fields)} 个关键字段尚未完成本申请季学校官网确认；"
            "这些信息只能用于准备建议，不能包装成正式申请结论。"
        )

    return ProgramTrustDetail(
        program_id=program.id,
        cycle=program.cycle,
        production_ready=production_ready,
        status_label=status_label,
        source_warning=source_warning,
        official_current_fields=official_fields,
        fields_requiring_review=review_fields,
        stale_or_reference_fields=reference_fields,
        reviewer_gate_fields=gate_fields,
        last_official_verified_at=program.last_verified_at,
        field_records=field_records,
    )


def _primary_records_by_field(records: list[FieldEvidenceRecord]) -> list[FieldEvidenceRecord]:
    by_field: dict[str, FieldEvidenceRecord] = {}
    for record in records:
        current = by_field.get(record.field_name)
        if current is None or _record_sort_key(record) < _record_sort_key(current):
            by_field[record.field_name] = record
    return sorted(by_field.values(), key=lambda record: (record.source_priority, record.field_name))


def _record_for_field(records: list[FieldEvidenceRecord], field_name: str) -> FieldEvidenceRecord | None:
    return next((record for record in records if record.field_name == field_name), None)


def _record_sort_key(record: FieldEvidenceRecord) -> tuple[int, int, int, str]:
    status_rank = {
        FieldVerificationStatus.official_verified_current: 0,
        FieldVerificationStatus.official_previous_cycle: 1,
        FieldVerificationStatus.not_published: 2,
        FieldVerificationStatus.conflicted: 3,
        FieldVerificationStatus.community_only: 4,
        FieldVerificationStatus.model_inferred: 5,
    }.get(record.status, 9)
    review_rank = 1 if record.review_required else 0
    return (status_rank, record.source_priority, review_rank, record.page_hash or "")


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
                agent_chain=_agent_chain_for(
                    evidence.source_type,
                    _status_from_legacy(evidence.status, evidence.source_type),
                ),
            )
        )
    return records


def _synthetic_review_records(program: Program) -> list[FieldEvidenceRecord]:
    source_url = program.official_program_url or program.source.url
    extracted_at = program.source.captured_at
    values = {
        "deadline": str(program.deadline),
        "tuition_hkd": str(program.tuition_hkd) if program.tuition_hkd is not None else None,
        "materials": ", ".join(program.materials),
        "language_requirement": ", ".join(
            f"{name} {score}" for name, score in program.requirements.language.items()
        ),
        "application_url": str(program.application_url) if program.application_url else None,
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
                evidence_snippet=(
                    "当前信息来自项目库抽取或规则推断，正式展示前需要回到项目页、PDF/FAQ 或申请系统确认。"
                ),
                snapshot_url=source_url,
                agent_chain=_agent_chain_for("official_program_index", _field_status(program, field_name, value)),
            )
        )
    return records


def _field_status(program: Program, field_name: str, value: str | None) -> FieldVerificationStatus:
    if not value or value == "NOT_PUBLISHED":
        return FieldVerificationStatus.not_published
    if program.last_verified_at and program.data_status == DataStatus.verified:
        return FieldVerificationStatus.official_verified_current
    if field_name in {"deadline", "tuition_hkd", "materials", "language_requirement", "application_url"}:
        return FieldVerificationStatus.official_previous_cycle
    return _status_from_legacy(program.data_status, "official_program_index")


def _status_from_legacy(status: DataStatus, source_type: str) -> FieldVerificationStatus:
    if "community" in source_type:
        return FieldVerificationStatus.community_only
    if status == DataStatus.verified:
        return FieldVerificationStatus.official_verified_current
    if status == DataStatus.not_published:
        return FieldVerificationStatus.not_published
    if status == DataStatus.changed:
        return FieldVerificationStatus.conflicted
    if status in {DataStatus.extracted, DataStatus.pending_review, DataStatus.stale, DataStatus.discovered}:
        return FieldVerificationStatus.official_previous_cycle
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


def _agent_chain_for(source_type: str, status: FieldVerificationStatus) -> list[str]:
    chain = ["SourceDiscoveryAgent", "PageFetchAgent", "FieldExtractionAgent"]
    if source_type.startswith("official"):
        chain.append("CrossCheckAgent")
    else:
        chain.append("CommunitySignalAgent")
    chain.append("HumanReviewAgent" if status != FieldVerificationStatus.official_verified_current else "AuditAgent")
    return chain
