from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


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


class ApplicantProfileInput(BaseModel):
    target_regions: list[Literal["HK", "SG"]] = Field(default_factory=lambda: ["HK", "SG"])
    target_cycle: str = "2027-fall"
    target_degree: Literal["taught_master", "research_master"] = "taught_master"
    discipline_interests: list[str] = Field(default_factory=list)
    raw_interest_text: str = ""
    education: EducationProfile
    language: LanguageScore = Field(default_factory=LanguageScore)
    experiences: list[Experience] = Field(default_factory=list)
    budget_hkd: int | None = Field(default=None, ge=0)
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
    budget_hkd: int | None = None
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


class FieldEvidenceRecord(BaseModel):
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
    agent_chain: list[str] = Field(default_factory=list)


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
    agent_chain: list[str] = Field(default_factory=list)


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


class ProgramTrustDetail(BaseModel):
    program_id: str
    cycle: str
    production_ready: bool
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


class ProgramDataPackage(BaseModel):
    program_id: str
    institution: str
    program_name: str
    cycle: str
    official_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None
    production_ready: bool = False
    freshness_warning: str
    official_requirements: list[FieldEvidenceRecord] = Field(default_factory=list)
    content_sections: list[ProgramContentSection] = Field(default_factory=list)
    essay_prompts: list[FieldEvidenceRecord] = Field(default_factory=list)
    timeline_fields: list[FieldEvidenceRecord] = Field(default_factory=list)
    community_experiences: list[ProgramExperienceSignal] = Field(default_factory=list)
    acquisition_plan: list[AcquisitionSourcePlan] = Field(default_factory=list)
    human_review_required: bool = True


class DataAcquisitionRequest(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    include_community: bool = True
    dry_run: bool = True
    max_sources_per_program: int = Field(default=8, ge=1, le=30)


class DataAcquisitionReport(BaseModel):
    run_id: str
    mode: Literal["dry_run", "live_fetch"]
    checked_at: datetime
    selected_program_ids: list[str] = Field(default_factory=list)
    packages: list[ProgramDataPackage] = Field(default_factory=list)
    source_plan: list[AcquisitionSourcePlan] = Field(default_factory=list)
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    agent_chain: list[str] = Field(default_factory=list)


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
    agent_chain: list[str] = Field(default_factory=list)


class CrawlQueueReport(BaseModel):
    generated_at: datetime
    selected_program_ids: list[str] = Field(default_factory=list)
    job_count: int
    official_job_count: int
    community_job_count: int
    items: list[CrawlQueueItem] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)
    agent_chain: list[str] = Field(default_factory=list)


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
    extracted_at: datetime | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    source_priority: int = 99
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    reviewer_id: str | None = None
    reviewer_note: str | None = None
    reviewed_at: datetime | None = None
    publishable: bool = False
    boundary: str = "Only official public sources can be published as current requirements after human review."
    agent_chain: list[str] = Field(default_factory=list)


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
class DataRefreshRequest(BaseModel):
    region: Literal["HK", "SG", "ALL"] = "ALL"
    institution: str | None = None
    selected_program_ids: list[str] = Field(default_factory=list)
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
    materials: list[str]
    requirements: ProgramRequirement
    source: ProgramSource
    data_status: DataStatus = DataStatus.pending_review
    last_verified_at: datetime | None = None
    official_program_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None
    field_evidence: dict[str, ProgramFieldEvidence] = Field(default_factory=dict)
    community_signals: list[CommunitySignal] = Field(default_factory=list)


class RuleCheck(BaseModel):
    rule_id: str
    program_id: str | None = None
    passed: bool
    severity: Literal["hard", "soft", "info"]
    message: str
    evidence_level: EvidenceLevel


class AssessmentResult(BaseModel):
    assessment_type: Literal["PRELIMINARY", "VERIFIED"]
    overall_level: Literal["A", "A-", "B+", "B", "C+", "C", "NEEDS_DATA"]
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
    level: Literal["高", "中", "低", "信息不足", "待确认"]
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
    tier: Literal["reach", "match", "safer", "not_recommended", "insufficient_info"]
    fit_score: int
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    match_category: Literal["core", "related", "general", "blocked"] = "general"
    intent_alignment: int = Field(default=50, ge=0, le=100)
    intent_reasons: list[str] = Field(default_factory=list)
    hard_rule_passed: bool
    formal_recommendation: bool = False
    data_status: DataStatus = DataStatus.pending_review
    reasons: list[str]
    risks: list[str]
    actions: list[str]
    rule_checks: list[RuleCheck]
    explanation: RecommendationExplanation | None = None
    strategy_band: Literal["reach", "target", "safe", "candidate", "blocked"] = "candidate"
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
    date_basis: Literal["官方截止倒推", "内部准备建议", "上一申请季参考", "人工复核"] | None = None
    previous_cycle_reference: date | Literal["NOT_PUBLISHED"] | None = None
    owner: str = "学生"
    status: Literal["待办", "进行中", "已完成", "等待官方发布", "需人工复核"] = "待办"
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
    fact_bindings: list[dict[str, str]]
    target_program_ids: list[str] = Field(default_factory=list)
    school_customization: list[str] = Field(default_factory=list)
    prompt_requirements: list[str] = Field(default_factory=list)
    cv_bullets: list[str] = Field(default_factory=list)
    reference_package: list[str] = Field(default_factory=list)
    risk_controls: list[str] = Field(default_factory=list)
    review_flags: list[str]


class WritingInterviewQuestion(BaseModel):
    id: str
    question: str
    why_it_matters: str
    target_section: Literal["项目题目", "故事卡", "技术深度", "Why Program", "职业目标", "事实核验"]
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


class ProgramCompareRow(BaseModel):
    program_id: str
    program_name: str
    institution: str
    tier: str = "候选"
    hard_condition: str = "待确认"
    academic_match: str = "未知"
    course_match: str = "未知"
    experience_match: str = "未知"
    budget_match: str = "未知"
    deadline_status: FieldVerificationStatus = FieldVerificationStatus.not_published
    data_status: str = "信息不足"
    main_risk: str = ""


class ConsultantPlanItem(BaseModel):
    program_id: str
    band: Literal["冲刺", "主申", "保底", "候选", "暂不建议"]
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
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    upstream_agents: list[str] = Field(default_factory=list)
    human_gate: str | None = None
    deterministic_guardrails: list[str] = Field(default_factory=list)


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
    cost_usd: float = 0.0
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
