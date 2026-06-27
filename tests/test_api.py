from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from harbor_agent.app import app


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
    assert any(section["id"] == "statement_motivation" for section in schema["sections"])

    background = client.post("/api/workflows/background", json=payload)
    assert background.status_code == 200
    background_data = background.json()
    assert background_data["assessment"]["overall_level"]
    assert len(background_data["trace"]) == 3

    program_plan = client.post("/api/workflows/program-plan", json=payload)
    assert program_plan.status_code == 200
    program_data = program_plan.json()
    assert program_data["recommendations"]
    assert program_data["consultant_plan"]["items"]
    assert program_data["consultant_plan"]["data_disclaimer"]
    assert any(item["program"]["official_program_url"] for item in program_data["recommendations"])
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
    assert any("学校官网" in risk or "学校确认" in risk for risk in first_match["risks"])

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
                    {
                        "field_id": "practical_examples",
                        "value": "在金融科技实习中搭建留存分析看板，减少周报时间并定位流失信号。",
                        "evidence_ids": [],
                    },
                    {"field_id": "career_plan", "value": "毕业后希望成为跨境科技公司的产品数据分析师。", "evidence_ids": []},
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
    assert writing_data["writing"]["version_id"]
    assert writing_data["writing"]["school_customization"]
    assert writing_data["writing"]["prompt_requirements"]
    assert writing_data["writing"]["cv_bullets"]
    assert writing_data["writing"]["reference_package"]
    assert writing_data["writing"]["risk_controls"]


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


def test_program_catalog_exposes_field_level_trust_detail() -> None:
    client = TestClient(app)

    response = client.get("/api/programs?limit=1")
    assert response.status_code == 200
    program = response.json()[0]
    trust = program["trust_detail"]

    assert trust["program_id"] == program["id"]
    assert trust["reviewer_gate_fields"]
    assert trust["fields_requiring_review"]
    assert trust["production_ready"] is False
    assert "学校官网确认" in trust["source_warning"]
    assert {"deadline", "tuition_hkd", "materials", "language_requirement", "application_url"} & {
        record["field_name"] for record in trust["field_records"]
    }
    assert all(record["agent_chain"] for record in trust["field_records"])

    detail = client.get(f"/api/programs/{program['id']}/trust")
    assert detail.status_code == 200
    assert detail.json()["field_records"] == trust["field_records"]


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
    assert any("GradWindow" in action for action in data["next_actions"])
