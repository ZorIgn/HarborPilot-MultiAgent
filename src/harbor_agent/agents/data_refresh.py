from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
from harbor_agent.services.data_loader import DATA_DIR, load_programs, load_source_registry
from harbor_agent.services.external_candidates import qs_import_summary_for_programs


class DataRefreshAgent:
    """Checks official/source registries and emits a review report without mutating catalog data."""

    name = "DataRefreshAgent"

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, request: DataRefreshRequest) -> DataRefreshReport:
        checked_at = datetime.now(UTC)
        programs = _select_programs(load_programs(), request)
        sources = _select_sources(request, programs)[: request.max_sources]
        source_checks = [self._check_source(source, request.dry_run, checked_at) for source in sources]
        findings = [_finding_for_program(program, sources, source_checks) for program in programs]
        extraction_results = _build_extraction_results(sources, source_checks, checked_at)
        qs_import_summary = qs_import_summary_for_programs(programs)
        if qs_import_summary["matched_candidate_count"]:
            extraction_results.insert(0, _qs_import_extraction_result(qs_import_summary, checked_at))
        field_records = [
            record
            for record in build_field_evidence_records(programs)
            if record.status != FieldVerificationStatus.official_verified_current
        ]
        if not request.dry_run:
            field_records = _live_field_records(programs, source_checks, checked_at) + field_records
        official_count = sum(1 for source in sources if source.trust_level == SourceTrustLevel.official)
        community_count = sum(1 for source in sources if source.trust_level == SourceTrustLevel.community)
        stale_ids = [
            finding.program_id
            for finding in findings
            if finding.data_status in {DataStatus.stale, DataStatus.pending_review, DataStatus.extracted}
        ]
        changed_ids = [
            finding.program_id
            for finding in findings
            if any(check.changed_fields for check in source_checks if check.status == "FETCH_OK")
        ]
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

        if request.use_llm and self.llm.name != "mock":
            summary, next_actions = self._llm_summarize(summary, next_actions, findings, source_checks)

        return DataRefreshReport(
            run_id=f"refresh_{uuid4().hex[:12]}",
            mode="dry_run" if request.dry_run else "live_fetch",
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
        )

    def _check_source(
        self,
        source: SourcePolicy,
        dry_run: bool,
        checked_at: datetime,
    ) -> SourceCheckResult:
        if dry_run:
            return SourceCheckResult(
                source_id=source.source_id,
                name=source.name,
                url=source.url,
                category=source.category,
                trust_level=source.trust_level,
                status="SKIPPED_DRY_RUN",
                checked_at=checked_at,
                summary=f"Dry-run：登记刷新策略为 {source.refresh_cadence}，本次不联网抓取。",
                next_actions=[
                    "正式刷新时先检查 robots/服务条款，再抓取官方索引或项目页。",
                    "抽取后只生成变化报告，不自动覆盖学校信息。",
                ],
            )

        try:
            request = Request(
                str(source.url),
                method="GET",
                headers={
                    "User-Agent": "HarborPilotAI/0.1 source freshness checker (manual review)",
                },
            )
            with urlopen(request, timeout=12) as response:
                http_status = int(response.status)
                body = response.read(512_000)
            page_hash = f"sha256:{hashlib.sha256(body).hexdigest()}"
            snapshot_path = _save_snapshot(source, body, checked_at, page_hash)
            sample = body[:4096].decode("utf-8", errors="ignore")
            return SourceCheckResult(
                source_id=source.source_id,
                name=source.name,
                url=source.url,
                category=source.category,
                trust_level=source.trust_level,
                status="FETCH_OK" if http_status < 400 else "REVIEW_REQUIRED",
                checked_at=checked_at,
                http_status=http_status,
                page_hash=page_hash,
                snapshot_path=snapshot_path,
                content_bytes=len(body),
                changed_fields=_field_hints_from_sample(sample),
                summary=(
                    f"已获取源页面 {len(body)} bytes，保存快照并生成 {page_hash[:19]}...；"
                    "下一步应提取候选信息、对比页面变化，并由人工确认后发布。"
                ),
                next_actions=[
                    "对项目名、截止日期、学费、材料、语言要求分别绑定学校来源。",
                    "对社区/目录来源只保留线索，不写入学校正式要求。",
                ],
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            return SourceCheckResult(
                source_id=source.source_id,
                name=source.name,
                url=source.url,
                category=source.category,
                trust_level=source.trust_level,
                status="FETCH_FAILED",
                checked_at=checked_at,
                http_status=getattr(exc, "code", None),
                summary=f"联网检查失败：{type(exc).__name__}。保留为待确认项。",
                next_actions=[
                    "打开官方页面人工确认是否改版、限流或需要 JS 渲染。",
                    "必要时改用学校提供的 PDF、FAQ 或申请系统页面作为字段来源。",
                ],
            )

    def _llm_summarize(
        self,
        summary: str,
        next_actions: list[str],
        findings: list[ProgramRefreshFinding],
        checks: list[SourceCheckResult],
    ) -> tuple[str, list[str]]:
        completion = self.llm.complete_json(
            system=(
                "You are a data-governance agent for an admissions information platform. "
                "Summarize only the provided source-check report. Do not invent school facts."
            ),
            user=(
                f"summary={summary}\n"
                f"program_findings={[item.model_dump(mode='json') for item in findings[:20]]}\n"
                f"source_checks={[item.model_dump(mode='json') for item in checks[:20]]}\n"
                f"next_actions={next_actions}"
            ),
            schema_hint={"summary": "string", "next_actions": ["string"]},
        )
        new_summary = completion.get("summary")
        actions = completion.get("next_actions")
        if not isinstance(new_summary, str) or not new_summary.strip():
            new_summary = summary
        if not isinstance(actions, list):
            actions = next_actions
        return new_summary, [str(item) for item in actions if str(item).strip()][:6]


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
    checks_by_id = {
        check.source_id: check
        for check in checks
        if check.status == "FETCH_OK" and check.page_hash
    }
    records: list[FieldEvidenceRecord] = []
    for program in programs:
        source_ids = _source_ids_for_programs([program])
        check = next((checks_by_id[source_id] for source_id in source_ids if source_id in checks_by_id), None)
        if not check:
            continue
        for field_name in _fields_requiring_review(program) or _reviewer_gate_fields():
            records.append(
                FieldEvidenceRecord(
                    program_id=program.id,
                    field_name=field_name,
                    value=_field_value(program, field_name),
                    cycle=program.cycle,
                    source_url=check.url,
                    source_type=check.category.value if hasattr(check.category, "value") else str(check.category),
                    extracted_at=checked_at,
                    verified_at=None,
                    page_hash=check.page_hash,
                    confidence="medium" if field_name in check.changed_fields else "low",
                    source_priority=_source_priority_from_category(check.category),
                    status=FieldVerificationStatus.official_previous_cycle,
                    review_required=True,
                    evidence_snippet=(
                        "已保存学校来源快照。该信息需要人工查看原文后才能发布为已确认。"
                    ),
                    snapshot_url=check.snapshot_path,
                    agent_chain=[
                        "SourceDiscoveryAgent",
                        "PageFetchAgent",
                        "SnapshotAgent",
                        "FieldExtractionAgent",
                        "CrossCheckAgent",
                        "HumanReviewAgent",
                    ],
                )
            )
    return records


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
                    agent_chain=["SourceDiscoveryAgent", "PageFetchAgent", "FieldExtractionAgent"],
                )
            )
            continue

        text = _read_snapshot_text(check.snapshot_path)
        raw_html = _read_snapshot_html(check.snapshot_path)
        candidates = _extract_field_candidates(text)
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
                    "review_required": True,
                },
                agent_chain=[
                    "SourceDiscoveryAgent",
                    "PageFetchAgent",
                    "SnapshotAgent",
                    "FieldExtractionAgent",
                    "CrossCheckAgent",
                    "HumanReviewAgent",
                ],
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
    candidates: list[FieldExtractionCandidate] = []
    deadline = _extract_deadline(text)
    if deadline:
        candidates.append(deadline)
    tuition = _extract_tuition(text)
    if tuition:
        candidates.append(tuition)
    language = _extract_language(text)
    if language:
        candidates.append(language)
    materials = _extract_materials(text)
    if materials:
        candidates.append(materials)
    app_url = _extract_application_hint(text)
    if app_url:
        candidates.append(app_url)
    essay = _extract_essay_prompt(text)
    if essay:
        candidates.append(essay)
    return candidates


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
    amount = re.search(r"(HK\$|S\$|SGD|HKD|RMB|CNY|USD)?\s?[0-9][0-9,]{3,}", snippet, re.IGNORECASE)
    return FieldExtractionCandidate(
        field_name="tuition_hkd",
        value=_normalize_space(amount.group(0)) if amount else None,
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
        [r"(?P<snippet>.{0,80}(essay|statement of purpose|personal statement|study plan|文书|个人陈述|学习计划).{0,160})"],
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
    return ["deadline", "tuition_hkd", "materials", "language_requirement", "application_url", "essay_prompts"]


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


def _save_snapshot(source: SourcePolicy, body: bytes, checked_at: datetime, page_hash: str) -> str:
    snapshot_dir = DATA_DIR / "snapshots" / checked_at.strftime("%Y%m%d")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source.source_id)[:80]
    digest = page_hash.split(":", 1)[-1][:16]
    suffix = ".html" if _looks_like_html(body) else ".bin"
    path = snapshot_dir / f"{safe_id}_{digest}{suffix}"
    path.write_bytes(body)
    return str(Path("data") / "snapshots" / checked_at.strftime("%Y%m%d") / path.name)


