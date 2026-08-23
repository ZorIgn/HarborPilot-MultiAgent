from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4
from urllib.parse import urlparse, urlunparse

from harbor_agent.core.llm import LLMProvider
from harbor_agent.models import (
    DataRefreshReport,
    DataRefreshRequest,
    DataStatus,
    FieldExtractionCandidate,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramRefreshFinding,
    SourceExtractionResult,
    SourceCategory,
    SourceCheckResult,
    SourcePolicy,
    SourceTrustLevel,
)
from harbor_agent.services.evidence_graph import build_field_evidence_records
from harbor_agent.services.field_contract import ACQUISITION_FIELD_ORDER, FORMAL_RECOMMENDATION_FIELDS
from harbor_agent.services.data_loader import DATA_DIR, load_programs, load_source_registry
from harbor_agent.services.external_candidates import qs_import_summary_for_programs
from harbor_agent.services.information_store import _scope_for_source
from harbor_agent.services.resolved_program import decision_fact_value, resolve_program_views


class DataRefreshService:
    """Checks official/source registries and emits a review report without mutating catalog data."""

    name = "DataRefreshService"

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, request: DataRefreshRequest) -> DataRefreshReport:
        if not request.dry_run:
            raise ValueError(
                "DataRefreshService is offline compatibility planning only; use ProgramDataAcquisitionService with explicit real/hybrid mode for live fetches."
            )
        checked_at = datetime.now(UTC)
        run_id = f"refresh_{uuid4().hex[:12]}"
        programs = _select_programs(load_programs(), request)
        sources = _select_sources(request, programs)[: request.max_sources]
        source_checks = [
            self._check_source(source, True, checked_at)
            for source in sources
        ]
        views = resolve_program_views(programs)
        findings = [_finding_for_program(program, sources, source_checks, views[program.id]) for program in programs]
        extraction_results = _build_extraction_results(sources, source_checks, checked_at)
        qs_import_summary = qs_import_summary_for_programs(programs)
        if qs_import_summary["matched_candidate_count"]:
            extraction_results.insert(0, _qs_import_extraction_result(qs_import_summary, checked_at))
        field_records = [
            record
            for record in build_field_evidence_records(programs)
            if record.status != FieldVerificationStatus.official_verified_current
        ]
        # A source-level refresh has no programme binding context. It may
        # produce snapshots and extraction candidates, but must not copy
        # catalog values into field evidence. Programme-bound extraction is
        # handled by ProgramDataAcquisitionService.
        official_count = sum(1 for source in sources if source.trust_level == SourceTrustLevel.official)
        community_count = sum(1 for source in sources if source.trust_level == SourceTrustLevel.community)
        stale_ids = [
            finding.program_id
            for finding in findings
            if finding.data_status in {DataStatus.stale, DataStatus.pending_review, DataStatus.extracted}
        ]
        changed_ids: list[str] = []
        not_published_ids = [
            finding.program_id
            for finding in findings
            if finding.data_status == DataStatus.not_published
            or "deadline" in finding.fields_requiring_review
        ]
        summary = _summary(request, sources, findings, source_checks)
        if qs_import_summary["matched_candidate_count"]:
            summary += (
                f" 已接入 GradWindow/QS Master Applications 的 "
                f"{qs_import_summary['matched_candidate_count']} 条港新官网线索。"
            )
        next_actions = _next_actions_clean(request, findings, qs_import_summary)

        if request.use_llm:
            # This compatibility report is a governance projection.  Letting a
            # free-form model rewrite its summary would create a second,
            # non-authoritative claim channel, so retain deterministic wording.
            next_actions.insert(
                0,
                "已忽略 use_llm：离线来源检查只输出由结构化 DecisionFact 投影的确定性说明。",
            )

        return DataRefreshReport(
            run_id=run_id,
            mode="dry_run",
            checked_at=checked_at,
            region=request.region,
            selected_program_ids=request.selected_program_ids,
            sources_checked=len(source_checks),
            official_sources_checked=official_count,
            community_sources_checked=community_count,
            source_checks=source_checks,
            program_findings=findings,
            field_evidence_records=field_records[:80],
            extraction_results=extraction_results[:40],
            parser_plan=_parser_plan(sources),
            review_queue_size=len(field_records),
            stale_program_ids=stale_ids,
            changed_program_ids=changed_ids,
            not_published_program_ids=not_published_ids,
            human_review_required=bool(stale_ids or not_published_ids or changed_ids),
            summary=summary,
            next_actions=next_actions,
            truth_scope="operational_source_check",
            formal_ready_program_count=sum(view.formal_readiness.value == "PASS" for view in views.values()),
            formal_blocker_count=sum(len(view.formal_blockers) for view in views.values()),
        )

    def _check_source(
        self,
        source: SourcePolicy,
        dry_run: bool,
        checked_at: datetime,
        run_id: str | None = None,
    ) -> SourceCheckResult:
        if not dry_run:
            raise ValueError(
                "DataRefreshService never performs live fetches; use ProgramDataAcquisitionService with real/hybrid mode."
            )
        return SourceCheckResult(
            source_id=source.source_id,
            name=source.name,
            url=source.url,
            category=source.category,
            trust_level=source.trust_level,
            status="SKIPPED_DRY_RUN",
            checked_at=checked_at,
            robots_txt_url=_robots_txt_url(str(source.url)),
            robots_allowed=None,
            robots_status="SKIPPED_DRY_RUN",
            summary=f"Dry-run：登记刷新策略为 {source.refresh_cadence}，本次不联网采集。",
            next_actions=[
                "真实更新请使用受控采集 API，并显式选择 real/hybrid 模式、项目范围和 operator 授权。",
                "抓取后只产生候选，仍需绑定、人工审核和发布，不能自动覆盖正式事实。",
            ],
        )


