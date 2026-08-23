from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from harbor_agent.app import app
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.services.deterministic_profile import normalize_profile
from harbor_agent.services.deterministic_timeline import build_timeline_tasks
from harbor_agent.services.writing_composer import STYLE_GUIDE, WritingComposer
from harbor_agent.services.data_refresh import _extract_field_candidates
from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.models import ApplicantProfileInput, FieldEvidenceRecord, FieldVerificationStatus, ProgramMatch, SourceScope, StoryCard
from harbor_agent.services.evidence_graph import build_field_evidence_records
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.program_urls import has_application_entry, has_program_detail_page, is_generic_program_url


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
    assert {"reach", "target", "safer", "candidate"} & {item.tier for item in result.focus_list}
    assert all(item.tier != "insufficient_info" for item in result.focus_list)


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
    assert any(task.date_basis == "学生准备动作" for task in application.timeline)
    assert not any(
        task.date_basis == "官方截止倒推" and task.official_deadline != "NOT_PUBLISHED"
        for task in application.timeline
    )
    allowed_statuses = {"未开始", "准备中", "待上传", "已提交", "需复核"}
    legacy_statuses = {"待办", "进行中", "已完成", "等待官方发布", "需人工复核"}
    assert {task.status for task in application.timeline} <= allowed_statuses
    assert not ({task.status for task in application.timeline} & legacy_statuses)


def test_timeline_uses_every_student_selected_program() -> None:
    programs = [program for program in load_programs() if has_application_entry(program)][:6]
    assert len(programs) == 6
    matches = [
        ProgramMatch(
            program=program,
            tier="target",
            fit_score=72,
            hard_rule_passed=True,
            reasons=["student selected this program"],
            risks=[],
            actions=[],
            rule_checks=[],
        )
        for program in programs
    ]

    timeline = build_timeline_tasks(matches, today=date(2026, 7, 5))
    task_program_ids = {program_id for task in timeline for program_id in task.linked_program_ids}

    assert {program.id for program in programs} <= task_program_ids
    assert all(program.name_zh or program.name for program in programs)


def test_review_agent_reports_field_level_timeline_blockers() -> None:
    payload = _sample()
    orchestrator = WorkflowOrchestrator(MockLLMProvider())
    application = orchestrator.run_application_plan_stage(payload, ["cuhk-msc-in-computer-science-2027"])

    assert application.review["passed"] is False
    assert "cuhk-msc-in-computer-science-2027" in application.review["programs_requiring_data_review"]
    blockers = application.review["timeline_blockers"].get("cuhk-msc-in-computer-science-2027", [])
    previous_fields = application.review["previous_cycle_reference_fields"].get("cuhk-msc-in-computer-science-2027", [])
    assert set(blockers) == {
        "official_program_url",
        "deadline",
        "application_url",
        "language_requirement",
        "materials",
        "tuition_hkd",
    }
    assert previous_fields == []
    assert application.review["programs_with_missing_or_blocked_fields"] == ["cuhk-msc-in-computer-science-2027"]
    assert "cuhk-msc-in-computer-science-2027" in application.review["programs_requiring_current_cycle_review"]
    assert application.review["required_timeline_fields"] == [
        "official_program_url",
        "deadline",
        "application_url",
        "language_requirement",
        "materials",
        "tuition_hkd",
    ]
    assert not any(
        task.task_type == "submission"
        and task.date_basis == "官方截止倒推"
        and task.official_deadline != "NOT_PUBLISHED"
        for task in application.timeline
    )
    assert any(
        task.task_type == "source_review"
        and "deadline" in task.materials
        and "cuhk-msc-in-computer-science-2027" in task.linked_program_ids
        for task in application.timeline
    )

