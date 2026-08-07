"use client";

import { Button as IslandButton, Card as IslandCard, Tabs as IslandTabs, Title as IslandTitle } from "animal-island-ui";
import { ArrowRight, Bot, BookOpenCheck, CalendarDays, CheckCircle2, Clock3, Database, ExternalLink, Play, RefreshCw, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { dataStatusLabels, fieldLabels } from "@/lib/copy";
import { getRuntimeWorkflow, getRuntimeWorkflowState, getRuntimeWorkflowTrace, resumeRuntimeWorkflow } from "@/lib/api";
import { ReviewQueuePanel } from "./admin/ReviewQueuePanel";
import type {
  CatalogAutoUpdateReport,
  CrawlQueueReport,
  DataAcquisitionReport,
  DataRefreshReport,
  EvidenceGraphSummary,
  FieldEvidenceRecord,
  ProgramDataPackage,
  ReviewBulkPublishResponse,
  ReviewPublishResponse,
  ReviewQueueSummary,
  RuntimeTraceEvent,
  RuntimeWorkflowGoal,
  RuntimeWorkflowListItem,
  RuntimeWorkflowState,
  RuntimeWorkflowStatus,
  RuntimeWorkflowTask,
  ScenarioAuditReport,
  SourceExtractionResult,
  SourceRegistry,
} from "@/lib/types";

type Props = {
  evidenceGraph: EvidenceGraphSummary | null;
  runtimeWorkflows: RuntimeWorkflowListItem[];
  modelProvider: string;
  modelName: string;
  runtimeMessage: string;
  runtimeBusy: boolean;
  sourceRegistry: SourceRegistry | null;
  sourceRefresh: DataRefreshReport | null;
  sourceAcquisition: DataAcquisitionReport | null;
  crawlQueue: CrawlQueueReport | null;
  reviewQueue: ReviewQueueSummary | null;
  reviewPublishResult: ReviewPublishResponse | null;
  reviewBulkPublishResult: ReviewBulkPublishResponse | null;
  scenarioAudit: ScenarioAuditReport | null;
  catalogAutoUpdate: CatalogAutoUpdateReport | null;
  selectedProgramCount: number;
  onRefresh: () => void;
  onLiveRefresh: () => void;
  onRunAcquisition: (dryRun: boolean) => void;
  onBuildCrawlQueue: () => void;
  onRunCatalogAutoUpdate: (dryRun: boolean) => void;
  onLoadReviewQueue: () => void;
  onLoadScenarioAudit: () => void;
  onPreviewReviewDecision: (reviewId: string, decision: "approve" | "reject", persist?: boolean) => void;
  onBulkPublishReview: (limit?: number, persist?: boolean) => void;
  onStartRuntimeWorkflow: (goal: RuntimeWorkflowGoal) => Promise<RuntimeWorkflowState | null>;
  onRefreshRuntimeWorkflows: () => Promise<void>;
  loading: string | null;
};

export function AdminDataCenter(props: Props) {
  const tabs = [
    { key: "refresh", label: "Source check", children: <SourceRefreshSummary report={props.sourceRefresh} evidenceGraph={props.evidenceGraph} /> },
    { key: "acquisition", label: "Crawler review", children: <AcquisitionPanel report={props.sourceAcquisition} loading={props.loading === "data"} onRun={props.onRunAcquisition} /> },
    { key: "catalog", label: "Program URL candidates", children: <CatalogAutoUpdatePanel report={props.catalogAutoUpdate} loading={props.loading === "catalog"} onRun={props.onRunCatalogAutoUpdate} /> },
    { key: "review", label: "Review queue", children: <ReviewQueuePanel report={props.reviewQueue} publishResult={props.reviewPublishResult} bulkPublishResult={props.reviewBulkPublishResult} loading={props.loading === "review"} onLoad={props.onLoadReviewQueue} onDecision={props.onPreviewReviewDecision} onBulkPublish={props.onBulkPublishReview} /> },
    { key: "records", label: "Field evidence", children: <EvidenceRecordList records={props.evidenceGraph?.sample_records ?? []} /> },
    { key: "sources", label: "Source registry", children: <SourceRegistryList registry={props.sourceRegistry} /> },
    { key: "queue", label: "Crawl queue", children: <CrawlQueuePanel report={props.crawlQueue} /> },
    { key: "scenario", label: "Scenario audit", children: <ScenarioAuditPanel report={props.scenarioAudit} loading={props.loading === "scenario"} onLoad={props.onLoadScenarioAudit} /> },
  ];
  return <div className="page-stack">
    <IslandCard className="panel-card" color="app-yellow">
      <div className="split-head">
        <div>
          <span className="mini-label"><Database size={16} aria-hidden />Admin data center</span>
          <h2>Field-level sources, crawler snapshots, candidate URLs, and human release gates</h2>
          <p>Use this page to review official programme pages, application portals, deadlines, language rules, materials, and tuition before publishing fields to students.</p>
        </div>
        <div className="card-actions">
          <IslandButton type="default" loading={props.loading === "catalog"} onClick={() => props.onRunCatalogAutoUpdate(true)}>Preview URL candidates</IslandButton>
          <IslandButton type="primary" loading={props.loading === "catalog"} onClick={() => props.onRunCatalogAutoUpdate(false)}>Write review queue</IslandButton>
          <IslandButton type="default" loading={props.loading === "crawl"} onClick={props.onBuildCrawlQueue}>Build crawl queue</IslandButton>
          <IslandButton type="default" loading={props.loading === "review"} onClick={props.onLoadReviewQueue}>Load review queue</IslandButton>
          <IslandButton type="default" loading={props.loading === "scenario"} onClick={props.onLoadScenarioAudit}>Run scenario audit</IslandButton>
          <IslandButton type="default" loading={props.loading === "data"} onClick={props.onRefresh}>Check source freshness</IslandButton>
          <IslandButton type="primary" loading={props.loading === "data"} onClick={() => props.onRunAcquisition(false)}>Run live crawler</IslandButton>
        </div>
      </div>
    </IslandCard>
    <AgentRuntimePanel runtimeWorkflows={props.runtimeWorkflows} modelProvider={props.modelProvider} modelName={props.modelName} runtimeMessage={props.runtimeMessage} runtimeBusy={props.runtimeBusy} onStartRuntimeWorkflow={props.onStartRuntimeWorkflow} onRefreshRuntimeWorkflows={props.onRefreshRuntimeWorkflows} />
    <section className="status-grid">
      <Metric label="Programs" value={`${props.evidenceGraph?.program_count ?? 0}`} detail="Local HK/SG taught-master catalog" />
      <Metric label="Field records" value={`${props.evidenceGraph?.field_record_count ?? 0}`} detail="Field-level source bindings" />
      <Metric label="Current verified" value={`${props.evidenceGraph?.verified_field_count ?? 0}`} detail="Required for formal use" />
      <Metric label="Need review" value={`${props.evidenceGraph?.pending_review_field_count ?? 0}`} detail="Operator must inspect source text" />
      <Metric label="Supervisor workflows" value={`${props.runtimeWorkflows.length}`} detail="真实执行状态与 checkpoint" />
      <Metric label="Selected programs" value={`${props.selectedProgramCount}`} detail="Prioritized for crawling" />
    </section>
    <IslandTabs className="animal-tabs" defaultActiveKey="acquisition" items={tabs} />
  </div>;
}

export function SourceRefreshSummary({ report, evidenceGraph }: { report: DataRefreshReport | null; evidenceGraph?: EvidenceGraphSummary | null }) {
  if (!report && !evidenceGraph) return <EmptyState text="No source check results yet." />;
  return <div className="source-report">
    <section className="status-grid three">
      <Metric label="Field records" value={`${evidenceGraph?.field_record_count ?? report?.field_evidence_records.length ?? 0}`} detail="deadline / tuition / language / materials" />
      <Metric label="Official sources" value={`${evidenceGraph?.official_source_count ?? report?.official_sources_checked ?? 0}`} detail="school site, programme page, portal" />
      <Metric label="Need review" value={`${report?.review_queue_size ?? evidenceGraph?.pending_review_field_count ?? 0}`} detail="review against source text" />
    </section>
    {report ? <><p className="form-note">{report.summary}</p><AdviceList title="Next actions" items={report.next_actions ?? []} /></> : null}
  </div>;
}

function AcquisitionPanel({ report, loading, onRun }: { report: DataAcquisitionReport | null; loading: boolean; onRun: (dryRun: boolean) => void }) {
  if (!report) return <div className="source-report">
    <p>The acquisition agent saves official HTML/PDF snapshots, creates page hashes, extracts field candidates, and routes candidates to human review.</p>
    <div className="card-actions"><IslandButton type="default" loading={loading} onClick={() => onRun(true)}>Preview plan</IslandButton><IslandButton type="primary" loading={loading} onClick={() => onRun(false)}>Run live crawler</IslandButton></div>
  </div>;
  return <div className="source-report">
    <section className="status-grid three"><Metric label="Packages" value={`${report.packages.length}`} detail={report.mode === "live_fetch" ? "live fetch" : "dry run"} /><Metric label="Extraction results" value={`${report.extraction_results.length}`} detail="HTML/PDF parser output" /><Metric label="Persisted evidence" value={`${report.persisted_evidence_count}`} detail="SQLite review candidates" /></section>
    <p className="form-note">{report.summary}</p>
    <AdviceList title="Crawler capabilities" items={report.crawler_capabilities} />
    <ExtractionCompareList results={report.extraction_results} />
    <EvidenceRecordList records={report.field_evidence_records} />
  </div>;
}

function ExtractionCompareList({ results }: { results: SourceExtractionResult[] }) {
  if (!results.length) return <EmptyState text="No snapshot extraction result yet." />;
  return <div className="evidence-list">{results.slice(0, 24).map((item) => <article key={`${item.source_id}-${item.page_hash ?? item.extracted_at}`}>
    <div className="program-title-row"><strong>{item.source_id}</strong><span className="tier-pill">{item.parser}</span></div>
    <p>{String(item.raw_json?.status ?? "Extraction result created")}</p>
    <div className="task-meta"><span>Fields {item.extracted_fields.length}</span><span>Unresolved {item.unresolved_fields.length}</span><span>{item.page_hash?.slice(0, 19) ?? "no hash"}</span></div>
    {item.snapshot_path ? <span className="form-note">Snapshot: {item.snapshot_path}</span> : null}
    {item.source_url ? <a className="text-link" href={item.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a> : null}
    <div className="coverage-list">{item.extracted_fields.slice(0, 8).map((field) => <article key={`${item.source_id}-${field.field_name}`}><div className="program-title-row"><strong>{fieldLabels[field.field_name] ?? field.field_name}</strong><span className="tier-pill">{field.confidence}</span></div><p>{field.evidence_snippet ?? field.value ?? "Inspect snapshot text manually"}</p></article>)}</div>
  </article>)}</div>;
}

function CatalogAutoUpdatePanel({ report, loading, onRun }: { report: CatalogAutoUpdateReport | null; loading: boolean; onRun: (dryRun: boolean) => void }) {
  if (!report) return <div className="source-report"><p>Preview missing programme-detail pages and write credible candidates to the review queue.</p><div className="card-actions"><IslandButton type="default" loading={loading} onClick={() => onRun(true)}>Preview candidates</IslandButton><IslandButton type="primary" loading={loading} onClick={() => onRun(false)}>Write review queue</IslandButton></div></div>;
  return <div className="source-report"><section className="status-grid three"><Metric label="Scanned" value={`${report.scanned_program_count}`} detail="programs processed" /><Metric label="Missing detail" value={`${report.missing_detail_page_count}`} detail="need official programme page" /><Metric label="Candidates" value={`${report.candidate_count}`} detail={`${report.persisted_candidate_count} persisted`} /></section><p className="form-note">{report.summary}</p><div className="evidence-list">{report.candidates.slice(0, 20).map((candidate) => <article key={`${candidate.program_id}-${candidate.candidate_url}`}><div className="program-title-row"><strong>{candidate.program_name}</strong><DataBadge status={candidate.status} /></div><p>{candidate.reason}</p><div className="task-meta"><span>{candidate.institution}</span><span>Match {Math.round(candidate.match_score * 100)}%</span><span>{candidate.review_required ? "needs review" : "publishable"}</span></div><a className="text-link" href={candidate.candidate_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />Open candidate</a></article>)}</div><AdviceList title="Warnings" items={report.warnings} /></div>;
}

function EvidenceRecordList({ records }: { records: FieldEvidenceRecord[] }) {
  if (!records.length) return <EmptyState text="No field evidence records yet." />;
  return <div className="evidence-list">{records.slice(0, 24).map((record) => <article key={`${record.program_id}-${record.field_name}-${record.page_hash ?? record.source_url ?? "field"}`}><div className="program-title-row"><strong>{fieldLabels[record.field_name] ?? record.field_name}</strong><DataBadge status={record.status} /></div><p>{record.evidence_snippet ?? record.value ?? "Waiting for official excerpt."}</p><div className="task-meta"><span>{record.cycle ?? "cycle to verify"}</span><span>priority {record.source_priority}</span><span>confidence {record.confidence}</span></div>{record.snapshot_url ? <span className="form-note">Snapshot: {record.snapshot_url}</span> : null}{record.source_url ? <a className="text-link" href={record.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a> : null}</article>)}</div>;
}

function SourceRegistryList({ registry }: { registry: SourceRegistry | null }) { if (!registry) return <EmptyState text="Source registry not loaded." />; return <div className="source-list">{registry.sources.slice(0, 24).map((source) => <article key={source.source_id}><div><strong>{source.name}</strong><span>{source.trust_level}</span></div><p>{source.allowed_uses?.[0] ?? "usage pending"}</p><a href={source.url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a></article>)}</div>; }
function CrawlQueuePanel({ report }: { report: CrawlQueueReport | null }) { if (!report) return <EmptyState text="Crawl queue has not been built." />; return <div className="source-report"><section className="status-grid three"><Metric label="Jobs" value={`${report.job_count}`} detail="crawl queue" /><Metric label="Official" value={`${report.official_job_count}`} detail="pages, portals, PDFs" /><Metric label="Community" value={`${report.community_job_count}`} detail="reference only" /></section><AdviceList title="Warnings" items={report.warnings} /><div className="evidence-list">{report.items.slice(0, 20).map((item) => <article key={item.job_id}><div className="program-title-row"><strong>{item.name}</strong><span className="tier-pill">{item.trust_level}</span></div><p>{item.publish_boundary}</p><div className="task-meta"><span>{item.fetch_method}</span><span>{item.parser}</span><span>priority {item.priority}</span></div><a className="text-link" href={item.url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a></article>)}</div></div>; }
function ScenarioAuditPanel({ report, loading, onLoad }: { report: ScenarioAuditReport | null; loading: boolean; onLoad: () => void }) { if (!report) return <div className="source-report"><p>Run scenario audits to check matching strictness, source boundaries, and human gates.</p><IslandButton type="primary" loading={loading} onClick={onLoad}>Run scenario audit</IslandButton></div>; return <div className="source-report"><section className="status-grid three"><Metric label="Result" value={report.passed ? "passed" : "failed"} detail="workflow audit" /><Metric label="Cases" value={`${report.case_count}`} detail="simulated profiles" /><Metric label="Failures" value={`${report.failure_count}`} detail="should be zero" /></section><AdviceList title="Failures" items={report.failures} /><div className="evidence-list">{report.cases.map((item) => <article key={item.name}><div className="program-title-row"><strong>{item.name}</strong><span className="tier-pill">{item.passed ? "passed" : "failed"}</span></div><AdviceList title="Issues" items={item.failures} /><div className="task-meta"><span>recommendations {item.application_mix_count}</span><span>official {item.crawl_queue.official_job_count}</span><span>community {item.crawl_queue.community_job_count}</span></div></article>)}</div></div>; }

export function ProgramPackageDrawer({ open, onClose, dataPackage }: { open: boolean; onClose: () => void; dataPackage: ProgramDataPackage | null }) {
  if (!open) return null;
  return <div className="drawer-backdrop" role="presentation" onClick={onClose}><aside className="decision-drawer program-package-drawer" role="dialog" aria-label="项目信息与来源" onClick={(event) => event.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow">项目信息与来源</span><h2>{dataPackage ? `${dataPackage.institution} - ${dataPackage.program_name}` : "项目信息"}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18} aria-hidden /></button></div>{!dataPackage ? <EmptyState text="项目信息正在加载。" /> : <div className="package-stack"><section className="status-grid two"><Metric label="时间线状态" value={dataPackage.production_ready ? "可生成正式时间线" : "关键信息需要复核"} detail={dataPackage.human_review_required ? "复核来源页面" : "来源可用"} /><Metric label="官方记录" value={`${dataPackage.official_requirements.length}`} detail="项目页、网申入口或官方 PDF" /></section><p className="form-note">{dataPackage.freshness_warning}</p><IslandCard className="panel-card"><PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title="关键信息" /><CoverageAuditList items={dataPackage.coverage_items} /></IslandCard><IslandCard className="panel-card"><PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title="官方要求" /><EvidenceRecordList records={dataPackage.official_requirements} /></IslandCard><IslandCard className="panel-card"><PanelTitle icon={<BookOpenCheck size={18} aria-hidden />} title="项目内容" /><div className="package-section-list">{dataPackage.content_sections.map((section) => <article key={section.section_id}><div className="program-title-row"><strong>{section.title}</strong><DataBadge status={section.source_status} /></div><p>{section.summary}</p>{section.evidence_snippet ? <small>{section.evidence_snippet}</small> : null}{section.source_url ? <a className="text-link" href={section.source_url} target="_blank" rel="noreferrer">打开来源</a> : null}</article>)}</div></IslandCard><IslandCard className="panel-card"><PanelTitle icon={<CalendarDays size={18} aria-hidden />} title="文书与时间线信息" /><EvidenceRecordList records={[...dataPackage.essay_prompts, ...dataPackage.timeline_fields]} /></IslandCard></div>}</aside></div>;
}

function CoverageAuditList({ items }: { items: ProgramDataPackage["coverage_items"] }) { if (!items.length) return <EmptyState text="No coverage audit generated." />; return <div className="coverage-list">{items.map((item) => <article className={item.blocks_formal_use ? "coverage-item blocked" : "coverage-item ready"} key={item.field_name}><div className="program-title-row"><strong>{fieldLabels[item.field_name] ?? item.field_name}</strong><DataBadge status={item.status} /></div><p>{item.next_action}</p><div className="task-meta"><span>{item.has_value ? "has candidate" : "missing current field"}</span><span>{item.blocks_formal_use ? "blocks formal use" : "planning only"}</span><span>{item.required_source === "official" ? "official source" : "public reference"}</span></div>{item.source_url ? <a className="text-link" href={item.source_url} target="_blank" rel="noreferrer">打开来源</a> : null}</article>)}</div>; }

const workflowGoals: Array<{ goal: RuntimeWorkflowGoal; label: string; detail: string }> = [
  { goal: "full_application_plan", label: "完整申请方案", detail: "评估、择校、核验、规划" },
  { goal: "program_recommendation", label: "项目推荐", detail: "召回、匹配、证据核验" },
  { goal: "background_assessment", label: "背景评估", detail: "资料完整度与关键缺口" },
  { goal: "application_planning", label: "申请规划", detail: "已选项目的准备节奏" },
  { goal: "writing", label: "文书准备", detail: "事实边界与写作任务" },
];

function AgentRuntimePanel({ runtimeWorkflows, modelProvider, modelName, runtimeMessage, runtimeBusy, onStartRuntimeWorkflow, onRefreshRuntimeWorkflows }: { runtimeWorkflows: RuntimeWorkflowListItem[]; modelProvider: string; modelName: string; runtimeMessage: string; runtimeBusy: boolean; onStartRuntimeWorkflow: (goal: RuntimeWorkflowGoal) => Promise<RuntimeWorkflowState | null>; onRefreshRuntimeWorkflows: () => Promise<void> }) {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(runtimeWorkflows[0]?.workflow_id ?? null);
  const [workflowState, setWorkflowState] = useState<RuntimeWorkflowState | null>(null);
  const [trace, setTrace] = useState<RuntimeTraceEvent[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  useEffect(() => {
    if (!runtimeWorkflows.length) {
      setSelectedWorkflowId(null);
      setWorkflowState(null);
      setTrace([]);
      return;
    }
    setSelectedWorkflowId((current) => runtimeWorkflows.some((item) => item.workflow_id === current) ? current : runtimeWorkflows[0].workflow_id);
  }, [runtimeWorkflows]);

  useEffect(() => {
    if (!selectedWorkflowId) return;
    let active = true;
    setDetailLoading(true);
    Promise.all([getRuntimeWorkflow(selectedWorkflowId), getRuntimeWorkflowTrace(selectedWorkflowId)])
      .then(([state, events]) => {
        if (!active) return;
        setWorkflowState(state);
        setTrace(events);
        setMessage("");
      })
      .catch((error: unknown) => {
        if (active) setMessage(error instanceof Error ? error.message : "无法读取工作流状态。");
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [selectedWorkflowId]);

  async function refreshSelectedCheckpoint() {
    if (!selectedWorkflowId) return;
    setDetailLoading(true);
    try {
      const [state, events] = await Promise.all([getRuntimeWorkflowState(selectedWorkflowId), getRuntimeWorkflowTrace(selectedWorkflowId)]);
      setWorkflowState(state);
      setTrace(events);
      setMessage("已读取最新 checkpoint 与执行轨迹。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法刷新工作流。");
    } finally {
      setDetailLoading(false);
    }
  }

  async function startWorkflow(goal: RuntimeWorkflowGoal) {
    setMessage("");
    try {
      const state = await onStartRuntimeWorkflow(goal);
      if (!state) return;
      setSelectedWorkflowId(state.workflow_id);
      setWorkflowState(state);
      setResumeText("");
      setTrace(await getRuntimeWorkflowTrace(state.workflow_id));
      setMessage(`已启动 ${goalLabel(state.goal)}：${statusLabel(state.status)}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法启动工作流。");
    }
  }

  async function resumeWorkflow() {
    if (!workflowState) return;
    const waitingForUser = workflowState.status === "WAITING_USER";
    if (waitingForUser && !resumeText.trim()) {
      setMessage("请先填写对学生问题的补充，再继续工作流。");
      return;
    }
    setDetailLoading(true);
    try {
      const state = await resumeRuntimeWorkflow(workflowState.workflow_id, waitingForUser
        ? { user_message: resumeText.trim() }
        : { human_resolution: resumeText.trim() || "管理员确认后继续执行。" });
      setWorkflowState(state);
      setResumeText("");
      setTrace(await getRuntimeWorkflowTrace(state.workflow_id));
      await onRefreshRuntimeWorkflows();
      setMessage(`已继续执行：${statusLabel(state.status)}。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法继续该工作流。");
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshWorkflowList() {
    try {
      await onRefreshRuntimeWorkflows();
      await refreshSelectedCheckpoint();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "无法刷新工作流列表。");
    }
  }

  const pricedEvents = trace.filter((event) => event.cost_usd !== null);
  const totalCost = pricedEvents.length ? pricedEvents.reduce((total, event) => total + (event.cost_usd ?? 0), 0) : null;
  const totalTokens = trace.reduce((total, event) => total + (event.total_tokens ?? 0), 0);
  const currentTask = workflowState?.tasks.find((task) => task.status === "RUNNING") ?? workflowState?.tasks.find((task) => task.status === "BLOCKED") ?? null;
  const canResume = workflowState?.status === "WAITING_USER" || workflowState?.status === "WAITING_HUMAN" || workflowState?.status === "FAILED_RETRYABLE";

  return <IslandCard className="panel-card agent-runtime-panel runtime-workbench">
    <div className="runtime-workbench-head">
      <div>
        <span className="mini-label"><Bot size={16} aria-hidden />Supervisor Runtime</span>
        <h2>真实工作流、共享状态与执行证据</h2>
        <p>这里只展示 Runtime 实际写入的路由、Agent、工具与 checkpoint；不再用预设 Agent 链或估算成本填充界面。</p>
      </div>
      <div className="runtime-model-badge">
        <span>{modelProvider === "mock" ? "deterministic runtime" : "provider connected"}</span>
        <strong>{modelName}</strong>
        <small>{modelProvider}</small>
      </div>
    </div>

    <section className="runtime-launchbar" aria-label="启动 Supervisor 工作流">
      <div><strong>从当前学生资料启动</strong><span>每次运行均创建独立 workflow，并在每个 Agent turn 后保存 checkpoint。</span></div>
      <div className="runtime-goal-actions">
        {workflowGoals.map((item) => <button key={item.goal} type="button" className={item.goal === "full_application_plan" ? "runtime-start primary" : "runtime-start"} onClick={() => void startWorkflow(item.goal)} disabled={runtimeBusy} title={item.detail}>
          <Play size={14} aria-hidden />{item.label}
        </button>)}
      </div>
    </section>

    <section className="runtime-overview" aria-label="运行时摘要">
      <Metric label="工作流历史" value={`${runtimeWorkflows.length}`} detail="来自 /api/agent/workflows" />
      <Metric label="当前 Agent" value={workflowState?.current_agent ?? "待选择"} detail={currentTask?.description ?? "选择一条工作流查看实时状态"} />
      <Metric label="实际 Token" value={totalTokens ? totalTokens.toLocaleString("zh-CN") : "—"} detail={trace.length ? `${trace.length} 个 Trace 事件` : "尚未读取 Trace"} />
      <Metric label="实际成本" value={formatCost(totalCost)} detail={totalCost === null ? "当前模型未配置价格" : "按 Provider usage 与 pricing 计算"} />
    </section>

    {runtimeMessage || message ? <p className="runtime-feedback" role="status">{message || runtimeMessage}</p> : null}

    <div className="runtime-workbench-grid">
      <section className="runtime-pane runtime-history-pane">
        <div className="runtime-pane-head"><div><span>工作流历史</span><h3>最近执行</h3></div><button type="button" className="runtime-icon-button" onClick={() => void refreshWorkflowList()} disabled={detailLoading} aria-label="刷新工作流"><RefreshCw size={16} aria-hidden /></button></div>
        {runtimeWorkflows.length ? <div className="runtime-workflow-list">{runtimeWorkflows.slice(0, 16).map((workflow) => <button type="button" key={workflow.workflow_id} className={`runtime-workflow-row ${selectedWorkflowId === workflow.workflow_id ? "selected" : ""}`} onClick={() => setSelectedWorkflowId(workflow.workflow_id)}>
          <div><span>{goalLabel(workflow.goal)}</span><strong>{workflow.current_agent ?? "Supervisor 等待路由"}</strong></div>
          <RuntimeStatusPill status={workflow.status} />
          <small>{formatDateTime(workflow.updated_at)} · {workflow.workflow_id.slice(-8)}</small>
        </button>)}</div> : <EmptyState text="尚无 Runtime 工作流。可直接以当前学生资料启动一条监督式流程。" />}
      </section>

      <section className="runtime-pane runtime-state-pane">
        <div className="runtime-pane-head"><div><span>共享状态</span><h3>{workflowState ? goalLabel(workflowState.goal) : "选择工作流"}</h3></div><button type="button" className="runtime-text-button" onClick={() => void refreshSelectedCheckpoint()} disabled={!selectedWorkflowId || detailLoading}>刷新 checkpoint</button></div>
        {!workflowState ? <EmptyState text={detailLoading ? "正在读取真实 Runtime 状态…" : "选择左侧工作流查看当前 Agent、任务和阻塞原因。"} /> : <>
          <div className="runtime-state-header"><RuntimeStatusPill status={workflowState.status} /><span>{workflowState.current_agent ?? "Supervisor"}</span><small>步数 {workflowState.step_count}/{workflowState.max_steps} · 工具调用 {workflowState.tool_call_count}</small></div>
          {workflowState.user_question ? <RuntimeCallout tone="user" title="等待学生补充" text={workflowState.user_question} /> : null}
          {workflowState.human_review_reason ? <RuntimeCallout tone="human" title="等待人工复核" text={workflowState.human_review_reason} /> : null}
          {workflowState.errors.length ? <RuntimeCallout tone="error" title="运行错误" text={workflowState.errors.at(-1) ?? "工作流终止。"} /> : null}
          <RuntimeTaskBoard tasks={workflowState.tasks} />
          {canResume ? <div className="runtime-resume"><label>{workflowState.status === "WAITING_USER" ? "补充给 Agent 的信息" : "人工处理结论"}<textarea value={resumeText} onChange={(event) => setResumeText(event.target.value)} placeholder={workflowState.status === "WAITING_USER" ? "例如：已取得 IELTS 7.0，单项均不低于 6.5。" : "记录核验结论或授权继续的原因。"} /></label><button type="button" className="runtime-start primary" onClick={() => void resumeWorkflow()} disabled={detailLoading}><ArrowRight size={14} aria-hidden />继续工作流</button></div> : null}
        </>}
      </section>

      <section className="runtime-pane runtime-trace-pane">
        <div className="runtime-pane-head"><div><span>真实 Trace</span><h3>Runtime 事件</h3></div><span className="runtime-trace-caption"><Clock3 size={14} aria-hidden />{trace.length} events</span></div>
        <RuntimeTraceList events={trace} expandedEventId={expandedEventId} onToggle={(eventId) => setExpandedEventId((current) => current === eventId ? null : eventId)} loading={detailLoading} />
      </section>
    </div>
  </IslandCard>;
}

function RuntimeStatusPill({ status }: { status: RuntimeWorkflowStatus | RuntimeWorkflowTask["status"] }) {
  return <span className={`runtime-status ${status.toLowerCase()}`}>{statusLabel(status)}</span>;
}

function RuntimeCallout({ tone, title, text }: { tone: "user" | "human" | "error"; title: string; text: string }) {
  return <div className={`runtime-callout ${tone}`}><strong>{title}</strong><p>{text}</p></div>;
}

function RuntimeTaskBoard({ tasks }: { tasks: RuntimeWorkflowTask[] }) {
  if (!tasks.length) return <div className="runtime-task-empty">Supervisor 尚未分配可见任务。</div>;
  return <div className="runtime-task-board"><div className="runtime-section-label">工作流任务</div>{tasks.map((task) => <article key={task.task_id}><div><strong>{task.description}</strong><span>{task.assigned_agent ?? "待 Supervisor 分配"}</span></div><RuntimeStatusPill status={task.status} />{task.blocker ? <p>{task.blocker}</p> : null}</article>)}</div>;
}

function RuntimeTraceList({ events, expandedEventId, onToggle, loading }: { events: RuntimeTraceEvent[]; expandedEventId: string | null; onToggle: (eventId: string) => void; loading: boolean }) {
  if (!events.length) return <EmptyState text={loading ? "正在加载执行轨迹…" : "该 workflow 尚未记录 Trace 事件。"} />;
  return <ol className="runtime-trace-list">{events.map((event) => {
    const expanded = expandedEventId === event.event_id;
    const summary = event.output_summary ?? event.input_summary ?? event.error_message ?? "Runtime 已记录该动作。";
    return <li key={event.event_id} className={event.error_message ? "error" : ""}><button type="button" className="runtime-trace-row" onClick={() => onToggle(event.event_id)} aria-expanded={expanded}>
      <span className="runtime-trace-marker" aria-hidden />
      <span className="runtime-trace-main"><strong>{traceEventLabel(event.event_type)}</strong><small>{event.agent_name ?? "Runtime"}{event.tool_name ? ` · ${event.tool_name}` : ""}</small><em>{summary}</em></span>
      <span className="runtime-trace-side"><time dateTime={event.started_at}>{formatClock(event.started_at)}</time><small>{formatDuration(event.duration_ms)}</small></span>
    </button>{expanded ? <div className="runtime-trace-detail"><dl><div><dt>事件</dt><dd>{event.event_type}</dd></div><div><dt>模型</dt><dd>{event.model ?? "—"}{event.provider ? ` · ${event.provider}` : ""}</dd></div><div><dt>Token</dt><dd>{event.total_tokens?.toLocaleString("zh-CN") ?? "—"}</dd></div><div><dt>成本</dt><dd>{formatCost(event.cost_usd)}</dd></div></dl>{event.input_summary ? <p><strong>输入摘要</strong>{event.input_summary}</p> : null}{event.output_summary ? <p><strong>输出摘要</strong>{event.output_summary}</p> : null}{event.error_message ? <p className="trace-error"><strong>{event.error_type ?? "错误"}</strong>{event.error_message}</p> : null}</div> : null}</li>;
  })}</ol>;
}

function goalLabel(goal: RuntimeWorkflowGoal) { return { background_assessment: "背景评估", program_recommendation: "项目推荐", application_planning: "申请规划", writing: "文书准备", full_application_plan: "完整申请方案" }[goal]; }
function statusLabel(status: RuntimeWorkflowStatus | RuntimeWorkflowTask["status"]) { return ({ RUNNING: "运行中", WAITING_USER: "等待学生", WAITING_HUMAN: "等待人工", COMPLETED: "已完成", FAILED: "失败", FAILED_RETRYABLE: "可重试", PENDING: "待执行", BLOCKED: "受阻", CANCELLED: "已取消" } as Record<string, string>)[status] ?? status; }
function traceEventLabel(eventType: RuntimeTraceEvent["event_type"]) { return ({ WORKFLOW_STARTED: "工作流启动", WORKFLOW_COMPLETED: "工作流结束", SUPERVISOR_ROUTE: "Supervisor 路由", AGENT_STARTED: "Agent 开始", AGENT_DECISION: "Agent 决策", TOOL_CALL: "工具调用", TOOL_RESULT: "工具结果", HANDOFF: "交接", CHECKPOINT: "状态保存", USER_WAIT: "等待学生", HUMAN_WAIT: "等待人工", RETRY: "重试", ERROR: "错误" } as Record<string, string>)[eventType] ?? eventType; }
function formatCost(value: number | null) { return value === null ? "未计价" : `$${value.toFixed(value < 0.01 ? 4 : 2)}`; }
function formatDuration(value: number | null) { return value === null ? "—" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`; }
function formatClock(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); }
function formatDateTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }); }
function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) { return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>; }
function AdviceList({ title, items }: { title: string; items: string[] }) { if (!items.length) return null; return <div className="advice-list"><h3>{title}</h3>{items.slice(0, 8).map((item) => <Rule text={item} key={item} />)}</div>; }
function Rule({ text }: { text: string }) { return <div><CheckCircle2 size={15} aria-hidden /><span>{text}</span></div>; }
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function DataBadge({ status }: { status?: string | null }) { const value = status ?? "MODEL_INFERRED"; return <span className={`data-badge ${value.toLowerCase()}`}>{dataStatusLabels[value] ?? value}</span>; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>; }
function formatDate(value?: string | null) { if (!value) return "not recorded"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toISOString().slice(0, 10); }
