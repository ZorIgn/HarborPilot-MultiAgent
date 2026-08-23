from __future__ import annotations

from datetime import date, datetime, date as CalendarDate
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class EvidenceLevel(str, Enum):
    self_reported = "SELF_REPORTED"
    user_confirmed = "USER_CONFIRMED"
    evidence_verified = "EVIDENCE_VERIFIED"
    conflicted = "CONFLICTED"
    rejected = "REJECTED"


class AgentStatus(str, Enum):
    completed = "COMPLETED"
    needs_human = "NEEDS_HUMAN"
    failed = "FAILED"


class DataStatus(str, Enum):
    discovered = "DISCOVERED"
    extracted = "EXTRACTED"
    pending_review = "PENDING_REVIEW"
    verified = "VERIFIED"
    stale = "STALE"
    changed = "CHANGED"
    not_published = "NOT_PUBLISHED"
    rejected = "REJECTED"
    archived = "ARCHIVED"


class FieldVerificationStatus(str, Enum):
    official_verified_current = "OFFICIAL_VERIFIED_CURRENT"
    official_previous_cycle = "OFFICIAL_PREVIOUS_CYCLE"
    not_published = "NOT_PUBLISHED"
    community_only = "COMMUNITY_ONLY"
    conflicted = "CONFLICTED"
    model_inferred = "MODEL_INFERRED"


class SourceCategory(str, Enum):
    official_program_index = "official_program_index"
    official_program_page = "official_program_page"
    official_application_system = "official_application_system"
    official_pdf_or_faq = "official_pdf_or_faq"
    ranking_or_directory = "ranking_or_directory"
    community_result = "community_result"
    selection_methodology = "selection_methodology"
    writing_style_reference = "writing_style_reference"


class SourceTrustLevel(str, Enum):
    official = "official"
    directory = "directory"
    community = "community"
    methodology = "methodology"
    writing_reference = "writing_reference"


class SourceScope(str, Enum):
    """Where a source sits in the information supply chain.

    An official institution index is trustworthy for discovering a programme
    URL, but it must not be treated as evidence for that programme's deadline
    or tuition.
    """

    programme_detail = "programme_detail"
    institution_index = "institution_index"
    application_portal = "application_portal"
    community_reference = "community_reference"
    methodology = "methodology"


class SourceConnectionMode(str, Enum):
    """Whether an acquisition request may contact live external sources."""

    mock = "mock"
    real = "real"
    hybrid = "hybrid"


class WorkflowStage(str, Enum):
    profile = "PROFILE"
    matching = "MATCHING"
    planning = "PLANNING"
    writing = "WRITING"


class Experience(BaseModel):
    type: Literal["research", "internship", "work", "project", "competition", "volunteer"]
    title: str
    organization: str
    months: int = Field(ge=0, le=120)
    role: str
    outcomes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    evidence_level: EvidenceLevel = EvidenceLevel.self_reported


class LanguageScore(BaseModel):
    test: Literal["IELTS", "TOEFL", "PTE", "NONE"] = "NONE"
    overall: float | None = None
    writing: float | None = None
    speaking: float | None = None
    reading: float | None = None
    listening: float | None = None
    planned_test_date: date | None = None
    evidence_level: EvidenceLevel = EvidenceLevel.self_reported


class EducationProfile(BaseModel):
    school: str = "未填写"
    school_tier: Literal["C9", "985", "211", "double_first_class", "regular", "overseas", "unknown"] = "unknown"
    degree: str = "Bachelor"
    major: str
    gpa: float = Field(ge=0, le=100, description="Normalized GPA on a 100-point scale.")
    gpa_scale: Literal["100", "4.0", "5.0"] = "100"
    ranking_percentile: float | None = Field(default=None, ge=0, le=100)
    evidence_level: EvidenceLevel = EvidenceLevel.self_reported


class PersonalInfo(BaseModel):
    preferred_name: str = ""
    citizenship: str = ""
    current_location: str = ""
    application_notes: str = ""


