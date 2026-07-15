from __future__ import annotations

from datetime import UTC, datetime, timedelta

from harbor_agent.models import FieldEvidenceRecord, FieldVerificationStatus
from harbor_agent.services.evidence_graph import _primary_records_by_field


def _record(status: FieldVerificationStatus, value: str, when: datetime) -> FieldEvidenceRecord:
    return FieldEvidenceRecord(
        program_id="demo-program",
        field_name="deadline",
        value=value,
        cycle="2027-fall",
        source_url="https://www.hku.hk/programme",
        source_type="official_program_page",
        extracted_at=when,
        verified_at=when,
        page_hash="sha256:" + value,
        confidence="high",
        source_priority=1,
        status=status,
        review_required=status != FieldVerificationStatus.official_verified_current,
        evidence_snippet=value,
    )


def test_newer_conflict_blocks_an_older_verified_value() -> None:
    now = datetime.now(UTC)
    verified = _record(FieldVerificationStatus.official_verified_current, "2027-01-10", now - timedelta(days=1))
    conflict = _record(FieldVerificationStatus.conflicted, "2027-01-20", now)

    primary = _primary_records_by_field([verified, conflict])

    assert primary[0].status == FieldVerificationStatus.conflicted
    assert primary[0].value == "2027-01-20"


def test_newer_verified_value_supersedes_an_old_conflict() -> None:
    now = datetime.now(UTC)
    conflict = _record(FieldVerificationStatus.conflicted, "2027-01-20", now - timedelta(days=1))
    verified = _record(FieldVerificationStatus.official_verified_current, "2027-01-25", now)

    primary = _primary_records_by_field([conflict, verified])

    assert primary[0].status == FieldVerificationStatus.official_verified_current
    assert primary[0].value == "2027-01-25"
