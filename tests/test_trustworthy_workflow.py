from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from harbor_agent.app import app
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.agents.data_refresh import _extract_field_candidates
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.services.evidence_graph import build_field_evidence_records
from harbor_agent.services.data_loader import load_programs


def _sample() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )


def test_extracted_programs_stay_candidate_only() -> None:
    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(_sample())

    assert len(result.focus_list) <= 15
    assert len(result.application_mix) <= 10
    assert result.intent_profile
    assert result.candidate_pool
    assert all(item.formal_recommendation is False for item in result.focus_list)
    assert all(item.tier == "insufficient_info" for item in result.focus_list)


def test_ai_intent_prioritizes_core_tech_programs() -> None:
    payload = _sample()
    payload.discipline_interests = ["artificial intelligence"]
    payload.raw_interest_text = "人工智能 machine learning deep learning AI computer science data science"
    payload.education.major = "Computer Science"

    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(payload)

    assert result.intent_profile
    assert result.intent_profile.strict_intent is True
    assert result.core_candidates
    assert result.related_candidates
    assert result.blocked_candidates
    assert all(item.match_category == "core" for item in result.core_candidates[:10])

    core_text = " ".join(
        f"{item.program.id} {item.program.name} {item.program.name_zh or ''}".lower()
        for item in result.core_candidates[:12]
    )
    for blocked_word in ["economics", "finance", "management", "marketing", "accounting", "english", "education"]:
        assert blocked_word not in core_text
    assert any(
        keyword in core_text
        for keyword in ["artificial", "computer", "computing", "data science", "machine learning", "big data"]
    )

    related_text = " ".join(item.program.name.lower() for item in result.related_candidates[:12])
    assert "business analytics" in related_text or "statistics" in related_text


def test_consultant_plan_has_reasonable_bands_for_211_ai_profile() -> None:
    payload = _sample()
    payload.education.school_tier = "211"
    payload.education.gpa = 86
    payload.education.major = "人工智能"
    payload.language.test = "IELTS"
    payload.language.overall = 7
    payload.language.writing = 6.5
    payload.discipline_interests = ["computer_science", "artificial_intelligence", "data_science"]
    payload.raw_interest_text = "计算机 人工智能 数据科学 CS AI machine learning"

    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(payload)
    plan = result.consultant_plan

    assert plan is not None
    assert plan.items
    assert "211" in plan.profile_summary
    assert any(item.band == "冲刺" and item.institution in {"香港大学", "香港科技大学", "香港中文大学", "新加坡国立大学", "南洋理工大学"} for item in plan.items)
    assert any(item.band == "主申" and item.institution in {"香港城市大学", "香港理工大学", "新加坡管理大学"} for item in plan.items)
    assert not any(item.band == "冲刺" and item.institution in {"香港浸会大学", "岭南大学"} for item in plan.items)
    assert all(item.why_this_band and item.main_risk and item.next_action for item in plan.items)
    assert "学校官网" in plan.data_disclaimer


def test_cs_ai_data_interest_is_not_rewritten_as_business() -> None:
    payload = _sample()
    payload.education.school = "西南财经大学"
    payload.education.school_tier = "211"
    payload.education.gpa = 86
    payload.education.major = "人工智能"
    payload.language.test = "IELTS"
    payload.language.overall = 7
    payload.language.writing = 6
    payload.discipline_interests = ["computer_science", "artificial_intelligence", "data_science"]
    payload.raw_interest_text = "计算机 人工智能 数据科学 CS AI machine learning"
    payload.career_goal = "希望进入跨境科技公司做产品数据分析。"

    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(payload)

    assert result.intent_profile
    assert result.intent_profile.strict_intent is True
    assert "business_analytics" not in result.intent_profile.primary_intents
    assert {"computer_science", "artificial_intelligence", "data_science"} & set(result.intent_profile.primary_intents)

    plan = result.consultant_plan
    assert plan is not None
    assert "目标方向：人工智能 / 计算机 / 数据科学" in plan.profile_summary
    assert not any(item.band == "冲刺" and item.institution in {"香港浸会大学", "岭南大学"} for item in plan.items)


def test_unverified_deadline_generates_preparation_tasks_only() -> None:
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    plan = orchestrator.run_program_plan_stage(_sample())
    selected_ids = [item.program.id for item in plan.focus_list[:2]]
    application = orchestrator.run_application_plan_stage(_sample(), selected_ids)

    assert application.timeline
    assert any(task.date_basis == "内部准备建议" for task in application.timeline)
    assert not any(
        task.date_basis == "官方截止倒推" and task.official_deadline != "NOT_PUBLISHED"
        for task in application.timeline
    )


def test_gradwindow_previous_cycle_evidence_is_visible_in_plan_and_timeline() -> None:
    payload = _sample()
    payload.education.school_tier = "211"
    payload.education.gpa = 86
    payload.education.major = "人工智能"
    payload.language.test = "IELTS"
    payload.language.overall = 7
    payload.discipline_interests = ["computer_science", "artificial_intelligence", "data_science"]
    payload.raw_interest_text = "计算机 人工智能 数据科学 CS AI machine learning"

    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    plan = orchestrator.run_program_plan_stage(payload)

    cuhk = next(item for item in plan.recommendations if item.program.id == "cuhk-msc-in-computer-science-2027")
    assert "GradWindow" in cuhk.source_warning
    assert "上一申请季官网窗口" in cuhk.source_warning

    application = orchestrator.run_application_plan_stage(payload, ["cuhk-msc-in-computer-science-2027"])
    reference_tasks = [
        task for task in application.timeline
        if task.date_basis == "上一申请季参考"
        and "cuhk-msc-in-computer-science-2027" in task.linked_program_ids
    ]
    assert reference_tasks
    assert any(task.previous_cycle_reference for task in reference_tasks)
    assert any("GradWindow" in (task.basis or "") for task in reference_tasks)


