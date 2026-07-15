from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from harbor_agent.models import (
    AcquisitionSourcePlan,
    DataAcquisitionReport,
    DataQualityMetric,
    DataAcquisitionRequest,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramContentSection,
    ProgramDataCoverageItem,
    ProgramDataPackage,
    ProgramExperienceSignal,
    SourceExtractionResult,
    SourcePolicy,
    SourceTrustLevel,
)
from harbor_agent.services.data_loader import load_acquisition_sources, load_programs, load_source_registry
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.program_store import upsert_field_evidence_records
from harbor_agent.services.program_urls import student_application_url, student_program_url
from harbor_agent.services.source_snapshot import (
    discovered_links,
    evidence_records_from_candidates,
    extract_field_candidates,
    snapshot_source,
)
from harbor_agent.agents.data_refresh import _source_ids_for_programs


OFFICIAL_REQUIREMENT_FIELD_ORDER = [
    "official_program_url",
    "deadline",
    "tuition_hkd",
    "language_requirement",
    "materials",
    "application_url",
    "essay_prompts",
]
OFFICIAL_REQUIREMENT_FIELDS = set(OFFICIAL_REQUIREMENT_FIELD_ORDER)
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
        quality_metrics = [package.quality_metric for package in packages if package.quality_metric]
        crawler_capabilities = _crawler_capabilities(source_plan)
        live_records: list[FieldEvidenceRecord] = []
        extraction_results: list[SourceExtractionResult] = []
        if not request.dry_run:
            live_records, extraction_results = _run_live_snapshot_pipeline(packages, checked_at)
            _attach_live_records(packages, live_records)
        persisted_count = 0
        if not request.dry_run:
            persisted_count = upsert_field_evidence_records([*_records_for_persistence(packages), *live_records])
        missing_official = sum(len(package.official_requirements) for package in packages)
        community_count = sum(len(package.community_experiences) for package in packages)
        summary_prefix = (
            f"已写入 {persisted_count} 条字段级证据候选到 SQLite；"
            if not request.dry_run
            else ""
        )
        return DataAcquisitionReport(
            run_id=f"acq_{uuid4().hex[:12]}",
            mode="dry_run" if request.dry_run else "live_fetch",
            checked_at=checked_at,
            selected_program_ids=request.selected_program_ids,
            packages=packages,
            source_plan=source_plan,
            field_evidence_records=live_records[:120],
            extraction_results=extraction_results[:80],
            persisted_evidence_count=persisted_count,
            summary=(
                summary_prefix + f"生成 {len(packages)} 个项目数据包，包含 {missing_official} 条官方字段证据或待审核字段，"
                f"{community_count} 条公开社区经验或搜索计划。"
            ),
            next_actions=[
                "先按 source_plan 采集官方项目页、PDF/FAQ 和申请系统入口，保存快照与 page hash。",
                "官方字段经人工审核后，才能发布为 OFFICIAL_VERIFIED_CURRENT。",
                "社区经验只保留短摘要、链接、发布时间、采集时间和经验标签，不能覆盖 deadline、学费、语言或材料要求。",
                "每个项目详情页都要展示官网信息来源、申请季、采集时间、审核状态和社区经验边界。",
            ],
            agent_chain=[
                "SourceDiscoveryAgent",
                "OfficialCrawlerAgent",
                "PdfFaqExtractionAgent",
                "CommunitySignalAgent",
                "EvidenceMergeAgent",
                "HumanReviewGateAgent",
            ],
            quality_metrics=quality_metrics,
            crawler_capabilities=crawler_capabilities,
        )



