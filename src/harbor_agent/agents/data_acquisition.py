from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from harbor_agent.models import (
    AcquisitionSourcePlan,
    DataAcquisitionReport,
    DataAcquisitionRequest,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramContentSection,
    ProgramDataPackage,
    ProgramExperienceSignal,
    SourcePolicy,
    SourceTrustLevel,
)
from harbor_agent.services.data_loader import load_acquisition_sources, load_programs, load_source_registry
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.agents.data_refresh import _source_ids_for_programs


OFFICIAL_REQUIREMENT_FIELDS = {
    "deadline",
    "tuition_hkd",
    "language_requirement",
    "materials",
    "application_url",
    "essay_prompts",
}
TIMELINE_FIELDS = {"deadline", "application_url", "essay_prompts"}


class ProgramDataAcquisitionAgent:
    """Builds reviewable data packages from public official and community sources."""

    name = "ProgramDataAcquisitionAgent"

    def run(self, request: DataAcquisitionRequest) -> DataAcquisitionReport:
        checked_at = datetime.now(UTC)
        programs = _select_programs(load_programs(), request.selected_program_ids)
        registry_sources = load_source_registry().sources
        config = load_acquisition_sources()
        packages = [
            _build_package(program, registry_sources, config, request, checked_at)
            for program in programs
        ]
        source_plan = _dedupe_plans(
            plan
            for package in packages
            for plan in package.acquisition_plan
        )
        missing_official = sum(len(package.official_requirements) for package in packages)
        community_count = sum(len(package.community_experiences) for package in packages)
        return DataAcquisitionReport(
            run_id=f"acq_{uuid4().hex[:12]}",
            mode="dry_run" if request.dry_run else "live_fetch",
            checked_at=checked_at,
            selected_program_ids=request.selected_program_ids,
            packages=packages,
            source_plan=source_plan,
            summary=(
                f"生成 {len(packages)} 个项目数据包，包含 {missing_official} 条官方字段证据或待审核字段，"
                f"{community_count} 条公开社区经验或搜索计划。"
            ),
            next_actions=[
                "先按 source_plan 抓取官方项目页、PDF/FAQ 和申请系统入口，保存快照与 page hash。",
                "官方字段经人工审核后，才能发布为 OFFICIAL_VERIFIED_CURRENT。",
                "社区经验只保留短摘要、链接、发布时间、抓取时间和经验标签，不能覆盖 deadline、学费、语言或材料要求。",
                "每个项目详情页都要展示字段来源、申请季、抓取时间、审核状态和社区经验边界。",
            ],
            agent_chain=[
                "SourceDiscoveryAgent",
                "OfficialCrawlerAgent",
                "PdfFaqExtractionAgent",
                "CommunitySignalAgent",
                "EvidenceMergeAgent",
                "HumanReviewGateAgent",
            ],
        )


def _select_programs(programs: list[Program], selected_ids: list[str]) -> list[Program]:
    if selected_ids:
        selected = [program for program in programs if program.id in set(selected_ids)]
        if selected:
            return selected
    return programs[:12]


def _build_package(
    program: Program,
    registry_sources: list[SourcePolicy],
    config: dict,
    request: DataAcquisitionRequest,
    checked_at: datetime,
) -> ProgramDataPackage:
    trust = build_program_trust_detail(program)
    records = trust.field_records
    official_requirements = [record for record in records if record.field_name in OFFICIAL_REQUIREMENT_FIELDS]
    essay_prompts = [record for record in records if record.field_name == "essay_prompts"]
    timeline_fields = [record for record in records if record.field_name in TIMELINE_FIELDS]
    acquisition_plan = _official_source_plans(program, registry_sources)
    if request.include_community:
        acquisition_plan.extend(_community_source_plans(config, program))
    acquisition_plan = acquisition_plan[: request.max_sources_per_program]

    return ProgramDataPackage(
        program_id=program.id,
        institution=program.institution_zh or program.institution,
        program_name=program.name_zh or program.name,
        cycle=program.cycle,
        official_url=program.official_program_url or program.source.url,
        application_url=program.application_url,
        production_ready=trust.production_ready,
        freshness_warning=trust.source_warning,
        official_requirements=official_requirements,
        content_sections=_content_sections(program, records),
        essay_prompts=essay_prompts,
        timeline_fields=timeline_fields,
        community_experiences=_community_experiences(program, config, checked_at) if request.include_community else [],
        acquisition_plan=acquisition_plan,
        human_review_required=True,
    )


def _official_source_plans(program: Program, registry_sources: list[SourcePolicy]) -> list[AcquisitionSourcePlan]:
    source_ids = _source_ids_for_programs([program])
    plans: list[AcquisitionSourcePlan] = []
    for source in registry_sources:
        if source.source_id not in source_ids:
            continue
        plans.append(
            AcquisitionSourcePlan(
                source_id=source.source_id,
                name=source.name,
                url=source.url,
                channel="official_requirement",
                trust_level=source.trust_level,
                allowed_fields=[
                    "program_overview",
                    "curriculum",
                    "deadline",
                    "tuition_hkd",
                    "language_requirement",
                    "materials",
                    "essay_prompts",
                    "application_url",
                ],
                crawler_method=source.extraction_method,
                rate_limit="queued_low_rate_fetch_with_snapshot_cache",
                requires_human_review=True,
                next_actions=[
                    "抓取官方项目页或目录页，并保存 HTML/PDF 快照。",
                    "抽取字段后逐项绑定原文片段、申请季和 page_hash。",
                ],
            )
        )
    if not plans and (program.official_program_url or program.source.url):
        plans.append(
            AcquisitionSourcePlan(
                source_id=f"program:{program.id}",
                name=f"{program.institution} programme page",
                url=program.official_program_url or program.source.url,
                channel="official_requirement",
                trust_level=SourceTrustLevel.official,
                allowed_fields=["deadline", "tuition_hkd", "language_requirement", "materials", "essay_prompts", "application_url"],
                crawler_method="direct programme page snapshot and field parser",
                next_actions=["打开项目页，确认是否已经发布当前申请季要求。"],
            )
        )
    return plans


