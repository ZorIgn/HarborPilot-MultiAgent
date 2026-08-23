"""Deterministic review-gate policy used by the CriticAgent's tools."""

from __future__ import annotations

from typing import Any

from harbor_agent.models import ProgramMatch, WritingDraft
from harbor_agent.services.claim_graph import build_claim_graph, claim_graph_passed
from harbor_agent.services.formal_gate import CRITICAL_TIMELINE_FIELDS, program_field_gate


def run_review_gate(
    matches: list[ProgramMatch],
    writing: WritingDraft | None,
    *,
    writing_ready: bool = False,
    writing_required: bool = True,
) -> dict[str, Any]:
    """Evaluate fixed admissions, source and writing gates without routing.

    A legacy caller cannot obtain a formal pass merely by sending an empty
    ``review_flags`` array.  When writing is in scope, a separate runtime
    ClaimGraph validation turn must have set ``writing_ready`` and the graph
    must still pass when rebuilt from current DecisionFacts.
    """

    active_matches = [item for item in matches if item.tier != "not_recommended"]
    hard_violations = [item.program.id for item in active_matches if not item.hard_rule_passed]
    field_gates = {item.program.id: program_field_gate(item.program) for item in active_matches}
    programs_with_missing_or_blocked_fields = [
        program_id
        for program_id, gate in field_gates.items()
        if gate["missing_or_blocked_fields"]
    ]
    timeline_blockers = {
        program_id: gate["missing_or_blocked_fields"]
        for program_id, gate in field_gates.items()
        if gate["missing_or_blocked_fields"]
    }
    previous_cycle_reference_fields = {
        program_id: gate["previous_cycle_fields"]
        for program_id, gate in field_gates.items()
        if gate["previous_cycle_fields"]
    }
    programs_requiring_current_cycle_review = sorted(
        set(programs_with_missing_or_blocked_fields) | set(previous_cycle_reference_fields)
    )
    graph = build_claim_graph(writing, matches) if writing is not None else None
    claim_grounding_ready = claim_graph_passed(graph)
    writing_blockers = list(graph.blockers) if graph is not None else ["writing draft is missing"]
    if writing_required and not writing_ready:
        writing_blockers.append("WritingAgent 尚未完成独立 ClaimGraph 验证。")
    writing_blockers = list(dict.fromkeys(writing_blockers))
    unbound_warning = (
        "文书尚未通过 ClaimGraph 与独立 runtime 验证，不能作为最终提交稿。"
        if writing_required and (not writing_ready or not claim_grounding_ready)
        else "文书 ClaimGraph 已通过；提交前仍需按正式交付状态复核。"
    )
    passed = (
        not hard_violations
        and not programs_requiring_current_cycle_review
        and (not writing_required or (writing_ready and claim_grounding_ready and not writing_blockers))
    )
    return {
        "passed": passed,
        "status_label": "可进入正式申请使用" if passed else "关键字段核验完成前不能作为正式申请计划",
        "hard_rule_violations": hard_violations,
        "programs_requiring_data_review": programs_requiring_current_cycle_review,
        "programs_with_missing_or_blocked_fields": programs_with_missing_or_blocked_fields,
        "programs_requiring_current_cycle_review": programs_requiring_current_cycle_review,
        "timeline_blockers": timeline_blockers,
        "previous_cycle_reference_fields": previous_cycle_reference_fields,
        "required_timeline_fields": CRITICAL_TIMELINE_FIELDS,
        "writing_review": unbound_warning,
        "writing_ready": writing_ready,
        "claim_grounding_ready": claim_grounding_ready,
        "claim_graph": graph.model_dump(mode="json") if graph is not None else None,
        "blockers": writing_blockers,
        "human_gates": [
            "正式提交倒推必须同时具备项目详情页、截止日期、申请入口、语言要求、材料清单和学费的字段级当前季官网证据。",
            "只有上一申请季证据时，只能生成带年份标注的准备动作，不能生成正式 DDL 倒推。",
            "社区、GitHub、论坛和第三方表格只作为线索，不能替代学校官网要求。",
            "学校定制文书句必须绑定项目官网、PDF/FAQ 或网申系统证据。",
        ],
    }
