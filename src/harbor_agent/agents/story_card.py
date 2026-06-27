from __future__ import annotations

from harbor_agent.models import QuestionnaireResponse, StoryCard


class StoryCardAgent:
    name = "StoryCardAgent"

    def run(self, questionnaire: QuestionnaireResponse) -> list[StoryCard]:
        cards: list[StoryCard] = []
        grouped = _answers_by_id(questionnaire)

        academic = grouped.get("academic_examples") or grouped.get("core_courses")
        if academic:
            cards.append(
                StoryCard(
                    id="story_academic_1",
                    title="学术能力故事",
                    category="education",
                    situation="申请人提供了课程、课题或竞赛相关素材。",
                    task="提炼与目标专业相关的学术能力证据。",
                    action=str(academic)[:500],
                    result=grouped.get("gpa_rank", ""),
                    reflection=grouped.get("transition_reason", ""),
                    related_skills=["学术理解", "分析能力", "课程匹配"],
                    target_program_relevance=["用于 PS/SOP 的学术基础段落"],
                    evidence_ids=_evidence_ids(questionnaire, {"academic_examples", "core_courses", "gpa_rank"}),
                    completeness=_score_card([academic, grouped.get("gpa_rank")]),
                )
            )

        practical = (
            grouped.get("practical_examples")
            or grouped.get("experience_process")
            or grouped.get("best_story_problem")
        )
        if practical:
            cards.append(
                StoryCard(
                    id="story_practice_1",
                    title="实践经历故事",
                    category="internship",
                    situation=grouped.get("experience_org", str(practical)[:500] or "申请人提供了一段实践经历。"),
                    task=grouped.get("experience_role", grouped.get("best_story_problem", "")),
                    action=(grouped.get("role_actions") or grouped.get("technical_role") or str(practical))[:600],
                    result=grouped.get("result_validation") or grouped.get("data_scale_validation") or grouped.get("experience_result", ""),
                    reflection=grouped.get("discipline_bridge") or grouped.get("career_transfer") or grouped.get("experience_reflection", ""),
                    related_skills=["执行力", "解决问题", "专业迁移", "量化产出"],
                    target_program_relevance=["用于项目能力、职业目标和贡献段落"],
                    evidence_ids=_evidence_ids(
                        questionnaire,
                        {
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
                        },
                    ),
                    completeness=_score_card([practical, grouped.get("role_actions"), grouped.get("result_validation"), grouped.get("discipline_bridge")]),
                )
            )

        motivation = grouped.get("interest_origin") or grouped.get("career_plan")
        if motivation:
            cards.append(
                StoryCard(
                    id="story_motivation_1",
                    title="申请动机与职业规划",
                    category="motivation",
                    situation=grouped.get("interest_origin", ""),
                    task="解释为什么现在申请该方向。",
                    action=grouped.get("why_program", ""),
                    result=grouped.get("career_plan", ""),
                    reflection=grouped.get("why_school", ""),
                    related_skills=["目标清晰度", "专业理解", "职业规划"],
                    target_program_relevance=["用于开头、Why Program、Career Plan"],
                    evidence_ids=_evidence_ids(
                        questionnaire,
                        {"interest_origin", "career_plan", "why_program", "why_school"},
                    ),
                    completeness=_score_card([motivation, grouped.get("career_plan")]),
                )
            )

        recommender = grouped.get("relationship") or grouped.get("impression_examples")
        if recommender:
            cards.append(
                StoryCard(
                    id="story_recommender_1",
                    title="推荐信可用事件",
                    category="recommender",
                    situation=grouped.get("relationship", ""),
                    task=grouped.get("course_or_project", ""),
                    action=grouped.get("impression_examples", ""),
                    result=grouped.get("other_observations", ""),
                    related_skills=["课堂表现", "协作", "推荐人观察"],
                    target_program_relevance=["用于推荐信素材整理"],
                    evidence_ids=_evidence_ids(
                        questionnaire,
                        {"relationship", "course_or_project", "impression_examples", "other_observations"},
                    ),
                    completeness=_score_card([recommender, grouped.get("impression_examples")]),
                )
            )

        return cards


def _answers_by_id(questionnaire: QuestionnaireResponse) -> dict[str, str]:
    output: dict[str, str] = {}
    for answer in (
        questionnaire.profile_answers
        + questionnaire.statement_answers
        + questionnaire.recommender_answers
    ):
        if answer.value is None:
            continue
        output[answer.field_id] = "\n".join(answer.value) if isinstance(answer.value, list) else str(answer.value)
    return output


def _evidence_ids(questionnaire: QuestionnaireResponse, field_ids: set[str]) -> list[str]:
    ids: list[str] = []
    for answer in (
        questionnaire.profile_answers
        + questionnaire.statement_answers
        + questionnaire.recommender_answers
    ):
        if answer.field_id in field_ids:
            ids.extend(answer.evidence_ids)
            ids.append(f"questionnaire:{answer.field_id}")
    return sorted(set(ids))


def _score_card(values: list[str | None]) -> int:
    present = sum(1 for value in values if value and len(value.strip()) >= 12)
    return min(100, 35 + present * 30)
