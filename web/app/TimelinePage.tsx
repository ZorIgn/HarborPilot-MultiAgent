"use client";

import { Bell, BookOpenCheck, CalendarDays, Download, ExternalLink, ShieldCheck, Sparkles } from "lucide-react";
import { Card as IslandCard, Button as IslandButton, Tabs as IslandTabs, Title as IslandTitle } from "animal-island-ui";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { dataStatusLabels, fieldLabels, materialLabels, previousCycleLabel, taskTypeLabels, timelineCopy } from "@/lib/copy";
import type { ProgramMatch, TimelineTask } from "@/lib/types";

type TimelineLoading = string | null;
type Program = ProgramMatch["program"];
type TrustRecord = NonNullable<Program["trust_detail"]>["field_records"][number];
type TaskStatus = NonNullable<TimelineTask["status"]>;
type EvidenceFieldState = {
  badgeStatus: string;
  label: string;
  kind: "published" | "awaiting_publish" | "needs_verification" | "missing";
};

type SourceSummary = {
  total: number;
  formalReady: number;
  referenceReady: number;
  needsSource: number;
  currentFields: number;
  referenceFields: number;
  missingFields: number;
};

type CompletionSummary = {
  total: number;
  submitted: number;
  inProgress: number;
  reviewNeeded: number;
};

const criticalFieldOrder = ["official_program_url", "application_url", "deadline", "language_requirement", "materials", "tuition_hkd"];
const taskStatusOptions: TaskStatus[] = ["未开始", "准备中", "待上传", "已提交", "需复核"];

export function TimelinePage({ selectedMatches, timeline, loading, onRun, onRefresh, onTaskStatusChange }: { selectedMatches: ProgramMatch[]; timeline: TimelineTask[]; loading: TimelineLoading; onRun: () => void; onRefresh: () => void; onTaskStatusChange?: (taskId: string, status: TaskStatus) => void }) {
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({});

  useEffect(() => {
    setTaskStatuses((current) => {
      const next: Record<string, TaskStatus> = {};
      let changed = Object.keys(current).length !== timeline.length;
      timeline.forEach((task) => {
        next[task.id] = current[task.id] ?? normalizeTaskStatus(task.status);
        if (next[task.id] !== current[task.id]) changed = true;
      });
      return changed ? next : current;
    });
  }, [timeline]);

  const displayTimeline = useMemo(() => timeline.map((task) => ({ ...task, status: taskStatuses[task.id] ?? normalizeTaskStatus(task.status) })), [timeline, taskStatuses]);
  const sourceSummary = useMemo(() => buildSourceSummary(selectedMatches), [selectedMatches]);
  const completionSummary = useMemo(() => buildCompletionSummary(displayTimeline), [displayTimeline]);
  const commonTasks = displayTimeline.filter((task) => (task.linked_program_ids?.length ?? 0) > 1 || task.task_type === "materials" || task.task_type === "language");
  const sourceTasks = displayTimeline.filter((task) => task.task_type === "source_review");
  const projectTasks = displayTimeline.filter((task) => !commonTasks.includes(task) && !sourceTasks.includes(task));
  const dateTasks = [...displayTimeline].sort(compareTasks);

  function handleStatusChange(taskId: string, status: TaskStatus) {
    setTaskStatuses((current) => ({ ...current, [taskId]: status }));
    onTaskStatusChange?.(taskId, status);
  }

  return <div className="page-stack">
    <IslandCard className="panel-card" color="app-teal">
      <div className="split-head">
        <div><span className="mini-label"><CalendarDays size={16} aria-hidden />{timelineCopy.heroEyebrow}</span><h2>{timelineCopy.heroTitle}</h2><p>{timelineCopy.heroBody}</p></div>
        <div className="card-actions"><IslandButton type="default" disabled={!selectedMatches.length} loading={loading === "data"} onClick={onRefresh}>{timelineCopy.refreshButton}</IslandButton><IslandButton type="default" disabled={!dateTasks.length} onClick={() => downloadTimelineIcs(dateTasks)}><Download size={16} aria-hidden />导出日历</IslandButton><IslandButton type="primary" disabled={!selectedMatches.length} loading={loading === "timeline"} onClick={onRun}>{timelineCopy.runButton}</IslandButton></div>
      </div>
    </IslandCard>

    <SourceAssurancePanel summary={sourceSummary} matches={selectedMatches} completion={completionSummary} />
    <SourceEvidenceMatrix matches={selectedMatches} />
    <IslandCard className="panel-card"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title={timelineCopy.selectedProgramsTitle} /><ProjectTimelineSummary matches={selectedMatches} tasks={displayTimeline} /></IslandCard>
    <IslandTabs className="animal-tabs" defaultActiveKey="date" items={[
      { key: "date", label: "按日期 " + dateTasks.length, children: <DateTimelineView tasks={dateTasks} onStatusChange={handleStatusChange} /> },
      { key: "project", label: "按项目 " + projectTasks.length, children: <ProjectTimelineView tasks={projectTasks} onStatusChange={handleStatusChange} /> },
      { key: "common", label: "通用材料 " + commonTasks.length, children: <TaskList tasks={commonTasks} onStatusChange={handleStatusChange} /> },
      { key: "sources", label: "信息更新 " + sourceTasks.length, children: <TaskList tasks={sourceTasks} onStatusChange={handleStatusChange} /> },
    ]} />
  </div>;
}

