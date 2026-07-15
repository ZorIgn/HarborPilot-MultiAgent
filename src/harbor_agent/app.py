from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any

from harbor_agent.agents.catalog_auto_update import CatalogAutoUpdateAgent
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.config import get_settings
from harbor_agent.core.llm import MockLLMProvider, OpenAICompatibleLLMProvider, build_llm_provider
from harbor_agent.models import (
    AgentSystemReport,
    ApplicantProfileInput,
    ApplicationPlanResult,
    CatalogAutoUpdateReport,
    CatalogAutoUpdateRequest,
    DataAcquisitionReport,
    DataAcquisitionRequest,
    CrawlQueueReport,
    CrawlQueueRequest,
    ProgramDataPackage,
    ReviewBulkPublishRequest,
    ReviewBulkPublishResponse,
    ReviewPublishRequest,
    ReviewPublishResponse,
    ReviewQueueSummary,
    BackgroundStageResult,
    DataRefreshReport,
    DataRefreshRequest,
    EvidenceGraphSummary,
    QuestionnaireAnswer,
    ProgramPlanResult,
    ProgramTrustDetail,
    QuestionnaireResponse,
    StoryCard,
    WritingDraft,
    WritingInterviewQuestion,
    WorkflowResult,
    WritingPlanResult,
    WritingReviewRubric,
)
from harbor_agent.services.evidence_graph import build_evidence_graph_summary, build_program_trust_detail
from harbor_agent.services.formal_gate import accepted_url
from harbor_agent.services.external_candidates import load_qs_master_applications_import
from harbor_agent.services.program_urls import is_generic_application_url, is_generic_program_url, student_application_url, student_program_url
from harbor_agent.services.profile_store import load_profile, load_workspace_state, profile_store_secret, save_profile, save_workspace_state
from harbor_agent.services.review_gate import build_review_queue, publish_review_batch, publish_review_item
from harbor_agent.services.scenario_audit_runner import scenario_audit_summary
from harbor_agent.services.agent_registry import build_agent_system_report
from harbor_agent.services.agent_worker import execute_agent_job
from harbor_agent.services.agent_runtime import (
    claim_next_agent_job,
    enqueue_agent_job,
    enqueue_catalog_refresh_plan,
    get_agent_run,
    handoff_step,
    list_agent_jobs,
    list_agent_runs,
    request_step_retry,
    resolve_handoff_step,
    rollback_agent_run,
    retry_agent_job,
    list_agent_events,
)
from harbor_agent.services.matching_strategy import load_matching_strategy, save_matching_strategy, strategy_source
from harbor_agent.services.matching_strategy_agent import propose_matching_strategy
from harbor_agent.services.data_loader import (
    load_community_sources,
    load_form_definition,
    load_programs,
    load_questionnaire_schema,
    load_source_registry,
    load_taxonomy,
    load_cv_profile_schema,
)

settings = get_settings()
llm_provider = build_llm_provider(settings)


class LLMConfigRequest(BaseModel):
    provider: str = Field(default="deepseek", pattern="^(openai|deepseek|compatible|mock)$")
    api_key: str | None = None
    model: str = "deepseek-v4-flash"
    base_url: str | None = None


class LLMConfigResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    base_url: str | None = None
    message: str


class MatchingStrategyProposalRequest(BaseModel):
    instruction: str
    apply: bool = False