def test_field_status_can_vary_independently() -> None:
    program = load_programs()[0]
    records = [record for record in build_field_evidence_records([program]) if record.program_id == program.id]
    by_field = {record.field_name: record for record in records}

    assert by_field["deadline"].status.value in {"OFFICIAL_PREVIOUS_CYCLE", "NOT_PUBLISHED"}
    assert by_field["tuition_hkd"].status.value in {"OFFICIAL_PREVIOUS_CYCLE", "NOT_PUBLISHED"}
    assert by_field["deadline"].field_name != by_field["tuition_hkd"].field_name


def test_field_extraction_candidates_return_reviewable_json() -> None:
    sample = """
    Application deadline: 2027-01-31.
    Tuition fee HKD 360,000.
    Applicants should submit official transcript, CV, personal statement and recommendation letter.
    English language requirement: IELTS 6.5 or TOEFL 90.
    Apply through the online application system.
    """

    candidates = _extract_field_candidates(sample)
    by_field = {candidate.field_name: candidate for candidate in candidates}

    assert by_field["deadline"].value == "2027-01-31"
    assert by_field["tuition_hkd"].value == "HKD 360,000"
    assert by_field["language_requirement"].review_required is True
    assert by_field["materials"].evidence_snippet
    assert by_field["application_url"].confidence == "low"


def test_writing_interview_and_schema_do_not_collect_sensitive_fields() -> None:
    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    schema = client.get("/api/questionnaire-schema").json()
    dumped_schema = json.dumps(schema, ensure_ascii=False).lower()
    for blocked in ["birth_date", "passport_status", "family_address", "phone", "email"]:
        assert blocked not in dumped_schema

    response = client.post("/api/workflows/writing-interview", json={"profile": payload, "document_type": "PS"})
    assert response.status_code == 200
    dumped_questions = json.dumps(response.json(), ensure_ascii=False).lower()
    for blocked in ["passport", "family address", "birth", "护照", "家庭住址", "出生日期"]:
        assert blocked not in dumped_questions

def test_985_ielts_65_cs_plan_keeps_core_tech_mix() -> None:
    payload = _sample()
    payload.education.school = "华南理工大学"
    payload.education.school_tier = "985"
    payload.education.gpa = 85
    payload.education.gpa_scale = "100"
    payload.education.ranking_percentile = 20
    payload.education.major = "计算机科学与技术"
    payload.language.test = "IELTS"
    payload.language.overall = 6.5
    payload.language.writing = 6.0
    payload.language.speaking = 6.0
    payload.language.reading = 6.5
    payload.language.listening = 6.5
    payload.discipline_interests = ["computer_science", "artificial_intelligence", "data_science"]
    payload.raw_interest_text = "CS AI machine learning 数据科学 数据结构 算法 数据库 机器学习"

    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(payload)

    assert result.intent_profile
    assert result.intent_profile.strict_intent is True
    assert result.consultant_plan is not None
    assert result.consultant_plan.band_counts["冲刺"] <= 4
    assert len(result.application_mix) == 10
    assert all(item.match_category == "core" for item in result.application_mix)
    assert not any("商业分析" in (item.program.name_zh or "") for item in result.application_mix[:8])
    assert all(item.formal_recommendation is False for item in result.application_mix)


def test_regular_business_analytics_plan_is_conservative_and_on_direction() -> None:
    payload = _sample()
    payload.education.school = "广东工业大学"
    payload.education.school_tier = "regular"
    payload.education.gpa = 82
    payload.education.gpa_scale = "100"
    payload.education.ranking_percentile = 25
    payload.education.major = "金融工程"
    payload.language.test = "IELTS"
    payload.language.overall = 6.5
    payload.language.writing = 6.0
    payload.language.speaking = 6.0
    payload.language.reading = 6.5
    payload.language.listening = 6.5
    payload.discipline_interests = ["business analytics", "data_science"]
    payload.raw_interest_text = "business analytics data analytics statistics SQL Python"
    payload.budget_hkd = 330000

    result = WorkflowOrchestrator(MockLLMProvider()).run_program_plan_stage(payload)

    assert result.intent_profile
    assert result.intent_profile.strict_intent is False
    assert "business_analytics" in result.intent_profile.primary_intents
    assert result.consultant_plan is not None
    assert result.consultant_plan.band_counts["冲刺"] == 0
    assert 6 <= len(result.application_mix) <= 10
    assert all(item.match_category == "core" for item in result.application_mix)
    names = " ".join(item.program.name.lower() for item in result.application_mix)
    assert "business analytics" in names or "business and data analytics" in names
    blocked_terms = ["marketing", "economics", "applied accounting", "communication management"]
    assert not any(term in names for term in blocked_terms)
    assert all(item.formal_recommendation is False for item in result.application_mix)
