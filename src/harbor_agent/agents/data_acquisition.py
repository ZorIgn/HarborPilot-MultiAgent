from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from harbor_agent.models import (
    AcquisitionSourcePlan,
    DataAcquisitionReport,
    DataQualityMetric,
    DataAcquisitionRequest,
    FieldExtractionCandidate,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramContentSection,
    ProgramDataCoverageItem,
    ProgramDataPackage,
    ProgramExperienceSignal,
    SourceExtractionResult,
    SourcePolicy,
    SourceScope,
    SourceTrustLevel,
)
from harbor_agent.services.data_loader import load_acquisition_sources, load_programs, load_source_registry
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.program_store import upsert_field_evidence_records
from harbor_agent.services.program_urls import student_application_url, student_program_url
from harbor_agent.services.source_identity import same_official_institution
from harbor_agent.services.source_snapshot import (
    discovered_links,
    evidence_records_from_candidates,
    extract_field_candidates,
    snapshot_source,
)
from harbor_agent.services.information_store import (
    finish_information_run,
    record_fetch_attempt,
    start_information_run,
    update_information_run_plan,
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
        run_id = f"acq_{uuid4().hex[:12]}"
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
        if not request.dry_run:
            start_information_run(
                run_id,
                mode="live_fetch",
                selected_program_ids=[program.id for program in programs],
                planned_source_count=len(source_plan),
            )
        live_records: list[FieldEvidenceRecord] = []
        extraction_results: list[SourceExtractionResult] = []
        pipeline_stats = {"attempted": 0, "successful": 0, "failed": 0, "binding_warnings": 0}
        run_warnings: list[str] = []
        try:
            if not request.dry_run:
                live_records, extraction_results, pipeline_stats, run_warnings = _run_live_snapshot_pipeline_with_run(
                    packages, checked_at, run_id
                )
                _attach_live_records(packages, live_records)
                source_plan = _dedupe_plans(
                    plan
                    for package in packages
                    for plan in package.acquisition_plan
                )
                update_information_run_plan(run_id, len(source_plan))
            persisted_count = 0
            if not request.dry_run:
                persisted_count = upsert_field_evidence_records(_records_for_persistence(packages))
        except Exception as exc:
            run_warnings.append(f"{type(exc).__name__}: {exc}")
            if not request.dry_run:
                finish_information_run(
                    run_id,
                    status="FAILED",
                    attempted_source_count=pipeline_stats["attempted"],
                    successful_source_count=pipeline_stats["successful"],
                    failed_source_count=pipeline_stats["failed"] + 1,
                    binding_warning_count=pipeline_stats["binding_warnings"],
                    warnings=run_warnings,
                )
            raise
        missing_official = sum(len(package.official_requirements) for package in packages)
        community_count = sum(len(package.community_experiences) for package in packages)
        summary_prefix = (
            f"已写入 {persisted_count} 条字段级证据候选到 SQLite；"
            if not request.dry_run
            else ""
        )
        run_status = (
            "NEEDS_REVIEW"
            if run_warnings or any(package.human_review_required for package in packages)
            else "COMPLETED"
        )
        if not request.dry_run:
            finish_information_run(
                run_id,
                status=run_status,
                attempted_source_count=pipeline_stats["attempted"],
                successful_source_count=pipeline_stats["successful"],
                failed_source_count=pipeline_stats["failed"],
                binding_warning_count=pipeline_stats["binding_warnings"],
                warnings=run_warnings,
            )
        return DataAcquisitionReport(
            run_id=run_id,
            mode="dry_run" if request.dry_run else "live_fetch",
            checked_at=checked_at,
            selected_program_ids=[program.id for program in programs],
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
            run_status=run_status,
            planned_source_count=len(source_plan),
            attempted_source_count=pipeline_stats["attempted"],
            successful_source_count=pipeline_stats["successful"],
            failed_source_count=pipeline_stats["failed"],
            binding_warning_count=pipeline_stats["binding_warnings"],
            run_warnings=run_warnings,
        )



def _run_live_snapshot_pipeline(
    packages: list[ProgramDataPackage],
    checked_at: datetime,
) -> tuple[list[FieldEvidenceRecord], list[SourceExtractionResult]]:
    records, results, _, _ = _run_live_snapshot_pipeline_with_run(packages, checked_at, "legacy_acquisition_run")
    return records, results


def _run_live_snapshot_pipeline_with_run(
    packages: list[ProgramDataPackage],
    checked_at: datetime,
    run_id: str,
) -> tuple[list[FieldEvidenceRecord], list[SourceExtractionResult], dict[str, int], list[str]]:
    records: list[FieldEvidenceRecord] = []
    results: list[SourceExtractionResult] = []
    stats = {"attempted": 0, "successful": 0, "failed": 0, "binding_warnings": 0}
    warnings: list[str] = []
    package_by_id = {package.program_id: package for package in packages}
    plans = _unique_live_plans(packages)
    queued_detail_urls = {
        (plan.target_program_id or package.program_id, str(plan.url))
        for package, plan in plans
        if package is not None and plan.source_scope == SourceScope.programme_detail
    }
    snapshot_cache: dict[tuple[str, str], object] = {}
    for package, plan in plans:
        target_id = plan.target_program_id or (package.program_id if package else None)
        target_package = package_by_id.get(target_id) if target_id else None
        cache_key = (plan.source_id, str(plan.url))
        snapshot = snapshot_cache.get(cache_key)
        cache_hit = snapshot is not None
        if snapshot is None:
            stats["attempted"] += 1
            snapshot = snapshot_source(str(plan.url), dry_run=False, checked_at=checked_at)
            snapshot_cache[cache_key] = snapshot
        if not snapshot.ok:
            if not cache_hit:
                stats["failed"] += 1
                warnings.append(
                    f"{plan.source_id}: {snapshot.status}"
                    + (f" ({snapshot.error})" if snapshot.error else "")
                )
            record_fetch_attempt(
                run_id,
                program_id=target_id,
                source_id=plan.source_id,
                source_scope=plan.source_scope,
                requested_url=str(plan.url),
                snapshot=snapshot,
            )
            results.append(_extraction_result_for_failure(plan, snapshot, checked_at))
            continue
        if not cache_hit:
            stats["successful"] += 1
        html = snapshot.html or snapshot.text
        links = discovered_links(html, str(plan.url), limit=30)
        if plan.source_scope == SourceScope.institution_index:
            candidate_url = _best_program_link(target_package, links) if target_package else None
            binding_status = "index_only"
            binding_score = 55 if candidate_url else 0
            if target_package and candidate_url:
                records.append(_index_link_record(target_package, candidate_url, str(plan.url), snapshot, checked_at))
                detail_key = (target_package.program_id, candidate_url)
                if detail_key not in queued_detail_urls:
                    discovered_plan = _discovered_detail_plan(target_package, candidate_url, plan.source_id)
                    queued_detail_urls.add(detail_key)
                    target_package.acquisition_plan.append(discovered_plan)
                    plans.append((target_package, discovered_plan))
            elif target_package:
                stats["binding_warnings"] += 1
                warnings.append(f"{target_package.program_id}: institution index did not yield a matching programme detail link")
            record_fetch_attempt(
                run_id,
                program_id=target_id,
                source_id=plan.source_id,
                source_scope=plan.source_scope,
                requested_url=str(plan.url),
                snapshot=snapshot,
                binding_status=binding_status,
                binding_score=binding_score,
                extracted_field_count=1 if candidate_url else 0,
            )
            results.append(_extraction_result_for_index(plan, snapshot, checked_at, links, binding_score))
            continue
        if target_package is None:
            continue
        binding_status, binding_score = _bind_program_page(target_package, snapshot)
        if binding_status == "unrelated":
            stats["binding_warnings"] += 1
            warnings.append(f"{target_package.program_id}: fetched page does not identify the requested programme")
            record_fetch_attempt(
                run_id,
                program_id=target_package.program_id,
                source_id=plan.source_id,
                source_scope=plan.source_scope,
                requested_url=str(plan.url),
                snapshot=snapshot,
                binding_status=binding_status,
                binding_score=binding_score,
            )
            results.append(_extraction_result_for_unrelated(plan, snapshot, checked_at, binding_score))
            continue
        candidates = extract_field_candidates(snapshot.text)
        application_url = _best_application_link(target_package, links)
        if application_url:
            candidates = [
                candidate for candidate in candidates
                if candidate.field_name != "application_url"
            ]
            candidates.append(
                FieldExtractionCandidate(
                    field_name="application_url",
                    value=application_url,
                    evidence_snippet=f"项目详情页链接到官方申请入口：{application_url}",
                    confidence="medium",
                )
            )
        detail_url_record = (
            _detail_url_record(target_package, snapshot, checked_at, binding_score)
            if binding_status == "matched"
            else None
        )
        if detail_url_record is not None:
            records.append(detail_url_record)
        records.extend(
            evidence_records_from_candidates(
                program_id=target_package.program_id,
                cycle=target_package.cycle,
                source_url=str(snapshot.final_url or plan.url),
                source_type="official_program_page",
                snapshot=snapshot,
                candidates=candidates,
                trust_level=plan.trust_level,
                source_scope=plan.source_scope,
                page_title=snapshot.page_title,
                final_url=snapshot.final_url,
                binding_status=binding_status,
                binding_score=binding_score,
            )
        )
        record_fetch_attempt(
            run_id,
            program_id=target_package.program_id,
            source_id=plan.source_id,
            source_scope=plan.source_scope,
            requested_url=str(plan.url),
            snapshot=snapshot,
            binding_status=binding_status,
            binding_score=binding_score,
            extracted_field_count=sum(candidate.value is not None for candidate in candidates)
            + (1 if detail_url_record else 0),
        )
        results.append(_extraction_result_for_detail(plan, snapshot, checked_at, links, candidates, binding_status, binding_score))
    return records, results, stats, warnings


def _discovered_detail_plan(
    package: ProgramDataPackage,
    candidate_url: str,
    parent_source_id: str,
) -> AcquisitionSourcePlan:
    return AcquisitionSourcePlan(
        source_id=f"program:{package.program_id}:discovered-detail",
        name=f"{package.institution} discovered programme detail page",
        url=candidate_url,
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=OFFICIAL_REQUIREMENT_FIELD_ORDER,
        crawler_method="index discovery followed by direct programme-page snapshot",
        rate_limit="queued_low_rate_fetch_with_snapshot_cache",
        requires_human_review=True,
        source_scope=SourceScope.programme_detail,
        target_program_id=package.program_id,
        next_actions=[
            f"由 {parent_source_id} 发现详情链接；校验院校域名、页面标题和项目名称。",
            "字段只进入人工审核队列，不自动覆盖项目目录。",
        ],
    )


def _detail_url_record(
    package: ProgramDataPackage,
    snapshot,
    checked_at: datetime,
    binding_score: int,
) -> FieldEvidenceRecord | None:
    final_url = str(snapshot.final_url or snapshot.url or "")
    if not final_url:
        return None
    return FieldEvidenceRecord(
        program_id=package.program_id,
        field_name="official_program_url",
        value=final_url,
        cycle=package.cycle,
        source_url=final_url,
        source_type="official_program_page",
        extracted_at=checked_at,
        page_hash=snapshot.page_hash,
        confidence="high" if binding_score >= 80 else "medium",
        source_priority=1,
        status=FieldVerificationStatus.official_previous_cycle,
        review_required=True,
        evidence_snippet=f"项目详情页身份匹配：{snapshot.page_title or final_url}",
        snapshot_url=snapshot.snapshot_path,
        source_scope=SourceScope.programme_detail,
        page_title=snapshot.page_title,
        final_url=final_url,
        binding_status="matched",
        binding_score=binding_score,
        agent_chain=[
            "SourceDiscoveryAgent",
            "SnapshotCrawlerAgent",
            "ProgrammeBindingGateAgent",
            "HumanReviewGateAgent",
        ],
    )


def _unique_live_plans(packages: list[ProgramDataPackage]) -> list[tuple[ProgramDataPackage | None, AcquisitionSourcePlan]]:
    output: list[tuple[ProgramDataPackage | None, AcquisitionSourcePlan]] = []
    seen: set[tuple[str, str, str]] = set()
    for package in packages:
        for plan in package.acquisition_plan:
            if plan.channel not in {"official_requirement", "official_content"}:
                continue
            key = (plan.source_id, str(plan.url), plan.source_scope.value)
            if plan.source_scope in {SourceScope.programme_detail, SourceScope.institution_index}:
                key = (plan.source_id, str(plan.url), f"{plan.source_scope.value}:{package.program_id}")
            if key in seen:
                continue
            seen.add(key)
            output.append((package, plan))
    return output


def _bind_program_page(package: ProgramDataPackage, snapshot) -> tuple[str, int]:
    """Require a programme identity signal before extracting field facts."""

    final_url = str(snapshot.final_url or snapshot.url or "")
    if not same_official_institution(final_url, str(package.official_url or "")):
        return "unrelated", 0
    title = str(snapshot.page_title or "").lower()
    content = " ".join([title, str(snapshot.text[:12000] or "")]).lower()
    url_text = str(snapshot.final_url or "").lower()
    tokens = _identity_tokens(package.program_name_en or package.program_name)
    if not tokens:
        return "weak_match", 35
    content_matched = sum(1 for token in tokens if token in content)
    title_matched = sum(1 for token in tokens if token in title)
    url_matched = sum(1 for token in tokens if token in url_text)
    degree_match = _degree_identity_match(package.program_name_en or package.program_name, content[:3000])
    if degree_match == "conflict":
        return "unrelated", 0
    score = round(
        min(
            100,
            (content_matched / len(tokens) * 75)
            + (title_matched / len(tokens) * 15)
            + (url_matched / len(tokens) * 5)
            + (5 if degree_match == "matched" else 0),
        )
    )
    minimum_content_tokens = 1 if len(tokens) <= 2 else 2
    if content_matched < minimum_content_tokens:
        return "unrelated", score
    if len(tokens) == 1 and title_matched == 0:
        return "weak_match", min(score, 55)
    if degree_match != "matched":
        return "weak_match", min(score, 55)
    if score >= 60:
        return "matched", score
    if score >= 35:
        return "weak_match", score
    return "unrelated", score


def _best_program_link(package: ProgramDataPackage | None, links: list[str]) -> str | None:
    if package is None:
        return None
    tokens = _identity_tokens(package.program_name_en or package.program_name)
    if not tokens:
        return None
    scored = []
    for link in links:
        if not same_official_institution(link, str(package.official_url or "")):
            continue
        low = link.lower()
        score = sum(1 for token in tokens if token in low)
        if score:
            scored.append((score, len(low), link))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return scored[0][2]


def _best_application_link(package: ProgramDataPackage, links: list[str]) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for link in links:
        low = link.lower()
        if not any(token in low for token in ("apply", "application", "admission")):
            continue
        if not same_official_institution(link, str(package.official_url or "")):
            continue
        score = (
            (3 if "apply" in low else 0)
            + (2 if "application" in low else 0)
            + (1 if "admission" in low else 0)
        )
        candidates.append((score, len(link), link))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return candidates[0][2]


def _identity_tokens(value: str) -> list[str]:
    import re

    stop = {"master", "msc", "of", "in", "and", "the", "programme", "program", "studies"}
    tokens = [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 3 and token not in stop]
    return list(dict.fromkeys(tokens))[:12]


def _degree_identity_match(target_name: str, page_surface: str) -> str:
    import re

    target = target_name.lower()
    surface = page_surface.lower()
    if re.search(r"\bmsc\b|m\.sc\.?|master of science", target):
        positive = r"\bmsc\b|m\.sc\.?|master(?:'s)? of science|master(?:'s)? degree"
    elif re.search(r"\bma\b|master of arts", target):
        positive = r"\bma\b|master(?:'s)? of arts|master(?:'s)? degree"
    elif re.search(r"\bmba\b", target):
        positive = r"\bmba\b|master of business administration"
    elif re.search(r"\bmph\b", target):
        positive = r"\bmph\b|master of public health"
    else:
        positive = r"\bmaster(?:'s)?\b|postgraduate"
    has_positive = re.search(positive, surface, re.IGNORECASE) is not None
    has_undergraduate = (
        re.search(r"\bbsc\b|b\.sc\.?|\bbachelor(?:'s)?\b|\bundergraduate\b", surface, re.IGNORECASE)
        is not None
    )
    if has_undergraduate and not has_positive:
        return "conflict"
    return "matched" if has_positive else "missing"


def _index_link_record(package: ProgramDataPackage, candidate_url: str, source_url: str, snapshot, checked_at: datetime) -> FieldEvidenceRecord:
    return FieldEvidenceRecord(
        program_id=package.program_id,
        field_name="official_program_url",
        value=candidate_url,
        cycle=package.cycle,
        source_url=source_url,
        source_type="official_program_index",
        extracted_at=checked_at,
        page_hash=snapshot.page_hash,
        confidence="medium",
        source_priority=2,
        status=FieldVerificationStatus.model_inferred,
        review_required=True,
        evidence_snippet=f"索引页发现项目详情链接：{candidate_url}",
        snapshot_url=snapshot.snapshot_path,
        source_scope=SourceScope.institution_index,
        page_title=snapshot.page_title,
        final_url=snapshot.final_url,
        binding_status="index_only",
        binding_score=55,
        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "ProgrammeLinkDiscoveryAgent", "HumanReviewGateAgent"],
    )