class LocalWorkspaceState(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    questionnaire_values: dict[str, str] = Field(default_factory=dict)
    result_snapshot: dict[str, Any] | None = None
    field_sensitivity: dict[str, str] = Field(default_factory=dict)
    writing_draft_history: list[dict[str, Any]] = Field(default_factory=list)

    program_scheme: dict[str, Any] = Field(default_factory=dict)


class SelectedProgramsRequest(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(min_length=1, max_length=20)


class WritingPlanRequest(BaseModel):
    profile: ApplicantProfileInput
    questionnaire: QuestionnaireResponse = Field(default_factory=QuestionnaireResponse)
    selected_program_ids: list[str] = Field(min_length=1, max_length=20)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")


class WritingInterviewRequest(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(min_length=1, max_length=20)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")


class WritingOutlineRequestPayload(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(min_length=1, max_length=20)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")
    interview_answers: list[QuestionnaireAnswer] = Field(default_factory=list)


class WritingReviewRequest(BaseModel):
    draft: WritingDraft
    story_cards: list[StoryCard] = Field(default_factory=list)


class AgentJobCreateRequest(BaseModel):
    workflow_name: str
    payload_summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=2, ge=1, le=10)


class CatalogRefreshPlanRequest(BaseModel):
    selected_program_ids: list[str] = Field(default_factory=list)
    institution: str | None = None
    dry_run: bool = False
    include_community: bool = True
    max_programs: int = Field(default=48, ge=1, le=200)
    max_candidates_per_program: int = Field(default=6, ge=1, le=20)
    max_sources_per_program: int = Field(default=8, ge=1, le=30)
    include_data_acquisition: bool = True
    include_crawl_queue: bool = True


class CatalogRefreshPlanResponse(BaseModel):
    ok: bool
    mode: str
    jobs: list[dict[str, Any]]
    next_step: str

class AgentJobRetryRequest(BaseModel):
    reviewer_id: str = "local_admin"


class AgentRetryRequest(BaseModel):
    reviewer_id: str = "local_admin"


class AgentHandoffRequest(BaseModel):
    assignee: str = "human_reviewer"
    reason: str = "Needs human review before continuing."


class AgentResolveHandoffRequest(BaseModel):
    reviewer_id: str = "local_admin"
    decision: str = Field(default="resume", pattern="^(resume|fail|complete)$")
    note: str = ""


class AgentRollbackRequest(BaseModel):
    target_step_id: str
    reviewer_id: str = "local_admin"
    reason: str = "Rollback requested by operator."
    enqueue_retry: bool = True


class AgentQueueRunResponse(BaseModel):
    ok: bool
    message: str
    job: dict[str, Any] | None = None

app = FastAPI(
    title="HarborPilot AI API",
    version="0.1.0",
    description="Multi-agent admissions planning API for Hong Kong and Singapore applications.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROFILE_COOKIE_NAME = "harbor_profile_id"
_PROFILE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,96}$")
_ADMIN_SAFE_METHODS = {"GET", "HEAD"}
_LOCAL_ADMIN_HOSTS = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def admin_api_guard(request: Request, call_next):
    if request.url.path.startswith("/api/admin/") and request.method != "OPTIONS":
        if not _admin_request_allowed(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Admin API 需要本机访问或管理员令牌。"},
            )
    return await call_next(request)


def _admin_request_allowed(request: Request) -> bool:
    configured = settings.admin_token
    supplied = request.headers.get("x-harbor-admin-token") or _bearer_token(request.headers.get("authorization"))
    if configured:
        return bool(supplied) and secrets.compare_digest(str(supplied), configured)

    client_host = request.client.host if request.client else ""
    if client_host == "testclient":
        return True
    if request.method in _ADMIN_SAFE_METHODS and client_host in _LOCAL_ADMIN_HOSTS:
        return True
    if settings.allow_insecure_local_admin and client_host in _LOCAL_ADMIN_HOSTS:
        return True
    return False


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "Bearer "
    return value[len(prefix):].strip() if value.startswith(prefix) else None


def _request_profile_id(request: Request, response: Response) -> str:
    candidate = _verify_profile_cookie(request.cookies.get(PROFILE_COOKIE_NAME))
    if not candidate:
        candidate = "student_" + secrets.token_urlsafe(18)
    response.set_cookie(
        PROFILE_COOKIE_NAME,
        _sign_profile_cookie(candidate),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return candidate


def _sign_profile_cookie(profile_id: str) -> str:
    signature = hmac.new(profile_store_secret(), profile_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{profile_id}.{signature}"


def _verify_profile_cookie(raw_cookie: str | None) -> str | None:
    if not raw_cookie or "." not in raw_cookie:
        return None
    profile_id, supplied_signature = raw_cookie.rsplit(".", 1)
    if not _PROFILE_ID_PATTERN.match(profile_id):
        return None
    expected_signature = hmac.new(profile_store_secret(), profile_id.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    return profile_id


def _load_profile_for_request(profile_id: str) -> ApplicantProfileInput | None:
    try:
        return load_profile(profile_id=profile_id)
    except TypeError:
        return load_profile()


def _save_profile_for_request(payload: ApplicantProfileInput, profile_id: str) -> ApplicantProfileInput:
    try:
        return save_profile(payload, profile_id=profile_id)
    except TypeError:
        return save_profile(payload)


def _load_workspace_for_request(profile_id: str) -> dict[str, Any]:
    try:
        return load_workspace_state(profile_id=profile_id)
    except TypeError:
        return load_workspace_state()


def _save_workspace_for_request(profile_id: str, payload: LocalWorkspaceState) -> dict[str, Any]:
    try:
        return save_workspace_state(
            selected_program_ids=payload.selected_program_ids,
            questionnaire_values=payload.questionnaire_values,
            result_snapshot=payload.result_snapshot,
            program_scheme=payload.program_scheme,
            writing_draft_history=payload.writing_draft_history,
            profile_id=profile_id,
        )
    except TypeError:
        return save_workspace_state(
            selected_program_ids=payload.selected_program_ids,
            questionnaire_values=payload.questionnaire_values,
            result_snapshot=payload.result_snapshot,
            writing_draft_history=payload.writing_draft_history,
        )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_mode": llm_provider.name, "llm_provider": llm_provider.provider}


@app.get("/api/admin/llm-config", response_model=LLMConfigResponse)
def get_llm_config() -> LLMConfigResponse:
    return LLMConfigResponse(
        ok=True,
        provider=llm_provider.provider,
        model=llm_provider.name,
        base_url=getattr(llm_provider, "base_url", None),
        message="模型适配器已就绪。",
    )


@app.get("/api/llm-config", response_model=LLMConfigResponse)
def get_student_llm_config() -> LLMConfigResponse:
    return get_llm_config()


def _configure_llm_provider(payload: LLMConfigRequest) -> LLMConfigResponse:
    global llm_provider

    if payload.provider == "mock":
        llm_provider = MockLLMProvider()
        return LLMConfigResponse(
            ok=True,
            provider="mock",
            model="mock",
            message="已切回示例模式，不使用 API Key。",
        )

    if not payload.api_key:
        raise HTTPException(status_code=400, detail="请选择模型并填写 API Key。")

    try:
        base_url = payload.base_url
        if payload.provider == "deepseek":
            base_url = "https://api.deepseek.com"
        provider = OpenAICompatibleLLMProvider(
            api_key=payload.api_key,
            model=payload.model,
            provider=payload.provider,
            base_url=base_url,
        )
        smoke = provider.complete_json(
            system="Return JSON only. You are testing an admissions multi-agent adapter.",
            user="用中文回复一个 JSON，确认模型连接正常。",
            schema_hint={"summary": "string"},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"模型连接失败：{exc}") from exc

    llm_provider = provider
    return LLMConfigResponse(
        ok=True,
        provider=provider.provider,
        model=provider.name,
        base_url=provider.base_url,
        message=f"连接成功，测试返回字段：{', '.join(smoke.keys()) or 'summary'}",
    )


@app.post("/api/admin/llm-config", response_model=LLMConfigResponse)
def configure_llm(payload: LLMConfigRequest) -> LLMConfigResponse:
    return _configure_llm_provider(payload)


@app.post("/api/llm-config", response_model=LLMConfigResponse)
def configure_student_llm(payload: LLMConfigRequest) -> LLMConfigResponse:
    return _configure_llm_provider(payload)


@app.get("/api/taxonomy")
def taxonomy() -> dict:
    return load_taxonomy()


@app.get("/api/form-definition")
def form_definition() -> dict:
    return load_form_definition()


@app.get("/api/questionnaire-schema")
def questionnaire_schema() -> dict:
    return load_questionnaire_schema()


@app.get("/api/cv-profile-schema")
def cv_profile_schema() -> dict:
    return load_cv_profile_schema()


@app.get("/api/community-sources")
def community_sources() -> dict:
    return load_community_sources()


@app.get("/api/profile/local", response_model=ApplicantProfileInput | None)
def get_local_profile(request: Request, response: Response) -> ApplicantProfileInput | None:
    return _load_profile_for_request(_request_profile_id(request, response))


@app.put("/api/profile/local", response_model=ApplicantProfileInput)
def put_local_profile(payload: ApplicantProfileInput, request: Request, response: Response) -> ApplicantProfileInput:
    return _save_profile_for_request(payload, _request_profile_id(request, response))


@app.get("/api/workspace/local", response_model=LocalWorkspaceState)
def get_local_workspace(request: Request, response: Response) -> LocalWorkspaceState:
    return LocalWorkspaceState.model_validate(_load_workspace_for_request(_request_profile_id(request, response)))


@app.put("/api/workspace/local", response_model=LocalWorkspaceState)
def put_local_workspace(payload: LocalWorkspaceState, request: Request, response: Response) -> LocalWorkspaceState:
    return LocalWorkspaceState.model_validate(_save_workspace_for_request(_request_profile_id(request, response), payload))


@app.get("/api/source-registry")
def source_registry() -> dict:
    return load_source_registry().model_dump(mode="json")


@app.get("/api/admin/matching-strategy")
def admin_matching_strategy() -> dict:
    return {"strategy": load_matching_strategy(), "source": strategy_source()}


@app.put("/api/admin/matching-strategy")
def admin_update_matching_strategy(payload: dict[str, Any]) -> dict:
    return {"strategy": save_matching_strategy(payload), "source": strategy_source()}




@app.post("/api/admin/matching-strategy/propose")
def admin_propose_matching_strategy(payload: MatchingStrategyProposalRequest) -> dict:
    return {
        **propose_matching_strategy(instruction=payload.instruction, llm=llm_provider, apply=payload.apply),
        "source": strategy_source(),
    }


@app.get("/api/external-candidates/qs-master-applications")
def qs_master_applications_candidates() -> dict:
    return load_qs_master_applications_import()


@app.get("/api/evidence-graph/summary", response_model=EvidenceGraphSummary)
def evidence_graph_summary() -> EvidenceGraphSummary:
    return build_evidence_graph_summary()

@app.get("/api/agent-system", response_model=AgentSystemReport)
def agent_system_report() -> AgentSystemReport:
    return build_agent_system_report()


@app.get("/api/admin/scenario-audit")
def admin_scenario_audit() -> dict:
    return scenario_audit_summary()


@app.get("/api/admin/agent-runs")
def admin_agent_runs(limit: int = Query(default=80, ge=1, le=500)) -> dict:
    return {"items": list_agent_runs(limit=limit)}


@app.get("/api/admin/agent-runs/{workflow_id}")
def admin_agent_run_detail(workflow_id: str) -> dict:
    detail = get_agent_run(workflow_id)
    if detail["run"] is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return detail


@app.post("/api/admin/agent-runs/{workflow_id}/rollback")
def admin_rollback_agent_run(workflow_id: str, payload: AgentRollbackRequest) -> dict:
    result = rollback_agent_run(
        workflow_id,
        payload.target_step_id,
        payload.reviewer_id,
        payload.reason,
        payload.enqueue_retry,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "rollback target not found"))
    return result


@app.post("/api/admin/agent-runs/{workflow_id}/steps/{step_id}/retry")
def admin_retry_agent_step(workflow_id: str, step_id: str, payload: AgentRetryRequest) -> dict:
    result = request_step_retry(workflow_id, step_id, payload.reviewer_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "step not found"))
    return result


@app.post("/api/admin/agent-runs/{workflow_id}/steps/{step_id}/handoff")
def admin_handoff_agent_step(workflow_id: str, step_id: str, payload: AgentHandoffRequest) -> dict:
    result = handoff_step(workflow_id, step_id, payload.assignee, payload.reason)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "step not found"))
    return result




@app.post("/api/admin/agent-runs/{workflow_id}/steps/{step_id}/resolve-handoff")
def admin_resolve_agent_handoff(workflow_id: str, step_id: str, payload: AgentResolveHandoffRequest) -> dict:
    result = resolve_handoff_step(workflow_id, step_id, payload.reviewer_id, payload.decision, payload.note)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "step not found"))
    return result


