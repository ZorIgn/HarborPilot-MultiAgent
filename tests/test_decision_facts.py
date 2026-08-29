from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from harbor_agent.models import (
    ApplicantProfileInput,
    DecisionStatus,
    FactProvenanceStatus,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    SourceScope,
)
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.decision_coverage import build_decision_coverage_summary
from harbor_agent.services.deterministic_profile import normalize_profile
from harbor_agent.services import data_loader, program_store
from harbor_agent.services.formal_gate import formal_recommendation_ready, program_field_gate
from harbor_agent.services.program_store import upsert_field_evidence_records
from harbor_agent.services.resolved_program import (
    decision_fact_value,
    materialize_decision_program,
    resolve_program_view,
)
from harbor_agent.tools.constraint_tools import (
    admissions_eligibility_checks,
    financial_feasibility,
)


TARGET_CYCLE = "2027-fall"
VERIFIED_AT = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture
def stored_program():
    """Seed one catalogue row into the test SQLite store and return it."""

    data_loader.clear_data_loader_caches()
    program = _program()
    program_store.seed_program_store(
        [program],
        db_path=program_store.DB_PATH,
        replace=True,
    )
    data_loader.clear_data_loader_caches()
    return program


def _program():
    return next(
        item
        for item in load_programs()
        if item.id == "cuhk-msc-in-computer-science-2027"
    )


def _valid_record(program_id: str, field_name: str, value: str, **overrides) -> FieldEvidenceRecord:
    payload = {
        "program_id": program_id,
        "field_name": field_name,
        "value": value,
        "cycle": TARGET_CYCLE,
        "source_url": "https://www.example.edu/programmes/cuhk-cs",
        "source_type": "official_program_page",
        "extracted_at": VERIFIED_AT,
        "verified_at": VERIFIED_AT,
        "page_hash": "sha256:test-current-page",
        "confidence": "high",
        "source_priority": 1,
        "status": FieldVerificationStatus.official_verified_current,
        "review_required": False,
        "reviewer_id": "reviewer-test",
        "evidence_snippet": f"Current official value for {field_name}: {value}",
        "snapshot_url": "https://snapshots.example.edu/cuhk-cs.html",
        "source_scope": SourceScope.programme_detail,
        "binding_status": "matched",
        "binding_score": 98,
        "review_decision_id": f"review-decision-{field_name}",
        "execution_ref": None,
    }
    payload.update(overrides)
    return FieldEvidenceRecord(**payload)


def _upsert(records: list[FieldEvidenceRecord]) -> None:
    assert upsert_field_evidence_records(records) == len(records)


def _full_current_records(program) -> list[FieldEvidenceRecord]:
    return [
        _valid_record(program.id, "official_program_url", "https://www.example.edu/programmes/cuhk-cs"),
        _valid_record(
            program.id,
            "application_url",
            "https://www.example.edu/apply/cuhk-cs",
            source_scope=SourceScope.application_portal,
            source_url="https://www.example.edu/apply/cuhk-cs",
            snapshot_url="https://snapshots.example.edu/cuhk-cs-application.html",
            page_hash="sha256:test-current-application-page",
        ),
        _valid_record(program.id, "deadline", "2027-03-15"),
        _valid_record(program.id, "tuition_hkd", "HKD 180000"),
        _valid_record(program.id, "min_gpa", "82"),
        _valid_record(program.id, "language_requirement", "IELTS 6.5; TOEFL 79"),
        _valid_record(program.id, "required_backgrounds", "computing"),
        _valid_record(program.id, "portfolio_required", "false"),
        _valid_record(program.id, "materials", "transcript, recommendation, CV, personal_statement"),
    ]


def test_seed_values_without_current_evidence_are_unknown_and_cannot_hard_block_budget(stored_program) -> None:
    program = stored_program
    view = resolve_program_view(program)

    for field_name in ("min_gpa", "language_requirement", "tuition_hkd"):
        fact = view.fact(field_name)
        assert fact.decision_status == DecisionStatus.UNKNOWN
        assert fact.formal_use_ready is False
        assert fact.normalized_value is None
        assert fact.provenance_status == FactProvenanceStatus.UNVERIFIED

    profile = normalize_profile(
        ApplicantProfileInput.model_validate_json(
            Path("examples/sample_profile.json").read_text(encoding="utf-8")
        )
    )
    admission_checks = admissions_eligibility_checks(profile, view)
    fact_checks = {
        item.check_id: item
        for item in admission_checks
        if item.check_id.startswith("fact_")
    }
    assert fact_checks
    assert all(item.status == DecisionStatus.UNKNOWN for item in fact_checks.values())

    feasibility = financial_feasibility(view, budget_hkd=1, budget_mode="hard_cap")
    assert feasibility.status == DecisionStatus.UNKNOWN
    assert feasibility.financial_status.value == "UNKNOWN"
    assert feasibility.tuition_hkd is None
    assert feasibility.blocks_user_selection is False


