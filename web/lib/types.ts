export type AgentContract = {
  agent_name: string;
  responsibility: string;
  inputs: string[];
  outputs: string[];
  tools: string[];
  upstream_agents: string[];
  human_gate: string | null;
  deterministic_guardrails: string[];
  llm_role: string;
  llm_guardrails: string[];
  retry_policy: string;
  handoff_policy: string;
};

export type AgentWorkflowContract = {
  workflow_name: string;
  required_agents: string[];
  terminal_agent: string | null;
  human_gate_required: boolean;
};

export type AgentContractCheck = {
  check_id: string;
  passed: boolean;
  detail: string;
};

export type AgentSystemReport = {
  generated_at: string;
  agents: AgentContract[];
  workflows: AgentWorkflowContract[];
  checks: AgentContractCheck[];
  human_gates: string[];
  deterministic_guardrails: string[];
};

export type AgentRunSummary = {
  workflow_id: string;
  workflow_name: string;
  status: "QUEUED" | "RUNNING" | "NEEDS_HUMAN" | "FAILED" | "COMPLETED" | string;
  current_step: string;
  created_at: string;
  updated_at: string;
};

export type AgentRuntimeStep = {
  step_id: string;
  node: string;
  status: "COMPLETED" | "NEEDS_HUMAN" | "FAILED" | "ROLLED_BACK" | "ROLLBACK_TARGET" | string;
  attempt: number;
  max_attempts: number;
  assigned_to: string;
  started_at: string;
  finished_at: string;
  input_summary: string;
  output_summary: string;
  payload: {
    tool_calls?: string[];
    model?: string;
    can_retry?: boolean;
    handoff_to?: string;
    needs_human_reason?: string | null;
    [key: string]: unknown;
  };
};