def _run_live_snapshot_pipeline(
    packages: list[ProgramDataPackage],
    checked_at: datetime,
) -> tuple[list[FieldEvidenceRecord], list[SourceExtractionResult]]:
    records: list[FieldEvidenceRecord] = []
    results: list[SourceExtractionResult] = []
    for package in packages:
        for plan in package.acquisition_plan:
            if plan.channel not in {"official_requirement", "official_content"}:
                continue
            snapshot = snapshot_source(str(plan.url), dry_run=False, checked_at=checked_at)
            if not snapshot.ok:
                results.append(
                    SourceExtractionResult(
                        source_id=plan.source_id,
                        source_url=plan.url,
                        source_type=plan.channel,
                        page_hash=snapshot.page_hash,
                        snapshot_path=snapshot.snapshot_path,
                        extracted_at=checked_at,
                        parser="not_run",
                        extracted_fields=[],
                        unresolved_fields=OFFICIAL_REQUIREMENT_FIELD_ORDER,
                        raw_json={
                            "status": snapshot.status,
                            "error": snapshot.error,
                            "robots_url": snapshot.robots_url,
                            "robots_allowed": snapshot.robots_allowed,
                        },
                        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "HtmlPdfTextExtractionAgent", "HumanReviewGateAgent"],
                    )
                )
                continue
            candidates = extract_field_candidates(snapshot.text)
            extracted = evidence_records_from_candidates(
                program_id=package.program_id,
                cycle=package.cycle,
                source_url=str(plan.url),
                source_type=plan.channel,
                snapshot=snapshot,
                candidates=candidates,
                trust_level=plan.trust_level,
            )
            records.extend(extracted)
            resolved = {candidate.field_name for candidate in candidates}
            results.append(
                SourceExtractionResult(
                    source_id=plan.source_id,
                    source_url=plan.url,
                    source_type=plan.channel,
                    page_hash=snapshot.page_hash,
                    snapshot_path=snapshot.snapshot_path,
                    extracted_at=checked_at,
                    parser="regex_html",
                    extracted_fields=candidates,
                    unresolved_fields=[field for field in OFFICIAL_REQUIREMENT_FIELD_ORDER if field not in resolved],
                    raw_json={
                        "status": snapshot.status,
                        "http_status": snapshot.http_status,
                        "snapshot_mime": snapshot.snapshot_mime,
                        "content_bytes": snapshot.content_bytes,
                        "discovered_links": discovered_links(snapshot.text, str(plan.url), limit=20),
                        "review_required": True,
                    },
                    agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "HtmlPdfTextExtractionAgent", "FieldCandidateAgent", "HumanReviewGateAgent"],
                )
            )
    return records, results


def _attach_live_records(packages: list[ProgramDataPackage], records: list[FieldEvidenceRecord]) -> None:
    by_program: dict[str, list[FieldEvidenceRecord]] = {}
    for record in records:
        by_program.setdefault(record.program_id, []).append(record)
    for package in packages:
        live = by_program.get(package.program_id, [])
        if not live:
            continue
        existing_keys = {(record.field_name, str(record.source_url), record.page_hash) for record in package.official_requirements}
        additions = [record for record in live if (record.field_name, str(record.source_url), record.page_hash) not in existing_keys]
        package.official_requirements.extend(additions)
        package.timeline_fields.extend([record for record in additions if record.field_name in TIMELINE_FIELDS])
        package.essay_prompts.extend([record for record in additions if record.field_name == "essay_prompts"])
        package.coverage_items = _coverage_items(package.official_requirements)
        package.quality_metric = _quality_metric_for_records(package.program_id, package.official_requirements, package.acquisition_plan)


def _quality_metric_for_records(
    scope: str,
    records: list[FieldEvidenceRecord],
    acquisition_plan: list[AcquisitionSourcePlan],
) -> DataQualityMetric:
    by_field = {record.field_name: record for record in records}
    required_fields = OFFICIAL_REQUIREMENT_FIELD_ORDER
    present_count = sum(1 for field_name in required_fields if (record := by_field.get(field_name)) is not None and bool(record.value))
    verified_count = sum(
        1
        for field_name in required_fields
        if (record := by_field.get(field_name)) is not None
        and record.status == FieldVerificationStatus.official_verified_current
        and not record.review_required
    )
    blocked_fields = [
        field_name
        for field_name in required_fields
        if (record := by_field.get(field_name)) is None
        or record.status not in {FieldVerificationStatus.official_verified_current, FieldVerificationStatus.official_previous_cycle}
        or record.review_required
    ]
    capabilities = []
    if any(str(plan.url).lower().endswith(".pdf") or "pdf" in plan.crawler_method.lower() for plan in acquisition_plan):
        capabilities.append("pdf_text_extraction_needed")
    if any(plan.channel == "official_requirement" for plan in acquisition_plan):
        capabilities.extend(["html_snapshot_needed", "field_level_evidence_needed"])
    if any(plan.requires_human_review for plan in acquisition_plan):
        capabilities.append("human_review_gate_needed")
    return DataQualityMetric(
        scope=scope,
        official_field_coverage=round(present_count / max(1, len(required_fields)) * 100),
        verified_current_coverage=round(verified_count / max(1, len(required_fields)) * 100),
        review_required_count=sum(1 for record in records if record.review_required),
        blocked_field_count=len(blocked_fields),
        blocked_fields=blocked_fields,
        parser_capabilities=capabilities,
        next_action="review_or_collect: " + ", ".join(blocked_fields[:4]) if blocked_fields else "ready_for_review",
    )


