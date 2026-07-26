from __future__ import annotations

import re
import json
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from harbor_agent.app import app
from harbor_agent.services import evidence_graph
from harbor_agent.services.data_loader import load_programs


def test_api_assessment_endpoint() -> None:
    client = TestClient(app)
    payload = Path("examples/sample_profile.json").read_text(encoding="utf-8")

    response = client.post(
        "/api/workflows/assessment",
        content=payload,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["workflow_id"].startswith("wf_")
    assert len(data["trace"]) == 8
    assert data["evidence"]["recommended_uploads"]


def test_workflow_input_contracts_reject_unsupported_or_unselected_requests() -> None:
    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    empty_selection = client.post(
        "/api/workflows/application-plan",
        json={"profile": payload, "selected_program_ids": []},
    )
    assert empty_selection.status_code == 422

    invalid_selection = client.post(
        "/api/workflows/application-plan",
        json={"profile": payload, "selected_program_ids": ["not-a-program"]},
    )
    assert invalid_selection.status_code == 422

    payload["target_cycle"] = "2032-fall"
    unsupported_cycle = client.post("/api/workflows/program-plan", json=payload)
    assert unsupported_cycle.status_code == 422
    assert "不支持申请季" in unsupported_cycle.json()["detail"]

    payload["target_cycle"] = "2027-fall"
    payload["target_degree"] = "research_master"
    unsupported_degree = client.post("/api/workflows/program-plan", json=payload)
    assert unsupported_degree.status_code == 422
    assert "尚未覆盖" in unsupported_degree.json()["detail"]


def test_student_source_refresh_is_official_only_and_scoped(monkeypatch) -> None:
    import importlib

    app_module = importlib.import_module("harbor_agent.app")
    captured: dict[str, object] = {}

    def fake_enqueue_catalog_refresh_plan(**kwargs):
        captured.update(kwargs)
        return [{"job_id": "job-test", "workflow_name": "catalog_refresh"}]

    monkeypatch.setattr(app_module, "enqueue_catalog_refresh_plan", fake_enqueue_catalog_refresh_plan)
    client = TestClient(app)
    response = client.post(
        "/api/catalog-refresh-plan",
        json={
            "selected_program_ids": ["hku-master-of-science-in-computer-science-2027"],
            "include_community": True,
            "max_programs": 48,
            "max_candidates_per_program": 20,
            "max_sources_per_program": 30,
        },
    )

    assert response.status_code == 200
    assert captured["include_community"] is False
    assert captured["max_programs"] == 1
    assert captured["max_candidates_per_program"] == 6
    assert captured["max_sources_per_program"] == 8



def test_program_catalog_returns_full_library_by_default() -> None:
    client = TestClient(app)
    programs = load_programs()

    response = client.get("/api/programs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(programs)
    assert len(data) >= 100

    limited = client.get("/api/programs?limit=1")
    assert limited.status_code == 200
    assert len(limited.json()) == 1


def test_llm_config_defaults_to_mock_and_requires_key_for_openai() -> None:
    client = TestClient(app)

    config = client.get("/api/admin/llm-config")
    assert config.status_code == 200
    assert config.json()["provider"] in {"mock", "openai", "deepseek", "compatible"}

    reset = client.post("/api/admin/llm-config", json={"provider": "mock"})
    assert reset.status_code == 200
    assert reset.json()["provider"] == "mock"

    missing_key = client.post("/api/admin/llm-config", json={"provider": "openai", "model": "gpt-4.1-mini"})
    assert missing_key.status_code == 400


def test_questionnaire_schema_and_stage_endpoints() -> None:
    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    schema_response = client.get("/api/questionnaire-schema")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["version"].startswith("questionnaire")
    section_titles = {section["title"] for section in schema["sections"]}
    for expected in {
        "PS：开篇动机",
        "PS：学术能力",
        "PS：核心课程",
        "PS：实践经历",
        "PS：职业规划",
        "PS：为什么该校该项目",
        "PS：补充信息",
        "PS：特殊题目",
        "推荐信：推荐人基本信息",
        "推荐信：推荐人关系",
        "推荐信：课程表现",
        "推荐信：presentation/小组活动/研究项目",
        "推荐信：具体印象",
        "推荐信：综合能力事件",
    }:
        assert expected in section_titles

    background = client.post("/api/workflows/background", json=payload)
    assert background.status_code == 200
    background_data = background.json()
    assert background_data["assessment"]["overall_level"]
    assert background_data["assessment"]["competitiveness_level"] in {"强", "中强", "中", "弱"}
    assert background_data["assessment"]["application_positioning"]
    assert background_data["assessment"]["hard_thresholds"]
    assert len(background_data["trace"]) == 3

    program_plan = client.post("/api/workflows/program-plan", json=payload)
    assert program_plan.status_code == 200
    program_data = program_plan.json()
    assert program_data["recommendations"]
    assert program_data["consultant_plan"]["items"]
    assert program_data["consultant_plan"]["data_disclaimer"]
    assert all("programme-list" not in str(item["program"].get("official_program_url") or "") for item in program_data["recommendations"])
    assert any(item["program"].get("official_program_url") is None for item in program_data["recommendations"])
    tiers = {item["tier"] for item in program_data["recommendations"]}
    assert {"reach", "target", "safe", "candidate", "not_recommended"} <= tiers
    assert "insufficient_info" not in tiers
    assert all(item["tier"] in {"reach", "target", "safe", "candidate", "not_recommended"} for item in program_data["recommendations"])

    first_match = program_data["recommendations"][0]
    assert first_match["score_breakdown"]
    assert set(first_match["score_breakdown"]) == {
        "academic",
        "language",
        "experience",
        "discipline_fit",
        "budget_fit",
        "data_trust",
    }
    assert first_match["formal_recommendation"] is False
    assert any("官网" in risk or "项目详情页" in risk for risk in first_match["risks"])

    selected_ids = [
        item["program"]["id"]
        for item in program_data["recommendations"]
        if item["tier"] != "not_recommended" and item["program"]["deadline"] != "NOT_PUBLISHED"
    ][:2]
    assert selected_ids

    application_plan = client.post(
        "/api/workflows/application-plan",
        json={"profile": payload, "selected_program_ids": selected_ids},
    )
    assert application_plan.status_code == 200
    application_data = application_plan.json()
    assert application_data["selected_programs"]
    assert application_data["timeline"]
    assert application_data["source_refresh"]["official_sources_checked"] >= 1
    assert application_data["source_refresh"]["program_findings"]
    assert application_data["source_refresh"]["field_evidence_records"]
    assert application_data["source_refresh"]["review_queue_size"] >= 1
    first_record = application_data["source_refresh"]["field_evidence_records"][0]
    assert first_record["cycle"] == payload["target_cycle"]
    assert first_record["review_required"] is True
    assert first_record["agent_chain"]
    assert application_data["source_refresh"]["parser_plan"]
    assert any(task.get("basis") for task in application_data["timeline"])
    assert any(task.get("source_url") for task in application_data["timeline"])
    assert any(task.get("task_type") == "source_review" for task in application_data["timeline"])
    assert any(task.get("dependencies") for task in application_data["timeline"])
    project_tasks = [task for task in application_data["timeline"] if task.get("program_name")]
    assert project_tasks
    assert any(task.get("program_round") for task in project_tasks)
    assert all("programme-list" not in str(task.get("application_url") or "") for task in project_tasks)
    assert all(task.get("submit_to") for task in project_tasks)
    project_submission_tasks = [task for task in project_tasks if task.get("task_type") == "submission"]
    assert project_submission_tasks
    assert all(task.get("application_url") for task in project_submission_tasks)
    assert all(task.get("materials") for task in project_submission_tasks)
    assert all(task.get("round_deadline") for task in project_submission_tasks)
    assert not any(str(task.get("due_date", "")).startswith("2028") for task in application_data["timeline"])

    writing_plan = client.post(
        "/api/workflows/writing-plan",
        json={
            "profile": payload,
            "selected_program_ids": selected_ids[:1],
            "document_type": "PS",
            "questionnaire": {
                "profile_answers": [
                    {"field_id": "core_courses", "value": "数据结构、数据库、统计学，均分表现稳定。", "evidence_ids": []},
                    {"field_id": "gpa_rank", "value": "84.5/100，专业前 18%。", "evidence_ids": []},
                ],
                "statement_answers": [
                    {"field_id": "opening_trigger", "value": "数据库课程项目让我开始关注数据产品如何影响业务决策。", "evidence_ids": []},
                    {
                        "field_id": "practice_problem",
                        "value": "在金融科技实习中，团队需要更快定位用户流失信号。",
                        "evidence_ids": [],
                    },
                    {"field_id": "practice_actions", "value": "我使用 SQL 和可视化工具搭建留存分析看板，拆分渠道和用户分层。", "evidence_ids": []},
                    {"field_id": "practice_result", "value": "看板减少周报整理时间，并支持团队识别关键流失节点。", "evidence_ids": []},
                    {"field_id": "career_plan", "value": "毕业后希望成为跨境科技公司的产品数据分析师。", "evidence_ids": []},
                    {"field_id": "why_program_binding", "value": "只绑定项目官网可确认的课程和培养目标。", "evidence_ids": []},
                ],
                "recommender_answers": [
                    {"field_id": "relationship", "value": "课程老师指导过数据库课程项目。", "evidence_ids": []}
                ],
            },
        },
    )
    assert writing_plan.status_code == 200
    writing_data = writing_plan.json()
    assert writing_data["story_cards"]
    assert writing_data["writing"]["outline"]
    assert writing_data["writing"]["draft_zh"]
    assert writing_data["writing"]["draft_en"]
    assert writing_data["writing"]["material_gaps"]
    assert writing_data["writing"]["paragraph_drafts"]
    assert writing_data["writing"]["fact_bindings"]
    assert writing_data["writing"]["version_id"]
    assert writing_data["writing"]["school_customization"]
    assert writing_data["writing"]["prompt_requirements"]
    assert writing_data["writing"]["cv_bullets"]
    assert writing_data["writing"]["reference_package"]
    assert writing_data["writing"]["risk_controls"]
    assert not re.search(r"[\u4e00-\u9fff]", writing_data["writing"]["draft_en"])
    assert "留存分析看板" in writing_data["writing"]["draft_zh"]
    for placeholder in ["解释为什么", "这里应写入", "Become a"]:
        assert placeholder not in writing_data["writing"]["draft_zh"]
    school_customization_text = " ".join(writing_data["writing"]["school_customization"])
    assert "学校定制句证据来源" in school_customization_text
    assert "http" in school_customization_text or "未找到项目详情页" in school_customization_text
    writing_payload_text = json.dumps(writing_data["writing"], ensure_ascii=False)
    assert "数据状态" not in writing_payload_text
    assert "Its data status" not in writing_payload_text
    for raw_status in ["VERIFIED", "PENDING_REVIEW", "MODEL_INFERRED", "OFFICIAL_VERIFIED_CURRENT", "OFFICIAL_PREVIOUS_CYCLE"]:
        assert raw_status not in writing_payload_text
    risk_control_text = " ".join(writing_data["writing"]["risk_controls"])
    for blocked_claim in ["课程", "教授", "就业数据", "录取概率"]:
        assert blocked_claim in risk_control_text




def test_admin_scenario_audit_endpoint_exposes_multiagent_self_audit() -> None:
    client = TestClient(app)

    response = client.get("/api/admin/scenario-audit")

    assert response.status_code == 200
    data = response.json()
    assert data["passed"] is True
    assert data["case_count"] >= 3
    assert data["failure_count"] == 0
    assert data["agent_chain"][-1] == "ScenarioAuditAgent"
    assert "ProgramDataAcquisitionAgent" in data["agent_chain"]
    assert "SourceCrawlQueueAgent" in data["agent_chain"]
    assert "ReviewAgent" in data["agent_chain"]

    first = data["cases"][0]
    assert first["targets"]
    assert first["trace_nodes"][-1] == "ScenarioAuditAgent"
    assert first["crawl_queue"]["official_job_count"] >= 1
    assert first["crawl_queue"]["community_job_count"] >= 1
    assert all(target["formal_recommendation"] is False for target in first["targets"])
    assert all(target["coverage_item_count"] >= 6 for target in first["targets"])
    assert all(target["review_pending_count"] >= 1 for target in first["targets"])


def test_writing_outline_does_not_auto_pick_program_when_student_has_not_selected() -> None:
    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    response = client.post(
        "/api/workflows/writing-outline",
        json={
            "profile": payload,
            "selected_program_ids": [],
            "document_type": "PS",
            "interview_answers": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]

def test_source_registry_and_data_refresh() -> None:
    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    registry_response = client.get("/api/source-registry")
    assert registry_response.status_code == 200
    registry = registry_response.json()
    assert registry["sources"]
    assert any(source["source_id"] == "collegeboard_bigfuture" for source in registry["sources"])
    assert any(source["trust_level"] == "official" for source in registry["sources"])

    evidence = client.get("/api/evidence-graph/summary")
    assert evidence.status_code == 200
    evidence_data = evidence.json()
    assert evidence_data["program_count"] >= 100
    assert evidence_data["field_record_count"] > evidence_data["program_count"]
    assert evidence_data["pending_review_field_count"] >= evidence_data["extracted_field_count"]
    assert "deadline" in evidence_data["field_breakdown"]
    assert "official_application_system" in evidence_data["official_priority"]
    assert evidence_data["sample_records"]
    assert evidence_data["sample_records"][0]["agent_chain"]

    program_plan = client.post("/api/workflows/program-plan", json=payload)
    assert program_plan.status_code == 200
    selected_ids = [
        item["program"]["id"]
        for item in program_plan.json()["recommendations"]
        if item["tier"] != "not_recommended"
    ][:2]

    refresh = client.post(
        "/api/workflows/data-refresh",
        json={"selected_program_ids": selected_ids, "dry_run": True, "max_sources": 12},
    )
    assert refresh.status_code == 200
    data = refresh.json()
    assert data["mode"] == "dry_run"
    assert data["official_sources_checked"] >= 1
    assert data["program_findings"]
    assert data["field_evidence_records"]
    assert data["extraction_results"]
    assert data["extraction_results"][0]["agent_chain"]
    assert data["extraction_results"][0]["unresolved_fields"]
    assert data["review_queue_size"] >= 1
    assert data["parser_plan"]
    assert data["human_review_required"] is True
    assert all(check["status"] == "SKIPPED_DRY_RUN" for check in data["source_checks"])
    assert all(check["robots_status"] == "SKIPPED_DRY_RUN" for check in data["source_checks"])
    assert all("robots_txt_url" in check for check in data["source_checks"])


def test_program_catalog_exposes_field_level_trust_detail(monkeypatch) -> None:
    monkeypatch.setattr(evidence_graph, "load_field_evidence_records", lambda _program_ids=None: [])
    monkeypatch.setattr(evidence_graph, "load_published_field_records", lambda: [])
    client = TestClient(app)

    response = client.get("/api/programs?limit=1")
    assert response.status_code == 200
    program = response.json()[0]
    trust = program["trust_detail"]

    assert trust["program_id"] == program["id"]
    assert trust["reviewer_gate_fields"]
    assert trust["production_ready"] is False
    assert trust["reference_ready"] is False
    assert trust["status_label"] == "\u7f3a\u5c11\u5173\u952e\u9879\u76ee\u5b57\u6bb5"
    assert "\u4e0d\u80fd\u751f\u6210\u6b63\u5f0f\u7533\u8bf7\u65f6\u95f4\u7ebf" in trust["source_warning"]
    assert trust["stale_or_reference_fields"] == []
    assert "deadline" in trust["fields_requiring_review"]
    assert {"official_program_url", "deadline", "tuition_hkd", "materials", "language_requirement", "application_url"} & {
        record["field_name"] for record in trust["field_records"]
    }
    assert all(record["agent_chain"] for record in trust["field_records"])

    detail = client.get(f"/api/programs/{program['id']}/trust")
    assert detail.status_code == 200
    assert detail.json()["field_records"] == trust["field_records"]


def test_program_data_package_exposes_official_and_community_acquisition_plan() -> None:
    client = TestClient(app)
    program_id = "hku-master-of-science-in-computer-science-2027"

    detail = client.get(f"/api/programs/{program_id}/data-package")
    assert detail.status_code == 200
    package = detail.json()

    assert package["program_id"] == program_id
    assert package["official_requirements"]
    assert package["coverage_items"]
    coverage_by_field = {item["field_name"]: item for item in package["coverage_items"]}
    assert {"deadline", "official_program_url", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"} <= set(coverage_by_field)
    assert all(item["required_source"] == "official" for item in package["coverage_items"])
    assert any(item["blocks_formal_use"] is True for item in package["coverage_items"])
    assert all(item["next_action"] for item in package["coverage_items"])
    assert package["content_sections"]
    assert package["timeline_fields"]
    assert package["community_experiences"]
    assert package["acquisition_plan"]
    assert package["human_review_required"] is True
    assert all(item["review_required"] is True for item in package["official_requirements"])
    assert any(plan["channel"] == "official_requirement" for plan in package["acquisition_plan"])
    assert any(plan["channel"] == "community_experience" for plan in package["acquisition_plan"])
    assert any(plan["source_id"] == "public_chinese_admission_forums" for plan in package["acquisition_plan"])
    assert all("社区经验" in item["use_boundary"] for item in package["community_experiences"])

    report = client.post(
        "/api/workflows/data-acquisition",
        json={"selected_program_ids": [program_id], "dry_run": True, "include_community": True},
    )
    assert report.status_code == 200
    data = report.json()
    assert data["mode"] == "dry_run"
    assert data["packages"][0]["program_id"] == program_id
    assert "OfficialCrawlerAgent" in data["agent_chain"]
    assert "CommunitySignalAgent" in data["agent_chain"]
    assert any("社区经验" in action for action in data["next_actions"])


def test_crawl_queue_separates_official_and_community_jobs() -> None:
    client = TestClient(app)
    program_id = "hku-master-of-science-in-computer-science-2027"

    response = client.post(
        "/api/admin/crawl-queue",
        json={
            "selected_program_ids": [program_id],
            "include_community": True,
            "max_sources_per_program": 8,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["job_count"] >= 2
    assert data["official_job_count"] >= 1
    assert data["community_job_count"] >= 1
    assert "SourceCrawlQueueAgent" in data["agent_chain"]
    assert any("review" in warning.lower() for warning in data["warnings"])

    official_jobs = [item for item in data["items"] if item["trust_level"] == "official"]
    community_jobs = [item for item in data["items"] if item["trust_level"] == "community"]
    assert official_jobs
    assert community_jobs
    assert all(item["snapshot_required"] is True for item in data["items"])
    assert all(item["human_review_required"] is True for item in data["items"])
    assert all(program_id in item["program_ids"] for item in official_jobs)
    assert any("OFFICIAL_VERIFIED_CURRENT" in item["publish_boundary"] for item in official_jobs)

    official_only = {"deadline", "official_program_url", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"}
    for item in community_jobs:
        assert not (official_only & set(item["allowed_fields"]))
        assert "reference-only" in item["publish_boundary"]
        assert item["parser"] == "community_signal_extraction"


def test_admin_catalog_auto_update_dry_run_discovers_reviewable_candidates() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/admin/catalog-auto-update",
        json={
            "selected_program_ids": [
                "hkbu-ma-communication-2027",
                "cityu-msc-electronic-information-engineering-2027",
            ],
            "dry_run": True,
            "max_programs": 4,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "dry_run"
    assert data["candidate_count"] >= 2
    assert data["persisted_candidate_count"] == 0
    assert data["review_queue_size"] == 0
    assert "CatalogAutoUpdateAgent" in data["agent_chain"]
    assert "HumanReviewGateAgent" in data["agent_chain"]
    assert all("taught-postgraduate-programmes" not in item["candidate_url"] for item in data["candidates"])
    assert all(item["evidence_record"]["field_name"] == "official_program_url" for item in data["candidates"])
    assert all(item["evidence_record"]["review_required"] is True for item in data["candidates"])
    conflicted = [item for item in data["candidates"] if item["status"] == "CONFLICTED"]
    assert conflicted
    assert all(item["publishable_after_review"] is False for item in conflicted)

def test_admin_catalog_auto_update_skips_programs_that_already_have_detail_pages() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/admin/catalog-auto-update",
        json={
            "selected_program_ids": [
                "hkbu-msc-business-management-2027",
                "hkbu-ma-communication-2027",
            ],
            "dry_run": True,
            "max_programs": 4,
        },
    )

    assert response.status_code == 200
    data = response.json()
    ids = {item["program_id"] for item in data["candidates"]}
    assert "hkbu-msc-business-management-2027" not in ids
    assert "hkbu-ma-communication-2027" in ids
    stale = next(item for item in data["candidates"] if item["program_id"] == "hkbu-ma-communication-2027")
    assert stale["status"] == "CONFLICTED"
    assert stale["publishable_after_review"] is False
    assert "404" in stale["reason"]

def test_review_queue_blocks_legacy_candidates_without_page_binding() -> None:
    client = TestClient(app)
    program_id = "hku-master-of-science-in-computer-science-2027"

    queue_response = client.get(f"/api/admin/review-queue?program_id={program_id}&limit=20")
    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert queue["pending_count"] >= 1
    assert queue["publishable_count"] == 0
    candidate = queue["items"][0]
    assert candidate["publishable"] is False
    assert "not publishable" in candidate["boundary"].lower()

    reject_response = client.post(
        "/api/admin/review-queue/publish",
        json={
            "review_id": candidate["review_id"],
            "decision": "reject",
            "reviewer_id": "qa_reviewer",
            "reviewer_note": "source did not match the current application cycle",
        },
    )
    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["ok"] is True
    assert rejected["item"]["status"] == "REJECTED"
    assert rejected["published_record"] is None

    approve_response = client.post(
        "/api/admin/review-queue/publish",
        json={
            "review_id": candidate["review_id"],
            "decision": "approve",
            "reviewer_id": "qa_reviewer",
            "reviewer_note": "checked the official public source in preview mode",
            "persist": False,
        },
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["ok"] is False
    assert approved["item"]["status"] == "REJECTED"
    assert approved["published_record"] is None




def test_admin_review_queue_bulk_preview_does_not_bypass_binding_gate() -> None:
    client = TestClient(app)
    program_id = "hku-master-of-science-in-computer-science-2027"

    queue_response = client.get(f"/api/admin/review-queue?program_id={program_id}&limit=20")
    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert queue["publishable_count"] == 0

    response = client.post(
        "/api/admin/review-queue/bulk-publish",
        json={
            "program_id": program_id,
            "limit": 3,
            "reviewer_id": "qa_reviewer",
            "reviewer_note": "checked official source evidence in preview mode",
            "persist": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["published_count"] == 0
    assert data["preview_count"] == 0
    assert data["queue_after"] is None
    assert data["queue_before"] == queue["pending_count"]
    assert data["responses"] == []

    after = client.get(f"/api/admin/review-queue?program_id={program_id}&limit=20").json()
    assert after["pending_count"] == queue["pending_count"]

def test_qs_master_applications_import_is_available_and_review_gated() -> None:
    client = TestClient(app)

    imported = client.get("/api/external-candidates/qs-master-applications")
    assert imported.status_code == 200
    import_data = imported.json()
    assert import_data["status"] == "ok"
    assert import_data["candidate_count"] >= 7
    assert any(item["institution_zh"] == "香港大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "香港中文大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "香港科技大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "香港城市大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "香港理工大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "新加坡国立大学" for item in import_data["candidates"])
    assert any(item["institution_zh"] == "南洋理工大学" for item in import_data["candidates"])

    refresh = client.post(
        "/api/workflows/data-refresh",
        json={
            "selected_program_ids": [
                "hku-master-of-science-in-computer-science-2027",
                "cuhk-msc-in-computer-science-2027",
                "ntu-msc-artificial-intelligence-2027",
            ],
            "dry_run": True,
            "max_sources": 8,
        },
    )
    assert refresh.status_code == 200
    data = refresh.json()
    qs_result = next(
        item for item in data["extraction_results"]
        if item["source_id"] == "qs_master_applications_github"
    )
    assert qs_result["raw_json"]["matched_candidate_count"] >= 3
    assert qs_result["agent_chain"] == [
        "SourceDiscoveryAgent",
        "RepositoryImportAgent",
        "OfficialLinkCandidateAgent",
        "ReviewerGateAgent",
    ]
    assert all(
        field["status"] != "OFFICIAL_VERIFIED_CURRENT"
        for field in qs_result["extracted_fields"]
    )
    assert any("港新官网线索" in action or "学校项目页" in action for action in data["next_actions"])


def test_admin_catalog_refresh_plan_queues_source_update_chain() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/admin/agent-queue/catalog-refresh-plan",
        json={
            "selected_program_ids": ["hku-mscs"],
            "dry_run": False,
            "max_programs": 5,
            "max_candidates_per_program": 3,
            "max_sources_per_program": 4,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["mode"] == "write"
    assert [job["workflow_name"] for job in data["jobs"]] == [
        "catalog_auto_update",
        "data_acquisition",
        "crawl_queue",
    ]
    assert [job["priority"] for job in data["jobs"]] == [90, 80, 70]
    assert all(job["status"] == "QUEUED" for job in data["jobs"])
    assert "review and publish" in data["next_step"]

    events = client.get("/api/admin/agent-events?entity_type=job&entity_id=catalog_refresh_plan")
    assert events.status_code == 200
    assert any(item["event_type"] == "CATALOG_REFRESH_PLAN_QUEUED" for item in events.json()["items"])

def test_agent_queue_records_attempts_and_retry() -> None:
    client = TestClient(app)

    created = client.post(
        "/api/admin/agent-queue",
        json={
            "workflow_name": "program_plan",
            "payload_summary": "intentional invalid profile for retry smoke",
            "payload": {"profile": {"bad": "shape"}},
            "priority": 100,
            "max_attempts": 2,
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    run = None
    for _ in range(20):
        run = client.post("/api/admin/agent-queue/run-next")
        assert run.status_code == 200
        claimed = run.json().get("job")
        if claimed and claimed.get("job_id") == job_id:
            break
    assert run is not None
    assert run.json()["job"]["job_id"] == job_id

    queue = client.get("/api/admin/agent-queue?limit=100")
    assert queue.status_code == 200
    job = next(item for item in queue.json()["items"] if item["job_id"] == job_id)
    assert job["status"] == "FAILED"
    assert job["attempts"] == 1
    assert job["max_attempts"] == 2
    assert job["can_retry"] is True
    assert job["last_error"]

    retry = client.post(f"/api/admin/agent-queue/{job_id}/retry", json={"reviewer_id": "pytest"})
    assert retry.status_code == 200
    assert retry.json()["status"] == "QUEUED"

    events = client.get(f"/api/admin/agent-events?entity_type=job&entity_id={job_id}")
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["items"]}
    assert {"JOB_QUEUED", "JOB_CLAIMED", "JOB_FAILED", "JOB_REQUEUED"}.issubset(event_types)


def test_agent_run_rollback_marks_later_steps_and_enqueues_retry() -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from harbor_agent.models import AgentStatus
    from harbor_agent.services.agent_runtime import record_agent_step, start_agent_run

    client = TestClient(app)
    workflow_id = "wf_pytest_rollback_" + uuid4().hex[:8]
    start_agent_run(workflow_id, "pytest_rollback")
    base = datetime.now(UTC)
    for index, node in enumerate(["ProfileAgent", "EvaluationAgent", "MatchingAgent"]):
        started = base + timedelta(seconds=index)
        record_agent_step(
            workflow_id=workflow_id,
            node=node,
            status=AgentStatus.completed,
            input_summary="input " + node,
            output_summary="output " + node,
            tool_calls=["pytest"],
            model="mock",
            started_at=started,
            finished_at=started + timedelta(milliseconds=10),
        )

    detail = client.get(f"/api/admin/agent-runs/{workflow_id}").json()
    target_step_id = next(step["step_id"] for step in detail["steps"] if step["node"] == "EvaluationAgent")
    rollback = client.post(
        f"/api/admin/agent-runs/{workflow_id}/rollback",
        json={"target_step_id": target_step_id, "reviewer_id": "pytest", "reason": "bad matching output"},
    )
    assert rollback.status_code == 200
    data = rollback.json()
    assert data["status"] == "ROLLED_BACK"
    assert data["current_step"] == "EvaluationAgent"
    assert data["rolled_back_step_count"] >= 1
    assert data["retry_job"]["workflow_name"] == "retry:EvaluationAgent"

    after = client.get(f"/api/admin/agent-runs/{workflow_id}").json()
    statuses = {step["node"]: step["status"] for step in after["steps"]}
    assert statuses["EvaluationAgent"] == "ROLLBACK_TARGET"
    assert statuses["MatchingAgent"] == "ROLLED_BACK"
    assert after["run"]["status"] == "ROLLED_BACK"
    assert any(event["event_type"] == "RUN_ROLLED_BACK" for event in after["events"])


def test_admin_api_requires_configured_token() -> None:
    import harbor_agent.app as app_module

    previous_token = app_module.settings.admin_token
    app_module.settings.admin_token = "pytest-admin-token"
    client = TestClient(app)
    try:
        missing = client.get("/api/admin/llm-config")
        assert missing.status_code == 403

        wrong = client.get("/api/admin/llm-config", headers={"x-harbor-admin-token": "wrong"})
        assert wrong.status_code == 403

        ok = client.get("/api/admin/llm-config", headers={"x-harbor-admin-token": "pytest-admin-token"})
        assert ok.status_code == 200

        blocked_post = client.post("/api/admin/llm-config", json={"provider": "mock"})
        assert blocked_post.status_code == 403

        wrong_post = client.post(
            "/api/admin/llm-config",
            json={"provider": "mock"},
            headers={"x-harbor-admin-token": "wrong"},
        )
        assert wrong_post.status_code == 403

        ok_post = client.post(
            "/api/admin/llm-config",
            json={"provider": "mock"},
            headers={"x-harbor-admin-token": "pytest-admin-token"},
        )
        assert ok_post.status_code == 200
    finally:
        app_module.settings.admin_token = previous_token

def test_admin_mutation_requires_token_or_explicit_insecure_local_mode() -> None:
    import harbor_agent.app as app_module

    previous_token = app_module.settings.admin_token
    previous_allow = app_module.settings.allow_insecure_local_admin
    try:
        app_module.settings.admin_token = None
        app_module.settings.allow_insecure_local_admin = False
        local_post = SimpleNamespace(method="POST", headers=Headers({}), client=SimpleNamespace(host="127.0.0.1"))
        local_get = SimpleNamespace(method="GET", headers=Headers({}), client=SimpleNamespace(host="127.0.0.1"))
        assert app_module._admin_request_allowed(local_get) is True
        assert app_module._admin_request_allowed(local_post) is False

        app_module.settings.allow_insecure_local_admin = True
        assert app_module._admin_request_allowed(local_post) is True
    finally:
        app_module.settings.admin_token = previous_token
        app_module.settings.allow_insecure_local_admin = previous_allow