def test_previous_cycle_evidence_is_visible_in_plan_and_timeline_without_internal_source_names() -> None:
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
    assert "GradWindow" not in cuhk.source_warning
    assert "上一申请季官网窗口" in cuhk.source_warning

    application = orchestrator.run_application_plan_stage(payload, ["cuhk-msc-in-computer-science-2027"])
    reference_tasks = [
        task for task in application.timeline
        if task.date_basis == "上一申请季参考"
        and "cuhk-msc-in-computer-science-2027" in task.linked_program_ids
    ]
    assert reference_tasks
    assert any(task.previous_cycle_reference for task in reference_tasks)
    assert not any("GradWindow" in (task.basis or "") for task in reference_tasks)
    assert any("上一申请季" in (task.basis or "") and "倒推" in (task.basis or "") for task in reference_tasks)
    expected_rounds = {
        "\u5f00\u653e\u7a97\u53e3\u76d1\u63a7",
        "\u5f53\u524d\u5b63\u5f85\u53d1\u5e03",
        "\u6587\u4e66\u9898\u76ee\u6838\u9a8c",
        "\u6750\u6599\u4e0a\u4f20\u81ea\u67e5",
    }
    assert expected_rounds <= {task.program_round for task in reference_tasks}
    assert all(task.due_date.year >= 2026 for task in reference_tasks)
    assert all(task.round_deadline == "NOT_PUBLISHED" for task in reference_tasks)
    assert all(task.application_url for task in reference_tasks)
    required_uploads = {"transcript", "degree_certificate", "language_score", "recommendation", "cv", "personal_statement"}
    assert any(required_uploads <= set(task.materials) for task in reference_tasks)


def test_previous_cycle_fields_are_reference_ready_not_formal_ready() -> None:
    from harbor_agent.services.formal_gate import program_field_gate

    program = next(item for item in load_programs() if item.id == "cuhk-msc-in-computer-science-2027")
    gate = program_field_gate(program)

    assert gate["production_ready"] is False
    assert gate["reference_ready"] is False
    assert set(gate["missing_or_blocked_fields"]) == {
        "official_program_url",
        "deadline",
        "application_url",
        "language_requirement",
        "materials",
        "tuition_hkd",
    }
    assert gate["previous_cycle_fields"] == []



def test_published_current_fields_drive_formal_timeline() -> None:
    from harbor_agent.services.program_store import upsert_field_evidence_records
    from harbor_agent.services.formal_gate import accepted_deadline, accepted_url, program_field_gate

    program = next(item for item in load_programs() if item.id == "cuhk-msc-in-computer-science-2027")
    current_deadline = date(2027, 3, 15)
    current_application_url = "https://apply.example.edu/cuhk-cs-2027"
    verified_at = datetime(2026, 7, 7, tzinfo=UTC)

    def record(field_name: str, value: str, source_type: str = "official_program_page") -> FieldEvidenceRecord:
        source_scope = (
            SourceScope.application_portal
            if source_type == "official_application_system"
            else SourceScope.programme_detail
        )
        return FieldEvidenceRecord(
            program_id=program.id,
            field_name=field_name,
            value=value,
            cycle="2027-fall",
            source_url="https://www.cuhk.edu.hk/programmes/current/cs",
            source_type=source_type,
            extracted_at=verified_at,
            verified_at=verified_at,
            page_hash="sha256:current-" + field_name,
            confidence="high",
            source_priority=1 if source_type == "official_application_system" else 2,
            status=FieldVerificationStatus.official_verified_current,
            review_required=False,
            reviewer_id="qa_reviewer",
            evidence_snippet=f"Verified current field: {field_name}",
            snapshot_url="data/source_snapshots/current/cuhk-cs.html",
            source_scope=source_scope,
            binding_status="matched",
            binding_score=97,
            review_decision_id=f"decision-{field_name}",
            execution_ref=None,
        )

    published_records = [
        record("official_program_url", "https://www.cuhk.edu.hk/programmes/current/cs"),
        record("deadline", current_deadline.isoformat()),
        record("application_url", current_application_url, "official_application_system"),
        record("language_requirement", "IELTS 6.5; TOEFL 79"),
        record("materials", "transcript, recommendation, CV, personal statement"),
        record("tuition_hkd", "HKD 180000"),
    ]
    # Formal gates read the canonical SQLite evidence store.  Keeping the
    # fixture here (instead of monkeypatching the legacy evidence graph)
    # exercises the same publish -> resolve path used in production.
    assert upsert_field_evidence_records(published_records) == len(published_records)

    gate = program_field_gate(program)
    assert gate["production_ready"] is True
    assert gate["reference_ready"] is False
    assert gate["missing_or_blocked_fields"] == []
    assert accepted_deadline(program, include_previous=False) == current_deadline
    assert accepted_url(program, "application_url", include_previous=False) == current_application_url

    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=78,
        hard_rule_passed=True,
        reasons=["student selected this program"],
        risks=[],
        actions=[],
        rule_checks=[],
    )
    timeline = build_timeline_tasks([match], today=date(2026, 7, 7))

    official_tasks = [
        task for task in timeline
        if task.linked_program_ids == [program.id]
        and task.date_basis == "\u5b98\u65b9\u622a\u6b62\u5012\u63a8"
    ]
    assert official_tasks
    assert all(task.official_deadline == current_deadline for task in official_tasks)
    assert any(task.task_type == "submission" and task.application_url == current_application_url for task in official_tasks)
    assert not any(task.program_round == "\u5f53\u524d\u5b63\u5f85\u53d1\u5e03" for task in official_tasks)