class AdditionalBackground(BaseModel):
    core_courses: list[str] = Field(default_factory=list)
    exchange_experiences: list[str] = Field(default_factory=list)
    research_outputs: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class ApplicantProfileInput(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    target_regions: list[Literal["HK", "SG"]] = Field(default_factory=lambda: ["HK", "SG"])
    target_cycle: str = Field(default="2027-fall", pattern=r"^20\d{2}-(fall|spring)$")
    target_degree: Literal["taught_master", "research_master"] = "taught_master"
    discipline_interests: list[str] = Field(default_factory=list)
    raw_interest_text: str = ""
    education: EducationProfile
    language: LanguageScore = Field(default_factory=LanguageScore)
    experiences: list[Experience] = Field(default_factory=list)
    additional_background: AdditionalBackground = Field(default_factory=AdditionalBackground)
    budget_hkd: int | None = Field(default=None, ge=0)
    budget_mode: Literal["soft", "hard_cap"] = "soft"
    career_goal: str = ""
    risk_flags: list[str] = Field(default_factory=list)


class NormalizedProfile(BaseModel):
    profile_id: str
    target_cycle: str
    target_regions: list[str]
    discipline_tags: list[str]
    raw_interest_text: str
    education: EducationProfile
    language: LanguageScore
    experiences: list[Experience]
    additional_background: AdditionalBackground = Field(default_factory=AdditionalBackground)
    budget_hkd: int | None = None
    budget_mode: Literal["soft", "hard_cap"] = "soft"
    career_goal: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    profile_completeness: int
    missing_fields: list[str]
    conflicts: list[dict[str, Any]]
    fact_summary: dict[str, int]


class ProgramRequirement(BaseModel):
    min_gpa: float | None = None
    language: dict[str, float] = Field(default_factory=dict)
    required_backgrounds: list[str] = Field(default_factory=list)
    preferred_backgrounds: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    portfolio_required: bool = False
    work_experience_preferred: bool = False


class ProgramSource(BaseModel):
    source_type: Literal["OFFICIAL", "COMMUNITY", "DEMO_SYNTHETIC"]
    url: HttpUrl | str
    captured_at: datetime
    field_coverage: Literal["complete", "partial", "not_published"]


class ProgramFieldEvidence(BaseModel):
    field_name: str
    value: str
    cycle: str
    official_url: HttpUrl | str
    source_type: Literal[
        "official_program_index",
        "official_program_page",
        "official_application_system",
        "official_admissions_page",
        "official_pdf",
        "official_faq",
        "community_signal",
    ]
    excerpt: str
    locator: str | None = None
    snapshot_id: str | None = None
    captured_at: datetime
    verified_at: datetime | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    status: DataStatus = DataStatus.extracted


class CommunitySignal(BaseModel):
    source_name: str
    url: HttpUrl | str
    signal_type: Literal["program_alias", "community_review", "admission_datapoint", "taxonomy_hint"]
    summary: str
    captured_at: datetime
    official_verification_required: bool = True


class SourcePolicy(BaseModel):
    source_id: str
    name: str
    url: HttpUrl | str
    category: SourceCategory
    region: Literal["HK", "SG", "US", "GLOBAL", "COMMUNITY"]
    trust_level: SourceTrustLevel
    allowed_uses: list[str] = Field(default_factory=list)
    forbidden_uses: list[str] = Field(default_factory=list)
    refresh_cadence: str
    extraction_method: str
    requires_official_confirmation: bool = True
    notes: str | None = None


class SourceRegistry(BaseModel):
    version: str
    updated_at: datetime
    sources: list[SourcePolicy]


class SourceCheckResult(BaseModel):
    source_id: str
    name: str
    url: HttpUrl | str
    category: SourceCategory
    trust_level: SourceTrustLevel
    status: Literal["SKIPPED_DRY_RUN", "FETCH_OK", "FETCH_FAILED", "REVIEW_REQUIRED"]
    checked_at: datetime
    http_status: int | None = None
    robots_txt_url: HttpUrl | str | None = None
    robots_allowed: bool | None = None
    robots_status: Literal[
        "NOT_CHECKED",
        "SKIPPED_DRY_RUN",
        "ALLOWED",
        "DISALLOWED",
        "ROBOTS_NOT_FOUND",
        "ROBOTS_UNAVAILABLE",
    ] = "NOT_CHECKED"
    page_hash: str | None = None
    previous_page_hash: str | None = None
    content_changed: bool | None = None
    snapshot_path: str | None = None
    snapshot_mime: str | None = None
    content_bytes: int = 0
    summary: str
    changed_fields: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ProgramRefreshFinding(BaseModel):
    program_id: str
    institution: str
    program_name: str
    data_status: DataStatus
    official_url: HttpUrl | str | None = None
    source_ids: list[str] = Field(default_factory=list)
    fields_requiring_review: list[str] = Field(default_factory=list)
    summary: str
    next_actions: list[str] = Field(default_factory=list)


class ExecutionReference(BaseModel):
    """Provenance for data produced through an actual runtime execution.

    Maintenance services may leave this unset when they run outside a workflow.
    They must never invent a sequence of agent names to stand in for a trace.
    """

    workflow_id: str | None = None
    trace_event_ids: list[str] = Field(default_factory=list)
    produced_by_agent: str | None = None
    produced_by_tool: str | None = None
    tool_call_id: str | None = None


class FieldEvidenceRecord(BaseModel):
    # ``evidence_id`` is the durable key of the candidate record in SQLite.
    # Legacy JSON records do not have one, which is intentional: their value
    # may be useful for discovery, but it must not silently become a formal
    # decision fact.
    evidence_id: str | None = None
    program_id: str
    field_name: str
    value: str | None = None
    cycle: str | None = None
    source_url: HttpUrl | str | None = None
    source_type: str
    extracted_at: datetime | None = None
    verified_at: datetime | None = None
    page_hash: str | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    source_priority: int = 99
    status: FieldVerificationStatus = FieldVerificationStatus.model_inferred
    review_required: bool = True
    reviewer_id: str | None = None
    evidence_snippet: str | None = None
    snapshot_url: HttpUrl | str | None = None
    execution_ref: ExecutionReference | None = None
    source_scope: SourceScope | None = None
    page_title: str | None = None
    final_url: HttpUrl | str | None = None
    binding_status: Literal["not_checked", "matched", "weak_match", "unrelated", "index_only"] = "not_checked"
    binding_score: int = Field(default=0, ge=0, le=100)
    reviewer_note: str | None = None
    review_decision_id: str | None = None


class FieldExtractionCandidate(BaseModel):
    field_name: str
    value: str | None = None
    evidence_snippet: str | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    status: FieldVerificationStatus = FieldVerificationStatus.official_previous_cycle
    review_required: bool = True


class SourceExtractionResult(BaseModel):
    source_id: str
    source_url: HttpUrl | str
    source_type: str
    page_hash: str | None = None
    snapshot_path: str | None = None
    extracted_at: datetime
    parser: Literal["regex_html", "llm_json", "not_run"] = "regex_html"
    extracted_fields: list[FieldExtractionCandidate] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    raw_json: dict[str, Any] = Field(default_factory=dict)
    execution_ref: ExecutionReference | None = None
    fetch_status: str = "UNKNOWN"
    final_url: HttpUrl | str | None = None
    page_title: str | None = None
    binding_status: Literal["not_checked", "matched", "weak_match", "unrelated", "index_only"] = "not_checked"
    binding_score: int = Field(default=0, ge=0, le=100)
    attempts: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)


class EvidenceGraphSummary(BaseModel):
    program_count: int
    field_record_count: int
    verified_field_count: int
    extracted_field_count: int
    pending_review_field_count: int
    official_source_count: int
    community_source_count: int
    status_breakdown: dict[str, int]
    field_breakdown: dict[str, int]
    official_priority: list[str]
    production_schema: list[str]
    reviewer_gate_fields: list[str]
    sample_records: list[FieldEvidenceRecord] = Field(default_factory=list)


