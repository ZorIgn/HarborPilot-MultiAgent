"use client";

import {
  Button as IslandButton,
  Card as IslandCard,
  Cursor,
  Footer,
  Title as IslandTitle,
} from "animal-island-ui";
import { AlertTriangle, BookOpenCheck, CheckCircle2, ClipboardList, GraduationCap, Settings, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  getEvidenceGraphSummary,
  getHealth,
  getLocalProfile,
  getLocalWorkspace,
  getProgramDataPackage,
  getPrograms,
  getQuestionnaireSchema,
  getReviewQueue,
  getScenarioAudit,
  getSourceHealth,
  getSourceRegistry,
  publishReviewBatch,
  publishReviewItem,
  getRuntimeWorkflows,
  startRuntimeWorkflow,
  queueStudentCatalogRefreshPlan,
  runApplicationPlan,
  runBackgroundStage,
  runCatalogAutoUpdate,
  runCrawlQueue,
  runDataAcquisition,
  runDataRefresh,
  runProgramPlan,
  runWritingInterview,
  runWritingPlan,
  runWritingReview,
  saveLocalProfile,
  saveLocalWorkspace,
} from "@/lib/api";
import { adminNavItems, appErrorCopy, dashboardCopy, pageTitles, progressCopy, studentNavItems, studentTrustWarning } from "@/lib/copy";
import { demoPayload } from "@/lib/demoPayload";
import { AdminDataCenter, ProgramPackageDrawer, SourceRefreshSummary } from "./AdminDataCenter";
import { AssessmentPage } from "./AssessmentPage";
import { filterCatalog, ProgramCatalogPage } from "./ProgramCatalogPage";
import { ProgramMiniList, TimelinePage } from "./TimelinePage";
import { WritingWorkspace } from "./WritingWorkspace";
import type {
  ApplicantPayload,
  ApplicationPlanResult,
  CatalogAutoUpdateReport,
  CatalogProgram,
  CrawlQueueReport,
  DataAcquisitionReport,
  DataRefreshReport,
  EvidenceGraphSummary,
  LayeredProgramPlanResult,
  ProgramDataPackage,
  ProgramMatch,
  ProgramSchemeState,
  QuestionnaireResponse,
  QuestionnaireSchema,
  ReviewBulkPublishResponse,
  ReviewPublishResponse,
  ReviewQueueSummary,
  RuntimeWorkflowGoal,
  RuntimeWorkflowListItem,
  RuntimeWorkflowState,
  ScenarioAuditReport,
  SourceRegistry,
  SourceHealthSummary,
  StoryCard,
  TimelineTask,
  WorkflowResult,
  WritingDraftHistoryItem,
  WritingInterviewQuestion,
  WritingPlanResult,
  WritingReviewRubric,
} from "@/lib/types";

type ViewMode = "home" | "assessment" | "programs" | "timeline" | "writing" | "agent" | "settings";
type StageLoading = "background" | "programs" | "timeline" | "writing" | "interview" | "data" | "crawl" | "catalog" | "review" | "scenario" | "package" | "llm" | null;
type SourceHealthLoadState = "loading" | "ready" | "error";
type DocumentType = "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
type QuestionnaireValues = Record<string, string>;
type AppState = Partial<WorkflowResult & LayeredProgramPlanResult & ApplicationPlanResult & WritingPlanResult> & {
  selected_programs?: ProgramMatch[];
  source_refresh?: DataRefreshReport | null;
  story_cards?: StoryCard[];
};

const defaultProgramScheme: ProgramSchemeState = {
  band_overrides: {},
  removed_program_ids: [],
  extra_candidate_ids: [],
};

function normalizeProgramScheme(value?: ProgramSchemeState | null): ProgramSchemeState {
  return {
    band_overrides: value?.band_overrides ?? {},
    removed_program_ids: Array.from(new Set(value?.removed_program_ids ?? [])),
    extra_candidate_ids: Array.from(new Set(value?.extra_candidate_ids ?? [])),
  };
}

