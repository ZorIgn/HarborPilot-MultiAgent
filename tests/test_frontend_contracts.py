from __future__ import annotations

from pathlib import Path


def test_frontend_does_not_auto_confirm_recommended_programs() -> None:
    source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")

    assert "persistSelected(response.application_mix" not in source
    assert "application_mix.slice(0, 3)" not in source
    assert "catalogProgramToCandidateMatch" in source
    assert "recommendations={writingProgramOptions}" in source
    assert "学生手动加入的清单项目" in source


def test_student_pages_use_specific_product_copy() -> None:
    student_files = [
        Path("web/app/AssessmentPage.tsx"),
        Path("web/app/ProgramCatalogPage.tsx"),
        Path("web/app/TimelinePage.tsx"),
        Path("web/app/WritingWorkspace.tsx"),
        Path("web/lib/copy.ts"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in student_files)

    blocked_terms = [
        "诊断报告",
        "过度承诺",
        "生成可解释",
        "待学校确认",
        "待确认",
        "未确认",
        "生成追问",
        "准备清单",
        "准备节奏",
        "建议组合",
        "生成任务",
        "申请方案",
        "刷新学校官网信息",
        "查看来源",
        "内部准备",
        "学校原文",
        "官网原文",
    ]
    for term in blocked_terms:
        assert term not in source

    assert "生成项目分档" in source
    assert "最终申请清单" in source
    assert "生成时间线" in source
    assert "打开官网页面" in source


def test_student_workflow_api_copy_avoids_blocked_terms() -> None:
    import json

    from fastapi.testclient import TestClient

    from harbor_agent.app import app

    client = TestClient(app)
    payload = json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))

    background = client.post("/api/workflows/background", json=payload)
    assert background.status_code == 200

    program_plan = client.post("/api/workflows/program-plan", json=payload)
    assert program_plan.status_code == 200
    program_data = program_plan.json()
    selected_ids = [
        item["program"]["id"]
        for item in program_data["recommendations"]
        if item["tier"] != "not_recommended"
    ][:2]
    assert selected_ids

    application_plan = client.post(
        "/api/workflows/application-plan",
        json={"profile": payload, "selected_program_ids": selected_ids},
    )
    assert application_plan.status_code == 200

    student_payload = json.dumps(
        {
            "background": background.json(),
            "program_plan": program_data,
            "application_plan": application_plan.json(),
        },
        ensure_ascii=False,
    )
    for term in [
        "诊断报告",
        "过度承诺",
        "生成可解释",
        "待学校确认",
        "待确认",
        "未确认",
        "生成追问",
        "准备清单",
        "准备节奏",
        "建议组合",
        "生成任务",
        "申请方案",
        "刷新学校官网信息",
        "查看来源",
        "内部准备",
        "学校原文",
        "官网原文",
        "学校暂未确认",
        "抓取",
    ]:
        assert term not in student_payload

    assert "需核验" in student_payload
    assert "项目清单" in student_payload


def test_student_workspace_state_is_not_kept_in_browser_storage() -> None:
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")
    api_source = Path("web/lib/api.ts").read_text(encoding="utf-8")
    backend_source = Path("src/harbor_agent/app.py").read_text(encoding="utf-8")

    assert "localStorage" not in app_source
    assert "STORAGE_" not in app_source
    assert "getLocalWorkspace" in api_source
    assert "saveLocalWorkspace" in api_source
    assert "/api/workspace/local" in backend_source


def test_high_visibility_student_copy_is_centralized() -> None:
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    assessment_source = Path("web/app/AssessmentPage.tsx").read_text(encoding="utf-8")
    program_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")
    timeline_source = Path("web/app/TimelinePage.tsx").read_text(encoding="utf-8")
    writing_source = Path("web/app/WritingWorkspace.tsx").read_text(encoding="utf-8")
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")

    assert "assessmentCopy" in copy_source
    assert "programCatalogCopy" in copy_source
    assert "timelineCopy" in copy_source
    assert "writingCopy" in copy_source
    assert "dashboardCopy" in copy_source
    assert "progressCopy" in copy_source
    assert "assessmentCopy.dimensionEmpty" in assessment_source
    assert "programCatalogCopy.heroTitle" in program_source
    assert "programCatalogCopy.addToList" in program_source
    assert "timelineCopy.heroTitle" in timeline_source
    assert "timelineCopy.applicationEntry" in timeline_source
    assert "writingCopy.title" in writing_source
    assert "writingCopy.materialQuestions" in writing_source
    assert "writingCopy.storyCardEmpty" in writing_source
    assert "writingCopy.materialGapEmpty" in writing_source
    assert "writingCopy.paragraphDraftEmpty" in writing_source
    assert "writingCopy.factBindingEmpty" in writing_source
    assert "writingCopy.interviewEmpty" in writing_source
    assert "dashboardCopy.heroTitle" in app_source
    assert "dashboardCopy.nextSteps" in app_source
    assert "progressCopy[stage" in app_source
    for scattered in [
        "\u7533\u8bf7\u6d41\u7a0b\u4ece\u8fd9\u91cc\u5f00\u59cb",
        "\u4eca\u5929\u5148\u505a\u4ec0\u4e48",
        "\u6b63\u5728\u751f\u6210\u80cc\u666f\u7ade\u4e89\u529b\u8bc4\u4f30",
        "\u8bf7\u7a0d\u7b49\uff0c\u5b8c\u6210\u540e\u9875\u9762\u4f1a\u81ea\u52a8\u66f4\u65b0",
    ]:
        assert scattered not in app_source