@app.get("/api/admin/agent-queue")
def admin_agent_queue(limit: int = Query(default=80, ge=1, le=500)) -> dict:
    return {"items": list_agent_jobs(limit=limit)}


@app.post("/api/admin/agent-queue")
def admin_enqueue_agent_job(payload: AgentJobCreateRequest) -> dict:
    return enqueue_agent_job(
        payload.workflow_name,
        payload.payload_summary,
        payload.payload,
        priority=payload.priority,
        max_attempts=payload.max_attempts,
    )





def _enqueue_catalog_refresh_response(payload: CatalogRefreshPlanRequest) -> CatalogRefreshPlanResponse:
    jobs = enqueue_catalog_refresh_plan(
        selected_program_ids=payload.selected_program_ids,
        institution=payload.institution,
        dry_run=payload.dry_run,
        include_community=payload.include_community,
        max_programs=payload.max_programs,
        max_candidates_per_program=payload.max_candidates_per_program,
        max_sources_per_program=payload.max_sources_per_program,
        include_data_acquisition=payload.include_data_acquisition,
        include_crawl_queue=payload.include_crawl_queue,
    )
    return CatalogRefreshPlanResponse(
        ok=True,
        mode="dry_run" if payload.dry_run else "write",
        jobs=jobs,
        next_step="已加入信息更新队列，运行本地 worker 后会把候选来源送入审核发布门槛。 Run the local worker, then review and publish field evidence.",
    )