export function HarborPilotApp({ view }: { view: ViewMode }) {
  const [payload, setPayload] = useState<ApplicantPayload>(demoPayload);
  const [result, setResult] = useState<AppState | null>(null);
  const [catalog, setCatalog] = useState<CatalogProgram[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [sourceRegistry, setSourceRegistry] = useState<SourceRegistry | null>(null);
  const [sourceHealth, setSourceHealth] = useState<SourceHealthSummary | null>(null);
  const [sourceHealthLoadState, setSourceHealthLoadState] = useState<SourceHealthLoadState>("loading");
  const [sourceAcquisition, setSourceAcquisition] = useState<DataAcquisitionReport | null>(null);
  const [crawlQueue, setCrawlQueue] = useState<CrawlQueueReport | null>(null);
  const [catalogAutoUpdate, setCatalogAutoUpdate] = useState<CatalogAutoUpdateReport | null>(null);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueSummary | null>(null);
  const [reviewPublishResult, setReviewPublishResult] = useState<ReviewPublishResponse | null>(null);
  const [reviewBulkPublishResult, setReviewBulkPublishResult] = useState<ReviewBulkPublishResponse | null>(null);
  const [scenarioAudit, setScenarioAudit] = useState<ScenarioAuditReport | null>(null);
  const [evidenceGraph, setEvidenceGraph] = useState<EvidenceGraphSummary | null>(null);
  const [runtimeWorkflows, setRuntimeWorkflows] = useState<RuntimeWorkflowListItem[]>([]);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [runtimeMessage, setRuntimeMessage] = useState("");
  const [questionnaireSchema, setQuestionnaireSchema] = useState<QuestionnaireSchema | null>(null);
  const [questionnaireValues, setQuestionnaireValues] = useState<QuestionnaireValues>({});
  const [selectedProgramIds, setSelectedProgramIds] = useState<string[]>([]);
  const [programScheme, setProgramScheme] = useState<ProgramSchemeState>(defaultProgramScheme);
  const [interviewQuestions, setInterviewQuestions] = useState<WritingInterviewQuestion[]>([]);
  const [writingReview, setWritingReview] = useState<WritingReviewRubric | null>(null);
  const [writingDraftHistory, setWritingDraftHistory] = useState<WritingDraftHistoryItem[]>([]);
  const [health, setHealth] = useState<{ status: string; llm_mode: string; llm_provider?: string } | null>(null);
  const [loading, setLoading] = useState<StageLoading>(null);
  const [profileSaveStatus, setProfileSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [programPackage, setProgramPackage] = useState<ProgramDataPackage | null>(null);
  const [packageOpen, setPackageOpen] = useState(false);
  const [filters, setFilters] = useState({ q: "", region: "", discipline: "", verification_status: "", deadline_status: "" });

  const [writingDocumentType, setWritingDocumentType] = useState<DocumentType>("PS");
  const [writingTargetProgramId, setWritingTargetProgramId] = useState("");
  const profileSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workspaceSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const profileSaveSeqRef = useRef(0);
  const workspaceSaveSeqRef = useRef(0);

  useEffect(() => {
    let active = true;
    getLocalProfile().then((storedProfile) => { if (active && storedProfile) setPayload(storedProfile); }).catch(() => undefined);
    getLocalWorkspace().then((workspace) => {
      if (!active) return;
      setResult((workspace.result_snapshot as AppState | null) ?? null);
      setSelectedProgramIds(workspace.selected_program_ids ?? []);
      setQuestionnaireValues(workspace.questionnaire_values ?? {});
      setProgramScheme(normalizeProgramScheme(workspace.program_scheme));
      setWritingDraftHistory(workspace.writing_draft_history ?? []);
    }).catch(() => undefined);
    getHealth().then(setHealth).catch(() => setHealth(null));
    getPrograms().then((items) => { setCatalog(items); setCatalogError(null); }).catch((err) => { setCatalog([]); setCatalogError(appErrorCopy.catalogLoadFailed); });
    getSourceRegistry().then(setSourceRegistry).catch(() => setSourceRegistry(null));
    getSourceHealth()
      .then((value) => { if (active) { setSourceHealth(value); setSourceHealthLoadState("ready"); } })
      .catch(() => { if (active) { setSourceHealth(null); setSourceHealthLoadState("error"); } });
    getEvidenceGraphSummary().then(setEvidenceGraph).catch(() => setEvidenceGraph(null));
    getRuntimeWorkflows(20).then(setRuntimeWorkflows).catch(() => setRuntimeWorkflows([]));
    getQuestionnaireSchema().then(setQuestionnaireSchema).catch(() => setQuestionnaireSchema(null));
    return () => {
      active = false;
      profileSaveSeqRef.current += 1;
      workspaceSaveSeqRef.current += 1;
      if (profileSaveTimerRef.current) clearTimeout(profileSaveTimerRef.current);
      if (workspaceSaveTimerRef.current) clearTimeout(workspaceSaveTimerRef.current);
    };
  }, []);

  const recommendations = result?.recommendations ?? [];
  const focusList = result?.focus_list?.length ? result.focus_list : recommendations.filter((item) => item.tier !== "not_recommended").slice(0, 15);
  const applicationMix = result?.application_mix?.length ? result.application_mix : focusList.slice(0, 8);
  const selectedMatches = useMemo(() => buildSelectedProgramSnapshots(selectedProgramIds), [catalog, recommendations, result?.selected_programs, selectedProgramIds, programScheme]);
  const writingProgramOptions = useMemo(() => selectedMatches, [selectedMatches]);
  const visibleCatalog = useMemo(() => filterCatalog(catalog, filters), [catalog, filters]);
  const visibleNavItems = useMemo(() => (view === "agent" ? [...studentNavItems, ...adminNavItems] : studentNavItems), [view]);
  const realModel = Boolean(health?.llm_provider && health.llm_provider !== "mock");

  function buildSelectedProgramSnapshots(ids: string[], scheme = programScheme): ProgramMatch[] {
    const byId = new Map<string, ProgramMatch>();
    recommendations.forEach((item) => byId.set(item.program.id, item));
    (result?.selected_programs ?? []).forEach((item) => byId.set(item.program.id, item));
    catalog.forEach((program) => { if (!byId.has(program.id)) byId.set(program.id, catalogProgramToCandidateMatch(program)); });
    return ids
      .map((id) => byId.get(id))
      .filter((item): item is ProgramMatch => Boolean(item))
      .map((item) => applyProgramSchemeToMatch(item, scheme));
  }

  function persistPayload(next: ApplicantPayload) {
    setPayload(next);
    setProfileSaveStatus("saving");
    const saveSeq = profileSaveSeqRef.current + 1;
    profileSaveSeqRef.current = saveSeq;
    if (profileSaveTimerRef.current) clearTimeout(profileSaveTimerRef.current);
    profileSaveTimerRef.current = setTimeout(() => {
      void saveLocalProfile(next)
        .then(() => {
          if (profileSaveSeqRef.current === saveSeq) setProfileSaveStatus("saved");
        })
        .catch(() => {
          if (profileSaveSeqRef.current !== saveSeq) return;
          setProfileSaveStatus("error");
          setError(appErrorCopy.profileSaveFailed);
        });
    }, 600);
  }

  function saveWorkspace(next: { selectedProgramIds?: string[]; questionnaireValues?: QuestionnaireValues; result?: AppState | null; programScheme?: ProgramSchemeState; writingDraftHistory?: WritingDraftHistoryItem[] }) {
    const snapshot = workspaceSnapshot(next);
    const saveSeq = workspaceSaveSeqRef.current + 1;
    workspaceSaveSeqRef.current = saveSeq;
    if (workspaceSaveTimerRef.current) clearTimeout(workspaceSaveTimerRef.current);
    workspaceSaveTimerRef.current = setTimeout(() => {
      void saveLocalWorkspace(snapshot).catch(() => {
        if (workspaceSaveSeqRef.current === saveSeq) setError(appErrorCopy.workspaceSaveFailed);
      });
    }, 600);
  }

  function workspaceSnapshot(next: { selectedProgramIds?: string[]; questionnaireValues?: QuestionnaireValues; result?: AppState | null; programScheme?: ProgramSchemeState; writingDraftHistory?: WritingDraftHistoryItem[] }) {
    return {
      selected_program_ids: next.selectedProgramIds ?? selectedProgramIds,
      questionnaire_values: next.questionnaireValues ?? questionnaireValues,
      result_snapshot: next.result ?? result ?? null,
      field_sensitivity: {},
      program_scheme: next.programScheme ?? programScheme,
      writing_draft_history: next.writingDraftHistory ?? writingDraftHistory,
    };
  }

  async function saveWorkspaceNow(next: { selectedProgramIds?: string[]; questionnaireValues?: QuestionnaireValues; result?: AppState | null; programScheme?: ProgramSchemeState; writingDraftHistory?: WritingDraftHistoryItem[] }) {
    const snapshot = workspaceSnapshot(next);
    const saveSeq = workspaceSaveSeqRef.current + 1;
    workspaceSaveSeqRef.current = saveSeq;
    if (workspaceSaveTimerRef.current) clearTimeout(workspaceSaveTimerRef.current);
    workspaceSaveTimerRef.current = null;
    try {
      return await saveLocalWorkspace(snapshot);
    } catch (saveError) {
      if (workspaceSaveSeqRef.current === saveSeq) setError(appErrorCopy.workspaceSaveFailed);
      throw saveError;
    }
  }
  function mergeResult(patch: Partial<AppState>) {
    setResult((previous) => {
      const merged = { ...(previous ?? {}), ...patch };
      saveWorkspace({ result: merged });
      return merged;
    });
  }

  function persistSelected(ids: string[]) {
    const unique = Array.from(new Set(ids));
    const selectedSnapshots = buildSelectedProgramSnapshots(unique);
    const nextResult = { ...(result ?? {}), selected_programs: selectedSnapshots };
    setSelectedProgramIds(unique);
    setResult(nextResult);
    // A selected programme is a workflow boundary: persist it immediately so
    // navigation to timeline/writing cannot cancel a debounced save.
    void saveWorkspaceNow({ selectedProgramIds: unique, result: nextResult }).catch(() => undefined);
  }

  function toggleProgram(id: string) {
    persistSelected(selectedProgramIds.includes(id) ? selectedProgramIds.filter((item) => item !== id) : [...selectedProgramIds, id]);
  }

  function updateProgramScheme(next: ProgramSchemeState) {
    const normalized = normalizeProgramScheme(next);
    setProgramScheme(normalized);
    const selectedSnapshots = buildSelectedProgramSnapshots(selectedProgramIds, normalized);
    const nextResult = result ? { ...result, selected_programs: selectedSnapshots } : result;
    if (nextResult) setResult(nextResult);
    saveWorkspace({ programScheme: normalized, result: nextResult ?? result });
  }

  function updateQuestionnaire(fieldId: string, value: string) {
    const next = { ...questionnaireValues, [fieldId]: value };
    setQuestionnaireValues(next);
    saveWorkspace({ questionnaireValues: next });
  }

  function updateWritingDraftHistory(history: WritingDraftHistoryItem[]) {
    setWritingDraftHistory(history);
    saveWorkspace({ writingDraftHistory: history });
  }

  async function refreshRuntimeWorkflows() {
    const workflows = await getRuntimeWorkflows(20);
    setRuntimeWorkflows(workflows);
  }

  async function startSupervisorWorkflow(goal: RuntimeWorkflowGoal): Promise<RuntimeWorkflowState | null> {
    setRuntimeBusy(true);
    setRuntimeMessage("");
    setError(null);
    const userRequest: Record<RuntimeWorkflowGoal, string> = {
      background_assessment: "请评估当前学生背景、资料完整度与下一步需要补充的信息。",
      program_recommendation: "请在招生资格、用户偏好和官网证据边界分离的前提下，生成项目推荐方案。",
      application_planning: "请基于已选项目与经核验的官方要求，生成申请准备规划。",
      writing: "请基于已确认事实、项目证据和问卷资料，规划文书准备任务。",
      full_application_plan: "请完成背景评估、项目推荐、官网核验与申请规划；信息不足时先提出问题。",
    };
    try {
      const state = await startRuntimeWorkflow({
        goal,
        profile: payload,
        user_request: userRequest[goal],
        questionnaire: buildQuestionnaireResponse(questionnaireSchema, questionnaireValues),
        selected_program_ids: selectedProgramIds.slice(0, 20),
        document_type: writingDocumentType,
      });
      setRuntimeMessage(`Supervisor Runtime 已创建 ${state.workflow_id}，当前状态：${state.status}。`);
      try {
        await refreshRuntimeWorkflows();
      } catch {
        // The newly-created workflow remains visible through its owner cookie;
        // the history endpoint itself intentionally requires administrator access.
      }
      return state;
    } catch (runtimeError) {
      const detail = runtimeError instanceof Error ? runtimeError.message : "无法启动 Supervisor Runtime。";
      setRuntimeMessage(detail);
      setError(detail);
      return null;
    } finally {
      setRuntimeBusy(false);
    }
  }
  async function requestProgramSourceUpdate(programId: string) {
    setError(null);
    try {
      const response = await queueStudentCatalogRefreshPlan({
        selected_program_ids: [programId],
        max_programs: 1,
        max_candidates_per_program: 6,
        max_sources_per_program: 8,
        include_data_acquisition: true,
        include_crawl_queue: true,
      });
      setRuntimeMessage(`信息更新队列已创建：${response.jobs.length} 个任务。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "信息更新队列暂时无法写入，请确认后端已启动。");
    }
  }
  async function runBackground(nextPayload = payload) {
    setLoading("background"); setError(null);
    try { const response = await runBackgroundStage(nextPayload); persistPayload(nextPayload); mergeResult(response); }
    catch (err) { setError(appErrorCopy.backgroundFailed); }
    finally { setLoading(null); }
  }

  async function runPrograms(nextPayload = payload, redirectToPrograms = false) {
    setLoading("programs"); setError(null);
    try {
      const response = await runProgramPlan(nextPayload);
      persistPayload(nextPayload);
      const nextResult = { ...(result ?? {}), ...response };
      setResult(nextResult);
      if (redirectToPrograms && typeof window !== "undefined") {
        await Promise.all([
          saveLocalProfile(nextPayload),
          saveWorkspaceNow({ result: nextResult }),
        ]);
        setProfileSaveStatus("saved");
        window.location.assign("/programs");
      } else {
        saveWorkspace({ result: nextResult });
      }
    } catch (err) { setError(appErrorCopy.programsFailed); }
    finally { setLoading(null); }
  }

  async function runTimeline() {
    if (!selectedProgramIds.length) { setError(appErrorCopy.selectProgramFirst); return; }
    setLoading("timeline"); setError(null);
    try {
      const selectedSnapshots = buildSelectedProgramSnapshots(selectedProgramIds);
      const response = await runApplicationPlan({ profile: payload, selected_program_ids: selectedProgramIds });
      mergeResult({ ...response, selected_programs: selectedSnapshots.length ? selectedSnapshots : response.selected_programs });
    }
    catch (err) { setError(appErrorCopy.timelineFailed); }
    finally { setLoading(null); }
  }

  function updateTimelineTaskStatus(taskId: string, status: NonNullable<TimelineTask["status"]>) {
    setResult((previous) => {
      if (!previous?.timeline?.length) return previous;
      const merged = {
        ...previous,
        timeline: previous.timeline.map((task) => task.id === taskId ? { ...task, status } : task),
      };
      saveWorkspace({ result: merged });
      return merged;
    });
  }

  async function openProgramPackage(programId: string) {
    setLoading("package"); setError(null);
    try { setProgramPackage(await getProgramDataPackage(programId)); setPackageOpen(true); }
    catch (err) { setError(appErrorCopy.packageFailed); }
    finally { setLoading(null); }
  }

  async function refreshSources(liveFetch = false) {
    setLoading("data"); setError(null);
    try {
      const response = await runDataRefresh({ region: "ALL", selected_program_ids: selectedProgramIds, dry_run: !liveFetch, use_llm: realModel, max_sources: selectedProgramIds.length ? 24 : 16 });
      mergeResult({ source_refresh: response });
      setEvidenceGraph(await getEvidenceGraphSummary());
      if (liveFetch) await reloadSourceHealth();
    } catch (err) { setError(appErrorCopy.sourceRefreshFailed); }
    finally { setLoading(null); }
  }

  async function runAcquisition(dryRun: boolean) {
    setLoading("data"); setError(null);
    try {
      const response = await runDataAcquisition({ selected_program_ids: selectedProgramIds, dry_run: dryRun, include_community: true, max_sources_per_program: selectedProgramIds.length ? 4 : 1 });
      setSourceAcquisition(response);
      if (!dryRun) { setEvidenceGraph(await getEvidenceGraphSummary()); await reloadSourceHealth(); }
    } catch (err) { setError(appErrorCopy.sourceRefreshFailed); }
    finally { setLoading(null); }
  }

  async function buildCrawlQueue() {
    setLoading("crawl"); setError(null);
    try { setCrawlQueue(await runCrawlQueue({ selected_program_ids: selectedProgramIds, include_community: true, max_sources_per_program: 8 })); }
    catch (err) { setError(appErrorCopy.crawlQueueFailed); }
    finally { setLoading(null); }
  }

  async function reloadSourceHealth() {
    setSourceHealthLoadState("loading");
    try {
      setSourceHealth(await getSourceHealth());
      setSourceHealthLoadState("ready");
    } catch {
      setSourceHealth(null);
      setSourceHealthLoadState("error");
    }
  }

  async function runCatalogUpdate(dryRun: boolean) {
    setLoading("catalog"); setError(null);
    try {
      const response = await runCatalogAutoUpdate({ selected_program_ids: selectedProgramIds, dry_run: dryRun, max_programs: selectedProgramIds.length ? Math.max(selectedProgramIds.length, 12) : 48, max_candidates_per_program: 6 });
      setCatalogAutoUpdate(response);
      if (!dryRun) { setEvidenceGraph(await getEvidenceGraphSummary()); setReviewQueue(await getReviewQueue({ limit: 80 })); setReviewPublishResult(null); await reloadSourceHealth(); }
    } catch (err) { setError(appErrorCopy.catalogUpdateFailed); }
    finally { setLoading(null); }
  }

  async function loadReviewQueue() {
    setLoading("review"); setError(null);
    try { setReviewQueue(await getReviewQueue({ limit: 80 })); setReviewPublishResult(null); setReviewBulkPublishResult(null); }
    catch (err) { setError(appErrorCopy.reviewQueueFailed); }
    finally { setLoading(null); }
  }

  async function loadScenarioAudit() {
    setLoading("scenario"); setError(null);
    try { setScenarioAudit(await getScenarioAudit()); }
    catch (err) { setError(appErrorCopy.scenarioAuditFailed); }
    finally { setLoading(null); }
  }

  async function publishReviewDecision(reviewId: string, decision: "approve" | "reject", persist = false) {
    setLoading("review"); setError(null);
    try {
      const response = await publishReviewItem({
        review_id: reviewId,
        decision,
        reviewer_id: "local_reviewer",
        reviewer_note: decision === "approve"
          ? persist ? "\u5df2\u6838\u5bf9\u5b66\u6821\u539f\u6587\uff0c\u53d1\u5e03\u5230\u5b66\u751f\u7aef\u3002" : "\u5df2\u6838\u5bf9\u5b66\u6821\u539f\u6587\uff0c\u9884\u89c8\u901a\u8fc7\u3002"
          : "\u5df2\u62d2\u7edd\u8be5\u5b57\u6bb5\u5019\u9009\uff0c\u9700\u8865\u5145\u66f4\u51c6\u786e\u6765\u6e90\u3002",
        persist,
      });
      setReviewPublishResult(response);
      if (persist && response.ok) {
        setReviewQueue(await getReviewQueue({ limit: 80 }));
        setEvidenceGraph(await getEvidenceGraphSummary());
        setCatalog(await getPrograms());
        await reloadSourceHealth();
      } else {
        setReviewQueue((previous) => previous ? { ...previous, items: previous.items.map((item) => item.review_id === response.item.review_id ? response.item : item) } : previous);
      }
    } catch (err) { setError(appErrorCopy.reviewPreviewFailed); }
    finally { setLoading(null); }
  }

  async function publishReviewBatchDecision(limit = 20, persist = true) {
    setLoading("review"); setError(null);
    try {
      const response = await publishReviewBatch({
        limit,
        persist,
        reviewer_id: "local_reviewer",
        reviewer_note: persist
          ? "Batch checked against official source evidence and published to student view."
          : "Batch checked against official source evidence in preview mode.",
      });
      setReviewBulkPublishResult(response);
      setReviewPublishResult(response.responses[0] ?? null);
      setReviewQueue(await getReviewQueue({ limit: 80 }));
      setEvidenceGraph(await getEvidenceGraphSummary());
      if (persist && response.published_count > 0) setCatalog(await getPrograms());
      if (persist) await reloadSourceHealth();
    } catch (err) { setError(appErrorCopy.reviewPreviewFailed); }
    finally { setLoading(null); }
  }

  async function runInterview() {
    setLoading("interview"); setError(null);
    try {
      const questions = await runWritingInterview({ profile: payload, selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || ""].filter(Boolean), document_type: writingDocumentType });
      setInterviewQuestions(questions);
    } catch (err) { setError(appErrorCopy.writingQuestionsFailed); }
    finally { setLoading(null); }
  }

  async function runWriting() {
    setLoading("writing"); setError(null);
    try {
      const response = await runWritingPlan({ profile: payload, questionnaire: buildQuestionnaireResponse(questionnaireSchema, questionnaireValues), selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || ""].filter(Boolean), document_type: writingDocumentType });
      mergeResult(response);
      setWritingReview(await runWritingReview({ draft: response.writing, story_cards: response.story_cards }));
    } catch (err) { setError(appErrorCopy.writingFailed); }
    finally { setLoading(null); }
  }

  async function useSampleProfile() {
    const sample = { ...demoPayload };
    persistPayload(sample);
    await runBackground(sample);
    await runPrograms(sample);
  }

  return (
    <Cursor>
      <main className="island-shell">
        <aside className="island-nav">
          <Link className="brand" href="/"><span className="brand-mark"><GraduationCap size={22} aria-hidden /></span><span><strong>HarborPilot</strong><small>港新硕士申请辅助平台</small></span></Link>
          <nav aria-label="主导航">{visibleNavItems.map((item) => <Link className={view === item.view ? "active" : ""} href={item.href} key={item.href}>{item.label}</Link>)}</nav>
          <div className="nav-footnote"><span className={`status-dot ${realModel ? "real" : "mock"}`} /><div><strong>{realModel ? dashboardCopy.navReady : dashboardCopy.navConfigured}</strong><small>{dashboardCopy.navNote}</small></div></div>
        </aside>
        <section className="island-workspace">
          <header className="workspace-topbar"><div><span className="eyebrow">2027 Fall / Hong Kong / Singapore</span><h1>{pageTitles[view]}</h1></div><span className="activity-button"><ShieldCheck size={18} aria-hidden />来源按官网展示</span></header>
          {error ? <div className="error-strip"><AlertTriangle size={18} aria-hidden /><span>{error}</span></div> : null}
          {loading ? <GlobalProgress stage={loading} /> : null}
          {!realModel && view === "agent" ? <AdminModelNotice onSample={useSampleProfile} /> : null}
          {view === "home" ? <DashboardView result={result} selectedMatches={selectedMatches} evidenceGraph={evidenceGraph} sourceHealth={sourceHealth} sourceHealthLoadState={sourceHealthLoadState} sourceRefresh={result?.source_refresh ?? null} loading={loading} onBackground={() => runBackground()} onPrograms={() => runPrograms()} onTimeline={runTimeline} onRefresh={() => refreshSources(false)} /> : null}
          {view === "assessment" ? <AssessmentPage payload={payload} setPayload={persistPayload} result={result} loading={loading} profileSaveStatus={profileSaveStatus} onRun={() => runBackground()} onRunPrograms={() => runPrograms(payload, true)} /> : null}
          {view === "programs" ? <ProgramCatalogPage payload={payload} catalog={visibleCatalog} catalogTotal={catalog.length} catalogError={catalogError} result={result} focusList={focusList} applicationMix={applicationMix} filters={filters} setFilters={setFilters} selectedProgramIds={selectedProgramIds} programScheme={programScheme} onSchemeChange={updateProgramScheme} onToggle={toggleProgram} onInspect={openProgramPackage} onRequestSourceUpdate={requestProgramSourceUpdate} onRun={() => runPrograms()} loading={loading} /> : null}
          {view === "timeline" ? <TimelinePage selectedMatches={selectedMatches} timeline={result?.timeline ?? []} loading={loading} onRun={runTimeline} onRefresh={() => refreshSources(false)} onTaskStatusChange={updateTimelineTaskStatus} /> : null}
          {view === "writing" ? <WritingWorkspace schema={questionnaireSchema} values={questionnaireValues} onChange={updateQuestionnaire} selectedProgramIds={selectedProgramIds} recommendations={writingProgramOptions} documentType={writingDocumentType} setDocumentType={setWritingDocumentType} targetProgramId={writingTargetProgramId} setTargetProgramId={setWritingTargetProgramId} questions={interviewQuestions} storyCards={result?.story_cards ?? []} writing={result?.writing} rubric={writingReview} draftHistory={writingDraftHistory} onDraftHistoryChange={updateWritingDraftHistory} loading={loading} onInterview={runInterview} onRun={runWriting} /> : null}
          {view === "agent" ? <AdminDataCenter evidenceGraph={evidenceGraph} runtimeWorkflows={runtimeWorkflows} modelProvider={health?.llm_provider ?? "mock"} modelName={health?.llm_mode ?? "mock"} runtimeMessage={runtimeMessage} runtimeBusy={runtimeBusy} sourceRegistry={sourceRegistry} sourceRefresh={result?.source_refresh ?? null} sourceAcquisition={sourceAcquisition} crawlQueue={crawlQueue} reviewQueue={reviewQueue} reviewPublishResult={reviewPublishResult} reviewBulkPublishResult={reviewBulkPublishResult} scenarioAudit={scenarioAudit} catalogAutoUpdate={catalogAutoUpdate} selectedProgramCount={selectedProgramIds.length} onRefresh={() => refreshSources(false)} onLiveRefresh={() => refreshSources(true)} onRunAcquisition={runAcquisition} onBuildCrawlQueue={buildCrawlQueue} onRunCatalogAutoUpdate={runCatalogUpdate} onLoadReviewQueue={loadReviewQueue} onLoadScenarioAudit={loadScenarioAudit} onPreviewReviewDecision={publishReviewDecision} onBulkPublishReview={publishReviewBatchDecision} onStartRuntimeWorkflow={startSupervisorWorkflow} onRefreshRuntimeWorkflows={refreshRuntimeWorkflows} loading={loading} /> : null}
          {view === "settings" ? <SettingsView currentProvider={health?.llm_provider ?? "mock"} currentModel={health?.llm_mode ?? "mock"} /> : null}
        </section>
        <ProgramPackageDrawer open={packageOpen} onClose={() => setPackageOpen(false)} dataPackage={programPackage} />
      </main>
      <Footer type="sea" />
    </Cursor>
  );
}

function DashboardView(props: { result: AppState | null; selectedMatches: ProgramMatch[]; evidenceGraph: EvidenceGraphSummary | null; sourceHealth: SourceHealthSummary | null; sourceHealthLoadState: SourceHealthLoadState; sourceRefresh: DataRefreshReport | null; loading: StageLoading; onBackground: () => void; onPrograms: () => void; onTimeline: () => void; onRefresh: () => void; }) {
  const assessmentReady = Boolean(props.result?.assessment);
  const planReady = Boolean(props.result?.focus_list?.length || props.result?.recommendations?.length);
  const timelineReady = Boolean(props.result?.timeline?.length);
  const stepDone: Record<string, boolean> = {
    assessment: assessmentReady,
    programs: planReady,
    selection: props.selectedMatches.length > 0,
    timeline: timelineReady,
    writing: Boolean(props.result?.writing),
  };
  return <div className="page-stack">
    <IslandCard className="hero-card" color="app-teal" pattern="app-yellow"><div><span className="mini-label"><Sparkles size={16} aria-hidden />{dashboardCopy.heroEyebrow}</span><h2>{dashboardCopy.heroTitle}</h2><p>{dashboardCopy.heroBody}</p></div><div className="hero-actions"><IslandButton type="primary" loading={props.loading === "background"} onClick={props.onBackground}>{dashboardCopy.runBackground}</IslandButton><IslandButton type="default" loading={props.loading === "programs"} onClick={props.onPrograms}>{dashboardCopy.runPrograms}</IslandButton><IslandButton type="dashed" loading={props.loading === "data"} onClick={props.onRefresh}>{dashboardCopy.refreshSources}</IslandButton></div></IslandCard>
    <section className="status-grid"><Metric label={dashboardCopy.metrics.profile.label} value={`${props.result?.profile?.profile_completeness ?? 0}%`} detail={dashboardCopy.metrics.profile.detail} /><Metric label={dashboardCopy.metrics.decision.label} value={`${props.result?.assessment?.decision_field_coverage ?? 0}%`} detail={dashboardCopy.metrics.decision.detail} /><Metric label={dashboardCopy.metrics.evidence.label} value={`${props.result?.assessment?.evidence_coverage ?? Math.round((props.result?.evidence?.verified_fact_ratio ?? 0) * 100)}%`} detail={dashboardCopy.metrics.evidence.detail} /><Metric label={dashboardCopy.metrics.source.label} value={`${props.evidenceGraph?.field_record_count ?? 0}`} detail={`${props.evidenceGraph?.verified_field_count ?? 0} ${dashboardCopy.metrics.source.verifiedSuffix}`} /></section>
    <IslandCard className="panel-card"><PanelTitle icon={<ClipboardList size={19} aria-hidden />} title={dashboardCopy.nextTitle} /><div className="next-step-list">{dashboardCopy.nextSteps.map((step) => <StepItem done={stepDone[step.key] ?? false} title={step.title} detail={step.detail} href={step.href} key={step.key} />)}</div></IslandCard>
    <SourceHealthStrip health={props.sourceHealth} loadState={props.sourceHealthLoadState} />
    <section className="two-column"><IslandCard className="panel-card"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title={dashboardCopy.applicationList} /><ProgramMiniList matches={props.selectedMatches} /><div className="card-actions"><IslandButton type="primary" loading={props.loading === "timeline"} onClick={props.onTimeline}>{dashboardCopy.runTimeline}</IslandButton><Link className="text-link" href="/programs">{dashboardCopy.adjustPrograms}</Link></div></IslandCard><IslandCard className="panel-card" type="dashed"><PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title={dashboardCopy.trustTitle} /><SourceRefreshSummary report={props.sourceRefresh} evidenceGraph={props.evidenceGraph} /></IslandCard></section>
  </div>;
}

function AdminModelNotice({ onSample }: { onSample: () => void }) {
  return <IslandCard className="key-card compact" color="app-yellow" pattern="default"><div className="key-card-copy"><span className="mini-label"><ShieldCheck size={16} aria-hidden />运行时策略</span><h2>当前使用确定性示例 Provider。</h2><p>模型供应商、密钥和兼容地址只由管理员在受保护的服务端配置；学生端不会提交或存储 API Key。</p></div><div className="key-actions"><IslandButton type="default" onClick={onSample}>使用示例档案体验</IslandButton><Link className="text-link" href="/settings">查看运行时状态</Link></div></IslandCard>;
}

function SettingsView(props: { currentProvider: string; currentModel: string }) {
  const connected = props.currentProvider !== "mock";
  return <div className="page-stack">
    <IslandCard className="panel-card" color="app-teal"><PanelTitle icon={<Settings size={19} aria-hidden />} title="AI 运行时状态" /><p className="form-note">为保护所有学生资料，模型 Provider、API Key 与兼容接口地址由管理员在服务端统一管理。该页面仅显示当前运行时，不提供匿名配置入口。</p></IslandCard>
    <IslandCard className="key-card" color="app-yellow" pattern="default"><div className="key-card-copy"><span className="mini-label"><ShieldCheck size={16} aria-hidden />受保护配置</span><h2>学生端不接触模型密钥</h2><p>Supervisor Runtime 只记录经过脱敏的执行摘要、Token 用量和已配置价格的真实成本；API Key 不会写入浏览器、本地工作区或 Trace。</p></div></IslandCard>
    <IslandCard className="panel-card"><PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="当前状态" /><section className="status-grid two"><Metric label="AI 服务" value={connected ? providerLabel(props.currentProvider) : "示例模式"} detail={connected ? "由管理员授权的 Provider" : "无外部密钥的确定性运行"} /><Metric label="当前模型" value={props.currentModel} detail="用于受权限约束的 Agent 决策与工具调用" /></section></IslandCard>
  </div>;
}
function providerLabel(value: string) {
  return ({ deepseek: "DeepSeek", openai: "OpenAI", compatible: "兼容接口", mock: "示例模式" } as Record<string, string>)[value] ?? value;
}

function GlobalProgress({ stage }: { stage: StageLoading }) {
  if (!stage) return null;
  const detail = progressCopy[stage as keyof typeof progressCopy] as { title: string; steps: readonly string[] };
  return <IslandCard className="progress-card" color="app-teal"><div className="progress-head"><strong>{detail.title}</strong><span>{progressCopy.doneMessage}</span></div><div className="progress-track"><span /></div><div className="progress-steps">{detail.steps.map((step) => <span key={step}>{step}</span>)}</div></IslandCard>;
}

function applyProgramSchemeToMatch(item: ProgramMatch, scheme: ProgramSchemeState): ProgramMatch {
  const band = scheme.band_overrides?.[item.program.id] as ProgramMatch["strategy_band"] | undefined;
  if (!band) return item;
  return { ...item, strategy_band: band, tier: band === "blocked" ? "not_recommended" : band };
}

function catalogProgramToCandidateMatch(program: CatalogProgram): ProgramMatch {
  return { program, tier: "candidate", fit_score: 0, score_breakdown: { academic: 0, language: 0, experience: 0, discipline_fit: 0, budget_fit: 0, data_trust: 0 }, match_category: "general", intent_alignment: 0, intent_reasons: ["学生从全量项目库加入"], hard_rule_passed: false, formal_recommendation: false, data_status: program.data_status, reasons: ["学生从全量项目库加入申请清单，需要结合背景评估进一步核对。"], risks: [studentTrustWarning(program.trust_detail, "项目详情页、申请入口和关键日期需要按来源逐项复核。")], actions: ["打开项目详情页和申请入口，核对轮次、DDL、材料和提交方式。"], strategy_band: "candidate", consultant_note: "学生手动加入的清单项目", source_warning: studentTrustWarning(program.trust_detail, "关键信息需要按来源逐项复核。") };
}

function buildQuestionnaireResponse(schema: QuestionnaireSchema | null, values: QuestionnaireValues): QuestionnaireResponse {
  const profileSectionIds = new Set(["cv_education", "cv_experience", "cv_research_projects", "cv_awards_skills"]);
  const recommenderSectionIds = new Set(["reference_recommender_profile", "reference_relationship", "reference_course_performance", "reference_activity_project", "reference_specific_impression", "reference_competency_events"]);
  const profile_answers: QuestionnaireResponse["profile_answers"] = [];
  const statement_answers: QuestionnaireResponse["statement_answers"] = [];
  const recommender_answers: QuestionnaireResponse["recommender_answers"] = [];

  for (const section of schema?.sections ?? []) {
    for (const field of section.fields) {
      const value = values[field.id]?.trim();
      if (field.sensitive || !value) continue;
      const answer = { field_id: field.id, value, evidence_ids: [`questionnaire:${section.id}:${field.id}`] };
      if (recommenderSectionIds.has(section.id)) recommender_answers.push(answer);
      else if (profileSectionIds.has(section.id)) profile_answers.push(answer);
      else statement_answers.push(answer);
    }
  }
  return { profile_answers, statement_answers, recommender_answers };
}


function PanelTitle({ icon, title }: { icon: React.ReactNode; title: string }) { return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>; }
function StepItem({ done, title, detail, href }: { done: boolean; title: string; detail: string; href: string }) { return <Link className={`step-item ${done ? "done" : ""}`} href={href}><CheckCircle2 size={18} aria-hidden /><span><strong>{title}</strong><small>{detail}</small></span></Link>; }
function SourceHealthStrip({ health, loadState }: { health: SourceHealthSummary | null; loadState: SourceHealthLoadState }) {
  if (loadState === "loading") {
    return <IslandCard className="panel-card source-health-strip" type="dashed"><PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title="信息获取 Agent" /><p className="form-note">正在读取官网来源运行记录…</p></IslandCard>;
  }
  if (loadState === "error" || !health) {
    return <IslandCard className="panel-card source-health-strip" type="dashed"><PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title="信息获取 Agent" /><p className="form-note">来源健康度暂不可用；不影响已保存的学生资料。</p></IslandCard>;
  }

  const allNeverRun = health.total_sources > 0 && health.never_run_sources === health.total_sources;
  const status = allNeverRun
    ? "尚未执行真实官网抓取"
    : health.failing_sources > 0
      ? "最近一次抓取存在失败"
      : health.stale_sources > 0
        ? "有来源需要重新核验"
        : health.due_sources > 0
          ? "有来源接近刷新周期"
          : health.healthy_sources === health.total_sources && health.total_sources > 0
            ? "全部已登记来源状态正常"
            : "仍有来源等待首次抓取";
  return <IslandCard className="panel-card source-health-strip" type="dashed"><PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title="信息获取 Agent" /><div className="status-grid three"><Metric label="健康来源" value={String(health.healthy_sources) + "/" + String(health.total_sources)} detail={status} /><Metric label="待处理来源" value={String(health.due_sources + health.stale_sources + health.never_run_sources)} detail={String(health.never_run_sources) + " 个未首次抓取 · " + String(health.failing_sources) + " 个最近失败"} /><Metric label="全库待审字段" value={String(health.pending_review_count)} detail="由运营审核，审核前不进入正式时间线" /></div><p className="form-note">索引页只负责发现项目链接；截止日期、学费、语言和材料必须绑定项目详情页快照。</p></IslandCard>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