class DecisionCoverageSummary(BaseModel):
    """Database-derived truth-coverage report, never a catalog-size proxy."""

    generated_at: datetime
    cycle: str | None = None
    program_count: int
    formal_ready_program_count: int
    decision_fact_status_breakdown: dict[str, int] = Field(default_factory=dict)
    required_field_formal_coverage: dict[str, int] = Field(default_factory=dict)
    current_verified_record_count: int = 0
    pending_review_record_count: int = 0
    records_missing_source_scope: int = 0
    programs_with_community_signals: int = 0
    community_signal_collection_status: Literal["NOT_COLLECTED", "PARTIAL", "PRESENT"] = "NOT_COLLECTED"
    blockers: list[str] = Field(default_factory=list)


class ProgramTrustDetail(BaseModel):
    program_id: str
    cycle: str
    production_ready: bool
    reference_ready: bool = False
    status_label: str
    source_warning: str
    official_current_fields: list[str] = Field(default_factory=list)
    fields_requiring_review: list[str] = Field(default_factory=list)
    stale_or_reference_fields: list[str] = Field(default_factory=list)
    reviewer_gate_fields: list[str] = Field(default_factory=list)
    last_official_verified_at: datetime | None = None
    field_records: list[FieldEvidenceRecord] = Field(default_factory=list)


class AcquisitionSourcePlan(BaseModel):
    source_id: str
    name: str
    url: HttpUrl | str
    channel: Literal["official_requirement", "official_content", "community_experience", "directory_signal", "methodology"]
    trust_level: SourceTrustLevel
    allowed_fields: list[str] = Field(default_factory=list)
    crawler_method: str
    rate_limit: str = "manual_or_low_rate"
    robots_policy: str = "check_robots_and_terms_before_live_fetch"
    requires_human_review: bool = True
    next_actions: list[str] = Field(default_factory=list)
    source_scope: SourceScope = SourceScope.programme_detail
    target_program_id: str | None = None


class ProgramContentSection(BaseModel):
    section_id: str
    title: str
    summary: str
    source_status: FieldVerificationStatus = FieldVerificationStatus.official_previous_cycle
    source_url: HttpUrl | str | None = None
    evidence_snippet: str | None = None
    review_required: bool = True


class ProgramExperienceSignal(BaseModel):
    signal_type: Literal["interview", "written_test", "essay_prompt", "admission_case", "timeline", "general_experience", "search_plan"]
    title: str
    summary: str
    source_name: str
    source_url: HttpUrl | str | None = None
    captured_at: datetime | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    official_verification_required: bool = True
    use_boundary: str = "社区经验只用于准备参考，不能替代学校官方要求。"


class ProgramDataCoverageItem(BaseModel):
    field_name: str
    required_source: Literal["official", "community_reference"] = "official"
    status: FieldVerificationStatus = FieldVerificationStatus.model_inferred
    has_value: bool = False
    source_url: HttpUrl | str | None = None
    source_type: str | None = None
    review_required: bool = True
    blocks_formal_use: bool = True
    next_action: str


class DataQualityMetric(BaseModel):
    scope: str
    official_field_coverage: int = Field(ge=0, le=100)
    verified_current_coverage: int = Field(ge=0, le=100)
    review_required_count: int = 0
    blocked_field_count: int = 0
    blocked_fields: list[str] = Field(default_factory=list)
    parser_capabilities: list[str] = Field(default_factory=list)
    next_action: str = ""

class ProgramDataPackage(BaseModel):
    program_id: str
    institution: str
    program_name: str
    program_name_en: str | None = None
    cycle: str
    official_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None
    production_ready: bool = False
    freshness_warning: str
    official_requirements: list[FieldEvidenceRecord] = Field(default_factory=list)
    coverage_items: list[ProgramDataCoverageItem] = Field(default_factory=list)
    content_sections: list[ProgramContentSection] = Field(default_factory=list)
    essay_prompts: list[FieldEvidenceRecord] = Field(default_factory=list)
    timeline_fields: list[FieldEvidenceRecord] = Field(default_factory=list)
    community_experiences: list[ProgramExperienceSignal] = Field(default_factory=list)
    acquisition_plan: list[AcquisitionSourcePlan] = Field(default_factory=list)
    human_review_required: bool = True
    quality_metric: DataQualityMetric | None = None


