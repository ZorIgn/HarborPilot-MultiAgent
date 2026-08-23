from __future__ import annotations

from datetime import date, datetime
import re

from harbor_agent.models import DecisionStatus, FieldEvidenceRecord, Program, ProgramMatch, ResolvedProgramView
from harbor_agent.services.field_contract import CRITICAL_TIMELINE_FIELDS, FORMAL_RECOMMENDATION_FIELDS
from harbor_agent.services.program_store import load_field_evidence_records
from harbor_agent.services.resolved_program import resolve_program_view

# Retain a list-valued compatibility export for existing API consumers.
CRITICAL_TIMELINE_FIELDS = list(CRITICAL_TIMELINE_FIELDS)


def program_field_gate(
    program: Program | ResolvedProgramView,
) -> dict[str, object]:
    """Evaluate the timeline gate from canonical decision facts only."""

    view = _resolved_view(program)
    current_fields: list[str] = []
    previous_cycle_fields: list[str] = []
    missing_or_blocked: list[str] = []
    field_status: dict[str, str] = {}

    for field in CRITICAL_TIMELINE_FIELDS:
        fact = view.fact(field)
        field_status[field] = fact.provenance_status.value
        if fact.provenance_status.value == "REVIEWED_PREVIOUS":
            previous_cycle_fields.append(field)
            continue
        if fact.decision_status != DecisionStatus.PASS:
            missing_or_blocked.append(field)
            continue
        if field == "deadline" and _parse_date_value(str(fact.normalized_value)) is None:
            missing_or_blocked.append(field)
            continue
        if fact.formal_use_ready:
            current_fields.append(field)
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
    gate = program_field_gate(_view_from_match(match))
    return bool(gate["production_ready"])


def formal_timeline_blockers(match: ProgramMatch) -> list[str]:
    gate = program_field_gate(_view_from_match(match))
    return list(gate["missing_or_blocked_fields"])


def primary_record(program: Program, field_name: str) -> FieldEvidenceRecord | None:
    fact = resolve_program_view(program).fact(field_name)
    if not fact.formal_use_ready or not fact.evidence_id:
        return None
    return next(
        (
            record
            for record in load_field_evidence_records([program.id])
            if record.evidence_id == fact.evidence_id
        ),
        None,
    )

def accepted_field_record(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> FieldEvidenceRecord | None:
    # ``include_previous`` is retained for API compatibility only.  Previous
    # cycle values may be displayed as references elsewhere, but cannot be
    # returned through this formal-decision API.
    del include_previous
    return primary_record(program, field_name)


def accepted_field_value(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> str | None:
    del include_previous
    fact = resolve_program_view(program).fact(field_name)
    if not fact.formal_use_ready or fact.normalized_value is None:
        return None
    if isinstance(fact.normalized_value, (list, dict)):
        import json

        return json.dumps(fact.normalized_value, ensure_ascii=False, sort_keys=True)
    return str(fact.normalized_value)


def accepted_url(
    program: Program,
    field_name: str,
    *,
    include_previous: bool = True,
) -> str | None:
    del include_previous
    return accepted_field_value(program, field_name)


def accepted_deadline(
    program: Program,
    *,
    include_previous: bool = True,
) -> date | None:
    del include_previous
    value = accepted_field_value(program, "deadline")
    parsed = _parse_date_value(value)
    if parsed:
        return parsed
    return None


def _resolved_view(program: Program | ResolvedProgramView) -> ResolvedProgramView:
    return program if isinstance(program, ResolvedProgramView) else resolve_program_view(program)


def _view_from_match(match: ProgramMatch) -> ResolvedProgramView:
    # Rebuild from the persisted canonical store so a stale checkpoint cannot
    # keep an old seed-derived readiness decision alive after a revocation.
    return resolve_program_view(match.program)


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
