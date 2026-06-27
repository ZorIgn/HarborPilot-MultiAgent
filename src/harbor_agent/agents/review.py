from __future__ import annotations

from typing import Any

from harbor_agent.models import ProgramMatch, WritingDraft


class ReviewAgent:
    name = "ReviewAgent"

    def run(self, matches: list[ProgramMatch], writing: WritingDraft) -> dict[str, Any]:
        active_matches = [item for item in matches if item.tier != "not_recommended"]
        hard_violations = [
            item.program.id
            for item in active_matches
            if not item.hard_rule_passed
        ]
        stale_or_uncertain = [
            item.program.id
            for item in active_matches
            if item.program.source.field_coverage != "complete"
            or item.program.deadline == "NOT_PUBLISHED"
            or item.program.data_status.value != "VERIFIED"
        ]
        unbound_warning = (
            "文书草稿需要绑定更多可验证事实，暂不建议直接导出。"
            if len(writing.fact_bindings) < 2
            else "文书草稿已建立基础事实绑定，但仍需逐句核对。"
        )
        passed = not hard_violations and not stale_or_uncertain and not writing.review_flags

        return {
            "passed": passed,
            "status_label": "可进入正式申请使用" if passed else "仍需确认后再使用",
            "hard_rule_violations": hard_violations,
            "programs_requiring_data_review": stale_or_uncertain,
            "writing_review": unbound_warning,
            "human_gates": [
                "最终规划前，逐项打开学校官网确认截止日期、学费、语言、材料和申请入口。",
                "进入正式评估前，逐条确认学生事实和上传材料。",
                "社区、GitHub、论坛和第三方表格只能作为线索，不能替代学校官网要求。",
            ],
        }
