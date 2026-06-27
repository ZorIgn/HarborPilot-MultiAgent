from __future__ import annotations

from datetime import datetime, timezone

from harbor_agent.models import (
    CommunitySignal,
    DataRefreshReport,
    DataStatus,
    NormalizedProfile,
    Program,
    ProgramMatch,
)
from harbor_agent.services.data_loader import load_community_sources, load_programs
from harbor_agent.services.intent import build_intent_profile, classify_program_intent


class ProgramIntelligenceAgent:
    name = "ProgramIntelligenceAgent"

    def run(self, profile: NormalizedProfile, limit: int = 80) -> list[Program]:
        intent_profile = build_intent_profile(profile)
        programs = [
            program
            for program in load_programs()
            if program.cycle == profile.target_cycle
            and program.country in profile.target_regions
            and program.degree_type == "taught_master"
        ]
        community_signals = _community_signals()
        viable: list[tuple[int, Program]] = []
        blocked: list[tuple[int, Program]] = []
        for program in programs:
            classification = classify_program_intent(profile, program, intent_profile)
            overlap = len(set(program.discipline_tags) & set(profile.discipline_tags))
            source_bonus = 4 if program.data_status == DataStatus.verified else 0
            coverage_bonus = 2 if program.source.field_coverage == "complete" else 0
            tier_bonus = 2 if program.institution in _HIGH_SIGNAL_INSTITUTIONS else 0
            program.community_signals = _match_community_signals(program, community_signals)
            community_bonus = min(3, len(program.community_signals))
            category_bonus = {
                "core": 90,
                "related": 52,
                "general": 26,
                "blocked": 0,
            }[classification.category]
            score = (
                category_bonus
                + classification.alignment
                + overlap * 8
                + source_bonus
                + coverage_bonus
                + tier_bonus
                + community_bonus
            )
            if classification.category == "blocked":
                blocked.append((score, program))
            else:
                viable.append((score, program))

        ranked_viable = [program for _, program in sorted(viable, key=lambda item: item[0], reverse=True)]
        ranked_blocked = [program for _, program in sorted(blocked, key=lambda item: item[0], reverse=True)]
        return ranked_viable[:limit] + ranked_blocked[:12]

    def refresh_selected(
        self,
        matches: list[ProgramMatch],
        selected_program_ids: list[str],
        refresh_report: DataRefreshReport | None = None,
    ) -> list[ProgramMatch]:
        selected = [item for item in matches if item.program.id in selected_program_ids]
        finding_by_id = {
            finding.program_id: finding
            for finding in (refresh_report.program_findings if refresh_report else [])
        }
        for item in selected:
            finding = finding_by_id.get(item.program.id)
            if finding:
                item.program.data_status = finding.data_status
                item.data_status = finding.data_status
                if finding.fields_requiring_review:
                    item.risks.insert(
                        0,
                        "信息刷新助手标记为待学校确认："
                        + "、".join(finding.fields_requiring_review[:4])
                        + "。",
                    )
                for action in reversed(finding.next_actions[:2]):
                    item.actions.insert(0, action)
            if item.program.data_status not in {DataStatus.verified, DataStatus.rejected}:
                if item.program.data_status not in {
                    DataStatus.not_published,
                    DataStatus.stale,
                    DataStatus.changed,
                }:
                    item.program.data_status = DataStatus.pending_review
                    item.data_status = DataStatus.pending_review
                item.risks.insert(0, "项目信息仍需查看学校官网原文，当前不能作为最终申请依据。")
                item.actions.insert(0, "高优先级刷新官方项目页、申请入口、截止日期和材料要求。")
        return selected


class ProgramResearchAgent(ProgramIntelligenceAgent):
    name = "ProgramResearchAgent"


_HIGH_SIGNAL_INSTITUTIONS = {
    "The University of Hong Kong",
    "The Chinese University of Hong Kong",
    "The Hong Kong University of Science and Technology",
    "National University of Singapore",
    "Nanyang Technological University",
}


def _community_signals() -> list[CommunitySignal]:
    captured_at = datetime(2026, 6, 13, tzinfo=timezone.utc)
    signals: list[CommunitySignal] = []
    for source in load_community_sources()["sources"]:
        for signal in source.get("signals", []):
            signals.append(
                CommunitySignal(
                    source_name=source["source_name"],
                    url=source["repository"],
                    signal_type=signal.get("signal_type", "program_alias"),
                    summary=f"{signal['program_alias']}：社区资料中的项目线索，需回到官方页面验证。",
                    captured_at=captured_at,
                )
            )
    return signals


def _match_community_signals(program: Program, signals: list[CommunitySignal]) -> list[CommunitySignal]:
    haystack = " ".join(
        [
            program.id.lower(),
            program.name.lower(),
            (program.name_zh or "").lower(),
            program.institution.lower(),
            (program.institution_zh or "").lower(),
        ]
    )
    matched: list[CommunitySignal] = []
    for signal in signals:
        words = [part.lower() for part in signal.summary.replace("@", " ").replace("：", " ").split()]
        if any(word and word in haystack for word in words[:3]):
            matched.append(signal)
    return matched[:3]