def _select_programs(programs: list[Program], request: DataRefreshRequest) -> list[Program]:
    selected_ids = set(request.selected_program_ids)
    filtered = [
        program
        for program in programs
        if (request.region == "ALL" or program.country == request.region)
        and (not request.institution or request.institution.lower() in program.institution.lower())
    ]
    if selected_ids:
        selected = [program for program in filtered if program.id in selected_ids]
        if selected:
            return selected
    return filtered[:24]


def _select_sources(request: DataRefreshRequest, programs: list[Program]) -> list[SourcePolicy]:
    registry = load_source_registry()
    source_ids = _source_ids_for_programs(programs)
    primary = [
        source
        for source in registry.sources
        if source.source_id in source_ids
        or (request.region != "ALL" and source.region == request.region and source.trust_level == SourceTrustLevel.official)
    ]
    methodology = [
        source
        for source in registry.sources
        if source.category
        in {
            SourceCategory.selection_methodology,
            SourceCategory.community_result,
            SourceCategory.writing_style_reference,
        }
    ][:6]
    seen: set[str] = set()
    ordered: list[SourcePolicy] = []
    for source in primary + methodology:
        if source.source_id not in seen:
            ordered.append(source)
            seen.add(source.source_id)
    return ordered


def _source_ids_for_programs(programs: list[Program]) -> set[str]:
    ids: set[str] = set()
    for program in programs:
        url = str(program.official_program_url or program.source.url).lower()
        institution = program.institution.lower()
        if "hku.hk" in url and "cuhk" not in url and "hkust" not in url and "cityu" not in url:
            ids.add("hku_tpg_index")
        if "cuhk" in url or "chinese university" in institution:
            ids.add("cuhk_programme_list")
        if "hkust" in url or "science and technology" in institution:
            ids.add("hkust_pgprog")
        if "cityu" in url or "city university" in institution:
            ids.add("cityuhk_tpg_index")
        if "polyu" in url or "polytechnic" in institution:
            ids.add("polyu_tpg_index")
        if "hkbu" in url or "baptist" in institution:
            ids.add("hkbu_tpg_index")
        if "ln.edu" in url or "lingnan" in institution:
            ids.add("lingnan_tpg_index")
        if "eduhk" in url or "education university" in institution:
            ids.add("eduhk_pg_index")
        if "nus.edu" in url or "national university of singapore" in institution:
            ids.add("nus_grad_programmes")
        if "ntu.edu" in url or "nanyang technological" in institution:
            ids.add("ntu_grad_programmes")
        if "smu.edu" in url or "singapore management" in institution:
            ids.add("smu_masters_programmes")
        if "sutd" in url or "technology and design" in institution:
            ids.add("sutd_graduate_admissions")
    return ids


