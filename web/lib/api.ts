import type {
  AgentQueueJob,
  AgentQueueRunResponse,
  AgentRunDetail,
  AgentRunSummary,
  AgentSystemReport,
  ApplicantPayload,
  ApplicationPlanResult,
  BackgroundStageResult,
  CatalogAutoUpdateReport,
  CatalogRefreshPlanResponse,
  CatalogProgram,
  CrawlQueueReport,
  DataAcquisitionReport,
  DataAcquisitionRequest,
  DataRefreshReport,
  EvidenceGraphSummary,
  LayeredProgramPlanResult,
  LLMConfigResponse,
  LocalWorkspaceState,
  ProgramDataPackage,
  QuestionnaireResponse,
  QuestionnaireSchema,
  ReviewBulkPublishResponse, ReviewPublishResponse,
  ReviewQueueSummary,
  RuntimeTraceEvent,
  RuntimeWorkflowGoal,
  RuntimeWorkflowListItem,
  RuntimeWorkflowState,
  ScenarioAuditReport,
  SourceRegistry,
  SourceHealthSummary,
  WorkflowResult,
  WritingDraft,
  WritingInterviewQuestion,
  WritingPlanResult,
  WritingReviewRubric,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const ADMIN_TOKEN_STORAGE_KEY = "harborpilot_admin_token";

type QueryValue = string | number | boolean | null | undefined;
export function getStoredAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) ?? "";
}

export function setStoredAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  const normalized = token.trim();
  if (normalized) window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, normalized);
  else window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
}

const ADMIN_AUTH_PATH_PREFIXES = [
  "/api/admin/",
  "/api/agent/workflows",
  "/api/workflows/data-acquisition",
  "/api/workflows/data-refresh",
  "/api/workflows/source-refresh",
] as const;

function requiresAdminAuth(path: string): boolean {
  return ADMIN_AUTH_PATH_PREFIXES.some((prefix) => path.startsWith(prefix));
}

function withAdminAuth(path: string, init?: RequestInit): RequestInit | undefined {
  if (!requiresAdminAuth(path)) return init;
  const token = getStoredAdminToken();
  if (!token) return init;
  const headers = new Headers(init?.headers);
  headers.set("x-harbor-admin-token", token);
  return { ...init, headers };
}

function withQuery(path: string, filters?: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  });
  const suffix = query.toString();
  return API_BASE + path + (suffix ? "?" + suffix : "");
}

async function apiJson<T>(path: string, init?: RequestInit, label = "API"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      API_BASE + path,
      withAdminAuth(path, { ...init, credentials: "include" }),
    );
  } catch {
    throw new Error("本地服务暂时无法连接，请确认 HarborPilot 后端服务已启动。");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? String((data as { detail?: unknown }).detail) : null;
    throw new Error(detail ?? label + " returned " + response.status);
  }
  return data as T;
}

async function apiQueryJson<T>(path: string, filters?: Record<string, QueryValue>, label = "API"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      withQuery(path, filters),
      withAdminAuth(path, { cache: "no-store", credentials: "include" }),
    );
  } catch {
    throw new Error("本地服务暂时无法连接，请确认 HarborPilot 后端服务已启动。");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? String((data as { detail?: unknown }).detail) : null;
    throw new Error(detail ?? label + " returned " + response.status);
  }
  return data as T;
}