@pytest.mark.parametrize(
    ("missing_field", "replacement"),
    [
        ("source_scope", None),
        ("review_required", True),
        ("binding_status", "weak_match"),
        ("snapshot_url", None),
        ("page_hash", None),
        ("reviewer_id", None),
        ("review_decision_id", None),
        ("verified_at", None),
    ],
)
def test_missing_formal_provenance_condition_never_becomes_decision_fact(
    missing_field: str,
    replacement,
    stored_program,
) -> None:
    program = stored_program
    record = _valid_record(
        program.id,
        "tuition_hkd",
        "180000",
        **{missing_field: replacement},
    )

    _upsert([record])
    view = resolve_program_view(program)
    fact = view.fact("tuition_hkd")

    assert fact.decision_status == DecisionStatus.UNKNOWN
    assert fact.formal_use_ready is False
    assert fact.normalized_value is None
    assert fact.provenance_status != FactProvenanceStatus.VERIFIED_CURRENT
    assert fact.blockers


def test_current_reviewed_evidence_overrides_catalog_seed_values(stored_program) -> None:
    program = stored_program
    records = [
        _valid_record(program.id, "min_gpa", "86"),
        _valid_record(program.id, "language_requirement", '{"IELTS": 7.0}'),
        _valid_record(program.id, "tuition_hkd", "HKD 180000"),
    ]

    _upsert(records)
    view = resolve_program_view(program)

    assert view.fact("min_gpa").decision_status == DecisionStatus.PASS
    assert view.fact("min_gpa").normalized_value == 86
    assert view.fact("language_requirement").normalized_value == {"IELTS": 7.0}
    assert view.fact("tuition_hkd").normalized_value == 180000
    assert all(view.fact(field).formal_use_ready for field in ("min_gpa", "language_requirement", "tuition_hkd"))

    # Compatibility consumers receive only resolved values; the catalog seed
    # remains available on ``view.catalog`` for discovery/UI rendering.
    decision_program = materialize_decision_program(view)
    assert decision_program.tuition_hkd == 180000
    assert decision_program.requirements.min_gpa == 86
    assert decision_program.requirements.language == {"IELTS": 7.0}


def test_non_100_scale_gpa_never_becomes_a_hard_predicate_without_reviewed_normalization(stored_program) -> None:
    program = stored_program
    raw_scale_record = _valid_record(
        program.id,
        "min_gpa",
        "3.6/4.0",
        evidence_snippet="Minimum GPA 3.6/4.0.",
    )

    _upsert([raw_scale_record])
    fact = resolve_program_view(program).fact("min_gpa")

    assert fact.decision_status == DecisionStatus.UNKNOWN
    assert fact.formal_use_ready is False
    assert fact.normalized_value is None
    assert any("规范化" in blocker or "类型" in blocker for blocker in fact.blockers)


def test_reviewed_empty_background_list_means_no_hard_background_restriction(stored_program) -> None:
    program = stored_program
    record = _valid_record(program.id, "required_backgrounds", "[]")

    _upsert([record])
    fact = resolve_program_view(program).fact("required_backgrounds")

    assert fact.decision_status == DecisionStatus.PASS
    assert fact.formal_use_ready is True
    assert fact.normalized_value == []


def test_two_current_values_produce_stable_conflict_and_unknown_fact(stored_program) -> None:
    program = stored_program
    first = _valid_record(
        program.id,
        "tuition_hkd",
        "180000",
        evidence_id="evidence-tuition-a",
        page_hash="sha256:page-a",
    )
    second = _valid_record(
        program.id,
        "tuition_hkd",
        "200000",
        evidence_id="evidence-tuition-b",
        page_hash="sha256:page-b",
        source_priority=2,
        review_decision_id="review-decision-tuition-b",
    )

    _upsert([first, second])
    first_view = resolve_program_view(program)
    reversed_view = resolve_program_view(program)
    first_fact = first_view.fact("tuition_hkd")
    reversed_fact = reversed_view.fact("tuition_hkd")

    assert first_fact.decision_status == DecisionStatus.UNKNOWN
    assert first_fact.formal_use_ready is False
    assert first_fact.provenance_status == FactProvenanceStatus.CONFLICTED
    assert first_fact.normalized_value is None
    assert first_fact.conflict_id
    assert first_fact.conflict_id == reversed_fact.conflict_id
    assert first_view.conflict_ids == [first_fact.conflict_id]