@app.post("/api/admin/agent-queue/catalog-refresh-plan", response_model=CatalogRefreshPlanResponse)
def admin_enqueue_catalog_refresh_plan(payload: CatalogRefreshPlanRequest) -> CatalogRefreshPlanResponse:
    return _enqueue_catalog_refresh_response(payload)


@app.post("/api/catalog-refresh-plan", response_model=CatalogRefreshPlanResponse)
def student_enqueue_catalog_refresh_plan(payload: CatalogRefreshPlanRequest) -> CatalogRefreshPlanResponse:
    selected = list(dict.fromkeys(payload.selected_program_ids))
    if not selected:
        raise HTTPException(status_code=422, detail="请选择需要更新官网信息的项目。")
    if len(selected) > 3:
        raise HTTPException(status_code=422, detail="学生端每次最多更新 3 个项目，请分批提交。")
    known_ids = {program.id for program in load_programs()}
    unknown_ids = [program_id for program_id in selected if program_id not in known_ids]
    if unknown_ids:
        raise HTTPException(status_code=422, detail="项目不存在：" + ", ".join(unknown_ids))
    payload.selected_program_ids = selected
    payload.dry_run = False
    payload.include_community = False
    payload.institution = None
    payload.max_programs = len(selected)
    payload.max_candidates_per_program = min(payload.max_candidates_per_program, 6)
    payload.max_sources_per_program = min(payload.max_sources_per_program, 8)
    return _enqueue_catalog_refresh_response(payload)