function SourceAssurancePanel({ summary, matches, completion }: { summary: SourceSummary; matches: ProgramMatch[]; completion: CompletionSummary }) {
  if (!matches.length) return null;
  return <IslandCard className="panel-card assurance-panel" type="dashed">
    <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title={timelineCopy.boundaryTitle} />
    <section className="status-grid four">
      <Metric label="已选项目" value={String(summary.total)} detail="只对你保存的申请清单生成" />
      <Metric label="当前季官方" value={String(summary.formalReady)} detail="可生成当前季日期任务" />
      <Metric label="往届参考" value={String(summary.referenceReady)} detail="可先安排材料动作" />
      <Metric label="进度" value={`${completion.submitted}/${completion.total}`} detail={`${completion.inProgress} 项进行中，${completion.reviewNeeded} 项需复核`} />
    </section>
    <div className="assurance-copy">
      <strong>{summary.formalReady ? timelineCopy.currentReady : summary.referenceReady ? timelineCopy.previousReady : timelineCopy.needsOfficial}</strong>
      <p>{timelineCopy.boundaryBody}</p>
    </div>
  </IslandCard>;
}


function SourceEvidenceMatrix({ matches }: { matches: ProgramMatch[] }) {
  if (!matches.length) return null;
  return <IslandCard className="panel-card source-evidence-matrix-card">
    <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="关键申请信息与来源" />
    <p className="form-note">这里直接展示已选项目可用的字段级证据。当前季官网字段可以用于正式安排；往届参考字段只能用于材料安排；没有来源的字段会进入信息更新任务。</p>
    <div className="source-evidence-matrix">
      {matches.map((item) => <article className="source-evidence-program" key={item.program.id}>
        <header>
          <div>
            <strong>{programInstitution(item.program)}</strong>
            <h3>{programTitle(item.program)}</h3>
            <p>{programSchoolLine(item.program)}</p>
          </div>
          <DataBadge status={sourceBadgeStatus(item.program)} />
        </header>
        <div className="source-evidence-grid">
          {criticalFieldOrder.map((field) => <EvidenceFieldCell field={field} program={item.program} key={field} />)}
        </div>
      </article>)}
    </div>
  </IslandCard>;
}