def test_previous_cycle_evidence_is_reference_only(stored_program) -> None:
    program = stored_program
    previous = _valid_record(
        program.id,
        "deadline",
        "2026-03-15",
        cycle="2026-fall",
        status=FieldVerificationStatus.official_previous_cycle,
        review_decision_id="review-decision-previous",
    )

    _upsert([previous])
    view = resolve_program_view(program)
    fact = view.fact("deadline")

    assert fact.decision_status == DecisionStatus.UNKNOWN
    assert fact.formal_use_ready is False
    assert fact.normalized_value is None
    assert fact.provenance_status == FactProvenanceStatus.REVIEWED_PREVIOUS
    assert any("往届" in blocker or "当前季" in blocker for blocker in fact.blockers)


def test_upserted_current_evidence_is_resolved_without_catalog_reseed(stored_program) -> None:
    program = stored_program
    before = resolve_program_view(program).fact("deadline")
    assert before.decision_status == DecisionStatus.UNKNOWN

    record = _valid_record(program.id, "deadline", "2027-03-15")
    assert upsert_field_evidence_records([record]) == 1

    after = resolve_program_view(program)
    fact = after.fact("deadline")
    assert fact.decision_status == DecisionStatus.PASS
    assert fact.formal_use_ready is True
    assert fact.normalized_value == "2027-03-15"
    assert fact.evidence_id
    assert fact.evidence_id != before.evidence_id


def test_decision_coverage_reports_catalog_without_formal_coverage(stored_program) -> None:
    program = stored_program
    summary = build_decision_coverage_summary([program], cycle=TARGET_CYCLE)

    assert summary.program_count == 1
    assert summary.formal_ready_program_count == 0
    assert summary.community_signal_collection_status == "NOT_COLLECTED"
    assert summary.programs_with_community_signals == 0
    assert summary.required_field_formal_coverage
    assert all(value == 0 for value in summary.required_field_formal_coverage.values())
    assert summary.decision_fact_status_breakdown.get(FactProvenanceStatus.UNVERIFIED.value, 0) > 0
    assert any("catalog" in blocker for blocker in summary.blockers)
    assert any("尚未收集" in blocker for blocker in summary.blockers)


def test_formal_recommendation_gate_requires_every_canonical_field(stored_program) -> None:
    program = stored_program
    _upsert(_full_current_records(program))

    view = resolve_program_view(program)
    gate = program_field_gate(view)

    assert gate["formal_recommendation_ready"] is True
    assert gate["formal_use_ready"] is True
    assert gate["formal_missing_or_blocked_fields"] == []
    assert formal_recommendation_ready(view) is True


def test_formal_recommendation_gate_fails_closed_for_missing_field(stored_program) -> None:
    program = stored_program
    _upsert(
        [
            record
            for record in _full_current_records(program)
            if record.field_name != "materials"
        ]
    )

    view = resolve_program_view(program)
    gate = program_field_gate(view)

    assert gate["formal_recommendation_ready"] is False
    assert formal_recommendation_ready(view) is False
    assert "materials" in gate["formal_missing_or_blocked_fields"]
    assert any("materials:" in blocker for blocker in gate["formal_blockers"])


def test_formal_recommendation_gate_fails_closed_for_conflicted_field(stored_program) -> None:
    program = stored_program
    records = _full_current_records(program)
    records.extend(
        [
            _valid_record(
                program.id,
                "tuition_hkd",
                "HKD 200000",
                evidence_id="evidence-tuition-conflict",
                page_hash="sha256:conflict-page",
                source_priority=2,
                review_decision_id="review-decision-tuition-conflict",
            )
        ]
    )
    _upsert(records)

    view = resolve_program_view(program)
    gate = program_field_gate(view)

    assert view.fact("tuition_hkd").decision_status == DecisionStatus.UNKNOWN
    assert gate["formal_recommendation_ready"] is False
    assert "tuition_hkd" in gate["formal_missing_or_blocked_fields"]


def test_formal_recommendation_gate_rejects_empty_materials_in_hand_built_view(stored_program) -> None:
    program = stored_program
    _upsert(_full_current_records(program))
    view = resolve_program_view(program)
    facts = dict(view.facts)
    facts["materials"] = facts["materials"].model_copy(update={"normalized_value": []})
    stale_view = view.model_copy(
        update={
            "facts": facts,
            "formal_readiness": DecisionStatus.PASS,
            "formal_blockers": [],
        }
    )

    gate = program_field_gate(stale_view)

    assert gate["formal_recommendation_ready"] is False
    assert "materials" in gate["formal_missing_or_blocked_fields"]


def test_formal_recommendation_gate_accepts_reviewed_empty_backgrounds(stored_program) -> None:
    program = stored_program
    records = _full_current_records(program)
    records = [
        _valid_record(program.id, "required_backgrounds", "[]")
        if record.field_name == "required_backgrounds"
        else record
        for record in records
    ]
    _upsert(records)

    gate = program_field_gate(resolve_program_view(program))

    assert gate["formal_recommendation_ready"] is True