@app.post("/api/admin/agent-queue/{job_id}/retry")
def admin_retry_agent_job(job_id: str, payload: AgentJobRetryRequest) -> dict:
    result = retry_agent_job(job_id, payload.reviewer_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "job is not retryable"))
    return result


@app.get("/api/admin/agent-events")
def admin_agent_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return {"items": list_agent_events(entity_type=entity_type, entity_id=entity_id, limit=limit)}


@app.post("/api/admin/agent-queue/run-next", response_model=AgentQueueRunResponse)
def admin_run_next_agent_job(background_tasks: BackgroundTasks) -> AgentQueueRunResponse:
    job = claim_next_agent_job()
    if job is None:
        return AgentQueueRunResponse(ok=True, message="No queued agent job is waiting.", job=None)
    background_tasks.add_task(execute_agent_job, job, llm_provider)
    return AgentQueueRunResponse(ok=True, message="Agent worker started.", job=job)



@app.get("/api/programs")
def programs(
    q: str | None = None,
    region: str | None = Query(default=None, pattern="^(HK|SG)$"),
    discipline: str | None = None,
    tuition_min: int | None = None,
    tuition_max: int | None = None,
    duration: int | None = None,
    language_min: float | None = None,
    verification_status: str | None = None,
    deadline_status: str | None = None,
    accepts_cross_major: bool | None = None,
    gre_gmat: bool | None = None,
    interview: bool | None = None,
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[dict]:
    items = load_programs()
    if q:
        needle = q.lower()
        items = [
            program
            for program in items
            if needle
            in " ".join(
                [
                    program.institution,
                    program.institution_zh or "",
                    program.school,
                    program.school_zh or "",
                    program.name,
                    program.name_zh or "",
                ]
            ).lower()
        ]
    if region:
        items = [program for program in items if program.country == region]
    if discipline:
        needle = discipline.lower()
        by_category = [
            program
            for program in items
            if program.category_zh and needle in program.category_zh.lower()
        ]
        items = by_category or [
            program for program in items if needle in " ".join(program.discipline_tags).lower()
        ]
    if tuition_min is not None:
        items = [program for program in items if program.tuition_hkd is not None and program.tuition_hkd >= tuition_min]
    if tuition_max is not None:
        items = [program for program in items if program.tuition_hkd is not None and program.tuition_hkd <= tuition_max]
    if duration is not None:
        items = [program for program in items if program.duration_months == duration]
    if language_min is not None:
        items = [program for program in items if program.requirements.language.get("IELTS", 0) <= language_min]
    if verification_status:
        items = [program for program in items if program.data_status.value == verification_status]
    if deadline_status == "published":
        items = [program for program in items if program.deadline != "NOT_PUBLISHED"]
    if deadline_status == "not_published":
        items = [program for program in items if program.deadline == "NOT_PUBLISHED"]
    if accepts_cross_major is not None:
        items = [
            program
            for program in items
            if (not program.requirements.required_backgrounds) == accepts_cross_major
        ]
    if gre_gmat is not None:
        items = [
            program
            for program in items
            if any("gmat" in material.lower() or "gre" in material.lower() for material in program.materials)
            == gre_gmat
        ]
    if interview is not None:
        items = [
            program
            for program in items
            if any("interview" in material.lower() or "面试" in material for material in program.materials)
            == interview
        ]
    limited_items = items if limit is None else items[:limit]
    return [_program_catalog_item(program) for program in limited_items]


@app.get("/api/programs/{program_id}/data-package", response_model=ProgramDataPackage)
def program_data_package(program_id: str) -> ProgramDataPackage:
    orchestrator = WorkflowOrchestrator(llm_provider)
    report = orchestrator.run_data_acquisition_stage(
        DataAcquisitionRequest(selected_program_ids=[program_id], dry_run=True, include_community=True)
    )
    if not report.packages:
        raise HTTPException(status_code=404, detail="项目不存在。")
    return report.packages[0]


@app.post("/api/workflows/data-acquisition", response_model=DataAcquisitionReport)
def run_data_acquisition_stage(payload: DataAcquisitionRequest) -> DataAcquisitionReport:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_data_acquisition_stage(payload)


@app.post("/api/admin/crawl-queue", response_model=CrawlQueueReport)
def admin_crawl_queue(payload: CrawlQueueRequest) -> CrawlQueueReport:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_crawl_queue_stage(payload)


@app.post("/api/admin/catalog-auto-update", response_model=CatalogAutoUpdateReport)
def admin_catalog_auto_update(payload: CatalogAutoUpdateRequest) -> CatalogAutoUpdateReport:
    return CatalogAutoUpdateAgent().run(payload)


@app.get("/api/programs/{program_id}/trust", response_model=ProgramTrustDetail)
def program_trust_detail(program_id: str) -> ProgramTrustDetail:
    program = next((item for item in load_programs() if item.id == program_id), None)
    if program is None:
        raise HTTPException(status_code=404, detail="项目不存在。")
    return build_program_trust_detail(program)

@app.get("/api/admin/review-queue", response_model=ReviewQueueSummary)
def admin_review_queue(
    program_id: str | None = None,
    limit: int = Query(default=80, ge=1, le=500),
) -> ReviewQueueSummary:
    return build_review_queue(program_id=program_id, limit=limit)


@app.post("/api/admin/review-queue/publish", response_model=ReviewPublishResponse)
def admin_publish_review_item(payload: ReviewPublishRequest) -> ReviewPublishResponse:
    return publish_review_item(payload)


@app.post("/api/admin/review-queue/bulk-publish", response_model=ReviewBulkPublishResponse)
def admin_bulk_publish_review_items(payload: ReviewBulkPublishRequest) -> ReviewBulkPublishResponse:
    return publish_review_batch(payload)


def _program_catalog_item(program) -> dict:
    item = program.model_dump(mode="json")
    trust = build_program_trust_detail(program)
    item["official_program_url"] = accepted_url(program, "official_program_url")
    item["application_url"] = accepted_url(program, "application_url")
    item["trust_detail"] = trust.model_dump(mode="json")
    return item



def _sanitize_student_urls(value):
    if isinstance(value, list):
        return [_sanitize_student_urls(item) for item in value]
    if isinstance(value, dict):
        cleaned = {key: _sanitize_student_urls(item) for key, item in value.items()}
        if "official_program_url" in cleaned:
            official_url = cleaned.get("official_program_url")
            if _is_url_scalar(official_url) and is_generic_program_url(official_url):
                cleaned["official_program_url"] = None
        if "application_url" in cleaned:
            application_url = cleaned.get("application_url")
            if _is_url_scalar(application_url) and is_generic_application_url(application_url):
                cleaned["application_url"] = None
        return cleaned
    return value


def _is_url_scalar(value) -> bool:
    return value is None or isinstance(value, str)


def _validate_supported_cycle(profile: ApplicantProfileInput) -> None:
    supported_cycles = sorted({program.cycle for program in load_programs()})
    if profile.target_cycle not in supported_cycles:
        raise HTTPException(
            status_code=422,
            detail=(
                f"当前项目库不支持申请季 {profile.target_cycle}。"
                f"可用申请季：{', '.join(supported_cycles) or '暂无'}。"
            ),
        )
    supported_scope = any(
        program.cycle == profile.target_cycle
        and program.degree_type == profile.target_degree
        and program.country in profile.target_regions
        for program in load_programs()
    )
    if not supported_scope:
        raise HTTPException(
            status_code=422,
            detail="当前项目库尚未覆盖所选学位类型或地区；目前以港新授课型硕士为主。",
        )


def _validate_selected_program_ids(profile: ApplicantProfileInput, selected_program_ids: list[str]) -> None:
    _validate_supported_cycle(profile)
    valid_ids = {
        program.id
        for program in load_programs()
        if program.cycle == profile.target_cycle
        and program.country in profile.target_regions
        and program.degree_type == profile.target_degree
    }
    unknown_ids = [program_id for program_id in selected_program_ids if program_id not in valid_ids]
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail="所选项目不存在或不属于当前申请季/地区：" + ", ".join(unknown_ids),
        )