def _records_for_persistence(packages: list[ProgramDataPackage]) -> list[FieldEvidenceRecord]:
    records: list[FieldEvidenceRecord] = []
    seen: set[tuple[str, str, str | None, str | None, str | None]] = set()
    for package in packages:
        for record in [*package.official_requirements, *package.timeline_fields, *package.essay_prompts]:
            key = (
                record.program_id,
                record.field_name,
                record.cycle,
                str(record.source_url) if record.source_url else None,
                record.page_hash,
            )
            if key in seen:
                continue
            records.append(record)
            seen.add(key)
    return records
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
        official_url=student_program_url(program) or program.source.url,
        application_url=student_application_url(program),
        production_ready=trust.production_ready,
        freshness_warning=trust.source_warning,
        official_requirements=official_requirements,
        coverage_items=_coverage_items(records),
        content_sections=_content_sections(program, records),
        essay_prompts=essay_prompts,
        timeline_fields=timeline_fields,
        community_experiences=_community_experiences(program, config, checked_at) if request.include_community else [],
        acquisition_plan=acquisition_plan,
        human_review_required=True,
        quality_metric=_quality_metric(program, records, acquisition_plan),
    )


def _coverage_items(records: list[FieldEvidenceRecord]) -> list[ProgramDataCoverageItem]:
    by_field = {record.field_name: record for record in records}
    items: list[ProgramDataCoverageItem] = []
    for field_name in OFFICIAL_REQUIREMENT_FIELD_ORDER:
        record = by_field.get(field_name)
        status = record.status if record else FieldVerificationStatus.not_published
        has_value = bool(record and record.value and record.value != "NOT_PUBLISHED")
        verified = status == FieldVerificationStatus.official_verified_current and bool(record) and not record.review_required
        items.append(
            ProgramDataCoverageItem(
                field_name=field_name,
                required_source="official",
                status=status,
                has_value=has_value,
                source_url=record.source_url if record else None,
                source_type=record.source_type if record else None,
                review_required=True if record is None else record.review_required,
                blocks_formal_use=not verified,
                next_action=_coverage_next_action(field_name, record, verified),
            )
        )
    return items


def _coverage_next_action(field_name: str, record: FieldEvidenceRecord | None, verified: bool) -> str:
    labels = {
        "official_program_url": "项目详情页",
        "deadline": "截止日期",
        "tuition_hkd": "学费",
        "language_requirement": "语言要求",
        "materials": "材料清单",
        "application_url": "申请入口",
        "essay_prompts": "文书题目",
    }
    label = labels.get(field_name, field_name)
    if verified:
        return f"{label}已完成官网当前季核验，可用于正式时间线和申请清单。"
    if record is None or not record.value or record.value == "NOT_PUBLISHED":
        return f"缺少{label}的项目详情页、官方 PDF/FAQ 或网申系统来源；补齐前不生成正式时间线。"
    if record.status == FieldVerificationStatus.official_previous_cycle:
        cycle = record.cycle or "上一申请季"
        return f"{label}当前只能作为 {cycle} 往届参考；当前季发布后需要重新核验。"
    if record.status == FieldVerificationStatus.conflicted:
        return f"{label}存在来源冲突，需要以项目详情页、官方 PDF/FAQ 或网申系统原文为准。"
    return f"{label}已有候选值，但还没有完成官网当前季核验，正式规划前需要人工复核来源。"