def _community_source_plans(config: dict, program: Program) -> list[AcquisitionSourcePlan]:
    plans: list[AcquisitionSourcePlan] = []
    for source in config.get("community_channels", []):
        plans.append(
            AcquisitionSourcePlan(
                source_id=str(source.get("source_id")),
                name=str(source.get("name")),
                url=str(source.get("url")),
                channel="community_experience",
                trust_level=SourceTrustLevel.community,
                allowed_fields=list(source.get("allowed_fields", [])),
                crawler_method=str(source.get("crawler_method")),
                rate_limit=str(source.get("rate_limit", "manual_or_low_rate")),
                robots_policy=str(source.get("policy", "check_robots_and_terms_before_live_fetch")),
                requires_human_review=True,
                next_actions=[
                    f"搜索：{_community_query(program, source.get('source_id'))}",
                    "只保存公开短摘要、URL、发布时间、抓取时间和经验标签。",
                ],
            )
        )
    return plans


def _content_sections(program: Program, records: list[FieldEvidenceRecord]) -> list[ProgramContentSection]:
    source_url = program.official_program_url or program.source.url
    status = _best_status(records)
    sections = [
        ProgramContentSection(
            section_id="overview",
            title="项目概览",
            summary=(
                f"{program.institution_zh or program.institution} {program.name_zh or program.name}："
                f"学制约 {program.duration_months} 个月，方向标签：{', '.join(program.discipline_tags[:5]) or '待确认'}。"
            ),
            source_status=status,
            source_url=source_url,
            evidence_snippet="项目名称、院校和学制来自项目库；正式展示需要绑定学校官网当前申请季页面。",
        ),
        ProgramContentSection(
            section_id="requirements_background",
            title="背景与先修课",
            summary=_background_summary(program),
            source_status=status,
            source_url=source_url,
            evidence_snippet="背景要求和先修课需要回到项目页或 FAQ 确认。",
        ),
        ProgramContentSection(
            section_id="materials_and_writing",
            title="材料与文书",
            summary=_materials_summary(program),
            source_status=status,
            source_url=source_url,
            evidence_snippet="文书题目、PS/SOP、推荐信和 CV 要求以学校申请系统或官方 PDF 为准。",
        ),
    ]
    return sections


def _background_summary(program: Program) -> str:
    parts = []
    if program.requirements.required_backgrounds:
        parts.append("硬背景：" + ", ".join(program.requirements.required_backgrounds))
    if program.requirements.preferred_backgrounds:
        parts.append("偏好背景：" + ", ".join(program.requirements.preferred_backgrounds))
    if program.requirements.prerequisites:
        parts.append("先修课/能力：" + ", ".join(program.requirements.prerequisites))
    if program.requirements.language:
        parts.append("语言：" + ", ".join(f"{k} {v:g}" for k, v in program.requirements.language.items()))
    return "；".join(parts) if parts else "背景要求待学校官网确认。"


def _materials_summary(program: Program) -> str:
    if not program.materials:
        return "材料清单待学校官网确认。"
    return "当前项目库记录材料：" + ", ".join(program.materials) + "。"


def _community_experiences(program: Program, config: dict, checked_at: datetime) -> list[ProgramExperienceSignal]:
    signals: list[ProgramExperienceSignal] = []
    for signal in program.community_signals[:4]:
        signals.append(
            ProgramExperienceSignal(
                signal_type="general_experience",
                title=signal.signal_type,
                summary=signal.summary,
                source_name=signal.source_name,
                source_url=signal.url,
                captured_at=signal.captured_at,
                confidence="low",
                official_verification_required=signal.official_verification_required,
            )
        )
    if not signals:
        for source in config.get("community_channels", [])[:3]:
            signals.append(
                ProgramExperienceSignal(
                    signal_type="search_plan",
                    title=f"待采集：{source.get('name')}",
                    summary=(
                        f"建议用公开搜索采集 {program.institution_zh or program.institution} "
                        f"{program.name_zh or program.name} 的面试、笔试、文书题目和申请时间线经验；"
                        "采集后只作为经验参考。"
                    ),
                    source_name=str(source.get("name")),
                    source_url=str(source.get("url")),
                    captured_at=checked_at,
                    confidence="low",
                )
            )
    return signals


def _community_query(program: Program, source_id: object) -> str:
    base = f"{program.institution_zh or program.institution} {program.name_zh or program.name} 面试 笔试 文书 申请经验"
    if source_id == "github_global_cs_watercs":
        return f"{program.institution} {program.name} application interview GitHub"
    if source_id == "thegradcafe_public_search":
        return f"{program.institution} {program.name} admission result timeline"
    return base


def _best_status(records: list[FieldEvidenceRecord]) -> FieldVerificationStatus:
    if any(record.status == FieldVerificationStatus.official_verified_current for record in records):
        return FieldVerificationStatus.official_verified_current
    if any(record.status == FieldVerificationStatus.official_previous_cycle for record in records):
        return FieldVerificationStatus.official_previous_cycle
    return FieldVerificationStatus.model_inferred


def _dedupe_plans(plans) -> list[AcquisitionSourcePlan]:
    output: list[AcquisitionSourcePlan] = []
    seen: set[str] = set()
    for plan in plans:
        if plan.source_id in seen:
            continue
        output.append(plan)
        seen.add(plan.source_id)
    return output
