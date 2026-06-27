from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.config import get_settings
from harbor_agent.core.llm import MockLLMProvider, OpenAICompatibleLLMProvider, build_llm_provider
from harbor_agent.models import (
    ApplicantProfileInput,
    ApplicationPlanResult,
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
from harbor_agent.services.external_candidates import load_qs_master_applications_import
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


class SelectedProgramsRequest(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(default_factory=list)


class WritingPlanRequest(BaseModel):
    profile: ApplicantProfileInput
    questionnaire: QuestionnaireResponse = Field(default_factory=QuestionnaireResponse)
    selected_program_ids: list[str] = Field(default_factory=list)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")


class WritingInterviewRequest(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(default_factory=list)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")


class WritingOutlineRequestPayload(BaseModel):
    profile: ApplicantProfileInput
    selected_program_ids: list[str] = Field(default_factory=list)
    document_type: str = Field(default="PS", pattern="^(PS|SOP|CV|ESSAY|REFERENCE_PACKAGE)$")
    interview_answers: list[QuestionnaireAnswer] = Field(default_factory=list)


class WritingReviewRequest(BaseModel):
    draft: WritingDraft
    story_cards: list[StoryCard] = Field(default_factory=list)

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


@app.post("/api/admin/llm-config", response_model=LLMConfigResponse)
def configure_llm(payload: LLMConfigRequest) -> LLMConfigResponse:
    global llm_provider

    if payload.provider == "mock":
        llm_provider = MockLLMProvider()
        return LLMConfigResponse(
            ok=True,
            provider="mock",
            model="mock",
            message="已切回 mock 模式，不使用 API Key。",
        )

    if not payload.api_key:
        raise HTTPException(status_code=400, detail="真实大模型模式需要填写 API Key。")

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


@app.get("/api/source-registry")
def source_registry() -> dict:
    return load_source_registry().model_dump(mode="json")


@app.get("/api/external-candidates/qs-master-applications")
def qs_master_applications_candidates() -> dict:
    return load_qs_master_applications_import()


@app.get("/api/evidence-graph/summary", response_model=EvidenceGraphSummary)
def evidence_graph_summary() -> EvidenceGraphSummary:
    return build_evidence_graph_summary()


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
    limit: int = Query(default=80, ge=1, le=200),
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
    return [_program_catalog_item(program) for program in items[:limit]]


@app.get("/api/programs/{program_id}/trust", response_model=ProgramTrustDetail)
def program_trust_detail(program_id: str) -> ProgramTrustDetail:
    program = next((item for item in load_programs() if item.id == program_id), None)
    if program is None:
        raise HTTPException(status_code=404, detail="项目不存在。")
    return build_program_trust_detail(program)


def _program_catalog_item(program) -> dict:
    item = program.model_dump(mode="json")
    item["trust_detail"] = build_program_trust_detail(program).model_dump(mode="json")
    return item


@app.post("/api/workflows/background", response_model=BackgroundStageResult)
def run_background_stage(payload: ApplicantProfileInput) -> BackgroundStageResult:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_background_stage(payload)


@app.post("/api/workflows/program-plan", response_model=ProgramPlanResult)
def run_program_plan_stage(payload: ApplicantProfileInput) -> ProgramPlanResult:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_program_plan_stage(payload)


@app.post("/api/workflows/application-plan", response_model=ApplicationPlanResult)
def run_application_plan_stage(payload: SelectedProgramsRequest) -> ApplicationPlanResult:
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_application_plan_stage(payload.profile, payload.selected_program_ids)


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
    orchestrator = WorkflowOrchestrator(llm_provider)
    return orchestrator.run_writing_plan_stage(
        payload.profile,
        payload.questionnaire,
        payload.selected_program_ids,
        payload.document_type,
    )


@app.post("/api/workflows/writing-interview", response_model=list[WritingInterviewQuestion])
def run_writing_interview(payload: WritingInterviewRequest) -> list[WritingInterviewQuestion]:
    orchestrator = WorkflowOrchestrator(llm_provider)
    profile = orchestrator.profile_agent.run(payload.profile)
    assessment = orchestrator.evaluation_agent.run(profile)
    matches = orchestrator.matching_agent.run(profile, assessment, orchestrator.program_agent.run(profile))
    selected = [item for item in matches if item.program.id in payload.selected_program_ids] or matches[:1]
    return orchestrator.writing_agent.interview_questions(profile, selected, payload.document_type)


@app.post("/api/workflows/writing-outline", response_model=WritingDraft)
def run_writing_outline(payload: WritingOutlineRequestPayload) -> WritingDraft:
    orchestrator = WorkflowOrchestrator(llm_provider)
    profile = orchestrator.profile_agent.run(payload.profile)
    assessment = orchestrator.evaluation_agent.run(profile)
    matches = orchestrator.matching_agent.run(profile, assessment, orchestrator.program_agent.run(profile))
    selected = [item for item in matches if item.program.id in payload.selected_program_ids] or matches[:1]
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