def _looks_like_html(body: bytes) -> bool:
    sample = body[:512].lower()
    return b"<html" in sample or b"<!doctype html" in sample or b"<body" in sample


def _finding_for_program(
    program: Program,
    sources: list[SourcePolicy],
    checks: list[SourceCheckResult],
) -> ProgramRefreshFinding:
    fields = _fields_requiring_review(program)
    source_ids = [source.source_id for source in sources if source.source_id in _source_ids_for_programs([program])]
    status = _recommended_status(program, fields)
    discovered_url = _discovered_program_url(program, checks)
    return ProgramRefreshFinding(
        program_id=program.id,
        institution=program.institution_zh or program.institution,
        program_name=program.name_zh or program.name,
        data_status=status,
        official_url=discovered_url or program.official_program_url or program.source.url,
        source_ids=source_ids,
        fields_requiring_review=fields,
        summary=(
            "关键信息已进入学校官网确认清单。"
            if fields
            else "当前信息没有发现明显缺口，但仍需在正式递交前再次查看学校页面。"
        ),
        next_actions=_program_actions(program, fields),
    )


def _fields_requiring_review(program: Program) -> list[str]:
    fields: list[str] = []
    if program.source.field_coverage != "complete":
        fields.extend(["deadline", "tuition_hkd", "materials", "requirements"])
    if program.deadline == "NOT_PUBLISHED":
        fields.append("deadline")
    if program.last_verified_at is None:
        fields.append("last_verified_at")
    if not program.official_program_url:
        fields.append("official_program_url")
    if not program.application_url:
        fields.append("application_url")
    return sorted(set(fields))