def _live_field_records(
    programs: list[Program],
    checks: list[SourceCheckResult],
    checked_at: datetime,
) -> list[FieldEvidenceRecord]:
    return []


def _build_extraction_results(
    sources: list[SourcePolicy],
    checks: list[SourceCheckResult],
    checked_at: datetime,
) -> list[SourceExtractionResult]:
    source_by_id = {source.source_id: source for source in sources}
    results: list[SourceExtractionResult] = []
    for check in checks:
        source = source_by_id.get(check.source_id)
        if not source:
            continue
        if check.status != "FETCH_OK" or not check.snapshot_path:
            results.append(
                SourceExtractionResult(
                    source_id=check.source_id,
                    source_url=check.url,
                    source_type=check.category.value if hasattr(check.category, "value") else str(check.category),
                    page_hash=check.page_hash,
                    snapshot_path=check.snapshot_path,
                    extracted_at=checked_at,
                    parser="not_run",
                    extracted_fields=[],
                    unresolved_fields=_reviewer_gate_fields(),
                    raw_json={
                        "status": check.status,
                        "reason": "source was not fetched; extraction skipped",
                    },
                    execution_ref=None,
                )
            )
            continue

        text = _read_snapshot_text(check.snapshot_path)
        raw_html = _read_snapshot_html(check.snapshot_path)
        source_scope = _scope_for_source(source)
        candidates = (
            _extract_field_candidates(text)
            if source_scope.value == "programme_detail"
            else []
        )
        resolved = {candidate.field_name for candidate in candidates}
        unresolved = [field for field in _reviewer_gate_fields() if field not in resolved]
        discovered_links = _discover_program_links(raw_html, source.url)
        results.append(
            SourceExtractionResult(
                source_id=check.source_id,
                source_url=check.url,
                source_type=check.category.value if hasattr(check.category, "value") else str(check.category),
                page_hash=check.page_hash,
                snapshot_path=check.snapshot_path,
                extracted_at=checked_at,
                parser="regex_html",
                extracted_fields=candidates,
                unresolved_fields=unresolved,
                raw_json={
                    "source_id": check.source_id,
                    "source_url": str(check.url),
                    "page_hash": check.page_hash,
                    "snapshot_path": check.snapshot_path,
                    "fields": [candidate.model_dump(mode="json") for candidate in candidates],
                    "unresolved_fields": unresolved,
                    "discovered_program_links": discovered_links[:30],
                    "source_scope": source_scope.value,
                    "index_boundary": (
                        "Institution/index sources may discover programme links but cannot provide programme-level requirement fields."
                        if source_scope.value == "institution_index"
                        else None
                    ),
                    "review_required": True,
                },
                fetch_status=check.status,
                binding_status=(
                    "index_only" if source_scope.value == "institution_index" else "not_checked"
                ),
                execution_ref=None,
            )
        )
    return results


def _read_snapshot_text(snapshot_path: str) -> str:
    return _clean_text(_read_snapshot_html(snapshot_path))


def _read_snapshot_html(snapshot_path: str) -> str:
    path = DATA_DIR.parent / snapshot_path
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="ignore")


def _extract_field_candidates(text: str) -> list[FieldExtractionCandidate]:
    # Retained for offline compatibility callers.  Reuse the controlled
    # pipeline extractor so this report cannot silently omit hard GPA,
    # background or portfolio fields from the operator's review contract.
    from harbor_agent.services.source_snapshot import extract_field_candidates

    return extract_field_candidates(text)