def test_persisted_review_publish_is_visible_to_student_catalog() -> None:
    from harbor_agent.services import review_gate
    from harbor_agent.services.program_store import load_field_evidence_records, upsert_field_evidence_records

    program_id = "hku-master-of-science-in-computer-science-2027"
    verified_at = datetime(2026, 7, 7, tzinfo=UTC)
    candidate = FieldEvidenceRecord(
        program_id=program_id,
        field_name="deadline",
        value="2027-03-20",
        cycle="2027-fall",
        source_url="https://www.hku.hk/current/cs",
        source_type="official_program_page",
        extracted_at=verified_at,
        page_hash="sha256:api-visible-deadline",
        confidence="high",
        source_priority=2,
        status=FieldVerificationStatus.official_previous_cycle,
        review_required=True,
        evidence_snippet="Application deadline: 2027-03-20.",
        snapshot_url="data/source_snapshots/current/hku-cs.html",
        source_scope=SourceScope.programme_detail,
        page_title="Master of Science in Computer Science",
        final_url="https://www.hku.hk/current/cs",
        binding_status="matched",
        binding_score=92,
        execution_ref=None,
    )
    assert upsert_field_evidence_records([candidate]) == 1

    client = TestClient(app)
    queue_response = client.get(f"/api/admin/review-queue?program_id={program_id}&limit=10")
    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert queue["publishable_count"] == 1
    review_id = queue["items"][0]["review_id"]

    publish_response = client.post(
        "/api/admin/review-queue/publish",
        json={
            "review_id": review_id,
            "decision": "approve",
            "reviewer_id": "qa_reviewer",
            "reviewer_note": "checked original source",
            "persist": True,
        },
    )
    assert publish_response.status_code == 200
    published = publish_response.json()
    assert published["ok"] is True
    assert published["published_record"]["status"] == "OFFICIAL_VERIFIED_CURRENT"
    persisted = load_field_evidence_records([program_id])
    assert any(
        record.field_name == "deadline"
        and record.status == FieldVerificationStatus.official_verified_current
        and record.review_required is False
        for record in persisted
    )

    trust_response = client.get(f"/api/programs/{program_id}/trust")
    assert trust_response.status_code == 200
    trust = trust_response.json()
    by_field = {record["field_name"]: record for record in trust["field_records"]}
    assert by_field["deadline"]["status"] == "OFFICIAL_VERIFIED_CURRENT"
    assert by_field["deadline"]["value"] == "2027-03-20"
    assert "deadline" in trust["official_current_fields"]

    catalog_response = client.get("/api/programs?limit=1000")
    assert catalog_response.status_code == 200
    catalog_program = next(item for item in catalog_response.json() if item["id"] == program_id)
    assert "deadline" in catalog_program["trust_detail"]["official_current_fields"]
    catalog_deadline = next(record for record in catalog_program["trust_detail"]["field_records"] if record["field_name"] == "deadline")
    assert catalog_deadline["value"] == "2027-03-20"

def test_field_status_can_vary_independently() -> None:
    program = next(item for item in load_programs() if item.id == "cityu-ma-communication-and-new-media-2027")
    records = [record for record in build_field_evidence_records([program]) if record.program_id == program.id]
    by_field = {record.field_name: record for record in records}

    assert by_field["deadline"].status == FieldVerificationStatus.model_inferred
    assert by_field["tuition_hkd"].status == FieldVerificationStatus.model_inferred
    assert by_field["deadline"].field_name != by_field["tuition_hkd"].field_name



