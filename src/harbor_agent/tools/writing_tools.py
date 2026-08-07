from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.services.deterministic_writing import build_fact_bound_writing_draft, build_story_cards
from harbor_agent.models import NormalizedProfile, ProgramMatch, QuestionnaireResponse, StoryCard, WritingDraft
from harbor_agent.runtime.state import AgentState
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
    unsupported_claims: list[str] = Field(default_factory=list)


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
    evidence: list[dict] = []
    for match in _matches(state):
        evidence.append(
            {
                "program_id": match.program.id,
                "official_program_url": str(match.program.official_program_url) if match.program.official_program_url else None,
                "application_url": str(match.program.application_url) if match.program.application_url else None,
                "data_status": match.program.data_status.value,
                "field_evidence": {key: value.model_dump(mode="json") for key, value in match.program.field_evidence.items()},
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
    flags = list(draft.review_flags) if draft else ["尚未生成文书草稿。"]
    unsupported = [flag for flag in flags if "不能" in flag or "需要" in flag or "缺少" in flag]
    return WritingClaimsResult(grounded=not unsupported, unsupported_claims=unsupported)


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
