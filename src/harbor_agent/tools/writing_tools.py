from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.models import (
    ClaimGraph,
    NormalizedProfile,
    ProgramMatch,
    QuestionnaireResponse,
    ResolvedProgramView,
    StoryCard,
    WritingDraft,
)
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.claim_graph import build_claim_graph, claim_graph_passed
from harbor_agent.services.resolved_program import resolve_program_view
from harbor_agent.services.deterministic_writing import (
    build_fact_bound_writing_draft,
    build_story_cards,
)
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class StudentFactsResult(BaseModel):
    facts: dict = Field(default_factory=dict)


class ProgramEvidenceResult(BaseModel):
    evidence: list[dict] = Field(default_factory=list)


class StoryCardsResult(BaseModel):
    story_cards: list[dict] = Field(default_factory=list)


class WritingGapsResult(BaseModel):
    gaps: list[str] = Field(default_factory=list)


class WritingClaimsResult(BaseModel):
    grounded: bool
    passed: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    graph: ClaimGraph


class WritingDraftResult(BaseModel):
    draft: dict


def _profile(state: AgentState) -> NormalizedProfile:
    if state.normalized_profile is None:
        raise ValueError("normalized profile is required")
    return NormalizedProfile.model_validate(state.normalized_profile)


def _matches(state: AgentState) -> list[ProgramMatch]:
    return [ProgramMatch.model_validate(item) for item in (state.selected_matches or list(state.program_matches.values()))]


def _student_facts(state: AgentState, _: EmptyToolInput) -> StudentFactsResult:
    profile = _profile(state)
    return StudentFactsResult(
        facts={
            "education": profile.education.model_dump(mode="json"),
            "language": profile.language.model_dump(mode="json"),
            "experiences": [item.model_dump(mode="json") for item in profile.experiences],
            "courses": profile.additional_background.core_courses,
            "skills": profile.additional_background.skills,
            "career_goal": profile.career_goal,
        }
    )


def _program_evidence(state: AgentState, _: EmptyToolInput) -> ProgramEvidenceResult:
    """Return only currently formal programme facts to the writing specialist.

    This tool is a prompt/input boundary, not an audit export.  Passing raw
    catalogue values, ``data_status`` or legacy ``field_evidence`` here would
    let a live writing model treat unreviewed seeds as source-backed facts even
    though the later ClaimGraph rejects them.  The specialist receives the
    same resolver projection that drives matching and formal gates.
    """

    evidence: list[dict] = []
    for match in _matches(state):
        view = resolve_program_view(match.program)
        formal_facts = {
            field_name: {
                "value": fact.normalized_value,
                "fact_id": fact.fact_id,
                "evidence_id": fact.evidence_id,
                "source_url": str(fact.source_url) if fact.source_url else None,
            }
            for field_name, fact in view.facts.items()
            if fact.formal_use_ready
        }
        evidence.append(
            {
                "program_id": match.program.id,
                "formal_readiness": view.formal_readiness.value,
                "formal_facts": formal_facts,
                "formal_blockers": view.formal_blockers,
            }
        )
    return ProgramEvidenceResult(evidence=evidence)


def _stories(state: AgentState, _: EmptyToolInput) -> StoryCardsResult:
    questionnaire = QuestionnaireResponse.model_validate(state.questionnaire or {})
    cards = build_story_cards(questionnaire)
    return StoryCardsResult(story_cards=[item.model_dump(mode="json") for item in cards])


def _gaps(state: AgentState, _: EmptyToolInput) -> WritingGapsResult:
    cards = [StoryCard.model_validate(item) for item in state.story_cards]
    gaps: list[str] = []
    if not cards:
        gaps.append("缺少可核实的课程、项目、科研或实习故事素材。")
    if any(item.completeness < 60 for item in cards):
        gaps.append("部分故事卡缺少行动、结果或反思，当前只能生成结构草稿。")
    if not state.selected_matches:
        gaps.append("尚未确定项目，不能写入具体学校或项目事实。")
    return WritingGapsResult(gaps=gaps)


def _claims(state: AgentState, _: EmptyToolInput) -> WritingClaimsResult:
    draft = WritingDraft.model_validate(state.writing_draft) if state.writing_draft else None
    matches = _matches(state)
    # A caller may provide an explicit read-only view in working memory for an
    # offline/golden fixture.  Production paths intentionally leave this empty
    # so build_claim_graph re-resolves from the persisted evidence store.
    raw_views = state.working_memory.get("resolved_program_views")
    views: dict[str, ResolvedProgramView] | None = None
    if isinstance(raw_views, dict):
        views = {
            str(program_id): (
                value
                if isinstance(value, ResolvedProgramView)
                else ResolvedProgramView.model_validate(value)
            )
            for program_id, value in raw_views.items()
        }
    graph = build_claim_graph(draft, matches, resolved_views=views)
    unsupported = [
        node.text
        for node in graph.nodes
        if node.required_for_formal and node.status.value != "SUPPORTED"
    ]
    grounded = claim_graph_passed(graph)
    blockers = list(graph.blockers)
    return WritingClaimsResult(
        grounded=grounded,
        passed=grounded,
        unsupported_claims=unsupported,
        blockers=blockers,
        graph=graph,
    )


def _draft(state: AgentState, _: EmptyToolInput) -> WritingDraftResult:
    profile = _profile(state)
    cards = [StoryCard.model_validate(item) for item in state.story_cards]
    draft = build_fact_bound_writing_draft(profile, _matches(state), cards, document_type=state.document_type)
    return WritingDraftResult(draft=draft.model_dump(mode="json"))


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("retrieve_student_facts", "Retrieve minimal, non-secret student facts for writing.", EmptyToolInput, StudentFactsResult, _student_facts),
        ToolDefinition("retrieve_program_evidence", "Retrieve source-bound programme evidence for writing.", EmptyToolInput, ProgramEvidenceResult, _program_evidence),
        ToolDefinition("build_story_cards", "Build typed, student-sourced experience story cards.", EmptyToolInput, StoryCardsResult, _stories),
        ToolDefinition("inspect_writing_gaps", "Identify missing writing material without filling it with invented facts.", EmptyToolInput, WritingGapsResult, _gaps),
        ToolDefinition("validate_writing_claims", "Validate that writing claims have facts or official programme evidence.", EmptyToolInput, WritingClaimsResult, _claims),
        ToolDefinition("build_writing_draft", "Create a fact-bound writing draft from selected story cards and programme evidence.", EmptyToolInput, WritingDraftResult, _draft),
    ]