def test_generic_school_urls_are_not_treated_as_program_detail_pages() -> None:
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-engineering-2027")

    assert is_generic_program_url("https://admissions.hku.hk/tpg/programme-list") is True
    assert has_program_detail_page(program) is True
    assert has_application_entry(program) is True
    assert str(program.official_program_url) != str(program.application_url)
    assert "programme-details?programme=master-of-science-in-engineering-engg" in str(program.official_program_url)
    assert "portal.hku.hk" in str(program.application_url)

    records = [record for record in build_field_evidence_records([program]) if record.program_id == program.id]
    by_field = {record.field_name: record for record in records}
    assert by_field["official_program_url"].status.value in {"OFFICIAL_PREVIOUS_CYCLE", "MODEL_INFERRED", "NOT_PUBLISHED"}
    assert by_field["official_program_url"].review_required is True
    assert by_field["official_program_url"].source_url

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
    old_story_label = "故事" + "访" + "谈"
    old_question_label = "追" + "问"
    old_generate_label = "生成" + old_question_label
    for blocked in ["birth_date", "passport_status", "family_address", "phone", "email", old_story_label, old_generate_label, old_question_label]:
        assert blocked not in dumped_schema

    response = client.post(
        "/api/workflows/writing-interview",
        json={
            "profile": payload,
            "selected_program_ids": ["hku-master-of-science-in-computer-science-2027"],
            "document_type": "PS",
        },
    )
    assert response.status_code == 200
    dumped_questions = json.dumps(response.json(), ensure_ascii=False).lower()
    for blocked in ["passport", "family address", "birth", "护照", "家庭住址", "出生日期", old_generate_label, old_question_label]:
        assert blocked not in dumped_questions


class UnsafeWritingLLM:
    name = "unsafe-live-model"
    provider = "test"

    def complete_json(self, system: str, user: str, schema_hint: dict[str, object]) -> dict[str, object]:
        return {
            "outline": ["motivation", "academic preparation", "why program"],
            "draft_zh": "\u8be5\u9879\u76ee\u7531\u9648\u6559\u6388\u4eb2\u81ea\u6307\u5bfc\u91cf\u5316\u91d1\u878d\u8bfe\u7a0b\uff0c\u5c31\u4e1a\u7387 98%\uff0c\u5f55\u53d6\u6982\u7387\u5f88\u9ad8\u3002\u6211\u7684\u7559\u5b58\u5206\u6790\u770b\u677f\u7ecf\u5386\u53ef\u4ee5\u4f5c\u4e3a\u7d20\u6750\u3002",
            "draft_en": "Professor Ada Chen teaches the Advanced AI Systems course in this programme. The programme reports a 98% employment rate and a high admission chance. My retention dashboard story remains the student-owned evidence.",
            "school_customization": [
                "Professor Ada Chen can supervise the student's AI plan.",
                "Advanced AI Systems course and 98% employment rate are available.",
            ],
            "prompt_requirements": ["No official prompt pasted yet."],
            "risk_controls": [],
            "material_gaps": [],
            "review_flags": [],
        }


def test_writing_style_rules_are_style_only_and_fact_bound() -> None:
    guide = " ".join(STYLE_GUIDE)

    assert "\u53ea\u62bd\u8c61" in guide
    assert "\u4e0d\u5f97\u590d\u5236" in guide
    assert "\u4e2a\u4eba\u4e8b\u5b9e" in guide
    assert "Why Program" in guide
    assert "\u9879\u76ee\u5b98\u7f51" in guide
    assert "\u4e0d\u540c\u6587\u4e66\u7c7b\u578b\u4e0d\u5f97\u4e92\u76f8\u6df7\u7528\u7ed3\u6784" in guide
    assert "\u63a8\u8350\u4fe1\u8349\u7a3f\u53ea\u5199\u63a8\u8350\u4eba\u53ef\u89c2\u5bdf" in guide


def test_writing_agent_respects_document_type_boundaries() -> None:
    payload = _sample()
    profile = normalize_profile(payload)
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=78,
        hard_rule_passed=True,
        reasons=[],
        risks=[],
        actions=[],
        rule_checks=[],
    )
    agent = WritingComposer(MockLLMProvider())

    cv_draft = agent.run_from_story_cards(profile, [match], [], document_type="CV")
    reference_draft = agent.run_from_story_cards(profile, [match], [], document_type="REFERENCE_PACKAGE")

    assert cv_draft.document_type == "CV"
    assert "CV Draft" in cv_draft.draft_en
    assert cv_draft.cv_bullets
    assert "Dear Members of the Admissions Committee" not in cv_draft.draft_en
    assert reference_draft.document_type == "REFERENCE_PACKAGE"
    assert "Dear Members of the Admissions Committee" in reference_draft.draft_en
    assert reference_draft.reference_package
    assert any("recommender" in item.lower() or "\u63a8\u8350\u4eba" in item for item in reference_draft.risk_controls + reference_draft.reference_package)


