"""Honest, database-derived coverage metrics for formal programme decisions."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from harbor_agent.models import (
    DecisionCoverageSummary,
    FieldVerificationStatus,
    Program,
)
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.program_store import load_field_evidence_records
from harbor_agent.services.field_contract import FORMAL_RECOMMENDATION_FIELDS
from harbor_agent.services.resolved_program import resolve_program_views


def build_decision_coverage_summary(
    programs: list[Program] | None = None,
    *,
    cycle: str | None = None,
) -> DecisionCoverageSummary:
    """Measure what is formally usable, not how many seed values exist."""

    program_list = programs if programs is not None else load_programs()
    records = load_field_evidence_records([program.id for program in program_list])
    views = resolve_program_views(program_list, evidence_records=records, cycle=cycle)
    facts = [fact for view in views.values() for fact in view.facts.values()]
    fact_status = Counter(fact.provenance_status.value for fact in facts)
    coverage: dict[str, int] = {}
    for field_name in FORMAL_RECOMMENDATION_FIELDS:
        denominator = len(program_list) or 1
        ready = sum(
            view.fact(field_name).formal_use_ready for view in views.values()
        )
        coverage[field_name] = round(ready / denominator * 100)
    community_programs = sum(bool(program.community_signals) for program in program_list)
    community_state = (
        "NOT_COLLECTED"
        if community_programs == 0
        else "PRESENT"
        if community_programs == len(program_list)
        else "PARTIAL"
    )
    formal_ready = sum(
        view.formal_readiness.value == "PASS" for view in views.values()
    )
    blockers = []
    if formal_ready == 0 and program_list:
        blockers.append(
            "当前 catalog 没有项目完成全部当前季字段级正式核验；catalog 覆盖不能表述为正式推荐覆盖。"
        )
    missing_scope = sum(record.source_scope is None for record in records)
    if missing_scope:
        blockers.append(f"{missing_scope} 条来源记录缺少 source_scope，不能用于字段级正式 gate。")
    if community_programs == 0:
        blockers.append("community_signals 为 0 表示尚未收集，不表示项目不存在社区信息。")
    return DecisionCoverageSummary(
        generated_at=datetime.now(UTC),
        cycle=cycle,
        program_count=len(program_list),
        formal_ready_program_count=formal_ready,
        decision_fact_status_breakdown=dict(fact_status),
        required_field_formal_coverage=coverage,
        current_verified_record_count=sum(
            record.status == FieldVerificationStatus.official_verified_current
            and not record.review_required
            for record in records
        ),
        pending_review_record_count=sum(record.review_required for record in records),
        records_missing_source_scope=missing_scope,
        programs_with_community_signals=community_programs,
        community_signal_collection_status=community_state,
        blockers=blockers,
    )
