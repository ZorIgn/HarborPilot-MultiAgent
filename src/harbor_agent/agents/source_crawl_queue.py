from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from harbor_agent.agents.data_acquisition import ProgramDataAcquisitionAgent
from harbor_agent.models import (
    AcquisitionSourcePlan,
    CrawlQueueItem,
    CrawlQueueReport,
    CrawlQueueRequest,
    DataAcquisitionRequest,
    SourceTrustLevel,
)

OFFICIAL_ONLY_FIELDS = {
    "deadline",
    "tuition_hkd",
    "language_requirement",
    "materials",
    "application_url",
    "essay_prompts",
}
COMMUNITY_REFERENCE_FIELDS = {
    "interview",
    "written_test",
    "admission_case",
    "timeline_experience",
    "application_timeline_experience",
    "interview_or_written_test_keywords",
    "preparation_advice",
    "program_alias",
}


class SourceCrawlQueueAgent:
    """Builds deterministic crawl jobs from public source plans without fetching or mutating data."""

    name = "SourceCrawlQueueAgent"

    def __init__(self) -> None:
        self.acquisition_agent = ProgramDataAcquisitionAgent()

    def run(self, request: CrawlQueueRequest) -> CrawlQueueReport:
        generated_at = datetime.now(UTC)
        acquisition = self.acquisition_agent.run(
            DataAcquisitionRequest(
                selected_program_ids=request.selected_program_ids,
                include_community=request.include_community,
                dry_run=True,
                max_sources_per_program=request.max_sources_per_program,
            )
        )
        grouped: dict[tuple[str, str], dict] = {}
        for package in acquisition.packages:
            for plan in package.acquisition_plan:
                key = (plan.source_id, plan.channel)
                bucket = grouped.setdefault(
                    key,
                    {
                        "plan": plan,
                        "program_ids": [],
                        "allowed_fields": set(),
                    },
                )
                bucket["program_ids"].append(package.program_id)
                bucket["allowed_fields"].update(plan.allowed_fields)

        items = [
            _queue_item(bucket["plan"], sorted(set(bucket["program_ids"])), sorted(bucket["allowed_fields"]))
            for bucket in grouped.values()
        ]
        items = sorted(items, key=lambda item: (item.priority, item.source_id, item.channel))
        official_count = sum(1 for item in items if item.trust_level == SourceTrustLevel.official)
        community_count = sum(1 for item in items if item.trust_level == SourceTrustLevel.community)
        warnings = _boundary_warnings(items)
        return CrawlQueueReport(
            generated_at=generated_at,
            selected_program_ids=request.selected_program_ids,
            job_count=len(items),
            official_job_count=official_count,
            community_job_count=community_count,
            items=items,
            summary=(
                f"Prepared {len(items)} crawl jobs: {official_count} official source jobs, "
                f"{community_count} community/reference jobs. No job mutates catalog data; "
                "all official fields remain review-gated."
            ),
            warnings=warnings,
            agent_chain=[
                "ProgramDataAcquisitionAgent",
                "SourceCrawlQueueAgent",
                "RobotsPolicyGate",
                "SnapshotPolicyGate",
                "HumanReviewGateAgent",
            ],
        )


def _queue_item(plan: AcquisitionSourcePlan, program_ids: list[str], allowed_fields: list[str]) -> CrawlQueueItem:
    trust = plan.trust_level
    return CrawlQueueItem(
        job_id=_job_id(plan, program_ids),
        source_id=plan.source_id,
        name=plan.name,
        url=plan.url,
        program_ids=program_ids,
        channel=plan.channel,
        trust_level=trust,
        priority=_priority(plan),
        allowed_fields=_bounded_allowed_fields(plan, allowed_fields),
        fetch_method=_fetch_method(plan),
        parser=_parser(plan),
        robots_policy=plan.robots_policy,
        rate_limit=plan.rate_limit,
        snapshot_required=True,
        human_review_required=True,
        publish_boundary=_publish_boundary(plan),
        next_actions=_next_actions(plan),
        agent_chain=_agent_chain(plan),
    )


