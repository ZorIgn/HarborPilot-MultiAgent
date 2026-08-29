"""Deterministic writing-material helpers used behind the Tool Registry."""

from __future__ import annotations

from harbor_agent.models import NormalizedProfile, ProgramMatch, QuestionnaireResponse, StoryCard, WritingDraft


def build_story_cards(questionnaire: QuestionnaireResponse) -> list[StoryCard]:
    """Build fact-bound story cards from the student's questionnaire responses."""

    cards: list[StoryCard] = []
    grouped = _answers_by_id(questionnaire)

    academic = _first(grouped, "academic_strength", "core_courses", "gpa_rank")
    if academic:
        cards.append(
            StoryCard(
                id="story_academic_1",
                title="学术能力故事",
                category="education",
                situation=_first(grouped, "major_degree", "gpa_rank"),
                task=_first(grouped, "prerequisite_fit", "core_courses"),
                action=academic[:600],
                result=_first(grouped, "gpa_rank"),
                reflection=_first(grouped, "problem_awareness", "career_transfer"),
                related_skills=_skills_from_text(academic, ["统计", "数据", "Python", "SQL", "研究", "写作"]),
                target_program_relevance=["用于 PS/SOP 的学术基础段落"],
                evidence_ids=_evidence_ids(questionnaire, {"academic_strength", "core_courses", "gpa_rank", "major_degree", "prerequisite_fit"}),
                completeness=_score_card([academic, grouped.get("core_courses"), grouped.get("gpa_rank")]),
            )
        )

    practice_problem = _first(grouped, "practice_problem", "best_story_problem", "practical_examples", "experience_process")
    practice_action = _first(grouped, "practice_actions", "practice_role", "role_actions", "technical_role", "discipline_bridge", "ba_to_cs_bridge")
    practice_result = _first(grouped, "practice_result", "result_validation", "data_scale_validation", "experience_result")
    practice_reflection = _first(grouped, "practice_reflection", "career_transfer", "why_program_binding", "discipline_bridge")
    if any([practice_problem, practice_action, practice_result, practice_reflection]):
        cards.append(
            StoryCard(
                id="story_practice_1",
                title="实践经历故事",
                category="internship",
                situation=_first(grouped, "experience_org", "practice_problem", "best_story_problem"),
                task=_first(grouped, "practice_role", "practice_problem", "best_story_problem"),
                action=practice_action[:700],
                result=practice_result,
                reflection=practice_reflection,
                related_skills=_skills_from_text(practice_action, ["Python", "SQL", "建模", "系统设计", "研究", "沟通", "分析", "写作"]),
                target_program_relevance=[_first(grouped, "why_program_binding") or "用于能力证据、职业目标和项目匹配段落"],
                evidence_ids=_evidence_ids(
                    questionnaire,
                    {
                        "practice_problem",
                        "practice_actions",
                        "practice_role",
                        "practice_result",
                        "practice_reflection",
                        "practical_examples",
                        "experience_process",
                        "best_story_problem",
                        "role_actions",
                        "technical_role",
                        "result_validation",
                        "data_scale_validation",
                        "discipline_bridge",
                        "career_transfer",
                        "experience_result",
                        "experience_reflection",
                        "why_program_binding",
                    },
                ),
                completeness=_score_card([practice_problem, practice_action, practice_result, practice_reflection]),
            )
        )

    motivation = _first(grouped, "opening_trigger", "interest_origin", "career_plan")
    if motivation:
        cards.append(
            StoryCard(
                id="story_motivation_1",
                title="申请动机与职业规划",
                category="motivation",
                situation=_first(grouped, "opening_trigger", "interest_origin"),
                task=_first(grouped, "problem_awareness"),
                action=_first(grouped, "why_program_binding", "why_program"),
                result=_first(grouped, "career_plan"),
                reflection=_first(grouped, "special_context", "why_school"),
                related_skills=["目标清晰度", "专业理解", "职业规划"],
                target_program_relevance=[_first(grouped, "why_program_binding") or "用于开篇、Why Program 和 Career Plan"],
                evidence_ids=_evidence_ids(
                    questionnaire,
                    {"opening_trigger", "interest_origin", "career_plan", "why_program_binding", "why_program", "why_school"},
                ),
                completeness=_score_card([motivation, grouped.get("career_plan"), grouped.get("why_program_binding")]),
            )
        )

    recommender = _first(grouped, "recommender_identity", "recommender_official_role", "relationship", "course_performance", "presentation_group_research", "impression_examples", "competency_events")
    if recommender:
        cards.append(
            StoryCard(
                id="story_recommender_1",
                title="推荐信事实素材卡",
                category="recommender",
                situation=_first(grouped, "recommender_identity", "recommender_official_role", "relationship"),
                task=_first(grouped, "relationship", "course_performance", "course_or_project", "recommender_submission_boundary"),
                action=_first(grouped, "presentation_group_research", "impression_examples"),
                result=_first(grouped, "competency_events", "other_observations"),
                related_skills=["课堂表现", "协作", "推荐人观察"],
                target_program_relevance=["用于推荐信素材整理"],
                evidence_ids=_evidence_ids(
                    questionnaire,
                    {"relationship", "course_performance", "presentation_group_research", "impression_examples", "competency_events", "course_or_project", "other_observations"},
                ),
                completeness=_score_card([recommender, grouped.get("course_performance"), grouped.get("competency_events")]),
            )
        )

    return cards