def test_local_writing_keeps_chinese_facts_without_fake_english_expansion() -> None:
    payload = _sample()
    payload.career_goal = "希望进入跨境科技公司做产品数据分析。"
    profile = normalize_profile(payload)
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=78,
        hard_rule_passed=True,
        reasons=[],
        risks=[],
        actions=[],
        rule_checks=[],
    )

    story = StoryCard(
        id="story-cn",
        title="数据质量实习",
        category="internship",
        situation="团队需要定位用户流失信号。",
        task="核对埋点口径并重建分析数据集。",
        action="使用 SQL 建立字段字典和异常检查。",
        result="重复计算误差从 12% 降到 2%。",
        reflection="数据质量和审计记录与模型同样重要。",
        evidence_ids=["questionnaire:practice"],
        completeness=100,
    )
    draft = WritingComposer(MockLLMProvider()).run_from_story_cards(profile, [match], [story], document_type="PS")

    assert "[English revision required" in draft.draft_en
    assert "Revision-ready expansion notes" not in draft.draft_en
    assert "希望希望" not in draft.draft_zh
    assert "。。" not in draft.draft_zh


def test_explicitly_selected_risky_program_is_not_silently_dropped() -> None:
    program = next(item for item in load_programs() if item.id == "smu-master-of-it-in-business-2027")
    selected = ProgramMatch(
        program=program,
        tier="not_recommended",
        fit_score=45,
        hard_rule_passed=False,
        reasons=["student explicitly selected this programme"],
        risks=["budget exceeds the stated limit"],
        actions=["confirm funding before applying"],
        rule_checks=[],
    )

    timeline = build_timeline_tasks([selected], today=date(2026, 7, 15))

    assert timeline
    assert any(program.id in task.linked_program_ids for task in timeline)


def test_unverified_catalog_deadline_is_not_accepted_as_previous_cycle_evidence() -> None:
    from harbor_agent.services.formal_gate import accepted_deadline

    program = next(item for item in load_programs() if item.id == "smu-master-of-it-in-business-2027")
    assert program.deadline != "NOT_PUBLISHED"

    assert accepted_deadline(program, include_previous=True) is None


def test_writing_agent_removes_unsupported_program_claims_from_live_model_output() -> None:
    payload = _sample()
    profile = normalize_profile(payload)
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    match = ProgramMatch(
        program=program,
        tier="target",
        fit_score=78,
        hard_rule_passed=True,
        reasons=["profile aligns with computing direction"],
        risks=[],
        actions=[],
        rule_checks=[],
    )

    draft = WritingComposer(UnsafeWritingLLM()).run_from_story_cards(profile, [match], [], document_type="PS")
    checked_text = "\n".join([draft.draft_zh, draft.draft_en, *draft.school_customization])

    for blocked in ["Professor Ada", "Advanced AI Systems", "98% employment", "admission chance", "\u9648\u6559\u6388"]:
        assert blocked not in checked_text
    assert "retention dashboard" in draft.draft_en
    assert any("\u5df2\u79fb\u9664" in flag for flag in draft.review_flags)
    assert any("\u5b66\u6821\u5b9a\u5236\u53e5\u8bc1\u636e\u6765\u6e90" in item for item in draft.school_customization)

    rubric = WritingComposer(MockLLMProvider()).review_rubric(draft, [])
    # The unsafe text was stripped, but a direct Composer preview has not gone
    # through WritingAgent + Critic and has no current DecisionFacts.  It must
    # therefore stay a non-formal artifact instead of returning a clean-looking
    # export recommendation.
    assert rubric.formal_use_ready is False
    assert rubric.export_recommendation == "不建议导出"
    assert rubric.formal_blockers

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
    assert 4 <= len(result.application_mix) <= 10
    assert all(item.match_category in {"core", "related"} for item in result.application_mix)
    names = " ".join(item.program.name.lower() for item in result.application_mix)
    assert not any(item.match_category == "general" for item in result.application_mix)
    blocked_terms = ["marketing", "economics", "applied accounting", "communication management"]
    assert not any(term in names for term in blocked_terms)
    assert all(item.formal_recommendation is False for item in result.application_mix)