def _extraction_result_for_failure(plan, snapshot, checked_at: datetime) -> SourceExtractionResult:
    return SourceExtractionResult(
        source_id=plan.source_id,
        source_url=plan.url,
        source_type=plan.channel,
        page_hash=snapshot.page_hash,
        snapshot_path=snapshot.snapshot_path,
        extracted_at=checked_at,
        parser="not_run",
        extracted_fields=[],
        unresolved_fields=OFFICIAL_REQUIREMENT_FIELD_ORDER,
        raw_json={"status": snapshot.status, "error": snapshot.error, "robots_url": snapshot.robots_url, "robots_allowed": snapshot.robots_allowed},
        fetch_status=snapshot.status,
        final_url=snapshot.final_url,
        page_title=snapshot.page_title,
        attempts=snapshot.attempts,
        duration_ms=snapshot.duration_ms,
        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "HtmlPdfTextExtractionAgent", "HumanReviewGateAgent"],
    )


def _extraction_result_for_index(plan, snapshot, checked_at: datetime, links: list[str], binding_score: int) -> SourceExtractionResult:
    return SourceExtractionResult(
        source_id=plan.source_id,
        source_url=plan.url,
        source_type=plan.channel,
        page_hash=snapshot.page_hash,
        snapshot_path=snapshot.snapshot_path,
        extracted_at=checked_at,
        parser="regex_html",
        extracted_fields=[],
        unresolved_fields=OFFICIAL_REQUIREMENT_FIELD_ORDER,
        raw_json={"status": snapshot.status, "discovered_links": links, "scope": plan.source_scope.value, "review_required": True},
        fetch_status=snapshot.status,
        final_url=snapshot.final_url,
        page_title=snapshot.page_title,
        binding_status="index_only",
        binding_score=binding_score,
        attempts=snapshot.attempts,
        duration_ms=snapshot.duration_ms,
        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "ProgrammeLinkDiscoveryAgent", "HumanReviewGateAgent"],
    )


