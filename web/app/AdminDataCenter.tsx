"use client";

import { Button as IslandButton, Card as IslandCard, Tabs as IslandTabs, Title as IslandTitle } from "animal-island-ui";
import { BookOpenCheck, CalendarDays, CheckCircle2, Database, ExternalLink, ShieldCheck, Sparkles, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { dataStatusLabels, fieldLabels } from "@/lib/copy";
import { getAgentRunDetail, handoffAgentStep, retryAgentStep, rollbackAgentRun } from "@/lib/api";
import { ReviewQueuePanel } from "./admin/ReviewQueuePanel";
import type {
  AgentQueueJob,
  AgentRunDetail,
  AgentRunSummary,
  AgentSystemReport,
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
  ScenarioAuditReport,
  SourceExtractionResult,
  SourceRegistry,
} from "@/lib/types";

type Props = {
  evidenceGraph: EvidenceGraphSummary | null;
  agentSystem: AgentSystemReport | null;
  agentRuns: AgentRunSummary[];
  agentQueue: AgentQueueJob[];
  modelProvider: string;
  modelName: string;
  workerMessage: string;
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
  onQueueAgentWorkflow: (workflowName: string, payloadSummary: string, payloadData?: Record<string, unknown>) => void;
  onQueueCatalogRefreshPlan: () => void;
  onRunAgentWorker: () => void;
  onRetryAgentJob: (jobId: string) => void;
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
    <AgentRuntimePanel agentSystem={props.agentSystem} agentRuns={props.agentRuns} agentQueue={props.agentQueue} modelProvider={props.modelProvider} modelName={props.modelName} workerMessage={props.workerMessage} onQueueAgentWorkflow={props.onQueueAgentWorkflow} onQueueCatalogRefreshPlan={props.onQueueCatalogRefreshPlan} onRunAgentWorker={props.onRunAgentWorker} onRetryAgentJob={props.onRetryAgentJob} />
    <section className="status-grid">
      <Metric label="Programs" value={`${props.evidenceGraph?.program_count ?? 0}`} detail="Local HK/SG taught-master catalog" />
      <Metric label="Field records" value={`${props.evidenceGraph?.field_record_count ?? 0}`} detail="Field-level source bindings" />
      <Metric label="Current verified" value={`${props.evidenceGraph?.verified_field_count ?? 0}`} detail="Required for formal use" />
      <Metric label="Need review" value={`${props.evidenceGraph?.pending_review_field_count ?? 0}`} detail="Operator must inspect source text" />
      <Metric label="Workflow contracts" value={`${props.agentSystem?.agents.length ?? 0}`} detail={`${props.agentSystem?.workflows.length ?? 0} workflows`} />
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

function AgentRuntimePanel({ agentSystem, agentRuns, agentQueue, modelProvider, modelName, workerMessage, onQueueAgentWorkflow, onQueueCatalogRefreshPlan, onRunAgentWorker, onRetryAgentJob }: { agentSystem: AgentSystemReport | null; agentRuns: AgentRunSummary[]; agentQueue: AgentQueueJob[]; modelProvider: string; modelName: string; workerMessage: string; onQueueAgentWorkflow: (workflowName: string, payloadSummary: string, payloadData?: Record<string, unknown>) => void; onQueueCatalogRefreshPlan: () => void; onRunAgentWorker: () => void; onRetryAgentJob: (jobId: string) => void }) {
  const liveModel = modelProvider !== "mock";
  const llmAgents = ["EvaluationAgent", "SchoolMatchingAgent", "DataRefreshAgent", "WritingAgent"];
  const latestRuns = agentRuns.slice(0, 8);
  const [runDetail, setRunDetail] = useState<AgentRunDetail | null>(null);
  const [runtimeMessage, setRuntimeMessage] = useState("");

  async function inspectRun(workflowId: string) {
    try {
      const detail = await getAgentRunDetail(workflowId);
      setRunDetail(detail);
      setRuntimeMessage("Loaded " + workflowId);
    } catch (err) {
      setRuntimeMessage(err instanceof Error ? err.message : "Run detail failed to load.");
    }
  }

  async function retryStep(stepId: string) {
    const workflowId = runDetail?.run?.workflow_id;
    if (!workflowId) return;
    try {
      await retryAgentStep(workflowId, stepId);
      setRunDetail(await getAgentRunDetail(workflowId));
      setRuntimeMessage("Step retry queued: " + stepId);
    } catch (err) {
      setRuntimeMessage(err instanceof Error ? err.message : "Step retry failed.");
    }
  }

  async function handoffStep(stepId: string) {
    const workflowId = runDetail?.run?.workflow_id;
    if (!workflowId) return;
    try {
      await handoffAgentStep(workflowId, stepId, "human_reviewer", "Operator requested human handoff from Admin runtime panel.");
      setRunDetail(await getAgentRunDetail(workflowId));
      setRuntimeMessage("Step handed off: " + stepId);
    } catch (err) {
      setRuntimeMessage(err instanceof Error ? err.message : "Step handoff failed.");
    }
  }

  async function rollbackStep(stepId: string) {
    const workflowId = runDetail?.run?.workflow_id;
    if (!workflowId) return;
    try {
      await rollbackAgentRun({ workflow_id: workflowId, target_step_id: stepId, reason: "Rollback from Admin runtime panel." });
      setRunDetail(await getAgentRunDetail(workflowId));
      setRuntimeMessage("Run rolled back to: " + stepId);
    } catch (err) {
      setRuntimeMessage(err instanceof Error ? err.message : "Run rollback failed.");
    }
  }

  return <IslandCard className="panel-card agent-runtime-panel" color="app-blue"><div className="split-head"><div><span className="mini-label"><Sparkles size={16} aria-hidden />AI Agent runtime</span><h2>Agents manage evaluation, matching, source governance, and writing support</h2><p>Students see business output. Admins see workflow nodes, model usage, tool boundaries, retries, and human handoffs.</p></div><div className="runtime-model-badge"><span>{liveModel ? "live model connected" : "mock model mode"}</span><strong>{modelName}</strong><small>{modelProvider}</small></div></div><section className="status-grid three"><Metric label="Agent roles" value={`${agentSystem?.agents.length ?? 0}`} detail="Profile / Evaluation / Matching / Data / Writing / Review" /><Metric label="LLM nodes" value={`${llmAgents.length}`} detail={llmAgents.join(", ")} /><Metric label="Recent runs" value={`${agentRuns.length}`} detail={`${agentQueue.length} queued jobs`} /></section><div className="agent-worker-actions"><p>{workerMessage}</p><div className="card-actions"><IslandButton type="primary" onClick={onQueueCatalogRefreshPlan}>Queue full update</IslandButton><IslandButton type="default" onClick={() => onQueueAgentWorkflow("data_acquisition", "Crawl selected programme sources", {selected_program_ids: []})}>Queue source crawl</IslandButton><IslandButton type="default" onClick={() => onQueueAgentWorkflow("crawl_queue", "Build official crawl queue", {selected_program_ids: []})}>Queue crawl plan</IslandButton><IslandButton type="default" onClick={() => onQueueAgentWorkflow("catalog_auto_update", "Find missing programme detail pages", {dry_run: true, max_programs: 48})}>Queue URL update</IslandButton><IslandButton type="primary" onClick={onRunAgentWorker}>Run next job</IslandButton></div></div><AgentQueueList jobs={agentQueue} onRetry={onRetryAgentJob} /><div className="runtime-columns"><div><h3>Recent agent workflows</h3>{latestRuns.length ? <div className="runtime-list">{latestRuns.map((run) => <article key={run.workflow_id}><div className="program-title-row"><strong>{workflowLabel(run.workflow_name)}</strong><DataBadge status={run.status} /></div><p>{run.workflow_id}</p><div className="task-meta"><span>current node {run.current_step || "complete"}</span><span>{formatDate(run.updated_at)}</span></div><div className="card-actions"><IslandButton type="default" size="small" onClick={() => inspectRun(run.workflow_id)}>Inspect steps</IslandButton></div></article>)}</div> : <EmptyState text="No agent run yet. Start assessment, matching, timeline, or writing." />}</div><div><h3>Selected run steps</h3><AgentRunDetailPanel detail={runDetail} message={runtimeMessage} onRetryStep={retryStep} onHandoffStep={handoffStep} onRollbackStep={rollbackStep} /></div><div><h3>AI capability boundaries</h3><div className="runtime-list compact">{(agentSystem?.agents ?? []).filter((agent) => agent.llm_role && !agent.llm_role.startsWith("none")).map((agent) => <article key={agent.agent_name}><strong>{agent.agent_name}</strong><p>{agent.llm_role}</p>{agent.llm_guardrails?.length ? <small>{agent.llm_guardrails[0]}</small> : null}</article>)}{!(agentSystem?.agents ?? []).some((agent) => agent.llm_role && !agent.llm_role.startsWith("none")) ? <article><strong>Model capability</strong><p>After connecting a live model, Evaluation, Matching, DataRefresh, and Writing call it within their own guardrails.</p></article> : null}</div></div></div></IslandCard>;
}

function AgentRunDetailPanel({ detail, message, onRetryStep, onHandoffStep, onRollbackStep }: { detail: AgentRunDetail | null; message: string; onRetryStep: (stepId: string) => void; onHandoffStep: (stepId: string) => void; onRollbackStep: (stepId: string) => void }) {
  if (!detail?.run) return <div className="runtime-list compact"><article><strong>No run selected</strong><p>Click Inspect steps on a recent workflow to manage retry, handoff, or rollback.</p>{message ? <small>{message}</small> : null}</article></div>;
  return <div className="runtime-list compact">
    <article><div className="program-title-row"><strong>{workflowLabel(detail.run.workflow_name)}</strong><DataBadge status={detail.run.status} /></div><p>{detail.run.workflow_id}</p>{message ? <small>{message}</small> : null}</article>
    {detail.steps.map((step) => <article key={step.step_id}>
      <div className="program-title-row"><strong>{step.node}</strong><DataBadge status={step.status} /></div>
      <p>{step.output_summary || step.input_summary}</p>
      <div className="task-meta"><span>attempt {step.attempt}/{step.max_attempts}</span><span>{step.assigned_to}</span><span>{step.payload?.model ? String(step.payload.model) : "no model"}</span></div>
      {step.payload?.needs_human_reason ? <small>{String(step.payload.needs_human_reason)}</small> : null}
      <div className="card-actions"><IslandButton type="default" size="small" onClick={() => onRetryStep(step.step_id)}>Retry</IslandButton><IslandButton type="default" size="small" onClick={() => onHandoffStep(step.step_id)}>Handoff</IslandButton><IslandButton type="default" size="small" onClick={() => onRollbackStep(step.step_id)}>Rollback</IslandButton></div>
    </article>)}
    {(detail.events ?? []).slice(0, 5).map((event) => <article key={event.event_id}><strong>{event.event_type}</strong><p>{event.summary}</p><small>{formatDate(event.created_at)}</small></article>)}
  </div>;
}

function AgentQueueList({ jobs, onRetry }: { jobs: AgentQueueJob[]; onRetry: (jobId: string) => void }) {
  const visible = jobs.slice(0, 8);
  if (!visible.length) return <div className="runtime-list compact"><article><strong>No queued jobs</strong><p>Queue source crawl, crawl plan, or URL update to test the worker.</p></article></div>;
  return <div className="runtime-list compact">{visible.map((job) => <article key={job.job_id}>
    <div className="program-title-row"><strong>{workflowLabel(job.workflow_name)}</strong><DataBadge status={job.status} /></div>
    <p>{job.payload_summary || job.job_id}</p>
    <div className="task-meta"><span>attempt {job.attempts ?? 0}/{job.max_attempts ?? 1}</span><span>priority {job.priority}</span><span>{job.assigned_to || "unassigned"}</span></div>
    {job.worker_summary ? <small>{job.worker_summary}</small> : null}
    {job.last_error ? <small>{job.last_error}</small> : null}
    {job.can_retry ? <div className="card-actions"><IslandButton type="default" size="small" onClick={() => onRetry(job.job_id)}>Retry job</IslandButton></div> : null}
  </article>)}</div>;
}

function workflowLabel(value: string) { return { background: "Background", program_plan: "Matching plan", application_plan: "Timeline", writing_plan: "Writing", assessment: "Full plan", selected_program_matches: "Selected matches", data_acquisition: "Source acquisition", catalog_auto_update: "URL discovery", crawl_queue: "Crawl queue" }[value] ?? value; }
function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) { return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>; }
function AdviceList({ title, items }: { title: string; items: string[] }) { if (!items.length) return null; return <div className="advice-list"><h3>{title}</h3>{items.slice(0, 8).map((item) => <Rule text={item} key={item} />)}</div>; }
function Rule({ text }: { text: string }) { return <div><CheckCircle2 size={15} aria-hidden /><span>{text}</span></div>; }
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function DataBadge({ status }: { status?: string | null }) { const value = status ?? "MODEL_INFERRED"; return <span className={`data-badge ${value.toLowerCase()}`}>{dataStatusLabels[value] ?? value}</span>; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>; }
function formatDate(value?: string | null) { if (!value) return "not recorded"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toISOString().slice(0, 10); }