function EvidenceFieldCell({ field, program }: { field: string; program: Program }) {
  const record = findRecord(program, field);
  const fallback = fallbackFieldValue(program, field);
  const usable = record && (record.status === "OFFICIAL_VERIFIED_CURRENT" || record.status === "OFFICIAL_PREVIOUS_CYCLE");
  const state = evidenceFieldState(program, field, record);
  return <section className={("source-field-cell " + (usable ? "usable" : "needs-source")).trim()}>
    <div className="source-field-head">
      <span>{fieldLabels[field] ?? field}</span>
      <DataBadge status={state.badgeStatus} label={state.label} />
    </div>
    <strong>{record ? fieldRecordDisplayValue(record) : fallback}</strong>
    <small>{record?.cycle ? previousCycleLabel(record.cycle) : state.kind === "awaiting_publish" ? "申请季待发布" : "申请季待补充"} · {formatSourceTime(record)}</small>
    {record?.evidence_snippet ? <p>{fieldRecordExcerpt(record.evidence_snippet)}</p> : null}
    {record?.source_url ? <a className="text-link" href={record.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a> : <span className="source-missing-note">{state.kind === "missing" ? "来源待补充" : state.kind === "needs_verification" ? "核验后更新来源" : "发布后更新来源"}</span>}
  </section>;
}

function TaskList({ tasks, onStatusChange }: { tasks: TimelineTask[]; onStatusChange: (taskId: string, status: TaskStatus) => void }) {
  if (!tasks.length) return <EmptyState text={timelineCopy.emptyTasks} />;
  return <div className="task-list">{[...tasks].sort(compareTasks).map((task) => <TaskCard task={task} key={task.id} onStatusChange={onStatusChange} />)}</div>;
}

function DateTimelineView({ tasks, onStatusChange }: { tasks: TimelineTask[]; onStatusChange: (taskId: string, status: TaskStatus) => void }) {
  const groups = groupTasks(tasks, taskDateKey);
  if (!groups.length) return <EmptyState text={timelineCopy.emptyTasks} />;
  return <div className="timeline-group-list">{groups.map((group) => <section className="timeline-group" key={group.key}><div className="timeline-group-head"><strong>{group.key}</strong><span>{group.items.length} 项任务</span></div><TaskList tasks={group.items} onStatusChange={onStatusChange} /></section>)}</div>;
}

function ProjectTimelineView({ tasks, onStatusChange }: { tasks: TimelineTask[]; onStatusChange: (taskId: string, status: TaskStatus) => void }) {
  const groups = groupTasks(tasks, taskProgramLabel);
  if (!groups.length) return <EmptyState text={timelineCopy.emptyTasks} />;
  return <div className="timeline-group-list">{groups.map((group) => <section className="timeline-group" key={group.key}><div className="timeline-group-head"><strong>{group.key}</strong><span>{projectRounds(group.items)}</span></div><TaskList tasks={group.items} onStatusChange={onStatusChange} /></section>)}</div>;
}

function TaskCard({ task, onStatusChange }: { task: TimelineTask; onStatusChange: (taskId: string, status: TaskStatus) => void }) {
  const [checkedMaterials, setCheckedMaterials] = useState<Record<string, boolean>>({});
  const due = String(task.suggested_due_date ?? task.due_date);
  const status = normalizeTaskStatus(task.status);
  const materials = task.upload_materials?.length ? task.upload_materials : task.materials ?? [];
  const dependencies = task.dependencies?.filter(Boolean) ?? [];
  return <article className="task-row">
    <div className="task-date"><CalendarDays size={17} aria-hidden /><strong>{due}</strong><span>{dateBasisLabel(task.date_basis)}</span></div>
    <div className="task-main">
      <div className="program-title-row"><span className={(`priority ${riskClass(task.risk_level ?? task.priority)}`).trim()}>风险：{riskLabel(task.risk_level ?? task.priority)}</span><span className="tier-pill">{taskTypeLabel(task.task_type)}</span></div>
      <h3>{task.task_name ?? task.title}</h3>
      {task.program_name ? <p className="task-program-line">{task.institution ? task.institution + " / " : ""}{task.program_name}</p> : null}
      <p>{task.basis || timelineCopy.defaultTaskBasis}</p>
      <TaskAssurance task={task} />
      <div className="task-control-row">
        <label className="task-status-control"><span>任务状态</span><select aria-label="更新任务状态" value={status} onChange={(event) => onStatusChange(task.id, event.target.value as TaskStatus)}>{taskStatusOptions.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>
        {task.reminder_at ? <div className="task-reminder"><Bell size={14} aria-hidden /><span>提醒：{formatReminder(task.reminder_at)}</span></div> : null}
        {task.owner ? <span className="task-owner">负责人：{task.owner}</span> : null}
      </div>
      <div className="task-meta">
        {task.program_name ? <span>项目：{task.institution ? task.institution + " / " : ""}{task.program_name}</span> : null}
        {task.program_round ? <span>轮次：{task.program_round}</span> : null}
        {task.round_open_date ? <span>开放：{String(task.round_open_date)}</span> : null}
        <span>DDL：{formatTaskDeadline(task)}</span>
        {task.submit_to ? <span>提交：{task.submit_to}</span> : null}
      </div>
      {materials.length ? <div className="task-material-checklist" aria-label="材料清单"><strong>材料</strong>{materials.map((item) => {
        const key = task.id + ":" + item;
        return <label key={item}><input type="checkbox" checked={Boolean(checkedMaterials[key])} onChange={() => setCheckedMaterials((current) => ({ ...current, [key]: !current[key] }))} /><span>{materialLabels[item] ?? fieldLabels[item] ?? item}</span></label>;
      })}</div> : null}
      {dependencies.length ? <div className="task-dependency-list"><strong>先完成</strong><div>{dependencies.map((item) => <span key={item}>{formatDependency(item)}</span>)}</div></div> : null}
      <div className="link-row">{task.application_url ? <a className="text-link" href={task.application_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />{timelineCopy.applicationEntry}</a> : null}{task.source_url ? <a className="text-link" href={task.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />{timelineCopy.schoolSource}</a> : null}</div>
    </div>
  </article>;
}

function TaskAssurance({ task }: { task: TimelineTask }) {
  if (task.official_deadline && task.official_deadline !== "NOT_PUBLISHED") {
    return <div className="task-assurance ready"><ShieldCheck size={14} aria-hidden /><span>使用当前季官方日期安排；提交前建议再打开项目页确认入口和轮次。</span></div>;
  }
  if (task.previous_cycle_reference && task.previous_cycle_reference !== "NOT_PUBLISHED") {
    return <div className="task-assurance warning"><ShieldCheck size={14} aria-hidden /><span>{previousCycleLabel(task.previous_cycle_reference)}：先按这个节奏准备，当前季发布后更新最终日期。</span></div>;
  }
  if (task.review_required) {
    return <div className="task-assurance blocked"><ShieldCheck size={14} aria-hidden /><span>当前季日期还未发布：先完成材料动作，项目页或申请入口发布后更新最终提交日期。</span></div>;
  }
  return null;
}

function ProjectTimelineSummary({ matches, tasks }: { matches: ProgramMatch[]; tasks: TimelineTask[] }) {
  if (!matches.length) return <EmptyState text={timelineCopy.noSelectedPrograms} />;
  return <div className="project-timeline-summary">{matches.map((item) => {
    const programTasks = tasks.filter((task) => task.linked_program_ids?.includes(item.program.id)).sort(compareTasks);
    const nextTasks = programTasks.slice(0, 4);
    return <article className="project-summary-card" key={item.program.id}>
      <div className="program-title-row"><DataBadge status={sourceBadgeStatus(item.program)} /><span className="tier-pill">{tierLabel(item)}</span></div>
      <div className="project-identity">
        <span>{programInstitution(item.program)}</span>
        <h3>{programTitle(item.program)}</h3>
        <p>{programSchoolLine(item.program)}</p>
      </div>
      <ProgramSourceAssurance program={item.program} />
      <div className="task-meta compact"><span>DDL：{formatProgramDeadline(item.program)}</span><span>语言：{formatLanguageRequirement(item.program)}</span><span>材料：{formatProgramMaterials(item.program)}</span><span>学费：{formatMoney(item.program.tuition_hkd)}</span></div>
      {nextTasks.length ? <div className="project-next-task-list">{nextTasks.map((task) => <div key={task.id}><strong>{String(task.suggested_due_date ?? task.due_date)}</strong><span>{task.program_round || task.task_name || task.title}</span><small>{formatTaskDeadline(task)} · {normalizeTaskStatus(task.status)}</small></div>)}</div> : <p>生成后会显示开放日、DDL、材料上传和提交入口。</p>}
      <div className="link-row">{item.program.application_url ? <a className="text-link" href={item.program.application_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开申请入口</a> : null}{item.program.official_program_url ? <a className="text-link" href={item.program.official_program_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开项目页</a> : null}</div>
    </article>;
  })}</div>;
}

function ProgramSourceAssurance({ program }: { program: Program }) {
  const trust = program.trust_detail;
  const records = criticalFieldOrder.map((field) => findRecord(program, field)).filter((record): record is TrustRecord => Boolean(record));
  const readyItems = records.filter((record) => record.status === "OFFICIAL_VERIFIED_CURRENT" || record.status === "OFFICIAL_PREVIOUS_CYCLE").map((record) => fieldLabels[record.field_name] ?? record.field_name);
  const missingItems = criticalFieldOrder.filter((field) => !records.some((record) => record.field_name === field && (record.status === "OFFICIAL_VERIFIED_CURRENT" || record.status === "OFFICIAL_PREVIOUS_CYCLE"))).map((field) => fieldLabels[field] ?? field);
  return <div className="project-reference-box">
    <div><span>资料可用性</span><strong>{trust?.production_ready ? "当前季官网信息可用" : trust?.reference_ready ? "有往届官方信息可参考" : "发布后更新"}</strong></div>
    <div><span>可参考内容</span><strong>{readyItems.length ? readyItems.slice(0, 4).join(" / ") : "先按通用材料准备"}</strong></div>
    <p>{trust?.production_ready ? "可生成当前季日期任务；提交前仍建议打开项目页确认入口和轮次。" : trust?.reference_ready ? "先按往届信息准备材料，当前季发布后更新最终日期。" : "先准备通用材料，并优先补项目页、申请入口和截止日期来源。"}</p>
    {missingItems.length ? <div className="source-mini-grid"><span><b>发布后更新</b>{missingItems.slice(0, 4).join(" / ")}</span></div> : null}
  </div>;
}

function groupTasks(tasks: TimelineTask[], keyFor: (task: TimelineTask) => string) {
  const buckets = new Map<string, TimelineTask[]>();
  tasks.forEach((task) => { const key = keyFor(task); buckets.set(key, [...(buckets.get(key) ?? []), task]); });
  return Array.from(buckets.entries()).map(([key, items]) => ({ key, items: items.sort(compareTasks) }));
}

function buildSourceSummary(matches: ProgramMatch[]): SourceSummary {
  return matches.reduce<SourceSummary>((summary, item) => {
    const trust = item.program.trust_detail;
    const records = trust?.field_records?.filter((record) => criticalFieldOrder.includes(record.field_name)) ?? [];
    const current = trust?.official_current_fields?.length ?? records.filter((record) => record.status === "OFFICIAL_VERIFIED_CURRENT").length;
    const reference = trust?.stale_or_reference_fields?.length ?? records.filter((record) => record.status === "OFFICIAL_PREVIOUS_CYCLE").length;
    const missing = trust?.fields_requiring_review?.length ?? Math.max(0, criticalFieldOrder.length - current - reference);
    return {
      total: summary.total + 1,
      formalReady: summary.formalReady + (trust?.production_ready ? 1 : 0),
      referenceReady: summary.referenceReady + (!trust?.production_ready && trust?.reference_ready ? 1 : 0),
      needsSource: summary.needsSource + (!trust?.production_ready && !trust?.reference_ready ? 1 : 0),
      currentFields: summary.currentFields + current,
      referenceFields: summary.referenceFields + reference,
      missingFields: summary.missingFields + missing,
    };
  }, { total: 0, formalReady: 0, referenceReady: 0, needsSource: 0, currentFields: 0, referenceFields: 0, missingFields: 0 });
}

function buildCompletionSummary(tasks: TimelineTask[]): CompletionSummary {
  return tasks.reduce<CompletionSummary>((summary, task) => {
    const status = normalizeTaskStatus(task.status);
    return {
      total: summary.total + 1,
      submitted: summary.submitted + (status === "已提交" ? 1 : 0),
      inProgress: summary.inProgress + (status === "准备中" || status === "待上传" ? 1 : 0),
      reviewNeeded: summary.reviewNeeded + (status === "需复核" ? 1 : 0),
    };
  }, { total: 0, submitted: 0, inProgress: 0, reviewNeeded: 0 });
}

export function downloadTimelineIcs(tasks: TimelineTask[]) {
  if (typeof window === "undefined" || !tasks.length) return;
  const now = toIcsTimestamp(new Date());
  const events = [...tasks].sort(compareTasks).map((task) => taskToIcsEvent(task, now)).join("\r\n");
  const content = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HarborPilot//Student Timeline//CN", "CALSCALE:GREGORIAN", events, "END:VCALENDAR"].filter(Boolean).join("\r\n");
  const blob = new Blob([content], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `HarborPilot-timeline-${new Date().toISOString().slice(0, 10)}.ics`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function taskToIcsEvent(task: TimelineTask, stamp: string) {
  const start = toIcsDate(parseTaskDate(taskDateKey(task)) ?? new Date());
  const summary = task.program_name ? `${task.institution ? task.institution + " / " : ""}${task.program_name}：${task.task_name ?? task.title}` : task.task_name ?? task.title;
  const description = [task.basis, task.program_round ? `轮次：${task.program_round}` : null, `DDL：${formatTaskDeadline(task)}`, task.submit_to ? `提交：${task.submit_to}` : null, task.reminder_at ? `提醒：${formatReminder(task.reminder_at)}` : null].filter(Boolean).join("\n");
  return [
    "BEGIN:VEVENT",
    `UID:${escapeIcsText(task.id)}@harborpilot.local`,
    `DTSTAMP:${stamp}`,
    `DTSTART;VALUE=DATE:${start}`,
    `SUMMARY:${escapeIcsText(summary)}`,
    `DESCRIPTION:${escapeIcsText(description)}`,
    task.application_url ? `URL:${escapeIcsText(task.application_url)}` : null,
    "END:VEVENT",
  ].filter(Boolean).join("\r\n");
}

function compareTasks(a: TimelineTask, b: TimelineTask) { return taskDateKey(a).localeCompare(taskDateKey(b)) || taskProgramLabel(a).localeCompare(taskProgramLabel(b)) || String(a.task_name ?? a.title).localeCompare(String(b.task_name ?? b.title)); }
function taskDateKey(task: TimelineTask) { return String(task.suggested_due_date ?? task.due_date); }
function taskProgramLabel(task: TimelineTask) { return task.program_name ? (task.institution ? task.institution + " / " : "") + task.program_name : "通用材料和语言"; }
function projectRounds(tasks: TimelineTask[]) { const rounds = Array.from(new Set(tasks.map((task) => task.program_round).filter(Boolean))); return rounds.length ? "轮次：" + rounds.join(" / ") : String(tasks.length) + " 项任务"; }
function formatTaskDeadline(task: TimelineTask) { const deadline = task.round_deadline ?? task.official_deadline; if (!deadline || deadline === "NOT_PUBLISHED") return task.previous_cycle_reference ? "当前季未发布，" + previousCycleLabel(task.previous_cycle_reference) + "：" + task.previous_cycle_reference : "当前季未发布"; return String(deadline); }
function formatProgramDeadline(program: Program) { const fallback = !program.deadline || program.deadline === "NOT_PUBLISHED" ? null : String(program.deadline); return formatProgramField(program, "deadline", fallback, "当前季未发布 / 待官网核验"); }
function formatLanguageRequirement(program: Program) { const language = program.requirements?.language ?? {}; const parts = Object.entries(language).filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => key.toUpperCase() + " " + String(value)); return formatProgramField(program, "language_requirement", parts.length ? parts.slice(0, 2).join(" / ") : null, "打开项目页核对"); }
function formatProgramMaterials(program: Program) { const materials = program.materials ?? []; const fallback = materials.length ? materials.slice(0, 4).map((item) => materialLabels[item] ?? item).join(" / ") : null; return formatProgramField(program, "materials", fallback, "成绩单 / 语言 / 推荐信 / CV / PS（待官网核验）"); }
function formatMoney(value: number | null | undefined) { return value ? String(Math.round(value / 10000)) + " 万港币" : "官网学费待补充"; }
function findRecord(program: Program, field: string) { return program.trust_detail?.field_records?.find((record) => record.field_name === field) ?? null; }

function formatProgramField(program: Program, field: string, fallback: string | null, empty: string) {
  const record = findRecord(program, field);
  if (record?.value && record.value !== "NOT_PUBLISHED") return fieldRecordDisplayValue(record);
  return fallback ? `待官网核验（库内参考：${fallback}）` : empty;
}

function fallbackFieldValue(program: Program, field: string) {
  if (field === "official_program_url") return program.official_program_url ? "已找到项目页，等待字段发布" : "未找到项目详情页";
  if (field === "application_url") return program.application_url ? "已找到申请入口，等待字段发布" : "申请入口待补充";
  if (field === "deadline") return formatProgramDeadline(program);
  if (field === "language_requirement") return formatLanguageRequirement(program);
  if (field === "materials") return formatProgramMaterials(program);
  if (field === "tuition_hkd") return formatProgramField(program, field, program.tuition_hkd ? formatMoney(program.tuition_hkd) : null, "官网学费待补充");
  return "等待来源更新";
}
function evidenceFieldState(program: Program, field: string, record: TrustRecord | null): EvidenceFieldState {
  if (record && record.status !== "MODEL_INFERRED") {
    const published = record.status === "OFFICIAL_VERIFIED_CURRENT" || record.status === "OFFICIAL_PREVIOUS_CYCLE";
    return { badgeStatus: record.status, label: dataStatusLabels[record.status] ?? record.status, kind: published ? "published" : "needs_verification" };
  }
  const hasCandidate = Boolean(record?.value && record.value !== "NOT_PUBLISHED") || hasProgramFieldCandidate(program, field);
  if (hasCandidate && (field === "official_program_url" || field === "application_url")) {
    return { badgeStatus: "EXTRACTED", label: "已提取待发布", kind: "awaiting_publish" };
  }
  if (hasCandidate) return { badgeStatus: "PENDING_REVIEW", label: "待官网核验", kind: "needs_verification" };
  return { badgeStatus: "MODEL_INFERRED", label: "缺少来源", kind: "missing" };
}
function hasProgramFieldCandidate(program: Program, field: string) {
  if (field === "official_program_url") return Boolean(program.official_program_url);
  if (field === "application_url") return Boolean(program.application_url);
  if (field === "deadline") return Boolean(program.deadline && program.deadline !== "NOT_PUBLISHED");
  if (field === "language_requirement") return Object.values(program.requirements?.language ?? {}).some((value) => value !== null && value !== undefined);
  if (field === "materials") return Boolean(program.materials?.length);
  if (field === "tuition_hkd") return Boolean(program.tuition_hkd);
  return false;
}
function fieldRecordDisplayValue(record: TrustRecord) {
  if (!record.value || record.value === "NOT_PUBLISHED") return "当前季未发布";
  const value = String(record.value).replace(/\s+/g, " ").trim();
  const compact = value.length > 96 ? value.slice(0, 96) + "..." : value;
  if (record.status === "OFFICIAL_VERIFIED_CURRENT") return compact;
  if (record.status === "OFFICIAL_PREVIOUS_CYCLE") return `${compact}（${previousCycleLabel(record.cycle)}）`;
  return `待官网核验（库内参考：${compact}）`;
}
function fieldRecordExcerpt(value: string) {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > 140 ? compact.slice(0, 140) + "..." : compact;
}
function formatSourceTime(record?: TrustRecord | null) {
  if (!record) return "来源待补充";
  const value = record.verified_at ?? record.extracted_at;
  if (!value) return "抓取时间待补充";
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
function sourceBadgeStatus(program: Program) { const trust = program.trust_detail; if (trust?.production_ready) return "OFFICIAL_VERIFIED_CURRENT"; if (trust?.reference_ready) return "OFFICIAL_PREVIOUS_CYCLE"; return program.data_status ?? "MODEL_INFERRED"; }
function dateBasisLabel(value?: string | null) { const raw = String(value ?? ""); if (raw.includes("官方")) return "官方倒推"; if (raw.includes("上一") || raw.includes("往届")) return "往届参考"; if (raw.includes("人工")) return "人工确认"; return "准备动作"; }
function riskLabel(value?: string | null) { const raw = String(value ?? "").toLowerCase(); if (raw.includes("high") || raw.includes("高")) return "高"; if (raw.includes("low") || raw.includes("低")) return "低"; return "中"; }
function riskClass(value?: string | null) { const label = riskLabel(value); return label === "高" ? "high" : label === "低" ? "low" : "medium"; }
function programTitle(program: Program) { return program.name_zh || program.name || "未找到项目名称"; }
function programInstitution(program: Program) { return program.institution_zh || program.institution || "学校待补充"; }
function programSchoolLine(program: Program) { return [program.school_zh || program.school, program.name_zh && program.name && program.name_zh !== program.name ? program.name : null, program.country === "HK" ? "香港" : "新加坡"].filter(Boolean).join(" / "); }
function tierLabel(item: ProgramMatch) { if (item.tier === "not_recommended") return "不建议"; if (!item.formal_recommendation) return "预评估"; return { reach: "冲刺", target: "主申", safer: "相对稳妥", candidate: "候选" }[item.tier]; }
function taskTypeLabel(value: string) { return value === "source_review" ? "信息更新" : taskTypeLabels[value] ?? value; }
function normalizeTaskStatus(value?: string | null): TaskStatus { return taskStatusOptions.includes(value as TaskStatus) ? value as TaskStatus : "未开始"; }
function formatDependency(value: string) { return materialLabels[value] ?? fieldLabels[value] ?? value.replace(/_/g, " "); }
function formatReminder(value: string) { return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value; }
function parseTaskDate(value: string) { const match = value.match(/20\d{2}-\d{2}-\d{2}/); if (!match) return null; const date = new Date(match[0] + "T00:00:00"); return Number.isNaN(date.getTime()) ? null : date; }
function toIcsDate(date: Date) { return date.toISOString().slice(0, 10).replace(/-/g, ""); }
function toIcsTimestamp(date: Date) { return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z"); }
function escapeIcsText(value: string) { return String(value).replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/,/g, "\\,").replace(/;/g, "\\;"); }
function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) { return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>; }
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function DataBadge({ status, label }: { status?: string | null; label?: string }) { const value = status ?? "MODEL_INFERRED"; return <span className={("data-badge " + value.toLowerCase()).trim()}>{label ?? dataStatusLabels[value] ?? value}</span>; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>; }

export function ProgramMiniList({ matches }: { matches: ProgramMatch[] }) {
  if (!matches.length) return <EmptyState text={timelineCopy.noSelectedPrograms} />;
  return <div className="mini-program-list">{matches.map((item) => <article className="mini-program" key={item.program.id}><DataBadge status={sourceBadgeStatus(item.program)} /><h3>{programTitle(item.program)}</h3><p>{programInstitution(item.program)} / {programSchoolLine(item.program)}</p><span>{tierLabel(item)}</span></article>)}</div>;
}
