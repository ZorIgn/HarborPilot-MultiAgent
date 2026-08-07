"""Deterministic review-gate policy used by the CriticAgent's tools."""

from __future__ import annotations

from typing import Any

from harbor_agent.models import ProgramMatch, WritingDraft
from harbor_agent.services.formal_gate import CRITICAL_TIMELINE_FIELDS, program_field_gate


def run_review_gate(matches: list[ProgramMatch], writing: WritingDraft) -> dict[str, Any]:
    """Evaluate fixed admissions, source and writing gates without routing decisions."""

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
    unbound_warning = (
        "文书草稿还缺少足够的事实绑定，不能作为最终提交稿。"
        if len(writing.fact_bindings) < 2
        else "文书草稿已有基础事实绑定，提交前仍需逐句核对学生事实和项目官网依据。"
    )
    passed = not hard_violations and not programs_requiring_current_cycle_review and not writing.review_flags
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
        "human_gates": [
            "正式提交倒推必须同时具备项目详情页、截止日期、申请入口、语言要求、材料清单和学费的字段级当前季官网证据。",
            "只有上一申请季证据时，只能生成带年份标注的准备动作，不能生成正式 DDL 倒推。",
            "社区、GitHub、论坛和第三方表格只作为线索，不能替代学校官网要求。",
            "学校定制文书句必须绑定项目官网、PDF/FAQ 或网申系统证据。",
        ],
    }