@app.post("/api/workflows/background", response_model=BackgroundStageResult)
def run_background_stage(payload: ApplicantProfileInput) -> BackgroundStageResult:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_background_stage(payload)


@app.post("/api/workflows/program-plan", response_model=ProgramPlanResult)
def run_program_plan_stage(payload: ApplicantProfileInput) -> ProgramPlanResult:
    _validate_supported_cycle(payload)
    orchestrator = WorkflowOrchestrator(llm_provider)
    return _sanitize_student_urls(orchestrator.run_program_plan_stage(payload).model_dump(mode="json"))


@app.post("/api/workflows/application-plan", response_model=ApplicationPlanResult)
def run_application_plan_stage(payload: SelectedProgramsRequest) -> ApplicationPlanResult:
    _validate_selected_program_ids(payload.profile, payload.selected_program_ids)
    orchestrator = WorkflowOrchestrator(llm_provider)
    result = orchestrator.run_application_plan_stage(payload.profile, payload.selected_program_ids)
    return _sanitize_student_urls(result.model_dump(mode="json"))


@app.post("/api/workflows/data-refresh", response_model=DataRefreshReport)
def run_data_refresh_stage(payload: DataRefreshRequest) -> DataRefreshReport:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_data_refresh_stage(payload)


@app.post("/api/workflows/source-refresh", response_model=DataRefreshReport)
def run_source_refresh_stage(payload: DataRefreshRequest) -> DataRefreshReport:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_data_refresh_stage(payload)