function postJson(body: unknown): RequestInit {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

function putJson(body: unknown): RequestInit {
  return { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export type StartRuntimeWorkflowPayload = {
  goal: RuntimeWorkflowGoal;
  profile: ApplicantPayload;
  user_request?: string;
  questionnaire?: QuestionnaireResponse | null;
  selected_program_ids?: string[];
  document_type?: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
};

export function startRuntimeWorkflow(payload: StartRuntimeWorkflowPayload): Promise<RuntimeWorkflowState> {
  return apiJson<RuntimeWorkflowState>("/api/agent/workflows", postJson(payload), "Agent workflow API");
}

export async function getRuntimeWorkflows(limit = 20): Promise<RuntimeWorkflowListItem[]> {
  return apiQueryJson<RuntimeWorkflowListItem[]>("/api/agent/workflows", { limit }, "Agent workflow list API");
}

export function getRuntimeWorkflow(workflowId: string): Promise<RuntimeWorkflowState> {
  return apiJson<RuntimeWorkflowState>("/api/agent/workflows/" + encodeURIComponent(workflowId), { cache: "no-store" }, "Agent workflow API");
}

export function resumeRuntimeWorkflow(workflowId: string, payload: { user_message?: string | null; human_resolution?: Record<string, unknown> | null }): Promise<RuntimeWorkflowState> {
  return apiJson<RuntimeWorkflowState>("/api/agent/workflows/" + encodeURIComponent(workflowId) + "/resume", postJson(payload), "Agent workflow resume API");
}

export function getRuntimeWorkflowTrace(workflowId: string): Promise<RuntimeTraceEvent[]> {
  return apiJson<RuntimeTraceEvent[]>("/api/agent/workflows/" + encodeURIComponent(workflowId) + "/trace", { cache: "no-store" }, "Agent workflow trace API");
}

export function getRuntimeWorkflowState(workflowId: string): Promise<RuntimeWorkflowState> {
  return apiJson<RuntimeWorkflowState>("/api/agent/workflows/" + encodeURIComponent(workflowId) + "/state", { cache: "no-store" }, "Agent workflow state API");
}
export function runAssessment(payload: ApplicantPayload): Promise<WorkflowResult> {
  return apiJson<WorkflowResult>("/api/workflows/assessment", postJson(payload), "Assessment API");
}

export function runBackgroundStage(payload: ApplicantPayload): Promise<BackgroundStageResult> {
  return apiJson<BackgroundStageResult>("/api/workflows/background", postJson(payload), "Background API");
}

export function runProgramPlan(payload: ApplicantPayload): Promise<LayeredProgramPlanResult> {
  return apiJson<LayeredProgramPlanResult>("/api/workflows/program-plan", postJson(payload), "Program plan API");
}

export function runApplicationPlan(payload: { profile: ApplicantPayload; selected_program_ids: string[] }): Promise<ApplicationPlanResult> {
  return apiJson<ApplicationPlanResult>("/api/workflows/application-plan", postJson(payload), "Application plan API");
}

export function runDataRefresh(payload: { region?: "HK" | "SG" | "ALL"; institution?: string | null; selected_program_ids?: string[]; dry_run?: boolean; use_llm?: boolean; max_sources?: number }): Promise<DataRefreshReport> {
  return apiJson<DataRefreshReport>("/api/workflows/data-refresh", postJson(payload), "Data refresh API");
}

export function runWritingPlan(payload: { profile: ApplicantPayload; questionnaire: QuestionnaireResponse; selected_program_ids: string[]; document_type?: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE" }): Promise<WritingPlanResult> {
  return apiJson<WritingPlanResult>("/api/workflows/writing-plan", postJson(payload), "Writing plan API");
}

export function runWritingInterview(payload: { profile: ApplicantPayload; selected_program_ids: string[]; document_type?: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE" }): Promise<WritingInterviewQuestion[]> {
  return apiJson<WritingInterviewQuestion[]>("/api/workflows/writing-interview", postJson(payload), "Writing interview API");
}

export function runWritingReview(payload: { draft: WritingDraft; story_cards: Array<unknown> }): Promise<WritingReviewRubric> {
  return apiJson<WritingReviewRubric>("/api/workflows/writing-review", postJson(payload), "Writing review API");
}

export function getHealth(): Promise<{ status: string; llm_mode: string; llm_provider?: string }> {
  return apiJson<{ status: string; llm_mode: string; llm_provider?: string }>("/api/health", { cache: "no-store" }, "Health API");
}

export function getLocalProfile(): Promise<ApplicantPayload | null> {
  return apiJson<ApplicantPayload | null>("/api/profile/local", { cache: "no-store" }, "Profile API");
}

export function saveLocalProfile(payload: ApplicantPayload): Promise<ApplicantPayload> {
  return apiJson<ApplicantPayload>("/api/profile/local", putJson(payload), "Profile API");
}

export function getLocalWorkspace(): Promise<LocalWorkspaceState> {
  return apiJson<LocalWorkspaceState>("/api/workspace/local", { cache: "no-store" }, "Workspace API");
}

export function saveLocalWorkspace(payload: LocalWorkspaceState): Promise<LocalWorkspaceState> {
  return apiJson<LocalWorkspaceState>("/api/workspace/local", putJson(payload), "Workspace API");
}

export function configureLLM(payload: { provider: "mock" | "openai" | "deepseek" | "compatible"; api_key?: string; model?: string; base_url?: string }): Promise<LLMConfigResponse> {
  return apiJson<LLMConfigResponse>("/api/admin/llm-config", postJson(payload), "LLM config API");
}

export function configureStudentLLM(payload: { provider: "mock" | "openai" | "deepseek" | "compatible"; api_key?: string; model?: string; base_url?: string }): Promise<LLMConfigResponse> {
  return apiJson<LLMConfigResponse>("/api/llm-config", postJson(payload), "AI model config API");
}

export function getLLMConfig(): Promise<LLMConfigResponse> {
  return apiJson<LLMConfigResponse>("/api/admin/llm-config", { cache: "no-store" }, "LLM config API");
}

export function getStudentLLMConfig(): Promise<LLMConfigResponse> {
  return apiJson<LLMConfigResponse>("/api/llm-config", { cache: "no-store" }, "AI model config API");
}

export function getPrograms(filters?: Record<string, QueryValue>): Promise<CatalogProgram[]> {
  return apiQueryJson<CatalogProgram[]>("/api/programs", filters, "Programs API");
}

export function getProgramDataPackage(programId: string): Promise<ProgramDataPackage> {
  return apiJson<ProgramDataPackage>("/api/programs/" + encodeURIComponent(programId) + "/data-package", { cache: "no-store" }, "Program data package API");
}

export function runCatalogAutoUpdate(payload: { selected_program_ids?: string[]; institution?: string | null; dry_run?: boolean; max_programs?: number; max_candidates_per_program?: number }): Promise<CatalogAutoUpdateReport> {
  return apiJson<CatalogAutoUpdateReport>("/api/admin/catalog-auto-update", postJson(payload), "Catalog auto update API");
}

export function runDataAcquisition(payload: DataAcquisitionRequest): Promise<DataAcquisitionReport> {
  return apiJson<DataAcquisitionReport>("/api/workflows/data-acquisition", postJson(payload), "Data acquisition API");
}

export function runCrawlQueue(payload: { selected_program_ids?: string[]; include_community?: boolean; max_sources_per_program?: number }): Promise<CrawlQueueReport> {
  return apiJson<CrawlQueueReport>("/api/admin/crawl-queue", postJson(payload), "Crawl queue API");
}

export function getSourceRegistry(): Promise<SourceRegistry> {
  return apiJson<SourceRegistry>("/api/source-registry", { cache: "no-store" }, "Source registry API");
}

export function getSourceHealth(): Promise<SourceHealthSummary> {
  return apiJson<SourceHealthSummary>("/api/source-health", { cache: "no-store" }, "Source health API");
}

export function getEvidenceGraphSummary(): Promise<EvidenceGraphSummary> {
  return apiJson<EvidenceGraphSummary>("/api/evidence-graph/summary", { cache: "no-store" }, "Evidence graph API");
}

export function getQuestionnaireSchema(): Promise<QuestionnaireSchema> {
  return apiJson<QuestionnaireSchema>("/api/questionnaire-schema", { cache: "no-store" }, "Questionnaire API");
}

export function getScenarioAudit(): Promise<ScenarioAuditReport> {
  return apiJson<ScenarioAuditReport>("/api/admin/scenario-audit", { cache: "no-store" }, "Scenario audit API");
}

export function getReviewQueue(filters?: { program_id?: string; limit?: number }): Promise<ReviewQueueSummary> {
  return apiQueryJson<ReviewQueueSummary>("/api/admin/review-queue", filters, "Review queue API");
}

export function publishReviewItem(payload: { review_id: string; decision: "approve" | "reject"; reviewer_id?: string; reviewer_note?: string | null; confirmed_value?: string | null; persist?: boolean }): Promise<ReviewPublishResponse> {
  return apiJson<ReviewPublishResponse>("/api/admin/review-queue/publish", postJson(payload), "Review publish API");
}

export function publishReviewBatch(payload: { program_id?: string | null; limit?: number; reviewer_id?: string; reviewer_note?: string | null; persist?: boolean }): Promise<ReviewBulkPublishResponse> {
  return apiJson<ReviewBulkPublishResponse>("/api/admin/review-queue/bulk-publish", postJson(payload), "Review bulk publish API");
}

export function getAgentSystemReport(): Promise<AgentSystemReport> {
  return apiJson<AgentSystemReport>("/api/agent-system", { cache: "no-store" }, "Agent system API");
}

export async function getAgentRuns(limit = 20): Promise<AgentRunSummary[]> {
  const data = await apiQueryJson<{ items?: AgentRunSummary[] } | AgentRunSummary[]>("/api/admin/agent-runs", { limit }, "Agent runs API");
  return Array.isArray(data) ? data : data.items ?? [];
}

export function getAgentRunDetail(workflowId: string): Promise<AgentRunDetail> {
  return apiJson<AgentRunDetail>("/api/admin/agent-runs/" + encodeURIComponent(workflowId), { cache: "no-store" }, "Agent run detail API");
}

export async function getAgentQueue(limit = 20): Promise<AgentQueueJob[]> {
  const data = await apiQueryJson<{ items?: AgentQueueJob[] } | AgentQueueJob[]>("/api/admin/agent-queue", { limit }, "Agent queue API");
  return Array.isArray(data) ? data : data.items ?? [];
}

export function enqueueAgentJob(payload: { workflow_name: string; payload_summary?: string; payload?: Record<string, unknown>; priority?: number; max_attempts?: number }): Promise<AgentQueueJob> {
  return apiJson<AgentQueueJob>("/api/admin/agent-queue", postJson(payload), "Agent queue API");
}

export function queueCatalogRefreshPlan(payload: { selected_program_ids?: string[]; institution?: string | null; dry_run?: boolean; include_community?: boolean; max_programs?: number; max_candidates_per_program?: number; max_sources_per_program?: number; include_data_acquisition?: boolean; include_crawl_queue?: boolean } = {}): Promise<CatalogRefreshPlanResponse> {
  return apiJson<CatalogRefreshPlanResponse>("/api/admin/agent-queue/catalog-refresh-plan", postJson(payload), "Catalog refresh queue API");
}

export function queueStudentCatalogRefreshPlan(payload: { selected_program_ids?: string[]; institution?: string | null; max_programs?: number; max_candidates_per_program?: number; max_sources_per_program?: number; include_data_acquisition?: boolean; include_crawl_queue?: boolean } = {}): Promise<CatalogRefreshPlanResponse> {
  return apiJson<CatalogRefreshPlanResponse>("/api/catalog-refresh-plan", postJson({ dry_run: false, include_community: true, ...payload }), "Source update queue API");
}

export function runNextAgentJob(): Promise<AgentQueueRunResponse> {
  return apiJson<AgentQueueRunResponse>("/api/admin/agent-queue/run-next", { method: "POST" }, "Agent worker API");
}

export function retryAgentJob(jobId: string, reviewerId = "local_admin"): Promise<{ ok: boolean; job_id: string; status: string }> {
  return apiJson<{ ok: boolean; job_id: string; status: string }>("/api/admin/agent-queue/" + encodeURIComponent(jobId) + "/retry", postJson({ reviewer_id: reviewerId }), "Agent retry API");
}

export function rollbackAgentRun(payload: { workflow_id: string; target_step_id: string; reviewer_id?: string; reason?: string; enqueue_retry?: boolean }): Promise<{ ok: boolean; status: string; current_step: string; rolled_back_step_count: number; retry_job?: AgentQueueJob | null }> {
  return apiJson<{ ok: boolean; status: string; current_step: string; rolled_back_step_count: number; retry_job?: AgentQueueJob | null }>(
    "/api/admin/agent-runs/" + encodeURIComponent(payload.workflow_id) + "/rollback",
    postJson({ target_step_id: payload.target_step_id, reviewer_id: payload.reviewer_id ?? "local_admin", reason: payload.reason ?? "Rollback requested by operator.", enqueue_retry: payload.enqueue_retry ?? true }),
    "Agent rollback API",
  );
}

export function retryAgentStep(workflowId: string, stepId: string, reviewerId = "local_admin"): Promise<{ ok: boolean; status: string; job?: AgentQueueJob }> {
  return apiJson<{ ok: boolean; status: string; job?: AgentQueueJob }>("/api/admin/agent-runs/" + encodeURIComponent(workflowId) + "/steps/" + encodeURIComponent(stepId) + "/retry", postJson({ reviewer_id: reviewerId }), "Agent step retry API");
}

export function handoffAgentStep(workflowId: string, stepId: string, assignee = "human_reviewer", reason = "Needs human review before continuing."): Promise<{ ok: boolean; assigned_to: string; reason: string }> {
  return apiJson<{ ok: boolean; assigned_to: string; reason: string }>("/api/admin/agent-runs/" + encodeURIComponent(workflowId) + "/steps/" + encodeURIComponent(stepId) + "/handoff", postJson({ assignee, reason }), "Agent handoff API");
}