def test_browser_metadata_uses_student_product_language() -> None:
    source = Path("web/app/layout.tsx").read_text(encoding="utf-8")

    assert "Multi-agent" not in source
    assert "console" not in source.lower()
    assert "HarborPilot" in source
    assert "\u6e2f\u65b0\u7855\u58eb\u7533\u8bf7\u8f85\u52a9\u5e73\u53f0" in source

def test_student_navigation_does_not_expose_admin_routes() -> None:
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    student_nav = copy_source.split("export const adminNavItems", 1)[0]

    assert "studentNavItems" in student_nav
    assert "/agent-lab" not in student_nav
    assert "/settings" in student_nav
    assert "AI " + "\u8bbe\u7f6e" in student_nav
    assert "Admin" not in student_nav






def test_student_program_detail_drawer_hides_collection_internals() -> None:
    source = Path("web/app/AdminDataCenter.tsx").read_text(encoding="utf-8")
    drawer = source.split("export function ProgramPackageDrawer", 1)[1].split("function CoverageAuditList", 1)[0]

    assert "\u9879\u76ee\u4fe1\u606f\u4e0e\u6765\u6e90" in drawer
    assert "\u65f6\u95f4\u7ebf\u72b6\u6001" in drawer
    assert "\u9879\u76ee\u6570\u636e\u5305" not in drawer
    assert "\u5b57\u6bb5\u8986\u76d6\u5ba1\u8ba1" not in drawer
    assert "\u91c7\u96c6\u8ba1\u5212" not in drawer
    for internal in ["crawler_method", "robots_policy", "acquisition_plan", "allowed_fields", "fetch_method", "parser"]:
        assert internal not in drawer

def test_previous_cycle_labels_include_specific_year_in_student_views() -> None:
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    catalog_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")
    timeline_source = Path("web/app/TimelinePage.tsx").read_text(encoding="utf-8")
    product_source = "\n".join([copy_source, catalog_source, timeline_source])

    assert "previousCycleLabel" in copy_source
    assert "2026 Fall" in copy_source
    assert "previousCycleLabel(record.cycle)" in catalog_source
    assert "previousCycleLabel(task.previous_cycle_reference)" in timeline_source
    assert "\u6309\u5f80\u5c4a\u53c2\u8003\u51c6\u5907" not in product_source
    assert "\u4f7f\u7528\u4e0a\u4e00\u5b63\u53c2\u8003" not in product_source

def test_dashboard_steps_keep_students_inside_application_flow() -> None:
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    dashboard_source = app_source.split("function DashboardView", 1)[1].split("function AdminModelNotice", 1)[0]
    dashboard_copy = copy_source.split("export const dashboardCopy", 1)[1].split("export const progressCopy", 1)[0]

    assert "href=\"/settings\"" not in dashboard_source
    assert "API Key" not in dashboard_source
    assert "Admin" not in dashboard_source
    for expected in ["/assessment", "/programs", "/timeline", "/writing"]:
        assert expected in dashboard_copy