@app.post("/api/workflows/writing-plan", response_model=WritingPlanResult)
def run_writing_plan_stage(payload: WritingPlanRequest) -> WritingPlanResult:
    _validate_selected_program_ids(payload.profile, payload.selected_program_ids)
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_writing_plan_stage(
        payload.profile,
        payload.questionnaire,
        payload.selected_program_ids,
        payload.document_type,
    )


@app.post("/api/workflows/writing-interview", response_model=list[WritingInterviewQuestion])
def run_writing_interview(payload: WritingInterviewRequest) -> list[WritingInterviewQuestion]:
    _validate_selected_program_ids(payload.profile, payload.selected_program_ids)
    orchestrator = WorkflowOrchestrator(llm_provider)
    profile, selected = orchestrator.selected_program_matches(payload.profile, payload.selected_program_ids)
    return orchestrator.writing_agent.interview_questions(profile, selected, payload.document_type)


@app.post("/api/workflows/writing-outline", response_model=WritingDraft)
def run_writing_outline(payload: WritingOutlineRequestPayload) -> WritingDraft:
    _validate_selected_program_ids(payload.profile, payload.selected_program_ids)
    orchestrator = WorkflowOrchestrator(llm_provider)
    profile, selected = orchestrator.selected_program_matches(payload.profile, payload.selected_program_ids)
    return orchestrator.writing_agent.outline_from_answers(
        profile,
        selected,
        payload.document_type,
        payload.interview_answers,
    )


@app.post("/api/workflows/writing-review", response_model=WritingReviewRubric)
def run_writing_review(payload: WritingReviewRequest) -> WritingReviewRubric:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.writing_agent.review_rubric(payload.draft, payload.story_cards)


@app.post("/api/workflows/assessment", response_model=WorkflowResult)
def run_assessment(payload: ApplicantProfileInput) -> WorkflowResult:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_assessment(payload)


@app.post("/api/admin/model-smoke-test")
def model_smoke_test() -> dict:
    response = llm_provider.complete_json(
        system="Return JSON only.",
        user="Say HarborPilot model wiring is ready.",
        schema_hint={"summary": "string"},
    )
    return {"model": llm_provider.name, "response": response}