def _job_id(plan: AcquisitionSourcePlan, program_ids: list[str]) -> str:
    raw = "|".join([plan.source_id, plan.channel, *program_ids])
    return "crawl_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _priority(plan: AcquisitionSourcePlan) -> int:
    if plan.trust_level == SourceTrustLevel.official and plan.channel == "official_requirement":
        return 10
    if plan.trust_level == SourceTrustLevel.official:
        return 20
    if plan.trust_level == SourceTrustLevel.directory:
        return 45
    if plan.trust_level == SourceTrustLevel.community:
        return 70
    return 90


def _bounded_allowed_fields(plan: AcquisitionSourcePlan, fields: list[str]) -> list[str]:
    if plan.trust_level == SourceTrustLevel.community:
        return [field for field in fields if field in COMMUNITY_REFERENCE_FIELDS]
    if plan.channel == "official_requirement":
        official_fields = [field for field in fields if field in OFFICIAL_ONLY_FIELDS or field in {"program_overview", "curriculum"}]
        return official_fields or sorted(OFFICIAL_ONLY_FIELDS)
    return fields


def _fetch_method(plan: AcquisitionSourcePlan) -> str:
    url = str(plan.url).lower()
    method = plan.crawler_method.lower()
    if url.endswith(".pdf") or "pdf" in method:
        return "pdf_snapshot"
    if plan.trust_level == SourceTrustLevel.community and "github" in url:
        return "repository_snapshot"
    if plan.trust_level == SourceTrustLevel.community or "search" in method or "google.com/search" in url:
        return "manual_search"
    return "html_snapshot"


def _parser(plan: AcquisitionSourcePlan) -> str:
    fetch_method = _fetch_method(plan)
    if fetch_method == "pdf_snapshot":
        return "pdf_text_extraction"
    if plan.trust_level == SourceTrustLevel.community:
        return "community_signal_extraction"
    if fetch_method == "manual_search":
        return "manual_review"
    return "html_field_extraction"


def _publish_boundary(plan: AcquisitionSourcePlan) -> str:
    if plan.trust_level == SourceTrustLevel.community:
        return "Community data is reference-only and must never update official requirements or formal timelines."
    if plan.trust_level == SourceTrustLevel.official:
        return "Official candidates stay PENDING_REVIEW until a human reviewer publishes OFFICIAL_VERIFIED_CURRENT."
    return "Directory or methodology data can discover candidates only; official fields require school-source review."


def _next_actions(plan: AcquisitionSourcePlan) -> list[str]:
    if plan.trust_level == SourceTrustLevel.community:
        return [
            "Use compliant public search or an allowlisted public URL only.",
            "Store source URL, short excerpt, captured_at, and experience tags.",
            "Do not copy long passages or collect login-only/private content.",
        ]
    return [
        "Check robots.txt and source terms before live fetch.",
        "Save HTML/PDF snapshot and page_hash before field extraction.",
        "Attach evidence snippets to each extracted field for human review.",
    ]


def _agent_chain(plan: AcquisitionSourcePlan) -> list[str]:
    if plan.trust_level == SourceTrustLevel.community:
        return [
            "SourceDiscoveryAgent",
            "CommunitySignalAgent",
            "ShortExcerptPolicyGate",
            "HumanReviewGateAgent",
        ]
    return [
        "SourceDiscoveryAgent",
        "RobotsPolicyGate",
        "OfficialCrawlerAgent",
        "SnapshotAgent",
        "FieldExtractionAgent",
        "HumanReviewGateAgent",
    ]


def _boundary_warnings(items: list[CrawlQueueItem]) -> list[str]:
    warnings = [
        "Live workers must not write to the programme catalog directly.",
        "Every official field candidate must pass human review before publication.",
        "Only OFFICIAL_VERIFIED_CURRENT fields may power formal recommendations or official deadline back-planning.",
    ]
    if any(item.trust_level == SourceTrustLevel.community for item in items):
        warnings.append("Community jobs are public-experience aggregation only; they are never requirement sources.")
    return warnings