def _extract_deadline(text: str) -> FieldExtractionCandidate | None:
    patterns = [
        r"(?P<snippet>.{0,80}(deadline|closing date|application closes|截止|申请截止).{0,120})",
        r"(?P<snippet>.{0,80}(20[2-9][0-9][-/.\s年]+[01]?[0-9][-/.\s月]+[0-3]?[0-9]).{0,80})",
    ]
    snippet = _first_snippet(text, patterns)
    if not snippet:
        return None
    date_match = re.search(r"20[2-9][0-9][-/.\s年]+[01]?[0-9][-/.\s月]+[0-3]?[0-9]", snippet)
    return FieldExtractionCandidate(
        field_name="deadline",
        value=_normalize_space(date_match.group(0)) if date_match else None,
        evidence_snippet=snippet,
        confidence="medium" if date_match else "low",
    )


def _extract_tuition(text: str) -> FieldExtractionCandidate | None:
    snippet = _first_snippet(
        text,
        [r"(?P<snippet>.{0,80}(tuition|programme fee|program fee|学费|费用).{0,120})"],
    )
    if not snippet:
        return None
    amount = re.search(
        r"(?P<currency>HK\$|HKD|S\$|SGD|RMB|CNY|USD)\s*(?P<amount>[0-9][0-9,]{3,})",
        snippet,
        re.IGNORECASE,
    )
    if amount is None:
        amount = re.search(
            r"(?P<currency>)(?P<amount>[0-9][0-9,]{3,})(?=\s*(?:per\s+year|tuition|fee|学费|费用))",
            snippet,
            re.IGNORECASE,
        )
    currency = (amount.group("currency") or "UNSPECIFIED").upper() if amount else None
    return FieldExtractionCandidate(
        field_name="tuition_hkd" if currency in {"HK$", "HKD"} else "tuition_original",
        value=(f"{currency} {amount.group('amount')}" if amount and currency else None),
        evidence_snippet=snippet,
        confidence="medium" if amount else "low",
    )


def _extract_language(text: str) -> FieldExtractionCandidate | None:
    snippet = _first_snippet(
        text,
        [r"(?P<snippet>.{0,80}(ielts|toefl|pte|english language|雅思|托福|语言).{0,120})"],
    )
    if not snippet:
        return None
    return FieldExtractionCandidate(
        field_name="language_requirement",
        value=_normalize_space(snippet[:180]),
        evidence_snippet=snippet,
        confidence="medium",
    )


def _extract_materials(text: str) -> FieldExtractionCandidate | None:
    snippet = _first_snippet(
        text,
        [
            r"(?P<snippet>.{0,80}(transcript|recommendation|personal statement|cv|resume|成绩单|推荐信|个人陈述|简历).{0,160})"
        ],
    )
    if not snippet:
        return None
    return FieldExtractionCandidate(
        field_name="materials",
        value=_normalize_space(snippet[:220]),
        evidence_snippet=snippet,
        confidence="medium",
    )


def _extract_application_hint(text: str) -> FieldExtractionCandidate | None:
    snippet = _first_snippet(
        text,
        [r"(?P<snippet>.{0,80}(online application|application system|apply now|apply|网申|申请系统).{0,120})"],
    )
    if not snippet:
        return None
    return FieldExtractionCandidate(
        field_name="application_url",
        value=None,
        evidence_snippet=snippet,
        confidence="low",
    )


def _extract_essay_prompt(text: str) -> FieldExtractionCandidate | None:
    snippet = _first_snippet(
        text,
        [r"(?P<snippet>.{0,80}(admission essay|essay question|statement of purpose|personal statement|writing sample|申请文书|文书题目|个人陈述).{0,160})"],
    )
    if not snippet:
        return None
    return FieldExtractionCandidate(
        field_name="essay_prompts",
        value=_normalize_space(snippet[:220]),
        evidence_snippet=snippet,
        confidence="low",
    )