def test_core_student_pages_do_not_reference_admin_only_terms() -> None:
    student_files = [
        Path("web/app/AssessmentPage.tsx"),
        Path("web/app/ProgramCatalogPage.tsx"),
        Path("web/app/TimelinePage.tsx"),
        Path("web/app/WritingWorkspace.tsx"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in student_files)
    internal_terms = [
        "API Key",
        "Admin " + "?" * 2,
        "Admin " + "?" * 4,
        "localStorage",
        "page_" + "hash",
        "crawl" + "er",
        "robot" + "s",
        "snap" + "shot",
        "Data" + "Status",
        "Field" + "Verification" + "Status",
    ]
    for term in internal_terms:
        assert term not in source




def test_student_error_and_empty_states_use_business_copy() -> None:
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")
    program_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")
    api_source = Path("web/lib/api.ts").read_text(encoding="utf-8")

    assert "appErrorCopy" in copy_source
    assert "setError(appErrorCopy.backgroundFailed)" in app_source
    assert "setCatalogError(appErrorCopy.catalogLoadFailed)" in app_source
    assert "programCatalogCopy.catalogError" in program_source
    assert "programCatalogCopy.catalogEmptyFiltered" in program_source
    assert "programCatalogCopy.noMatches" in program_source
    assert "HarborPilot \u540e\u7aef\u670d\u52a1\u5df2\u542f\u52a8" in api_source

    for source in [app_source, program_source, api_source]:
        for blocked in [
            "\u63a5\u53e3\u8c03\u7528\u5931\u8d25",
            "\u540e\u7aef 8000",
            "\u9879\u76ee\u5e93\u63a5\u53e3\u9519\u8bef",
            "\u5237\u65b0\u9879\u76ee\u5e93\u63a5\u53e3",
            "\u5b57\u6bb5\u7ea7\u6765\u6e90\u52a0\u8f7d\u4e2d",
            "\u5f53\u524d\u63a8\u8350\u7528\u4e8e\u7b5b\u9009",
            "?" * 4,
        ]:
            assert blocked not in source



def test_assessment_form_covers_master_profile_sections() -> None:
    source = Path("web/app/AssessmentPage.tsx").read_text(encoding="utf-8")
    type_source = Path("web/lib/types.ts").read_text(encoding="utf-8")

    for expected in [
        "个人信息",
        "申请意向",
        "GPA 口径",
        "专业排名百分比",
        "阅读",
        "听力",
        "口语",
        "核心课程 / 先修课",
        "交换 / 海外经历",
        "科研 / 论文 / 报告",
        "活动 / 领导力",
        "奖项",
        "技能",
        "经历素材",
        "个人与意向",
        "教育与语言",
        "课程与经历",
        "材料核验",
        "正式成绩单",
        "语言成绩单",
        "核心课程说明",
        "正在保存到本地档案",
        "保存失败",
    ]:
        assert expected in source
    assert "assessmentSteps" in source
    assert "materialStatusItems" in source
    assert "profileSaveStatus" in source
    assert "material_ready:" in source
    assert "personal_info" in type_source
    assert "additional_background" in type_source



def test_local_autosave_has_debounce_and_stale_response_guards() -> None:
    source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")

    assert "profileSaveTimerRef" in source
    assert "workspaceSaveTimerRef" in source
    assert "profileSaveSeqRef" in source
    assert "workspaceSaveSeqRef" in source
    assert "const saveSeq = profileSaveSeqRef.current + 1" in source
    assert "const saveSeq = workspaceSaveSeqRef.current + 1" in source
    assert "if (profileSaveSeqRef.current === saveSeq) setProfileSaveStatus" in source
    assert "if (profileSaveSeqRef.current !== saveSeq) return" in source
    assert "if (workspaceSaveSeqRef.current === saveSeq) setError" in source
    assert "profileSaveSeqRef.current += 1" in source
    assert "workspaceSaveSeqRef.current += 1" in source
    assert "writingDraftHistory" in source
    assert "workspace.writing_draft_history" in source
    assert "updateWritingDraftHistory" in source
    assert "saveWorkspace({ writingDraftHistory: history })" in source


def test_writing_workspace_guides_questionnaire_to_downloadable_draft() -> None:
    source = Path("web/app/WritingWorkspace.tsx").read_text(encoding="utf-8")
    config_source = Path("web/app/writing/workspaceConfig.ts").read_text(encoding="utf-8")
    css = Path("web/app/globals.css").read_text(encoding="utf-8")

    assert "awaitingExport" in source
    assert "setActiveStep(3)" in source
    assert "completion.requiredMissing === 0" in source
    assert "\u8fd8\u5dee ${completion.requiredMissing} \u4e2a\u5fc5\u586b\u95ee\u9898" in source
    assert "\u4e0b\u8f7d Word \u6587\u6863" in source
    assert "reference_recommender_profile" in config_source
    assert "documentFlows" in config_source
    assert "type FlowDefinition =" not in source
    assert "writing-type-segment" in source
    assert "WritingMethodPanel" in source
    assert "writing-questionnaire-note" in source
    assert "activeFieldIndex" in source
    assert "currentQuestionReady" in source
    assert "writing-one-question" in source
    assert "flow.outputHint" in source
    assert "downloadDocxFile" in source
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in source
    assert "[Content_Types].xml" in source
    assert "word/document.xml" in source
    assert "buildStoredZip(files)" in source
    assert '.doc"' not in source
    assert "Writing workspace v15" in css
    assert "Writing workspace v16" in css
    assert ".writing-type-segment" in css
    assert ".writing-method-panel" in css
    assert ".writing-field-list.writing-one-question" in css

def test_writing_workspace_tracks_versions_and_fact_locks() -> None:
    source = Path("web/app/WritingWorkspace.tsx").read_text(encoding="utf-8")
    css = Path("web/app/globals.css").read_text(encoding="utf-8")

    assert "DraftHistoryItem" in source
    assert "draftHistory" in source
    assert "DraftVersionPanel" in source
    assert "FactLockSummary" in source
    assert "onDraftHistoryChange" in source
    assert "countDraftWords" in source
    assert "\u7248\u672c\u5386\u53f2" in source
    assert "\u4e8b\u5b9e\u9501\u5b9a" in source
    assert "unsupported_claims" in source
    assert "WritingExportGate" in source
    assert "writingExportGate" in source
    assert "production_ready" in source
    assert "reference_ready" in source
    assert "canDownloadWord" in source
    assert "buildDraftMarkdown(writing, targetProgram, documentType, rubric)" in source
    assert "\u4e0b\u8f7d\u524d\u590d\u6838" in source
    assert "\u4e0d\u80fd\u4f5c\u4e3a\u6700\u7ec8\u7a3f" in source
    assert "\u5e26\u590d\u6838\u6807\u8bb0" in source
    assert "writing-export-gate" in css
    assert "Writing workspace v18" in css
    assert "writing-version-panel" in css
    assert "writing-fact-lock-panel" in css
    assert "Writing workspace v17" in css


def test_writing_workspace_only_uses_student_selected_programs() -> None:
    source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")

    writing_options_line = "const writingProgramOptions = useMemo(() => selectedMatches, [selectedMatches]);"

    assert writing_options_line in source
    assert "selectedProgram?.id" not in source
    assert "const writingProgramOptions = useMemo(() => {" not in source
    assert 'runWritingInterview({ profile: payload, selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || ""].filter(Boolean)' in source
    assert 'runWritingPlan({ profile: payload, questionnaire: buildQuestionnaireResponse(questionnaireSchema, questionnaireValues), selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || ""].filter(Boolean)' in source


def test_timeline_page_has_date_and_program_views() -> None:
    source = Path("web/app/TimelinePage.tsx").read_text(encoding="utf-8")
    css = Path("web/app/globals.css").read_text(encoding="utf-8")

    assert 'defaultActiveKey="date"' in source
    assert "DateTimelineView" in source
    assert "ProjectTimelineView" in source
    assert "groupTasks(tasks, taskDateKey)" in source
    assert "groupTasks(tasks, taskProgramLabel)" in source
    assert "weekTasks" not in source
    assert "\u6309\u65e5\u671f" in source
    assert "\u6309\u9879\u76ee" in source
    assert "downloadTimelineIcs" in source
    assert "\u5bfc\u51fa\u65e5\u5386" in source
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")

    assert "taskStatusOptions" in source
    assert "onTaskStatusChange" in source
    assert "updateTimelineTaskStatus" in app_source
    assert "saveWorkspace({ result: merged })" in app_source
    assert "\u4efb\u52a1\u72b6\u6001" in source
    assert "reminder_at" in source
    assert "dependencies" in source
    assert "task-material-checklist" in source
    assert "task-dependency-list" in source
    assert "\u4fe1\u606f\u66f4\u65b0" in source
    assert "Timeline workspace v4" in css
    assert ".task-status-control" in css
    assert ".task-material-checklist" in css




def test_program_cards_show_student_decision_fields_without_truncating_trust_records() -> None:
    source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")

    assert "formatLanguageRequirement" in source
    assert "formatMaterials" in source
    assert "orderedTrustRecords(records).map" in source
    assert "records.slice(0, 5)" not in source
    for expected in [
        "\u8bed\u8a00\u8981\u6c42",
        "\u6750\u6599\u6e05\u5355",
        "official_program_url",
        "application_url",
        "deadline",
        "language_requirement",
        "materials",
        "tuition_hkd",
    ]:
        assert expected in source


def test_program_catalog_shows_student_readiness_layers() -> None:
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    catalog_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")

    assert "readinessTitle" in copy_source
    assert "readinessCurrent" in copy_source
    assert "readinessReference" in copy_source
    assert "readinessIncomplete" in copy_source
    assert "CatalogReadinessPanel" in catalog_source
    assert "buildCatalogReadinessStats" in catalog_source
    assert "studentSourceStatus(program)" in catalog_source
    assert "program.data_status !== filters.verification_status" not in catalog_source


def test_program_catalog_recommendations_are_grouped_by_strategy_bands() -> None:
    source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")

    assert 'defaultActiveKey="reach"' in source
    assert '"reach", "target", "safe", "candidate", "blocked"' in source
    assert "bandedMatches" in source
    assert "mergeProgramMatches" in source
    assert "bandKey(item)" in source
    assert "PlanTrustGate" in source
    assert "buildPlanTrustStats" in source
    assert "\u65b9\u6848\u53ef\u4fe1\u5ea6\u95f8\u95e8" in source
    assert "\u5f53\u524d\u5b63\u5b98\u65b9" in source
    assert "\u5f85\u5b98\u7f51\u6838\u9a8c" in source
    assert "\u4e0d\u628a\u5b83\u5199\u6210\u53ef\u63d0\u4ea4\u7ed3\u8bba" in source
    assert "\u6838\u5fc3\u5339\u914d" not in source
    assert "\u76f8\u5173\u5019\u9009" not in source
    assert "props.focusList.length" not in source


def test_admin_review_queue_panel_is_extracted_from_data_center() -> None:
    admin_source = Path("web/app/AdminDataCenter.tsx").read_text(encoding="utf-8")
    panel_source = Path("web/app/admin/ReviewQueuePanel.tsx").read_text(encoding="utf-8")

    assert 'from "./admin/ReviewQueuePanel"' in admin_source
    assert "function ReviewQueuePanel" not in admin_source
    assert "export function ReviewQueuePanel" in panel_source
    assert "ReviewBulkPublishResponse" in panel_source



def test_student_model_settings_use_student_api_without_admin_token() -> None:
    api_source = Path("web/lib/api.ts").read_text(encoding="utf-8")
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")
    copy_source = Path("web/lib/copy.ts").read_text(encoding="utf-8")
    student_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "web/app/AssessmentPage.tsx",
            "web/app/ProgramCatalogPage.tsx",
            "web/app/TimelinePage.tsx",
            "web/app/WritingWorkspace.tsx",
        ]
    )

    assert "harborpilot_admin_token" in api_source
    assert "x-harbor-admin-token" in api_source
    assert "withAdminAuth(path" in api_source
    assert "path.startsWith(\"/api/admin/\")" in api_source
    assert "configureStudentLLM" in api_source
    assert "\"/api/llm-config\"" in api_source
    assert "configureStudentLLM(request)" in app_source
    assert "AI " + "\u8bbe\u7f6e" in copy_source
    assert "Admin Token" not in app_source
    assert "Admin Token" not in student_sources