def _extraction_result_for_unrelated(plan, snapshot, checked_at: datetime, binding_score: int) -> SourceExtractionResult:
    return SourceExtractionResult(
        source_id=plan.source_id,
        source_url=plan.url,
        source_type="official_program_page",
        page_hash=snapshot.page_hash,
        snapshot_path=snapshot.snapshot_path,
        extracted_at=checked_at,
        parser="not_run",
        extracted_fields=[],
        unresolved_fields=OFFICIAL_REQUIREMENT_FIELD_ORDER,
        raw_json={"status": snapshot.status, "reason": "programme binding gate rejected page"},
        fetch_status=snapshot.status,
        final_url=snapshot.final_url,
        page_title=snapshot.page_title,
        binding_status="unrelated",
        binding_score=binding_score,
        attempts=snapshot.attempts,
        duration_ms=snapshot.duration_ms,
        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "ProgrammeBindingGateAgent", "HumanReviewGateAgent"],
    )


def _extraction_result_for_detail(
    plan,
    snapshot,
    checked_at: datetime,
    links: list[str],
    candidates,
    binding_status: str,
    binding_score: int,
) -> SourceExtractionResult:
    resolved = {candidate.field_name for candidate in candidates if candidate.value is not None}
    if binding_status == "matched":
        resolved.add("official_program_url")
    return SourceExtractionResult(
        source_id=plan.source_id,
        source_url=plan.url,
        source_type="official_program_page",
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
            "discovered_links": links,
            "scope": plan.source_scope.value,
            "review_required": True,
        },
        fetch_status=snapshot.status,
        final_url=snapshot.final_url,
        page_title=snapshot.page_title,
        binding_status=binding_status,
        binding_score=binding_score,
        attempts=snapshot.attempts,
        duration_ms=snapshot.duration_ms,
        agent_chain=["SourceDiscoveryAgent", "SnapshotCrawlerAgent", "ProgrammeBindingGateAgent", "HtmlPdfTextExtractionAgent", "FieldCandidateAgent", "HumanReviewGateAgent"],
    )


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
            # Catalog/synthetic values are useful for gap analysis, but they
            # are not a source snapshot.  Persist them only as explicitly
            # non-publishable reference candidates.
            if record.status == FieldVerificationStatus.official_verified_current and not record.review_required:
                seen.add(key)
                continue
            if record.source_type == "official_program_index":
                record = record.model_copy(
                    update={
                        "source_type": "catalog_reference",
                        "status": FieldVerificationStatus.model_inferred,
                        "review_required": True,
                        "verified_at": None,
                    }
                )
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
        program_name_en=program.name,
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
    detail_url = student_program_url(program)
    if detail_url:
        plans.append(
            AcquisitionSourcePlan(
                source_id=f"program:{program.id}:detail",
                name=f"{program.institution} programme detail page",
                url=detail_url,
                channel="official_requirement",
                trust_level=SourceTrustLevel.official,
                allowed_fields=["official_program_url", "deadline", "tuition_hkd", "language_requirement", "materials", "essay_prompts", "application_url"],
                crawler_method="direct programme page snapshot and field parser",
                source_scope=SourceScope.programme_detail,
                target_program_id=program.id,
                next_actions=["确认页面标题、项目代码和当前申请季后，再把字段送入人工审核。"],
            )
        )
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
                source_scope=SourceScope.institution_index,
                target_program_id=program.id,
                next_actions=[
                    "采集官方索引页只用于发现项目详情链接，并保存 HTML/PDF 快照。",
                    "索引页不能直接提供截止日期、学费、语言或材料字段；必须再抓取项目详情页。",
                ],
            )
        )
    if not plans and not detail_url and program.source.url:
        plans.append(
            AcquisitionSourcePlan(
                source_id=f"program:{program.id}:index",
                name=f"{program.institution} programme index",
                url=program.source.url,
                channel="official_requirement",
                trust_level=SourceTrustLevel.official,
                allowed_fields=["official_program_url"],
                crawler_method="programme index snapshot and link discovery",
                source_scope=SourceScope.institution_index,
                target_program_id=program.id,
                next_actions=["先从索引页发现项目详情页，再按项目页重新采集要求字段。"],
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
                source_scope=SourceScope.community_reference,
                target_program_id=program.id,
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
