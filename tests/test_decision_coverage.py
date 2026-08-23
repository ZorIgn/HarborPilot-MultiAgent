from __future__ import annotations

import pytest

from harbor_agent.services import data_loader, program_store
from harbor_agent.services.decision_coverage import build_decision_coverage_summary
from harbor_agent.services.resolved_program import FORMAL_RECOMMENDATION_FIELDS

from test_decision_facts import _full_current_records, _upsert


@pytest.fixture
def stored_program():
    data_loader.clear_data_loader_caches()
    program = next(
        item
        for item in data_loader.load_programs()
        if item.id == "cuhk-msc-in-computer-science-2027"
    )
    program_store.seed_program_store(
        [program],
        db_path=program_store.DB_PATH,
        replace=True,
    )
    data_loader.clear_data_loader_caches()
    return program


def test_decision_coverage_reports_zero_formal_coverage_and_not_collected_community(
    stored_program,
) -> None:
    summary = build_decision_coverage_summary(programs=[stored_program], cycle="2027-fall")

    assert summary.program_count == 1
    assert summary.formal_ready_program_count == 0
    assert summary.current_verified_record_count == 0
    assert summary.required_field_formal_coverage == {
        field_name: 0 for field_name in FORMAL_RECOMMENDATION_FIELDS
    }
    assert summary.programs_with_community_signals == 0
    assert summary.community_signal_collection_status == "NOT_COLLECTED"
    assert any("没有项目完成" in blocker for blocker in summary.blockers)
    assert any("尚未收集" in blocker for blocker in summary.blockers)


def test_decision_coverage_counts_only_persisted_current_reviewed_facts(stored_program) -> None:
    _upsert(_full_current_records(stored_program))

    summary = build_decision_coverage_summary(programs=[stored_program], cycle="2027-fall")

    assert summary.program_count == 1
    assert summary.formal_ready_program_count == 1
    assert summary.current_verified_record_count == 9
    assert summary.pending_review_record_count == 0
    assert summary.records_missing_source_scope == 0
    assert summary.required_field_formal_coverage == {
        field_name: 100 for field_name in FORMAL_RECOMMENDATION_FIELDS
    }
    assert summary.decision_fact_status_breakdown["VERIFIED_CURRENT"] >= 9
    assert summary.programs_with_community_signals == 0
    assert summary.community_signal_collection_status == "NOT_COLLECTED"