export type AgentRuntimeEvent = {
  event_id: string;
  entity_type: string;
  entity_id: string;
  event_type: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type AgentRunDetail = {
  run: AgentRunSummary | null;
  steps: AgentRuntimeStep[];
  events?: AgentRuntimeEvent[];
};

export type AgentQueueRunResponse = {
  ok: boolean;
  message: string;
  job: AgentQueueJob | null;
};

export type AgentQueueJob = {
  job_id: string;
  workflow_name: string;
  status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  payload_summary: string;
  assigned_to?: string | null;
  last_error?: string | null;
  worker_summary?: string | null;
  can_retry?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type CatalogRefreshPlanResponse = {
  ok: boolean;
  mode: "dry_run" | "write" | string;
  jobs: AgentQueueJob[];
  next_step: string;
};
export type EvidenceLevel =
  | "SELF_REPORTED"
  | "USER_CONFIRMED"
  | "EVIDENCE_VERIFIED"
  | "CONFLICTED"
  | "REJECTED";

export type DataStatus =
  | "DISCOVERED"
  | "EXTRACTED"
  | "PENDING_REVIEW"
  | "VERIFIED"
  | "STALE"
  | "CHANGED"
  | "NOT_PUBLISHED"
  | "REJECTED"
  | "ARCHIVED"
  | "OFFICIAL_VERIFIED_CURRENT"
  | "OFFICIAL_PREVIOUS_CYCLE"
  | "COMMUNITY_ONLY"
  | "CONFLICTED"
  | "MODEL_INFERRED";

export type FieldVerificationStatus =
  | "OFFICIAL_VERIFIED_CURRENT"
  | "OFFICIAL_PREVIOUS_CYCLE"
  | "NOT_PUBLISHED"
  | "COMMUNITY_ONLY"
  | "CONFLICTED"
  | "MODEL_INFERRED";

export type SourceCategory =
  | "official_program_index"
  | "official_program_page"
  | "official_application_system"
  | "official_pdf_or_faq"
  | "ranking_or_directory"
  | "community_result"
  | "selection_methodology"
  | "writing_style_reference";

export type SourceTrustLevel = "official" | "directory" | "community" | "methodology" | "writing_reference";
export type ConfidenceLevel = "low" | "medium" | "high";

export type SourcePolicy = {
  source_id: string;
  name: string;
  url: string;
  category: SourceCategory;
  region: "HK" | "SG" | "US" | "GLOBAL" | "COMMUNITY";
  trust_level: SourceTrustLevel;
  allowed_uses: string[];
  forbidden_uses: string[];
  refresh_cadence: string;
  extraction_method: string;
  requires_official_confirmation: boolean;
  notes?: string | null;
};

export type SourceRegistry = {
  version: string;
  updated_at: string;
  sources: SourcePolicy[];
};

export type SourceCheckResult = {
  source_id: string;
  name: string;
  url: string;
  category: SourceCategory;
  trust_level: SourceTrustLevel;
  status: "SKIPPED_DRY_RUN" | "FETCH_OK" | "FETCH_FAILED" | "REVIEW_REQUIRED";
  checked_at: string;
  http_status: number | null;
  robots_txt_url?: string | null;
  robots_allowed?: boolean | null;
  robots_status?: "NOT_CHECKED" | "SKIPPED_DRY_RUN" | "ALLOWED" | "DISALLOWED" | "ROBOTS_NOT_FOUND" | "ROBOTS_UNAVAILABLE";
  page_hash?: string | null;
  previous_page_hash?: string | null;
  content_changed?: boolean | null;
  snapshot_path?: string | null;
  snapshot_mime?: string | null;
  content_bytes?: number;
  summary: string;
  changed_fields: string[];
  next_actions: string[];
};

export type ProgramRefreshFinding = {
  program_id: string;
  institution: string;
  program_name: string;
  data_status: DataStatus;
  official_url: string | null;
  source_ids: string[];
  fields_requiring_review: string[];
  summary: string;
  next_actions: string[];
};

export type FieldExtractionCandidate = {
  field_name: string;
  value: string | null;
  evidence_snippet: string | null;
  confidence: ConfidenceLevel;
  status: FieldVerificationStatus;
  review_required: boolean;
};

export type SourceExtractionResult = {
  source_id: string;
  source_url: string;
  source_type: string;
  page_hash: string | null;
  snapshot_path: string | null;
  extracted_at: string;
  parser: "regex_html" | "llm_json" | "not_run";
  extracted_fields: FieldExtractionCandidate[];
  unresolved_fields: string[];
  raw_json: Record<string, unknown>;
  agent_chain: string[];
};

export type AcquisitionSourcePlan = {
  source_id: string;
  name: string;
  url: string;
  channel: "official_requirement" | "official_content" | "community_experience" | "directory_signal" | "methodology";
  trust_level: SourceTrustLevel;
  allowed_fields: string[];
  crawler_method: string;
  rate_limit: string;
  robots_policy: string;
  requires_human_review: boolean;
  next_actions: string[];
};

export type ProgramContentSection = {
  section_id: string;
  title: string;
  summary: string;
  source_status: FieldVerificationStatus;
  source_url: string | null;
  evidence_snippet: string | null;
  review_required: boolean;
};

export type ProgramExperienceSignal = {
  signal_type: "interview" | "written_test" | "essay_prompt" | "admission_case" | "timeline" | "general_experience" | "search_plan";
  title: string;
  summary: string;
  source_name: string;
  source_url: string | null;
  captured_at: string | null;
  confidence: ConfidenceLevel;
  official_verification_required: boolean;
  use_boundary: string;
};

export type ProgramDataCoverageItem = {
  field_name: string;
  required_source: "official" | "community_reference";
  status: FieldVerificationStatus;
  has_value: boolean;
  source_url: string | null;
  source_type: string | null;
  review_required: boolean;
  blocks_formal_use: boolean;
  next_action: string;
};

export type DataQualityMetric = {
  scope: string;
  official_field_coverage: number;
  verified_current_coverage: number;
  review_required_count: number;
  blocked_field_count: number;
  blocked_fields: string[];
  parser_capabilities: string[];
  next_action: string;
};

export type ProgramDataPackage = {
  program_id: string;
  institution: string;
  program_name: string;
  cycle: string;
  official_url: string | null;
  application_url: string | null;
  production_ready: boolean;
  freshness_warning: string;
  official_requirements: FieldEvidenceRecord[];
  coverage_items: ProgramDataCoverageItem[];
  content_sections: ProgramContentSection[];
  essay_prompts: FieldEvidenceRecord[];
  timeline_fields: FieldEvidenceRecord[];
  community_experiences: ProgramExperienceSignal[];
  acquisition_plan: AcquisitionSourcePlan[];
  human_review_required: boolean;
  quality_metric?: DataQualityMetric | null;
};

export type DataAcquisitionReport = {
  run_id: string;
  mode: "dry_run" | "live_fetch";
  checked_at: string;
  selected_program_ids: string[];
  packages: ProgramDataPackage[];
  source_plan: AcquisitionSourcePlan[];
  field_evidence_records: FieldEvidenceRecord[];
  extraction_results: SourceExtractionResult[];
  persisted_evidence_count: number;
  summary: string;
  next_actions: string[];
  agent_chain: string[];
  quality_metrics: DataQualityMetric[];
  crawler_capabilities: string[];
};

export type CrawlQueueItem = {
  job_id: string;
  source_id: string;
  name: string;
  url: string;
  program_ids: string[];
  channel: "official_requirement" | "official_content" | "community_experience" | "directory_signal" | "methodology";
  trust_level: SourceTrustLevel;
  priority: number;
  allowed_fields: string[];
  fetch_method: "html_snapshot" | "pdf_snapshot" | "repository_snapshot" | "manual_search";
  parser: "html_field_extraction" | "pdf_text_extraction" | "community_signal_extraction" | "manual_review";
  robots_policy: string;
  rate_limit: string;
  snapshot_required: boolean;
  human_review_required: boolean;
  publish_boundary: string;
  next_actions: string[];
  agent_chain: string[];
};

export type CrawlQueueReport = {
  generated_at: string;
  selected_program_ids: string[];
  job_count: number;
  official_job_count: number;
  community_job_count: number;
  items: CrawlQueueItem[];
  summary: string;
  warnings: string[];
  agent_chain: string[];
};


export type ScenarioAuditTarget = {
  program_id: string;
  fit_score: number | null;
  match_category: string | null;
  formal_recommendation: boolean | null;
  data_status: string | null;
  coverage_item_count: number;
  production_ready: boolean | null;
  review_pending_count: number | null;
  publishable_count: number | null;
};

export type ScenarioAuditCase = {
  name: string;
  passed: boolean;
  failures: string[];
  strict_intent: boolean | null;
  application_mix_count: number;
  review_passed: boolean | null;
  crawl_queue: {
    job_count: number;
    official_job_count: number;
    community_job_count: number;
  };
  targets: ScenarioAuditTarget[];
  trace_nodes: string[];
};

export type ScenarioAuditReport = {
  passed: boolean;
  case_count: number;
  failure_count: number;
  failures: string[];
  cases: ScenarioAuditCase[];
  agent_chain: string[];
};

export type ReviewQueueItem = {
  review_id: string;
  program_id: string;
  field_name: string;
  proposed_value: string | null;
  cycle: string | null;
  source_url: string | null;
  source_type: string;
  evidence_snippet: string | null;
  page_hash: string | null;
  snapshot_url?: string | null;
  extracted_at: string | null;
  confidence: ConfidenceLevel;
  source_priority: number;
  status: "PENDING" | "APPROVED" | "REJECTED";
  reviewer_id: string | null;
  reviewer_note: string | null;
  reviewed_at: string | null;
  publishable: boolean;
  boundary: string;
  agent_chain: string[];
};

export type ReviewQueueSummary = {
  generated_at: string;
  pending_count: number;
  publishable_count: number;
  items: ReviewQueueItem[];
};

export type ReviewPublishResponse = {
  ok: boolean;
  item: ReviewQueueItem;
  published_record: FieldEvidenceRecord | null;
  message: string;
};

export type ReviewBulkPublishResponse = {
  ok: boolean;
  published_count: number;
  preview_count: number;
  skipped_count: number;
  queue_before: number;
  queue_after: number | null;
  responses: ReviewPublishResponse[];
  message: string;
};
export type ProgramUrlCandidate = {
  program_id: string;
  institution: string;
  program_name: string;
  candidate_url: string;
  candidate_label: string;
  source_url: string | null;
  match_score: number;
  status: FieldVerificationStatus;
  reason: string;
  review_required: boolean;
  publishable_after_review: boolean;
  evidence_record: FieldEvidenceRecord;
};

export type CatalogAutoUpdateReport = {
  run_id: string;
  mode: "dry_run" | "live_fetch";
  checked_at: string;
  selected_program_ids: string[];
  scanned_program_count: number;
  missing_detail_page_count: number;
  candidate_count: number;
  persisted_candidate_count: number;
  review_queue_size: number;
  candidates: ProgramUrlCandidate[];
  warnings: string[];
  summary: string;
  agent_chain: string[];
};
export type DataRefreshReport = {
  run_id: string;
  mode: "dry_run" | "live_fetch";
  checked_at: string;
  region: "HK" | "SG" | "ALL";
  selected_program_ids: string[];
  sources_checked: number;
  official_sources_checked: number;
  community_sources_checked: number;
  source_checks: SourceCheckResult[];
  program_findings: ProgramRefreshFinding[];
  field_evidence_records: FieldEvidenceRecord[];
  extraction_results: SourceExtractionResult[];
  parser_plan: string[];
  review_queue_size: number;
  stale_program_ids: string[];
  changed_program_ids: string[];
  not_published_program_ids: string[];
  human_review_required: boolean;
  summary: string;
  next_actions: string[];
};

export type FieldEvidenceRecord = {
  program_id: string;
  field_name: string;
  value: string | null;
  cycle: string | null;
  source_url: string | null;
  source_type: string;
  extracted_at: string | null;
  verified_at: string | null;
  page_hash: string | null;
  confidence: ConfidenceLevel;
  source_priority: number;
  status: FieldVerificationStatus;
  review_required: boolean;
  reviewer_id: string | null;
  evidence_snippet: string | null;
  snapshot_url?: string | null;
  agent_chain: string[];
};

export type EvidenceGraphSummary = {
  program_count: number;
  field_record_count: number;
  verified_field_count: number;
  extracted_field_count: number;
  pending_review_field_count: number;
  official_source_count: number;
  community_source_count: number;
  status_breakdown: Record<string, number>;
  field_breakdown: Record<string, number>;
  official_priority: string[];
  production_schema: string[];
  reviewer_gate_fields: string[];
  sample_records: FieldEvidenceRecord[];
};

export type ProgramTrustDetail = {
  program_id: string;
  cycle: string;
  production_ready: boolean;
  reference_ready: boolean;
  status_label: string;
  source_warning: string;
  official_current_fields: string[];
  fields_requiring_review: string[];
  stale_or_reference_fields: string[];
  reviewer_gate_fields: string[];
  last_official_verified_at: string | null;
  field_records: FieldEvidenceRecord[];
};

export type ApplicantPayload = {
  personal_info: {
    preferred_name: string;
    citizenship: string;
    current_location: string;
    application_notes: string;
  };
  target_regions: Array<"HK" | "SG">;
  target_cycle: string;
  target_degree: "taught_master" | "research_master";
  discipline_interests: string[];
  raw_interest_text: string;
  education: {
    school: string;
    school_tier: "C9" | "985" | "211" | "double_first_class" | "regular" | "overseas" | "unknown";
    degree: string;
    major: string;
    gpa: number;
    gpa_scale: "100" | "4.0" | "5.0";
    ranking_percentile: number | null;
    evidence_level: EvidenceLevel;
  };
  language: {
    test: "IELTS" | "TOEFL" | "PTE" | "NONE";
    overall: number | null;
    writing: number | null;
    speaking: number | null;
    reading: number | null;
    listening: number | null;
    evidence_level: EvidenceLevel;
  };
  experiences: Array<{
    type: "research" | "internship" | "work" | "project" | "competition" | "volunteer";
    title: string;
    organization: string;
    months: number;
    role: string;
    outcomes: string[];
    tools: string[];
    evidence_level: EvidenceLevel;
  }>;
  additional_background: {
    core_courses: string[];
    exchange_experiences: string[];
    research_outputs: string[];
    activities: string[];
    awards: string[];
    skills: string[];
  };
  budget_hkd: number | null;
  career_goal: string;
  risk_flags: string[];
};

export type WorkflowResult = {
  workflow_id: string;
  profile: {
    profile_id: string;
    discipline_tags: string[];
    target_regions?: string[];
    additional_background?: ApplicantPayload["additional_background"];
    profile_completeness: number;
    missing_fields: string[];
    fact_summary: Record<string, number>;
  };
  evidence: {
    verified_fact_ratio: number;
    pending_confirmations: string[];
    conflicts: string[];
    recommended_uploads: string[];
    human_gate_required: boolean;
  };
  assessment: {
    assessment_type: "PRELIMINARY" | "VERIFIED";
    overall_level: string;
    competitiveness_level: "强" | "中强" | "中" | "弱";
    competitiveness_summary: string;
    application_positioning: Record<string, string>;
    hard_thresholds: string[];
    strengthening_actions: string[];
  confidence: ConfidenceLevel;
    data_completeness: number;
    dimension_scores: Record<string, number>;
    strengths: string[];
    weaknesses: string[];
    risks: string[];
    actions: string[];
    qualification_status: string;
    decision_field_coverage: number;
    evidence_coverage: number;
    scope_note: string;
    dimension_findings: DimensionFinding[];
  };
  recommendations: ProgramMatch[];
  timeline: TimelineTask[];
  writing: {
    document_type: string;
    version_id: string;
    title: string;
    outline: string[];
    draft: string;
    draft_zh: string;
    draft_en: string;
    material_gaps: string[];
    paragraph_drafts: string[];
    fact_bindings: Array<{ claim: string; fact_id: string }>;
    target_program_ids: string[];
    school_customization: string[];
    prompt_requirements: string[];
    cv_bullets: string[];
    reference_package: string[];
    risk_controls: string[];
    review_flags: string[];
  };
  review: {
    passed: boolean;
    status_label?: string;
    hard_rule_violations: string[];
    programs_requiring_data_review: string[];
    programs_with_missing_or_blocked_fields?: string[];
    programs_requiring_current_cycle_review?: string[];
    timeline_blockers?: Record<string, string[]>;
    previous_cycle_reference_fields?: Record<string, string[]>;
    required_timeline_fields?: string[];
    writing_review: string;
    human_gates: string[];
  };
  trace: AgentTrace[];
};

export type ProgramMatch = {
  program: {
    id: string;
    institution: string;
    institution_zh: string | null;
    country: "HK" | "SG";
    school: string;
    school_zh: string | null;
    name: string;
    name_zh: string | null;
    degree_type?: "taught_master" | "research_master";
    cycle?: string;
    category_zh: string | null;
    deadline: string;
    duration_months: number;
    tuition_hkd: number | null;
    application_fee_hkd?: number | null;
    discipline_tags: string[];
    materials: string[];
    requirements?: {
      min_gpa: number | null;
      language: Record<string, number>;
      required_backgrounds: string[];
      preferred_backgrounds: string[];
      prerequisites: string[];
      portfolio_required: boolean;
      work_experience_preferred: boolean;
    };
    source: {
      source_type: "OFFICIAL" | "COMMUNITY" | "DEMO_SYNTHETIC";
      field_coverage: "complete" | "partial" | "not_published";
      url?: string;
    };
    data_status: DataStatus;
    last_verified_at: string | null;
    official_program_url: string | null;
    application_url: string | null;
    trust_detail?: ProgramTrustDetail;
    community_signals: Array<{
      source_name: string;
      url: string;
      signal_type: "program_alias" | "community_review" | "admission_datapoint" | "taxonomy_hint";
      summary: string;
      official_verification_required: boolean;
    }>;
  };
  tier: "reach" | "target" | "safe" | "candidate" | "not_recommended";
  fit_score: number;
  score_breakdown: Record<
    "academic" | "language" | "experience" | "discipline_fit" | "budget_fit" | "data_trust",
    number
  >;
  match_category: "core" | "related" | "general" | "blocked";
  intent_alignment: number;
  intent_reasons: string[];
  hard_rule_passed: boolean;
  formal_recommendation: boolean;
  data_status: DataStatus;
  reasons: string[];
  risks: string[];
  actions: string[];
  explanation?: RecommendationExplanation | null;
  strategy_band?: "reach" | "target" | "safe" | "candidate" | "blocked";
  consultant_note?: string;
  source_warning?: string;
};

export type ConsultantPlanItem = {
  program_id: string;
  band: "冲刺" | "主申" | "保底" | "候选" | "暂不建议";
  institution: string;
  program_name: string;
  why_this_band: string;
  student_fit: string;
  main_risk: string;
  next_action: string;
  data_warning: string;
  official_url: string | null;
  application_url: string | null;
};

export type ConsultantSchoolPlan = {
  title: string;
  profile_summary: string;
  strategy_summary: string;
  data_disclaimer: string;
  band_counts: Record<string, number>;
  items: ConsultantPlanItem[];
  rejected_or_deferred: string[];
  next_actions: string[];
};

export type DimensionFinding = {
  dimension: string;
  level: "高" | "中" | "低" | "信息不足" | "需核验";
  conclusion: string;
  basis: string;
  applicable_to: string[];
  uncertainties: string[];
  actions: string[];
};

export type RecommendationExplanation = {
  hard_condition: "通过" | "需核验" | "未通过";
  academic_match: "高" | "中" | "低" | "未知";
  course_match: "高" | "中" | "低" | "未知";
  experience_match: "高" | "中" | "低" | "未知";
  budget_match: "高" | "中" | "低" | "未知";
  timeline_feasibility: "可规划" | "准备建议" | "未知";
  confidence: ConfidenceLevel;
  decision_basis: string[];
  uncertainties: string[];
};

export type CatalogProgram = ProgramMatch["program"] & {
  degree_type: "taught_master" | "research_master";
  cycle: string;
  duration_months: number;
  trust_detail?: ProgramTrustDetail;
};

export type TimelineTask = {
  id: string;
  title: string;
  due_date: string;
  priority: "high" | "medium" | "low";
  task_type:
    | "profile"
    | "source_review"
    | "materials"
    | "language"
    | "recommendation"
    | "writing"
    | "submission"
    | "scholarship";
  linked_program_ids: string[];
  risk: string | null;
  institution?: string | null;
  program_name?: string | null;
  round_open_date?: string | null;
  round_deadline?: string | "NOT_PUBLISHED" | null;
  application_url?: string | null;
  submit_to?: string | null;
  program_round?: string | null;
  official_deadline?: string | "NOT_PUBLISHED" | null;
  source_url?: string | null;
  basis?: string | null;
  materials?: string[];
  dependencies?: string[];
  data_status?: DataStatus;
  review_required?: boolean;
  task_name?: string | null;
  suggested_due_date?: string | null;
  date_basis?: "官方截止倒推" | "学生准备动作" | "上一申请季参考" | "人工复核" | null;
  previous_cycle_reference?: string | "NOT_PUBLISHED" | null;
  owner?: string;
  status?: "未开始" | "准备中" | "待上传" | "已提交" | "需复核";
  upload_materials?: string[];
  reminder_at?: string | null;
  risk_level?: "高" | "中" | "低";
};

export type AgentTrace = {
  node: string;
  status: "COMPLETED" | "NEEDS_HUMAN" | "FAILED";
  started_at?: string;
  finished_at?: string;
  input_summary: string;
  output_summary: string;
  tool_calls: string[];
  model: string;
  cost_usd: number;
  needs_human_reason?: string | null;
};


export type ProgramSchemeState = {
  band_overrides: Record<string, "reach" | "target" | "safe" | "candidate" | "blocked">;
  removed_program_ids: string[];
  extra_candidate_ids: string[];
};


export type WritingDraftHistoryItem = {
  id: string;
  createdAt: string;
  title: string;
  documentType: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
  targetProgram: string;
  factCount: number;
  gapCount: number;
  wordCount: number;
};

export type LocalWorkspaceState = {
  selected_program_ids: string[];
  questionnaire_values: Record<string, string>;
  result_snapshot: unknown | null;
  field_sensitivity: Record<string, string>;
  writing_draft_history?: WritingDraftHistoryItem[];
  program_scheme?: ProgramSchemeState;
};

export type LLMConfigResponse = {
  ok: boolean;
  provider: "mock" | "openai" | "deepseek" | "compatible";
  model: string;
  base_url: string | null;
  message: string;
};

export type QuestionnaireSchema = {
  version: string;
  source_templates: string[];
  sections: Array<{
    id: string;
    title: string;
    description: string;
    source_template?: string;
    repeatable?: boolean;
    fields: Array<{
      id: string;
      label: string;
      type: "text" | "textarea" | "select" | "date";
      options?: string[];
      sensitive?: boolean;
      required?: boolean;
      placeholder?: string;
      help?: string;
    }>;
  }>;
};

export type QuestionnaireResponse = {
  profile_answers: Array<{ field_id: string; value: string | string[] | null; evidence_ids: string[] }>;
  statement_answers: Array<{ field_id: string; value: string | string[] | null; evidence_ids: string[] }>;
  recommender_answers: Array<{ field_id: string; value: string | string[] | null; evidence_ids: string[] }>;
};

export type StoryCard = {
  id: string;
  title: string;
  category: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  reflection: string;
  related_skills: string[];
  target_program_relevance: string[];
  evidence_ids: string[];
  completeness: number;
};

export type WritingPlanResult = {
  workflow_id: string;
  story_cards: StoryCard[];
  writing: WorkflowResult["writing"];
  review: WorkflowResult["review"];
  trace: AgentTrace[];
};

export type WritingDraft = WorkflowResult["writing"];

export type BackgroundStageResult = Pick<WorkflowResult, "workflow_id" | "profile" | "evidence" | "assessment" | "trace">;

export type ProgramPlanResult = Pick<WorkflowResult, "workflow_id" | "profile" | "assessment" | "recommendations" | "trace">;

export type ProgramIntentProfile = {
  primary_intents: string[];
  strict_intent: boolean;
  user_terms: string[];
  core_program_keywords: string[];
  related_program_keywords: string[];
  blocked_program_keywords: string[];
  explanation: string;
};

export type LayeredProgramPlanResult = ProgramPlanResult & {
  intent_profile?: ProgramIntentProfile | null;
  candidate_pool: ProgramMatch[];
  focus_list: ProgramMatch[];
  application_mix: ProgramMatch[];
  final_candidates: ProgramMatch[];
  core_candidates: ProgramMatch[];
  related_candidates: ProgramMatch[];
  blocked_candidates: ProgramMatch[];
  consultant_plan?: ConsultantSchoolPlan | null;
};

export type ApplicationPlanResult = {
  workflow_id: string;
  selected_programs: ProgramMatch[];
  timeline: TimelineTask[];
  source_refresh?: DataRefreshReport | null;
  review: WorkflowResult["review"];
  trace: AgentTrace[];
};

export type WritingInterviewQuestion = {
  id: string;
  question: string;
  why_it_matters: string;
  target_section: string;
  required: boolean;
  sensitive: boolean;
};

export type WritingReviewRubric = {
  prompt_coverage: string;
  program_specificity: string;
  fact_coverage: string;
  unsupported_claims: number;
  cv_conflicts: number;
  word_count_status: string;
  template_language: "低" | "中" | "高";
  export_recommendation: "建议导出" | "修改后导出" | "不建议导出";
  issues: string[];
  next_actions: string[];
};