def test_frontend_dev_and_build_outputs_are_isolated_and_plan_is_labeled_preliminary() -> None:
    import json

    package = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    program_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "NEXT_DIST_DIR=next-dev" in package["scripts"]["dev"]
    assert "NEXT_DIST_DIR=next-build" in package["scripts"]["build"]
    assert "NEXT_DIST_DIR=next-build" in package["scripts"]["start"]
    assert "next-dev" in readme and "next-build" in readme
    assert "可编辑择校方案（预评估）" in program_source
    assert "预评估 / 待官网核验" in program_source


def test_student_workflow_persists_selection_and_labels_unverified_fields() -> None:
    api_source = Path("web/lib/api.ts").read_text(encoding="utf-8")
    app_source = Path("web/app/HarborPilotApp.tsx").read_text(encoding="utf-8")
    program_source = Path("web/app/ProgramCatalogPage.tsx").read_text(encoding="utf-8")
    timeline_source = Path("web/app/TimelinePage.tsx").read_text(encoding="utf-8")
    writing_source = Path("web/app/WritingWorkspace.tsx").read_text(encoding="utf-8")

    assert 'credentials: "include"' in api_source
    assert "saveWorkspaceNow({ selectedProgramIds: unique" in app_source
    assert "autoRequested" not in program_source
    assert "formatDeadlineForProgram" in program_source
    assert "当前季已核验日期" in program_source
    assert "待官网核验（库内参考：" in timeline_source
    assert "englishNeedsRevision" in writing_source
