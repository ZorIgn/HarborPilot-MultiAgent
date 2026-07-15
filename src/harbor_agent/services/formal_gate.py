from __future__ import annotations

from datetime import date, datetime
import re

from harbor_agent.models import FieldEvidenceRecord, FieldVerificationStatus, Program, ProgramMatch
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.program_urls import student_application_url, student_program_url

CRITICAL_TIMELINE_FIELDS = [
    "official_program_url",
    "deadline",
    "application_url",
    "language_requirement",
    "materials",
    "tuition_hkd",
]


def program_field_gate(program: Program) -> dict[str, object]:
    trust = build_program_trust_detail(program)
    by_field = {record.field_name: record for record in trust.field_records}
    current_fields: list[str] = []
    previous_cycle_fields: list[str] = []
    missing_or_blocked: list[str] = []
    field_status: dict[str, str] = {}

    for field in CRITICAL_TIMELINE_FIELDS:
        record = by_field.get(field)
        field_status[field] = record.status.value if record else "MISSING"
        if record is None or not _has_publishable_value(record):
            missing_or_blocked.append(field)
            continue
        if field == "deadline" and _parse_date_value(str(record.value)) is None:
            missing_or_blocked.append(field)
            continue
        if record.status == FieldVerificationStatus.official_verified_current and not record.review_required:
            current_fields.append(field)
            continue
        if record.status == FieldVerificationStatus.official_previous_cycle:
            previous_cycle_fields.append(field)
            continue
        missing_or_blocked.append(field)

    missing_unique = sorted(set(missing_or_blocked))
    production_ready = not missing_unique and sorted(current_fields) == sorted(CRITICAL_TIMELINE_FIELDS)
    reference_ready = (
        not production_ready
        and not missing_unique
        and sorted(current_fields + previous_cycle_fields) == sorted(CRITICAL_TIMELINE_FIELDS)
    )
    return {
        "production_ready": production_ready,
        "reference_ready": reference_ready,
        "current_fields": current_fields,
        "previous_cycle_fields": previous_cycle_fields,
        "missing_or_blocked_fields": missing_unique,
        "field_status": field_status,
    }


def formal_timeline_ready(match: ProgramMatch) -> bool:
    gate = program_field_gate(match.program)
    return bool(gate["production_ready"])


def formal_timeline_blockers(match: ProgramMatch) -> list[str]:
    gate = program_field_gate(match.program)
    return list(gate["missing_or_blocked_fields"])


def primary_record(program: Program, field_name: str) -> FieldEvidenceRecord | None:
    trust = build_program_trust_detail(program)
    return next((record for record in trust.field_records if record.field_name == field_name), None)

def accepted_field_record(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> FieldEvidenceRecord | None:
    record = primary_record(program, field_name)
    if record is None or not _has_publishable_value(record):
        return None
    if record.status == FieldVerificationStatus.official_verified_current and not record.review_required:
        return record
    if include_previous and record.status == FieldVerificationStatus.official_previous_cycle:
        return record
    return None


def accepted_field_value(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> str | None:
    record = accepted_field_record(program, field_name, include_previous=include_previous)
    if record is None or record.value is None:
        return None
    return str(record.value)


def accepted_url(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> str | None:
    value = accepted_field_value(program, field_name, include_previous=include_previous)
    if value:
        return value
    if field_name == "official_program_url":
        fallback = student_program_url(program)
    elif field_name == "application_url":
        fallback = student_application_url(program)
    else:
        fallback = None
    return str(fallback) if fallback else None


def accepted_deadline(
    program: Program,
    *,
    include_previous: bool = True,
) -> date | None:
    value = accepted_field_value(program, "deadline", include_previous=include_previous)
    parsed = _parse_date_value(value)
    if parsed:
        return parsed
    return None


def _has_publishable_value(record: FieldEvidenceRecord) -> bool:
    return bool(record.value and str(record.value).strip() and str(record.value).strip() != "NOT_PUBLISHED")


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    iso = re.search(r"20\d{2}[-/.][01]?\d[-/.][0-3]?\d", text)
    if iso:
        normalized = iso.group(0).replace("/", "-").replace(".", "-")
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            pass
    for pattern in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
        match = re.search(r"[0-3]?\d\s+[A-Za-z]{3,9}\s+20\d{2}|[A-Za-z]{3,9}\s+[0-3]?\d,?\s+20\d{2}", text)
        if not match:
            break
        candidate = match.group(0).replace(",", "")
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue
    return None
