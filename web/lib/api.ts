import type {
  AgentSystemReport,
  ApplicantPayload,
  CatalogProgram,
  DataAcquisitionReport,
  DataRefreshReport,
  ProgramDataPackage,
  EvidenceGraphSummary,
  LLMConfigResponse,
  ApplicationPlanResult,
  BackgroundStageResult,
  LayeredProgramPlanResult,
  QuestionnaireResponse,
  QuestionnaireSchema,
  ReviewPublishResponse,
  ReviewQueueSummary,
  SourceRegistry,
  WorkflowResult,
  WritingDraft,
  WritingInterviewQuestion,
  WritingPlanResult,
  WritingReviewRubric
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function runAssessment(payload: ApplicantPayload): Promise<WorkflowResult> {
  const response = await fetch(`${API_BASE}/api/workflows/assessment`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Assessment API returned ${response.status}`);
  }
  return response.json();
}

export async function runBackgroundStage(payload: ApplicantPayload): Promise<BackgroundStageResult> {
  const response = await fetch(`${API_BASE}/api/workflows/background`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Background API returned ${response.status}`);
  }
  return response.json();
}

export async function runProgramPlan(payload: ApplicantPayload): Promise<LayeredProgramPlanResult> {
  const response = await fetch(`${API_BASE}/api/workflows/program-plan`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Program plan API returned ${response.status}`);
  }
  return response.json();
}

export async function runApplicationPlan(payload: {
  profile: ApplicantPayload;
  selected_program_ids: string[];
}): Promise<ApplicationPlanResult> {
  const response = await fetch(`${API_BASE}/api/workflows/application-plan`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Application plan API returned ${response.status}`);
  }
  return response.json();
}

export async function runDataRefresh(payload: {
  region?: "HK" | "SG" | "ALL";
  institution?: string | null;
  selected_program_ids?: string[];
  dry_run?: boolean;
  use_llm?: boolean;
  max_sources?: number;
}): Promise<DataRefreshReport> {
  const response = await fetch(`${API_BASE}/api/workflows/data-refresh`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Data refresh API returned ${response.status}`);
  }
  return response.json();
}

export async function runWritingPlan(payload: {
  profile: ApplicantPayload;
  questionnaire: QuestionnaireResponse;
  selected_program_ids: string[];
  document_type?: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
}): Promise<WritingPlanResult> {
  const response = await fetch(`${API_BASE}/api/workflows/writing-plan`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Writing plan API returned ${response.status}`);
  }
  return response.json();
}

export async function runWritingInterview(payload: {
  profile: ApplicantPayload;
  selected_program_ids: string[];
  document_type?: "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
}): Promise<WritingInterviewQuestion[]> {
  const response = await fetch(`${API_BASE}/api/workflows/writing-interview`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Writing interview API returned ${response.status}`);
  }
  return response.json();
}

export async function runWritingReview(payload: {
  draft: WritingDraft;
  story_cards: Array<unknown>;
}): Promise<WritingReviewRubric> {
  const response = await fetch(`${API_BASE}/api/workflows/writing-review`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Writing review API returned ${response.status}`);
  }
  return response.json();
}

export async function getHealth(): Promise<{ status: string; llm_mode: string; llm_provider?: string }> {
  const response = await fetch(`${API_BASE}/api/health`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Health API returned ${response.status}`);
  }
  return response.json();
}

export async function configureLLM(payload: {
  provider: "mock" | "openai" | "deepseek" | "compatible";
  api_key?: string;
  model?: string;
  base_url?: string;
}): Promise<LLMConfigResponse> {
  const response = await fetch(`${API_BASE}/api/admin/llm-config`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `LLM config API returned ${response.status}`);
  }
  return data;
}

export async function getLLMConfig(): Promise<LLMConfigResponse> {
  const response = await fetch(`${API_BASE}/api/admin/llm-config`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`LLM config API returned ${response.status}`);
  }
  return response.json();
}

export async function getPrograms(filters?: Record<string, string | number | boolean | null | undefined>): Promise<CatalogProgram[]> {
  const query = new URLSearchParams();
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(`${API_BASE}/api/programs${suffix}`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Programs API returned ${response.status}`);
  }
  return response.json();
}

export async function getProgramDataPackage(programId: string): Promise<ProgramDataPackage> {
  const response = await fetch(`${API_BASE}/api/programs/${programId}/data-package`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Program data package API returned ${response.status}`);
  }
  return response.json();
}

export async function runDataAcquisition(payload: {
  selected_program_ids?: string[];
  include_community?: boolean;
  dry_run?: boolean;
  max_sources_per_program?: number;
}): Promise<DataAcquisitionReport> {
  const response = await fetch(`${API_BASE}/api/workflows/data-acquisition`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Data acquisition API returned ${response.status}`);
  }
  return response.json();
}
export async function getSourceRegistry(): Promise<SourceRegistry> {
  const response = await fetch(`${API_BASE}/api/source-registry`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Source registry API returned ${response.status}`);
  }
  return response.json();
}

export async function getEvidenceGraphSummary(): Promise<EvidenceGraphSummary> {
  const response = await fetch(`${API_BASE}/api/evidence-graph/summary`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Evidence graph API returned ${response.status}`);
  }
  return response.json();
}

export async function getQuestionnaireSchema(): Promise<QuestionnaireSchema> {
  const response = await fetch(`${API_BASE}/api/questionnaire-schema`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Questionnaire API returned ${response.status}`);
  }
  return response.json();
}
export async function getReviewQueue(filters?: { program_id?: string; limit?: number }): Promise<ReviewQueueSummary> {
  const query = new URLSearchParams();
  if (filters?.program_id) query.set("program_id", filters.program_id);
  if (filters?.limit) query.set("limit", String(filters.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(`${API_BASE}/api/admin/review-queue${suffix}`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Review queue API returned ${response.status}`);
  }
  return response.json();
}

export async function publishReviewItem(payload: {
  review_id: string;
  decision: "approve" | "reject";
  reviewer_id?: string;
  reviewer_note?: string | null;
  confirmed_value?: string | null;
  persist?: boolean;
}): Promise<ReviewPublishResponse> {
  const response = await fetch(`${API_BASE}/api/admin/review-queue/publish`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Review publish API returned ${response.status}`);
  }
  return response.json();
}
export async function getAgentSystemReport(): Promise<AgentSystemReport> {
  const response = await fetch(`${API_BASE}/api/agent-system`, {cache: "no-store"});
  if (!response.ok) {
    throw new Error(`Agent system API returned ${response.status}`);
  }
  return response.json();
}