def build_fact_bound_writing_draft(
    profile: NormalizedProfile,
    matches: list[ProgramMatch],
    story_cards: list[StoryCard],
    *,
    document_type: str = "PS",
) -> WritingDraft:
    """Create the local deterministic writing draft used by the mock runtime path."""

    # These are deterministic formatting primitives, not an Agent API. The
    # public service keeps this narrow composition boundary stable.
    from harbor_agent.services.writing_composer import (
        _cv_bullets,
        _card_text,
        _ensure_minimum_application_draft,
        _guard_writing_outputs,
        _local_draft,
        _material_gaps,
        _normalize_document_type,
        _outline_for,
        _paragraph_drafts,
        _prompt_requirements,
        _reference_package,
        _review_flags,
        _risk_controls,
        _school_customization,
        _school_name,
        _target_name,
        _story_cards_from_profile,
    )

    if not story_cards:
        story_cards = _story_cards_from_profile(profile)
        document_type = "PS"
    doc_type = _normalize_document_type(document_type)
    target = matches[0] if matches else None
    target_name = _target_name(target)
    school_name = _school_name(target)
    outline = _outline_for(doc_type)
    fact_bindings = [
        {
            "claim": _card_text(card, card.title),
            "fact_id": ",".join(card.evidence_ids) or card.id,
        }
        for card in story_cards
    ]
    draft_zh, draft_en = _local_draft(profile, target, story_cards, doc_type)
    flags = _review_flags(story_cards, target)
    school_customization = _school_customization(target, doc_type)
    prompt_requirements = _prompt_requirements(target, doc_type)
    cv_bullets = _cv_bullets(story_cards)
    reference_package = _reference_package(story_cards)
    risk_controls = _risk_controls(story_cards, target)
    material_gaps = _material_gaps(story_cards, target, doc_type)

    draft_zh, draft_en, school_customization = _guard_writing_outputs(
        draft_zh,
        draft_en,
        school_customization,
        target,
        doc_type,
        flags,
    )
    if doc_type in {"PS", "SOP", "ESSAY"}:
        draft_en = _ensure_minimum_application_draft(draft_en, profile, target, story_cards)
        draft_zh, draft_en, school_customization = _guard_writing_outputs(
            draft_zh,
            draft_en,
            school_customization,
            target,
            doc_type,
            flags,
        )
    paragraph_drafts = _paragraph_drafts(draft_zh, draft_en)
    doc_label = {"REFERENCE_PACKAGE": "推荐信", "PS": "PS", "SOP": "SOP", "CV": "CV", "ESSAY": "Essay"}.get(doc_type, doc_type)
    title = f"{school_name} {target_name} {doc_label} 中英文草稿"
    return WritingDraft(
        document_type=doc_type,
        version_id="v1-student-story",
        title=title,
        outline=outline,
        draft=draft_zh,
        draft_zh=draft_zh,
        draft_en=draft_en,
        material_gaps=material_gaps,
        paragraph_drafts=paragraph_drafts,
        fact_bindings=fact_bindings,
        target_program_ids=[target.program.id] if target else [],
        school_customization=school_customization,
        prompt_requirements=prompt_requirements,
        cv_bullets=cv_bullets,
        reference_package=reference_package,
        risk_controls=risk_controls,
        review_flags=flags,
    )


def _answers_by_id(questionnaire: QuestionnaireResponse) -> dict[str, str]:
    output: dict[str, str] = {}
    for answer in questionnaire.profile_answers + questionnaire.statement_answers + questionnaire.recommender_answers:
        if answer.value is not None:
            output[answer.field_id] = "\n".join(answer.value) if isinstance(answer.value, list) else str(answer.value)
    return output


def _first(grouped: dict[str, str], *field_ids: str) -> str:
    for field_id in field_ids:
        value = str(grouped.get(field_id) or "").strip()
        if value:
            return value
    return ""


def _skills_from_text(text: str, skills: list[str]) -> list[str]:
    lowered = text.lower()
    return [skill for skill in skills if skill.lower() in lowered]


def _evidence_ids(questionnaire: QuestionnaireResponse, field_ids: set[str]) -> list[str]:
    ids: list[str] = []
    for answer in questionnaire.profile_answers + questionnaire.statement_answers + questionnaire.recommender_answers:
        if answer.field_id in field_ids:
            ids.extend(answer.evidence_ids)
            ids.append(f"questionnaire:{answer.field_id}")
    return sorted(set(ids))


def _score_card(values: list[str | None]) -> int:
    present = sum(1 for value in values if value and len(value.strip()) >= 12)
    return min(100, 35 + present * 22)