def _quality_metric(
    program: Program,
    records: list[FieldEvidenceRecord],
    acquisition_plan: list[AcquisitionSourcePlan],
) -> DataQualityMetric:
    by_field = {record.field_name: record for record in records}
    required_fields = OFFICIAL_REQUIREMENT_FIELD_ORDER
    present_count = sum(
        1
        for field_name in required_fields
        if (record := by_field.get(field_name)) is not None and bool(record.value)
    )
    verified_count = sum(
        1
        for field_name in required_fields
        if (record := by_field.get(field_name)) is not None
        and record.status == FieldVerificationStatus.official_verified_current
        and not record.review_required
    )
    blocked_fields = [
        field_name
        for field_name in required_fields
        if (record := by_field.get(field_name)) is None
        or record.status not in {
            FieldVerificationStatus.official_verified_current,
            FieldVerificationStatus.official_previous_cycle,
        }
        or record.review_required
    ]
    review_required_count = sum(1 for record in records if record.review_required)
    capabilities = []
    if any(str(plan.url).lower().endswith(".pdf") or "pdf" in plan.crawler_method.lower() for plan in acquisition_plan):
        capabilities.append("pdf_text_extraction_needed")
    if any(plan.channel == "official_requirement" for plan in acquisition_plan):
        capabilities.append("html_snapshot_needed")
        capabilities.append("field_level_evidence_needed")
    if any(plan.requires_human_review for plan in acquisition_plan):
        capabilities.append("human_review_gate_needed")
    if program.application_url:
        capabilities.append("application_system_check_needed")
    next_action = "ready_for_review" if present_count == len(required_fields) else "collect_missing_official_fields"
    if blocked_fields:
        next_action = "review_or_collect: " + ", ".join(blocked_fields[:4])
    return DataQualityMetric(
        scope=program.id,
        official_field_coverage=round(present_count / max(1, len(required_fields)) * 100),
        verified_current_coverage=round(verified_count / max(1, len(required_fields)) * 100),
        review_required_count=review_required_count,
        blocked_field_count=len(blocked_fields),
        blocked_fields=blocked_fields,
        parser_capabilities=capabilities,
        next_action=next_action,
    )


def _crawler_capabilities(source_plan: list[AcquisitionSourcePlan]) -> list[str]:
    capabilities = {
        "queued_worker",
        "field_level_evidence",
        "human_review_gate",
        "snapshot_cache",
    }
    for plan in source_plan:
        method = plan.crawler_method.lower()
        url = str(plan.url).lower()
        if "pdf" in method or url.endswith(".pdf"):
            capabilities.add("pdf_text_extraction")
        if "playwright" in method or "render" in method or "application" in method:
            capabilities.add("playwright_rendered_page")
        if plan.channel == "community_experience":
            capabilities.add("community_signal_boundary")
        if plan.trust_level == SourceTrustLevel.official:
            capabilities.add("official_source_priority")
    return sorted(capabilities)


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
                    "official_program_url",
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
                    "采集官方项目页或目录页，并保存 HTML/PDF 快照。",
                    "抽取字段后逐项绑定原文片段、申请季和 page_hash。",
                ],
            )
        )
    detail_url = student_program_url(program)
    if not plans and (detail_url or program.source.url):
        plans.append(
            AcquisitionSourcePlan(
                source_id=f"program:{program.id}",
                name=f"{program.institution} programme page",
                url=detail_url or program.source.url,
                channel="official_requirement",
                trust_level=SourceTrustLevel.official,
                allowed_fields=["official_program_url", "deadline", "tuition_hkd", "language_requirement", "materials", "essay_prompts", "application_url"],
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
                    "只保存公开短摘要、URL、发布时间、采集时间和经验标签。",
                ],
            )
        )
    return plans


def _content_sections(program: Program, records: list[FieldEvidenceRecord]) -> list[ProgramContentSection]:
    source_url = student_program_url(program) or program.source.url
    status = _best_status(records)
    sections = [
        ProgramContentSection(
            section_id="overview",
            title="项目概览",
            summary=(
                f"{program.institution_zh or program.institution} {program.name_zh or program.name}："
                f"学制约 {program.duration_months} 个月，方向标签：{', '.join(program.discipline_tags[:5]) or '待补充'}。"
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