class DataAcquisitionRequest(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    include_community: bool = True
    # Safe by default: setting ``dry_run=False`` alone is never authority to
    # contact the public web.  An operator must opt into real/hybrid explicitly.
    connection_mode: SourceConnectionMode = SourceConnectionMode.mock
    dry_run: bool = True
    max_sources_per_program: int = Field(default=8, ge=1, le=30)


class DataAcquisitionReport(BaseModel):
    run_id: str
    mode: Literal["dry_run", "live_fetch"]
    checked_at: datetime
    selected_program_ids: list[str] = Field(default_factory=list)
    packages: list[ProgramDataPackage] = Field(default_factory=list)
    source_plan: list[AcquisitionSourcePlan] = Field(default_factory=list)
    field_evidence_records: list[FieldEvidenceRecord] = Field(default_factory=list)
    extraction_results: list[SourceExtractionResult] = Field(default_factory=list)
    persisted_evidence_count: int = 0
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    execution_ref: ExecutionReference | None = None
    quality_metrics: list[DataQualityMetric] = Field(default_factory=list)
    crawler_capabilities: list[str] = Field(default_factory=list)
    run_status: Literal["COMPLETED", "NEEDS_REVIEW", "FAILED"] = "NEEDS_REVIEW"
    planned_source_count: int = 0
    attempted_source_count: int = 0
    successful_source_count: int = 0
    failed_source_count: int = 0
    binding_warning_count: int = 0
    run_warnings: list[str] = Field(default_factory=list)


class SourceHealthItem(BaseModel):
    source_id: str
    name: str
    url: HttpUrl | str
    source_scope: SourceScope = SourceScope.programme_detail
    last_status: str = "NEVER_RUN"
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_http_status: int | None = None
    last_page_hash: str | None = None
    attempt_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    failure_rate: float = Field(default=0, ge=0, le=1)
    average_duration_ms: int = Field(default=0, ge=0)
    review_pending_count: int = 0
    freshness_state: Literal["fresh", "due", "stale", "unknown"] = "unknown"
    next_action: str = "等待首次运行"


class SourceHealthSummary(BaseModel):
    generated_at: datetime
    total_sources: int
    healthy_sources: int
    due_sources: int
    stale_sources: int
    never_run_sources: int
    failing_sources: int = 0
    pending_review_count: int
    items: list[SourceHealthItem] = Field(default_factory=list)


class CrawlQueueRequest(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    include_community: bool = True
    max_sources_per_program: int = Field(default=8, ge=1, le=30)


class CrawlQueueItem(BaseModel):
    job_id: str
    source_id: str
    name: str
    url: HttpUrl | str
    program_ids: list[str] = Field(default_factory=list)
    channel: Literal["official_requirement", "official_content", "community_experience", "directory_signal", "methodology"]
    trust_level: SourceTrustLevel
    priority: int = Field(ge=1, le=100)
    allowed_fields: list[str] = Field(default_factory=list)
    fetch_method: Literal["html_snapshot", "pdf_snapshot", "repository_snapshot", "manual_search"]
    parser: Literal["html_field_extraction", "pdf_text_extraction", "community_signal_extraction", "manual_review"]
    robots_policy: str
    rate_limit: str
    snapshot_required: bool = True
    human_review_required: bool = True
    publish_boundary: str
    next_actions: list[str] = Field(default_factory=list)
    execution_ref: ExecutionReference | None = None


class CrawlQueueReport(BaseModel):
    generated_at: datetime
    selected_program_ids: list[str] = Field(default_factory=list)
    job_count: int
    official_job_count: int
    community_job_count: int
    items: list[CrawlQueueItem] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)
    execution_ref: ExecutionReference | None = None


class ReviewQueueItem(BaseModel):
    review_id: str
    program_id: str
    field_name: str
    proposed_value: str | None = None
    cycle: str | None = None
    source_url: HttpUrl | str | None = None
    source_type: str
    evidence_snippet: str | None = None
    page_hash: str | None = None
    snapshot_url: HttpUrl | str | None = None
    source_scope: SourceScope | None = None
    page_title: str | None = None
    final_url: HttpUrl | str | None = None
    binding_status: Literal["not_checked", "matched", "weak_match", "unrelated", "index_only"] = "not_checked"
    binding_score: int = Field(default=0, ge=0, le=100)
    extracted_at: datetime | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    source_priority: int = 99
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    reviewer_id: str | None = None
    reviewer_note: str | None = None
    reviewed_at: datetime | None = None
    publishable: bool = False
    boundary: str = "Only official public sources can be published as current requirements after human review."
    execution_ref: ExecutionReference | None = None


class ReviewQueueSummary(BaseModel):
    generated_at: datetime
    pending_count: int
    publishable_count: int
    items: list[ReviewQueueItem] = Field(default_factory=list)


class ReviewPublishRequest(BaseModel):
    review_id: str
    decision: Literal["approve", "reject"]
    reviewer_id: str = "local_reviewer"
    reviewer_note: str | None = None
    confirmed_value: str | None = None
    persist: bool = False


class ReviewPublishResponse(BaseModel):
    ok: bool
    item: ReviewQueueItem
    published_record: FieldEvidenceRecord | None = None
    message: str


class ReviewBulkPublishRequest(BaseModel):
    program_id: str | None = None
    limit: int = Field(default=20, ge=1, le=200)
    reviewer_id: str = "local_reviewer"
    reviewer_note: str | None = None
    persist: bool = True


class ReviewBulkPublishResponse(BaseModel):
    ok: bool
    published_count: int
    preview_count: int
    skipped_count: int
    queue_before: int
    queue_after: int | None = None
    responses: list[ReviewPublishResponse] = Field(default_factory=list)
    message: str


class DataRefreshRequest(BaseModel):
    region: Literal["HK", "SG", "ALL"] = "ALL"
    institution: str | None = None
    selected_program_ids: list[str] = Field(default_factory=list)
    # Deprecated compatibility endpoint.  It remains offline/source-health
    # planning only; live official acquisition must use DataAcquisitionRequest
    # with an explicit ``real`` or ``hybrid`` connection mode.
    dry_run: bool = True
    use_llm: bool = False
    max_sources: int = Field(default=16, ge=1, le=80)


class DataRefreshReport(BaseModel):
    run_id: str
    mode: Literal["dry_run", "live_fetch"]
    checked_at: datetime
    region: Literal["HK", "SG", "ALL"]
    selected_program_ids: list[str] = Field(default_factory=list)
    sources_checked: int
    official_sources_checked: int
    community_sources_checked: int
    source_checks: list[SourceCheckResult] = Field(default_factory=list)
    program_findings: list[ProgramRefreshFinding] = Field(default_factory=list)
    field_evidence_records: list[FieldEvidenceRecord] = Field(default_factory=list)
    extraction_results: list[SourceExtractionResult] = Field(default_factory=list)
    parser_plan: list[str] = Field(default_factory=list)
    review_queue_size: int = 0
    stale_program_ids: list[str] = Field(default_factory=list)
    changed_program_ids: list[str] = Field(default_factory=list)
    not_published_program_ids: list[str] = Field(default_factory=list)
    human_review_required: bool
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    truth_scope: Literal["operational_source_check", "runtime_evidence_projection"] = "operational_source_check"
    formal_ready_program_count: int = 0
    formal_blocker_count: int = 0


class CatalogAutoUpdateRequest(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    institution: str | None = None
    dry_run: bool = True
    max_programs: int = Field(default=24, ge=1, le=200)
    max_candidates_per_program: int = Field(default=6, ge=1, le=20)


class ProgramUrlCandidate(BaseModel):
    program_id: str
    institution: str
    program_name: str
    candidate_url: HttpUrl | str
    candidate_label: str
    source_url: HttpUrl | str | None = None
    match_score: int = Field(ge=0, le=100)
    status: FieldVerificationStatus = FieldVerificationStatus.official_previous_cycle
    reason: str
    review_required: bool = True
    publishable_after_review: bool = False
    evidence_record: FieldEvidenceRecord


class CatalogAutoUpdateReport(BaseModel):
    run_id: str
    mode: Literal["dry_run", "live_fetch"]
    checked_at: datetime
    selected_program_ids: list[str] = Field(default_factory=list)
    scanned_program_count: int
    missing_detail_page_count: int
    candidate_count: int
    persisted_candidate_count: int = 0
    review_queue_size: int = 0
    candidates: list[ProgramUrlCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str
    execution_ref: ExecutionReference | None = None


class ApplicationRound(BaseModel):
    """A programme can publish different dates for multiple applicant rounds."""

    name: str
    open_date: date | None = None
    deadline: date | None = None
    applicant_scope: str | None = None


class ExtractedDeadline(BaseModel):
    round_name: str | None = None
    date: CalendarDate | None = None
    cycle: str | None = None
    applicant_type: str | None = None
    confidence: float = Field(ge=0, le=1)
    excerpt: str


class ExtractedLanguageRequirement(BaseModel):
    test: Literal["IELTS", "TOEFL", "PTE"]
    overall: float | None = None
    subscores: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    excerpt: str


class ExtractedTuition(BaseModel):
    currency: str
    amount: float | None = None
    period: str | None = None
    confidence: float = Field(ge=0, le=1)
    excerpt: str

class Program(BaseModel):
    id: str
    institution: str
    institution_zh: str | None = None
    country: Literal["HK", "SG"]
    school: str
    school_zh: str | None = None
    name: str
    name_zh: str | None = None
    degree_type: Literal["taught_master", "research_master"]
    cycle: str
    category_zh: str | None = None
    discipline_tags: list[str]
    duration_months: int
    tuition_hkd: int | None = None
    application_fee_hkd: int | None = None
    open_date: date | None = None
    deadline: date | Literal["NOT_PUBLISHED"]
    application_rounds: list[ApplicationRound] = Field(default_factory=list)
    materials: list[str]
    requirements: ProgramRequirement
    source: ProgramSource
    data_status: DataStatus = DataStatus.pending_review
    last_verified_at: datetime | None = None
    official_program_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None
    field_evidence: dict[str, ProgramFieldEvidence] = Field(default_factory=dict)
    community_signals: list[CommunitySignal] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_main_application_round(self) -> "Program":
        """Expose known single-date data as one explicitly named round.

        Older catalogue rows may publish only one window. Keeping it as a
        named main round preserves that limitation without implying it covers
        every applicant scope or future round.
        """

        if not self.application_rounds:
            self.application_rounds = [ApplicationRound(name="主轮次", open_date=self.open_date, deadline=self.deadline if isinstance(self.deadline, date) else None)]
        return self


class RuleCheck(BaseModel):
    rule_id: str
    program_id: str | None = None
    passed: bool
    severity: Literal["hard", "soft", "info"]
    message: str
    evidence_level: EvidenceLevel


class ConstraintCategory(str, Enum):
    """Separate decision dimensions; a budget is never an admissions rule."""

    ADMISSIONS_ELIGIBILITY = "ADMISSIONS_ELIGIBILITY"
    USER_PREFERENCE = "USER_PREFERENCE"
    FINANCIAL_FEASIBILITY = "FINANCIAL_FEASIBILITY"
    DATA_CONFIDENCE = "DATA_CONFIDENCE"
    STRATEGY_FIT = "STRATEGY_FIT"
    EVIDENCE_READINESS = "EVIDENCE_READINESS"


class DecisionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class FactProvenanceStatus(str, Enum):
    """Trust state of the evidence backing one resolved programme field.

    This is deliberately separate from :class:`DecisionStatus`.  A value can
    be perfectly parseable but still be ``UNVERIFIED``; consumers must then
    receive ``UNKNOWN`` rather than treating a catalogue seed as a fact.
    """

    VERIFIED_CURRENT = "VERIFIED_CURRENT"
    REVIEWED_PREVIOUS = "REVIEWED_PREVIOUS"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    REVOKED = "REVOKED"


class DecisionFact(BaseModel):
    """One field-level fact that is safe (or explicitly unsafe) for decisions.

    ``catalog_value`` retains a discovery hint for an explorer UI, while
    ``normalized_value`` is populated only when the record clears the formal
    resolver checks.  Decision consumers must use ``normalized_value`` and
    ``decision_status`` rather than a value embedded in ``Program``.
    """

    fact_id: str
    program_id: str
    field_name: str
    cycle: str | None = None
    catalog_value: Any | None = None
    raw_value: Any | None = None
    normalized_value: Any | None = None
    decision_status: DecisionStatus = DecisionStatus.UNKNOWN
    provenance_status: FactProvenanceStatus = FactProvenanceStatus.UNVERIFIED
    formal_use_ready: bool = False
    evidence_id: str | None = None
    source_url: HttpUrl | str | None = None
    source_scope: SourceScope | None = None
    source_type: str | None = None
    source_locator: str | None = None
    evidence_quote: str | None = None
    snapshot_url: HttpUrl | str | None = None
    page_hash: str | None = None
    observed_at: datetime | None = None
    verified_at: datetime | None = None
    reviewer_id: str | None = None
    review_decision_id: str | None = None
    conflict_id: str | None = None
    blockers: list[str] = Field(default_factory=list)


class ResolvedProgramView(BaseModel):
    """Single decision read model for a catalogue programme and one cycle.

    ``catalog`` is present solely for stable identity, rendering and exploratory
    retrieval.  Facts are projected only from published, source-complete
    evidence.  This makes the source boundary inspectable at every consumer.
    """

    program_id: str
    cycle: str
    catalog: "Program"
    facts: dict[str, DecisionFact] = Field(default_factory=dict)
    conflict_ids: list[str] = Field(default_factory=list)
    formal_readiness: DecisionStatus = DecisionStatus.UNKNOWN
    formal_blockers: list[str] = Field(default_factory=list)
    provenance_summary: dict[str, int] = Field(default_factory=dict)

    def fact(self, field_name: str) -> DecisionFact:
        return self.facts.get(
            field_name,
            DecisionFact(
                fact_id=f"missing:{self.program_id}:{field_name}",
                program_id=self.program_id,
                field_name=field_name,
                cycle=self.cycle,
                blockers=["未找到该字段的已发布证据。"],
            ),
        )


class ClaimValidationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICTED = "CONFLICTED"
    BLOCKED = "BLOCKED"


class ClaimNode(BaseModel):
    """Atomic objective claim in a recommendation or writing draft."""

    claim_id: str
    text: str
    claim_type: Literal["student_fact", "program_fact", "recommendation", "writing"]
    program_id: str | None = None
    required_for_formal: bool = True
    status: ClaimValidationStatus = ClaimValidationStatus.UNSUPPORTED
    decision_fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class ClaimEdge(BaseModel):
    """A typed relationship from evidence/facts to one claim."""

    source_id: str
    target_claim_id: str
    relation: Literal["SUPPORTS", "CONTRADICTS", "QUALIFIES"]
    reason: str = ""


class ClaimGraph(BaseModel):
    """Deterministic claim/evidence graph used by writing and Critic gates."""

    graph_id: str
    nodes: list[ClaimNode] = Field(default_factory=list)
    edges: list[ClaimEdge] = Field(default_factory=list)
    formal_status: DecisionStatus = DecisionStatus.UNKNOWN
    blockers: list[str] = Field(default_factory=list)


class CriticReadiness(str, Enum):
    """Separates formal approval, preliminary completion and a hard block."""

    FORMAL_PASS = "FORMAL_PASS"
    PRELIMINARY_COMPLETE = "PRELIMINARY_COMPLETE"
    BLOCKED = "BLOCKED"


class RuleSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class ConstraintCheck(BaseModel):
    """A v2 constraint result with an explicit unknown state."""

    check_id: str
    program_id: str | None = None
    category: ConstraintCategory
    status: DecisionStatus
    severity: RuleSeverity
    message: str
    evidence_level: EvidenceLevel
    source_url: str | None = None


class FinancialFeasibilityStatus(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    SLIGHTLY_OVER = "SLIGHTLY_OVER"
    OVER_BUDGET = "OVER_BUDGET"
    UNKNOWN = "UNKNOWN"


class FinancialFeasibility(BaseModel):
    program_id: str
    status: DecisionStatus
    budget_hkd: int | None = None
    tuition_hkd: int | None = None
    gap_hkd: int | None = None
    budget_mode: Literal["soft", "hard_cap"] = "soft"
    financial_status: FinancialFeasibilityStatus = FinancialFeasibilityStatus.UNKNOWN
    blocks_user_selection: bool = False
    message: str


class DataConfidenceAssessment(BaseModel):
    program_id: str
    status: DecisionStatus
    verified_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    formal_use_ready: bool = False

class AssessmentResult(BaseModel):
    assessment_type: Literal["PRELIMINARY", "VERIFIED"]
    overall_level: Literal["A", "A-", "B+", "B", "C+", "C", "NEEDS_DATA"]
    competitiveness_level: Literal["强", "中强", "中", "弱"] = "中"
    competitiveness_summary: str = ""
    application_positioning: dict[str, str] = Field(default_factory=dict)
    hard_thresholds: list[str] = Field(default_factory=list)
    strengthening_actions: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    data_completeness: int
    dimension_scores: dict[str, int]
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    actions: list[str]
    rule_checks: list[RuleCheck]
    template_confidence: Literal["low", "medium", "high"]
    qualification_status: str = ""
    decision_field_coverage: int = Field(default=0, ge=0, le=100)
    evidence_coverage: int = Field(default=0, ge=0, le=100)
    dimension_findings: list["DimensionFinding"] = Field(default_factory=list)
    scope_note: str = ""


class DimensionFinding(BaseModel):
    dimension: str
    level: Literal["高", "中", "低", "信息不足", "需核验"]
    conclusion: str
    basis: str
    applicable_to: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class RecommendationExplanation(BaseModel):
    hard_condition: str
    academic_match: str
    course_match: str
    experience_match: str
    budget_match: str
    timeline_feasibility: str
    confidence: str
    decision_basis: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ProgramIntentProfile(BaseModel):
    primary_intents: list[str] = Field(default_factory=list)
    strict_intent: bool = False
    user_terms: list[str] = Field(default_factory=list)
    core_program_keywords: list[str] = Field(default_factory=list)
    related_program_keywords: list[str] = Field(default_factory=list)
    blocked_program_keywords: list[str] = Field(default_factory=list)
    explanation: str = ""


class ProgramMatch(BaseModel):
    program: Program
    tier: Literal["reach", "target", "safer", "candidate", "not_recommended"]
    admissions_status: DecisionStatus = DecisionStatus.UNKNOWN
    admissions_checks: list[ConstraintCheck] = Field(default_factory=list)
    academic_fit_score: int = Field(default=0, ge=0, le=100)
    language_fit_score: int = Field(default=0, ge=0, le=100)
    discipline_fit_score: int = Field(default=0, ge=0, le=100)
    experience_fit_score: int = Field(default=0, ge=0, le=100)
    applicant_fit_score: int = Field(default=0, ge=0, le=100)
    preference_fit_score: int = Field(default=0, ge=0, le=100)
    financial_fit_score: int | None = Field(default=None, ge=0, le=100)
    data_confidence_score: int = Field(default=0, ge=0, le=100)
    strategy_score: int = Field(default=0, ge=0, le=100)
    fit_score: int
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    match_category: Literal["core", "related", "general", "blocked"] = "general"
    intent_alignment: int = Field(default=50, ge=0, le=100)
    intent_reasons: list[str] = Field(default_factory=list)
    hard_rule_passed: bool
    formal_recommendation: bool = False
    # A compatibility ``Program`` remains embedded for catalogue rendering,
    # but all hard-decision provenance is carried separately.  Consumers must
    # never infer formal readiness from ``program.data_status`` alone.
    decision_facts: dict[str, DecisionFact] = Field(default_factory=dict)
    formal_gate_status: DecisionStatus = DecisionStatus.UNKNOWN
    formal_blockers: list[str] = Field(default_factory=list)
    data_status: DataStatus = DataStatus.pending_review
    reasons: list[str]
    risks: list[str]
    actions: list[str]
    rule_checks: list[RuleCheck]
    explanation: RecommendationExplanation | None = None
    strategy_band: Literal["reach", "target", "safer", "candidate", "blocked"] = "candidate"
    consultant_note: str = ""
    source_warning: str = ""


class TimelineTask(BaseModel):
    id: str
    title: str
    due_date: date
    priority: Literal["high", "medium", "low"]
    task_type: Literal[
        "profile",
        "source_review",
        "materials",
        "language",
        "recommendation",
        "writing",
        "submission",
        "scholarship",
    ] = "materials"
    linked_program_ids: list[str] = Field(default_factory=list)
    risk: str | None = None
    institution: str | None = None
    program_name: str | None = None
    round_open_date: date | None = None
    round_deadline: date | Literal["NOT_PUBLISHED"] | None = None
    application_url: HttpUrl | str | None = None
    submit_to: str | None = None
    program_round: str | None = None
    official_deadline: date | Literal["NOT_PUBLISHED"] | None = None
    source_url: HttpUrl | str | None = None
    basis: str | None = None
    materials: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    data_status: DataStatus = DataStatus.pending_review
    review_required: bool = False
    task_name: str | None = None
    suggested_due_date: date | None = None
    date_basis: Literal["官方截止倒推", "学生准备动作", "上一申请季参考", "人工复核"] | None = None
    previous_cycle_reference: date | Literal["NOT_PUBLISHED"] | None = None
    owner: str = "学生"
    status: Literal["未开始", "准备中", "待上传", "已提交", "需复核"] = "未开始"
    upload_materials: list[str] = Field(default_factory=list)
    reminder_at: date | None = None
    risk_level: Literal["高", "中", "低"] = "中"


class WritingDraft(BaseModel):
    document_type: Literal["PS", "SOP", "CV", "ESSAY", "REFERENCE_PACKAGE"]
    version_id: str = "v1"
    title: str
    outline: list[str]
    draft: str
    draft_zh: str = ""
    draft_en: str = ""
    material_gaps: list[str] = Field(default_factory=list)
    paragraph_drafts: list[str] = Field(default_factory=list)
    fact_bindings: list[dict[str, str]]
    target_program_ids: list[str] = Field(default_factory=list)
    school_customization: list[str] = Field(default_factory=list)
    prompt_requirements: list[str] = Field(default_factory=list)
    cv_bullets: list[str] = Field(default_factory=list)
    reference_package: list[str] = Field(default_factory=list)
    risk_controls: list[str] = Field(default_factory=list)
    review_flags: list[str]
    # A draft may be useful for revision long before it is safe for formal
    # programme-specific use.  These fields carry the deterministic ClaimGraph
    # result instead of asking clients to infer readiness from prose flags.
    claim_graph: ClaimGraph | None = None
    claim_grounding_ready: bool = False
    # This is copied from the Supervisor/Critic runtime when a draft is
    # delivered through a workflow.  Direct outline helpers deliberately use
    # a non-formal status, so clients cannot infer approval from prose alone.
    delivery_status: CriticReadiness | Literal["UNREVIEWED"] = "UNREVIEWED"
    formal_use_ready: bool = False
    formal_blockers: list[str] = Field(default_factory=list)


class WritingInterviewQuestion(BaseModel):
    id: str
    question: str
    why_it_matters: str
    target_section: str
    required: bool = True
    sensitive: bool = False


class WritingOutlineRequest(BaseModel):
    document_type: Literal["PS", "SOP", "CV", "ESSAY", "REFERENCE_PACKAGE"] = "PS"
    target_program_ids: list[str] = Field(default_factory=list)
    story_cards: list["StoryCard"] = Field(default_factory=list)
    interview_answers: list[QuestionnaireAnswer] = Field(default_factory=list)


class WritingReviewRubric(BaseModel):
    prompt_coverage: str
    program_specificity: str
    fact_coverage: str
    unsupported_claims: int = 0
    cv_conflicts: int = 0
    word_count_status: str
    template_language: Literal["低", "中", "高"]
    export_recommendation: Literal["建议导出", "修改后导出", "不建议导出"]
    issues: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    # The standalone rubric is an inspection aid.  It must surface the same
    # ClaimGraph boundary as the runtime instead of promoting a clean-looking
    # draft solely because ``review_flags`` happened to be empty.
    claim_graph: ClaimGraph | None = None
    formal_status: DecisionStatus = DecisionStatus.UNKNOWN
    # The request carries client-controlled prose, story cards and draft
    # metadata.  It can therefore be a deterministic preliminary lint only;
    # the Supervisor/Critic workflow is the sole producer of FORMAL_PASS.
    delivery_status: Literal["PRELIMINARY_COMPLETE", "BLOCKED"] = "PRELIMINARY_COMPLETE"
    formal_use_ready: bool = False
    formal_blockers: list[str] = Field(default_factory=list)


class ProgramCompareRow(BaseModel):
    program_id: str
    program_name: str
    institution: str
    tier: str = "候选"
    hard_condition: str = "需核验"
    academic_match: str = "未知"
    course_match: str = "未知"
    experience_match: str = "未知"
    budget_match: str = "未知"
    deadline_status: FieldVerificationStatus = FieldVerificationStatus.not_published
    data_status: str = "信息不足"
    main_risk: str = ""


class ConsultantPlanItem(BaseModel):
    program_id: str
    band: Literal["冲刺", "主申", "相对稳妥", "候选", "暂不建议"]
    institution: str
    program_name: str
    why_this_band: str
    student_fit: str
    main_risk: str
    next_action: str
    data_warning: str
    official_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None


class ConsultantSchoolPlan(BaseModel):
    title: str
    profile_summary: str
    strategy_summary: str
    data_disclaimer: str
    band_counts: dict[str, int] = Field(default_factory=dict)
    items: list[ConsultantPlanItem] = Field(default_factory=list)
    rejected_or_deferred: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class QuestionnaireAnswer(BaseModel):
    field_id: str
    value: str | list[str] | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class QuestionnaireResponse(BaseModel):
    profile_answers: list[QuestionnaireAnswer] = Field(default_factory=list)
    statement_answers: list[QuestionnaireAnswer] = Field(default_factory=list)
    recommender_answers: list[QuestionnaireAnswer] = Field(default_factory=list)


class StoryCard(BaseModel):
    id: str
    title: str
    category: Literal["education", "internship", "research", "project", "competition", "activity", "motivation", "recommender"]
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    reflection: str = ""
    related_skills: list[str] = Field(default_factory=list)
    target_program_relevance: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    completeness: int = Field(ge=0, le=100, default=0)


class AgentContract(BaseModel):
    agent_name: str
    responsibility: str
    is_autonomous: bool = True
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    decision_schema: str = "AgentDecision"
    can_handoff_to: list[str] = Field(default_factory=list)
    can_ask_user: bool = False
    can_request_human: bool = False
    max_tool_rounds: int = 6
    upstream_agents: list[str] = Field(default_factory=list)
    human_gate: str | None = None
    deterministic_guardrails: list[str] = Field(default_factory=list)
    llm_role: str = "none"
    llm_guardrails: list[str] = Field(default_factory=list)
    retry_policy: str = "retry failed step from Admin queue after operator review"
    handoff_policy: str = "handoff to human reviewer when source or fact confidence is insufficient"


class AgentWorkflowContract(BaseModel):
    workflow_name: str
    required_agents: list[str] = Field(default_factory=list)
    terminal_agent: str | None = None
    human_gate_required: bool = False


class AgentContractCheck(BaseModel):
    check_id: str
    passed: bool
    detail: str


class AgentSystemReport(BaseModel):
    generated_at: datetime
    agents: list[AgentContract] = Field(default_factory=list)
    workflows: list[AgentWorkflowContract] = Field(default_factory=list)
    checks: list[AgentContractCheck] = Field(default_factory=list)
    human_gates: list[str] = Field(default_factory=list)
    deterministic_guardrails: list[str] = Field(default_factory=list)
class AgentTraceEvent(BaseModel):
    node: str
    status: AgentStatus
    started_at: datetime
    finished_at: datetime
    input_summary: str
    output_summary: str
    tool_calls: list[str] = Field(default_factory=list)
    model: str = "mock"
    cost_usd: float | None = None
    needs_human_reason: str | None = None


class EvidenceReview(BaseModel):
    verified_fact_ratio: int
    pending_confirmations: list[str]
    conflicts: list[str]
    recommended_uploads: list[str]
    human_gate_required: bool


class BackgroundStageResult(BaseModel):
    workflow_id: str
    profile: NormalizedProfile
    evidence: EvidenceReview
    assessment: AssessmentResult
    trace: list[AgentTraceEvent]


class ProgramPlanResult(BaseModel):
    workflow_id: str
    profile: NormalizedProfile
    assessment: AssessmentResult
    intent_profile: ProgramIntentProfile | None = None
    recommendations: list[ProgramMatch]
    candidate_pool: list[ProgramMatch] = Field(default_factory=list)
    focus_list: list[ProgramMatch] = Field(default_factory=list)
    application_mix: list[ProgramMatch] = Field(default_factory=list)
    final_candidates: list[ProgramMatch] = Field(default_factory=list)
    core_candidates: list[ProgramMatch] = Field(default_factory=list)
    related_candidates: list[ProgramMatch] = Field(default_factory=list)
    blocked_candidates: list[ProgramMatch] = Field(default_factory=list)
    consultant_plan: ConsultantSchoolPlan | None = None
    trace: list[AgentTraceEvent]


class ApplicationPlanResult(BaseModel):
    workflow_id: str
    selected_programs: list[ProgramMatch]
    timeline: list[TimelineTask]
    source_refresh: DataRefreshReport | None = None
    review: dict[str, Any]
    trace: list[AgentTraceEvent]


class WritingPlanResult(BaseModel):
    workflow_id: str
    story_cards: list[StoryCard]
    writing: WritingDraft
    review: dict[str, Any]
    trace: list[AgentTraceEvent]
    critic_readiness: CriticReadiness | None = None
    delivery_status: str = "UNREVIEWED"
    formal_use_ready: bool = False
    formal_blockers: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    workflow_id: str
    profile: NormalizedProfile
    evidence: EvidenceReview
    assessment: AssessmentResult
    recommendations: list[ProgramMatch]
    timeline: list[TimelineTask]
    writing: WritingDraft
    review: dict[str, Any]
    trace: list[AgentTraceEvent]