def _first_snippet(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_space(match.group("snippet"))
    return None


def _clean_text(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _normalize_space(text)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _field_value(program: Program, field_name: str) -> str | None:
    if field_name == "deadline":
        return str(program.deadline)
    if field_name == "tuition_hkd":
        return str(program.tuition_hkd) if program.tuition_hkd is not None else None
    if field_name == "materials":
        return ", ".join(program.materials)
    if field_name in {"requirements", "language_requirement"}:
        return ", ".join(f"{name} {score}" for name, score in program.requirements.language.items())
    if field_name == "application_url":
        return str(program.application_url) if program.application_url else None
    if field_name == "official_program_url":
        return str(program.official_program_url) if program.official_program_url else None
    if field_name == "last_verified_at":
        return program.last_verified_at.isoformat() if program.last_verified_at else None
    return None


def _reviewer_gate_fields() -> list[str]:
    return list(ACQUISITION_FIELD_ORDER)


def _source_priority_from_category(category: SourceCategory) -> int:
    priority = {
        SourceCategory.official_application_system: 1,
        SourceCategory.official_program_page: 2,
        SourceCategory.official_pdf_or_faq: 3,
        SourceCategory.official_program_index: 4,
        SourceCategory.ranking_or_directory: 5,
        SourceCategory.community_result: 6,
    }
    return priority.get(category, 99)


def _field_hints_from_sample(sample: str) -> list[str]:
    hints: list[str] = []
    patterns = {
        "deadline": r"deadline|application closes|closing date|截止|申请截止",
        "tuition_hkd": r"tuition|programme fee|application fee|学费|费用",
        "materials": r"transcript|recommendation|personal statement|cv|resume|成绩单|推荐信|个人陈述",
        "language_requirement": r"ielts|toefl|pte|english language|雅思|托福|语言",
        "application_url": r"apply|application system|online application|网申|申请系统",
        "essay_prompts": r"essay|statement of purpose|personal statement|文书|题目",
    }
    lowered = sample.lower()
    for field_name, pattern in patterns.items():
        if re.search(pattern, lowered, re.IGNORECASE):
            hints.append(field_name)
    return hints


def _robots_txt_url(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def _finding_for_program(
    program: Program,
    sources: list[SourcePolicy],
    checks: list[SourceCheckResult],
    view,
) -> ProgramRefreshFinding:
    """Build an offline discovery report from DecisionFacts, never catalog rows.

    ``official_url`` is reserved for a published current fact.  A URL seen in
    a registry or token-overlap discovery pass is only a candidate and must go
    through controlled acquisition, binding and reviewer publication first.
    """

    fields = _fields_requiring_review(view)
    source_ids = [source.source_id for source in sources if source.source_id in _source_ids_for_programs([program])]
    status = _recommended_status(view, fields)
    official_url = decision_fact_value(view, "official_program_url")
    return ProgramRefreshFinding(
        program_id=program.id,
        institution=program.institution_zh or program.institution,
        program_name=program.name_zh or program.name,
        data_status=status,
        official_url=official_url,
        source_ids=source_ids,
        fields_requiring_review=fields,
        summary=(
            "当前季字段级正式事实尚未齐全；catalog 与发现链接只作为采集线索。"
            if fields
            else "当前季字段级正式事实已齐全；提交前仍应重新核对学校页面。"
        ),
        next_actions=_program_actions(program, fields),
    )


def _fields_requiring_review(view) -> list[str]:
    return [
        field_name
        for field_name in FORMAL_RECOMMENDATION_FIELDS
        if not view.fact(field_name).formal_use_ready
    ]


def _recommended_status(view, fields: list[str]) -> DataStatus:
    deadline = view.fact("deadline")
    if deadline.provenance_status.value == "NOT_PUBLISHED":
        return DataStatus.not_published
    if not fields and view.formal_readiness.value == "PASS":
        return DataStatus.verified
    return DataStatus.pending_review


def _program_actions(program: Program, fields: list[str]) -> list[str]:
    actions = []
    if "deadline" in fields:
        actions.append("打开官方项目页或申请系统，确认 2027 Fall 申请开放时间和最终截止日期。")
    if "tuition_hkd" in fields:
        actions.append("确认学费币种、全日制/兼读制差异和是否按学年收费。")
    if any(field in fields for field in {"materials", "min_gpa", "language_requirement", "required_backgrounds", "portfolio_required"}):
        actions.append("核对材料清单、语言要求、先修课、作品集或工作经验要求。")
    if program.community_signals:
        actions.append("社区线索只用于发现别名，需回到学校页面确认。")
    return actions[:5]


def _summary(
    request: DataRefreshRequest,
    sources: list[SourcePolicy],
    findings: list[ProgramRefreshFinding],
    checks: list[SourceCheckResult],
) -> str:
    mode = "dry-run 策略检查" if request.dry_run else "联网可达性检查"
    official = sum(1 for source in sources if source.trust_level == SourceTrustLevel.official)
    failed = sum(1 for check in checks if check.status == "FETCH_FAILED")
    review_fields = sum(len(item.fields_requiring_review) for item in findings)
    return (
        f"本次执行 {mode}，覆盖 {len(findings)} 个项目、{len(sources)} 个来源，其中官方来源 {official} 个。"
        f"发现 {review_fields} 个需核验信息点；联网失败来源 {failed} 个。"
    )


def _next_actions(request: DataRefreshRequest, findings: list[ProgramRefreshFinding]) -> list[str]:
    actions = [
        "优先处理已选项目，不把需核验信息用于最终申请结论。",
        "官方索引只负责发现项目；截止日期、学费、材料和语言要求必须回到项目页、PDF、FAQ 或申请系统逐项确认。",
        "社区和目录来源只作为线索、别名、经验和产品方法参考。",
    ]
    if request.dry_run:
        actions.insert(0, "如需实际联网检查，将 dry_run 设为 false；系统仍只生成报告，不覆盖数据文件。")
    if any("deadline" in finding.fields_requiring_review for finding in findings):
        actions.append("生成正式时间线前，应确认截止日期；学校未公布时标记为本季未发布。")
    return actions[:6]


def _next_actions_clean(
    request: DataRefreshRequest,
    findings: list[ProgramRefreshFinding],
    qs_import_summary: dict | None = None,
) -> list[str]:
    actions = [
        "优先处理学生最终项目清单；没有项目官网页面核对的信息，只作为材料准备提醒。",
        "项目名称、申请入口、截止日期、学费、语言和材料要求，需要回到学校项目页、PDF/FAQ 或申请系统逐项确认。",
        "GitHub、GradCafe、小红书等二级来源只用于发现线索和理解经验，不能直接当作学校要求。",
    ]
    if qs_import_summary and qs_import_summary.get("matched_candidate_count"):
        actions.insert(
            0,
            "已找到 GradWindow/QS Master Applications 的港新官网线索；下一步打开对应学校项目页确认当前申请季原文。",
        )
    if request.dry_run:
        actions.insert(0, "当前是预检查：系统只整理线索和确认清单，不会改写项目库。")
    if any("deadline" in finding.fields_requiring_review for finding in findings):
        actions.append("生成正式日程前，必须确认截止日期；学校尚未公布时，只生成准备建议。")
    return actions[:6]


def _qs_import_extraction_result(qs_import_summary: dict, checked_at: datetime) -> SourceExtractionResult:
    candidates = qs_import_summary.get("matched_candidates", [])
    extracted_fields: list[FieldExtractionCandidate] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        closes_at = candidate.get("closes_at")
        if closes_at:
            extracted_fields.append(
                FieldExtractionCandidate(
                    field_name="deadline",
                    value=str(closes_at),
                    evidence_snippet=str(candidate.get("evidence") or "")[:500],
                    confidence="medium",
                    # A GitHub/QS discovery import is a lead, never official
                    # prior-cycle evidence.  It requires an independent
                    # official snapshot, binding and review before publication.
                    status=FieldVerificationStatus.model_inferred,
                    review_required=True,
                )
            )
        application_url = candidate.get("application_url")
        if application_url:
            extracted_fields.append(
                FieldExtractionCandidate(
                    field_name="application_url",
                    value=str(application_url),
                    evidence_snippet="GradWindow 导入的学校申请入口线索，需回到学校官网确认后发布。",
                    confidence="medium",
                    status=FieldVerificationStatus.model_inferred,
                    review_required=True,
                )
            )

    return SourceExtractionResult(
        source_id=str(qs_import_summary.get("source_id") or "qs_master_applications_github"),
        source_url=str(qs_import_summary.get("source_url") or "https://github.com/lione12138/qs-master-applications"),
        source_type="selection_methodology",
        page_hash=None,
        snapshot_path=None,
        extracted_at=checked_at,
        parser="not_run",
        extracted_fields=extracted_fields[:24],
        unresolved_fields=list(ACQUISITION_FIELD_ORDER),
        raw_json=qs_import_summary,
        execution_ref=None,
    )


def _parser_plan(sources: list[SourcePolicy]) -> list[str]:
    official_names = [source.name for source in sources if source.trust_level == SourceTrustLevel.official]
    return [
        "Playwright/httpx 采集官方索引，保存 HTML/PDF 快照和 page_hash。",
        "字段提取流程抽取截止日期、学费、材料、语言、申请入口等候选信息。",
        "变更比较流程比对上次快照，只有页面变化才进入确认清单。",
        "人工审核确认关键信息；未核验字段在学生端显示为官网当前季未核验或往届参考。",
        "当前优先 parser：" + "、".join(official_names[:6]) if official_names else "当前没有匹配到官方 parser。",
    ]


def _discover_program_links(html: str, base_url: str) -> list[dict[str, str]]:
    if not html:
        return []
    links: list[dict[str, str]] = []
    for match in re.finditer(
        r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<label>.*?)</a>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        label = _clean_text(match.group("label"))
        href = match.group("href").strip()
        if not label or len(label) < 4:
            continue
        lowered = f"{label} {href}".lower()
        if not any(token in lowered for token in ["master", "msc", "programme", "program", "postgraduate", "graduate"]):
            continue
        links.append({"label": label[:160], "url": _absolute_url(base_url, href)})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        if link["url"] in seen:
            continue
        deduped.append(link)
        seen.add(link["url"])
    return deduped


def _discovered_program_url(program: Program, checks: list[SourceCheckResult]) -> str | None:
    program_terms = _program_terms(program)
    best: tuple[int, str] | None = None
    for check in checks:
        if check.status != "FETCH_OK" or not check.snapshot_path:
            continue
        if check.trust_level != SourceTrustLevel.official:
            continue
        html = _read_snapshot_html(check.snapshot_path)
        for link in _discover_program_links(html, str(check.url)):
            haystack = f"{link['label']} {link['url']}".lower()
            score = sum(1 for term in program_terms if term and term in haystack)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, link["url"])
    return best[1] if best else None


def _program_terms(program: Program) -> list[str]:
    raw = [
        program.name,
        program.name_zh or "",
        program.institution,
        program.institution_zh or "",
        *(program.name.lower().replace("-", " ").split()),
    ]
    stopwords = {"master", "msc", "science", "in", "of", "the", "and", "理学硕士", "硕士"}
    terms = []
    for item in raw:
        text = str(item).strip().lower()
        if not text or text in stopwords or len(text) < 3:
            continue
        terms.append(text)
    return terms[:18]


def _absolute_url(base_url: str, href: str) -> str:
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    base = str(base_url)
    if href.startswith("/"):
        root_match = re.match(r"^(https?://[^/]+)", base)
        return (root_match.group(1) if root_match else base.rstrip("/")) + href
    return base.rsplit("/", 1)[0].rstrip("/") + "/" + href