def _recommended_status(program: Program, fields: list[str]) -> DataStatus:
    if program.deadline == "NOT_PUBLISHED":
        return DataStatus.not_published
    if program.data_status == DataStatus.verified and not fields:
        return DataStatus.verified
    if program.data_status in {DataStatus.changed, DataStatus.stale}:
        return program.data_status
    return DataStatus.pending_review if fields else program.data_status


def _program_actions(program: Program, fields: list[str]) -> list[str]:
    actions = []
    if "deadline" in fields:
        actions.append("打开官方项目页或申请系统，确认 2027 Fall 申请开放时间和最终截止日期。")
    if "tuition_hkd" in fields:
        actions.append("确认学费币种、全日制/兼读制差异和是否按学年收费。")
    if "materials" in fields or "requirements" in fields:
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
        f"发现 {review_fields} 个待确认信息点；联网失败来源 {failed} 个。"
    )


def _next_actions(request: DataRefreshRequest, findings: list[ProgramRefreshFinding]) -> list[str]:
    actions = [
        "优先处理已选项目，不把未确认信息用于最终申请结论。",
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
        "优先处理已加入申请方案的项目；没有学校原文确认的信息，只作为准备提醒。",
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
                    status=FieldVerificationStatus.official_previous_cycle,
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
                    status=FieldVerificationStatus.official_previous_cycle,
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
        unresolved_fields=["tuition_hkd", "language_requirement", "materials", "current_cycle_deadline"],
        raw_json=qs_import_summary,
        agent_chain=[
            "SourceDiscoveryAgent",
            "RepositoryImportAgent",
            "OfficialLinkCandidateAgent",
            "ReviewerGateAgent",
        ],
    )


def _parser_plan(sources: list[SourcePolicy]) -> list[str]:
    official_names = [source.name for source in sources if source.trust_level == SourceTrustLevel.official]
    return [
        "Playwright/httpx 抓取官方索引，保存 HTML/PDF 快照和 page_hash。",
        "FieldExtractionAgent 抽取截止日期、学费、材料、语言、申请入口等候选信息。",
        "DiffAgent 比较上次快照，只有页面变化才进入确认清单。",
        "ReviewerGate 对关键信息做人工确认；未确认信息在前端继续显示为待学校确认。",
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
