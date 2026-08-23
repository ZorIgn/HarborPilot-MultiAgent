"use client";

import { Button as IslandButton, Card as IslandCard, Tabs as IslandTabs, Title as IslandTitle } from "animal-island-ui";
import { BookOpenCheck, CheckCircle2, ClipboardList, ExternalLink, Search, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { dataStatusLabels, disciplineOptions, fieldLabels, materialLabels, previousCycleLabel, programCatalogCopy, studentTrustWarning } from "@/lib/copy";
import type { ApplicantPayload, CatalogProgram, DecisionFact, DecisionStatus, LayeredProgramPlanResult, ProgramMatch, ProgramSchemeState, WorkflowResult } from "@/lib/types";

type ProgramCatalogLoading = string | null;
export type ProgramCatalogFilters = { q: string; region: string; discipline: string; verification_status: string; deadline_status: string };
type ProgramCatalogState = Partial<WorkflowResult & LayeredProgramPlanResult> | null;
type ProgramLike = ProgramMatch["program"] | CatalogProgram;
type DecisionFacts = Record<string, DecisionFact>;
type ProgramContext = { program: ProgramLike; decision_facts?: DecisionFacts; formal_gate_status?: DecisionStatus; formal_use_ready?: boolean; formal_recommendation?: boolean };
type StrategyBand = NonNullable<ProgramMatch["strategy_band"]>;
type PlanTrustStats = { total: number; currentOfficial: number; previousReference: number; needsReview: number; selectedNeedsReview: number };
type CatalogReadinessStats = { total: number; currentOfficial: number; referenceReady: number; incomplete: number };

const bandKeys: StrategyBand[] = ["reach", "target", "safer", "candidate", "blocked"];
const decisionFieldOrder = ["official_program_url", "application_url", "deadline", "language_requirement", "materials", "tuition_hkd"];

export function ProgramCatalogPage(props: {
  payload: ApplicantPayload;
  catalog: CatalogProgram[];
  catalogTotal: number;
  catalogError: string | null;
  result: ProgramCatalogState;
  focusList: ProgramMatch[];
  applicationMix: ProgramMatch[];
  filters: ProgramCatalogFilters;
  setFilters: (filters: ProgramCatalogFilters) => void;
  selectedProgramIds: string[];
  programScheme: ProgramSchemeState;
  onSchemeChange: (scheme: ProgramSchemeState) => void;
  onToggle: (id: string) => void;
  onRun: () => void;
  onInspect: (id: string) => void;
  onRequestSourceUpdate?: (id: string) => void;
  loading: ProgramCatalogLoading;
}) {
  const [catalogLimit, setCatalogLimit] = useState(18);
  const [bandOverrides, setBandOverrides] = useState<Record<string, StrategyBand>>(props.programScheme.band_overrides ?? {});
  const [removedProgramIds, setRemovedProgramIds] = useState<string[]>(props.programScheme.removed_program_ids ?? []);
  const [extraCandidateIds, setExtraCandidateIds] = useState<string[]>(props.programScheme.extra_candidate_ids ?? []);
  const primaryMatches = props.applicationMix.length ? props.applicationMix.slice(0, 10) : props.focusList.slice(0, 12);
  const blockedPreview = (props.result?.blocked_candidates ?? props.result?.recommendations?.filter((item) => item.strategy_band === "blocked") ?? []).slice(0, 3);
  const allMatches = mergeProgramMatches([...primaryMatches, ...blockedPreview]);
  const extraMatches = props.catalog.filter((program) => extraCandidateIds.includes(program.id)).map(catalogProgramToEditableMatch);
  const editableMatches = mergeProgramMatches([...allMatches, ...extraMatches])
    .filter((item) => !removedProgramIds.includes(item.program.id))
    .map((item) => applyBandOverride(item, bandOverrides[item.program.id]));
  const bandedMatches = groupByBand(editableMatches);
  const selectedPrograms = buildSelectedPrograms(props.selectedProgramIds, editableMatches, props.catalog);
  const trustStats = buildPlanTrustStats(editableMatches, props.selectedProgramIds);
  const catalogReadiness = buildCatalogReadinessStats(props.catalog);
  const visibleCatalogSlice = props.catalog.slice(0, catalogLimit);
  const availableProgramTotal = Math.max(
    props.catalogTotal,
    new Set([...props.catalog.map((program) => program.id), ...editableMatches.map((item) => item.program.id)]).size,
  );

  useEffect(() => {
    setBandOverrides(props.programScheme.band_overrides ?? {});
    setRemovedProgramIds(props.programScheme.removed_program_ids ?? []);
    setExtraCandidateIds(props.programScheme.extra_candidate_ids ?? []);
  }, [props.programScheme]);

  function emitScheme(next: Partial<ProgramSchemeState>) {
    props.onSchemeChange({
      band_overrides: next.band_overrides ?? bandOverrides,
      removed_program_ids: next.removed_program_ids ?? removedProgramIds,
      extra_candidate_ids: next.extra_candidate_ids ?? extraCandidateIds,
    });
  }

  function changeBand(programId: string, band: StrategyBand) {
    const nextOverrides = { ...bandOverrides, [programId]: band };
    const nextRemoved = removedProgramIds.filter((id) => id !== programId);
    setBandOverrides(nextOverrides);
    setRemovedProgramIds(nextRemoved);
    emitScheme({ band_overrides: nextOverrides, removed_program_ids: nextRemoved });
  }

  function removeFromScheme(programId: string) {
    const nextRemoved = removedProgramIds.includes(programId) ? removedProgramIds : [...removedProgramIds, programId];
    setRemovedProgramIds(nextRemoved);
    emitScheme({ removed_program_ids: nextRemoved });
  }

  function addCatalogToScheme(programId: string) {
    const nextExtra = extraCandidateIds.includes(programId) ? extraCandidateIds : [...extraCandidateIds, programId];
    const nextOverrides = { ...bandOverrides, [programId]: (bandOverrides[programId] ?? "candidate") as StrategyBand };
    const nextRemoved = removedProgramIds.filter((id) => id !== programId);
    setExtraCandidateIds(nextExtra);
    setBandOverrides(nextOverrides);
    setRemovedProgramIds(nextRemoved);
    emitScheme({ band_overrides: nextOverrides, removed_program_ids: nextRemoved, extra_candidate_ids: nextExtra });
  }
const tabs = bandKeys.map((band) => ({
    key: band,
    label: strategyLabel(band) + " " + bandedMatches[band].length,
    children: <ProgramRows matches={bandedMatches[band]} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} onInspect={props.onInspect} onRequestSourceUpdate={props.onRequestSourceUpdate} loading={props.loading} muted={band === "blocked"} />,
  }));

  return <div className="page-stack">
    <IslandCard className="panel-card program-command" color="app-yellow">
      <div><span className="mini-label"><Search size={16} aria-hidden />{programCatalogCopy.heroEyebrow}</span><h2>{programCatalogCopy.heroTitle}</h2><p>{programCatalogCopy.heroBody}</p></div>
      <IslandButton type="primary" loading={props.loading === "programs"} onClick={props.onRun}>{props.loading === "programs" ? programCatalogCopy.runningButton : programCatalogCopy.runButton}</IslandButton>
    </IslandCard>

    <IslandCard className="panel-card" type="dashed">
      <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title={programCatalogCopy.trustBoundaryTitle} />
      <p>{programCatalogCopy.trustBoundaryBody}</p>
      <p className="form-note">{programCatalogCopy.trustBoundaryAction}</p>
    </IslandCard>

    <IslandCard className="panel-card">
      <PanelTitle icon={<ClipboardList size={19} aria-hidden />} title="当前意向与判断依据" />
      <div className="intent-grid">
        <div><span>目标方向</span><strong>{props.payload.discipline_interests.map(intentLabel).join("、") || "待选择"}</strong></div>
        <div><span>学校层级</span><strong>{props.payload.education.school_tier}</strong></div>
        <div><span>预算</span><strong>{formatMoney(props.payload.budget_hkd)}</strong></div>
        <div><span>判断方式</span><strong>规则打分 + 项目官网信息；模型只做解释、排序和文案辅助</strong></div>
      </div>
    </IslandCard>

    <section className="status-grid">
      <Metric label="择校方案项目" value={String(editableMatches.length)} detail="先展示 Agent 分档结果，不把全量库铺满首屏" />
      <Metric label="冲刺 / 主申 / 相对稳妥" value={bandedMatches.reach.length + "/" + bandedMatches.target.length + "/" + bandedMatches.safer.length} detail="按院校层级、GPA、语言、方向、经历和预算规则" />
      <Metric label="学生已保存" value={String(props.selectedProgramIds.length)} detail="时间线和文书只读取最终申请清单" />
      <Metric label="当前可用项目" value={String(availableProgramTotal)} detail="项目库与当前 Agent 方案去重；全量库在下方按需加载" />
    </section>

    <PlanTrustGate stats={trustStats} />
    <CatalogReadinessPanel stats={catalogReadiness} />
    <SelectedProgramShelf programs={selectedPrograms} onToggle={props.onToggle} onInspect={props.onInspect} loading={props.loading} />
    <EditablePlanTable matches={editableMatches} bandedMatches={bandedMatches} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} onInspect={props.onInspect} onBandChange={changeBand} onRemove={removeFromScheme} loading={props.loading} />
    <IslandTabs className="animal-tabs" items={tabs} defaultActiveKey="reach" />

    <IslandCard className="panel-card" type="dashed">
      <PanelTitle icon={<Search size={19} aria-hidden />} title={programCatalogCopy.fullCatalogTitle} />
      <p className="form-note">全量库不再默认铺满页面。需要补充候选项目时，在这里按学校、方向或地区搜索，并加入上方择校方案。</p>
      <div className="filters-grid">
        <label className="search-field">学校 / 学院 / 项目名<input value={props.filters.q} onChange={(event) => props.setFilters({ ...props.filters, q: event.target.value })} placeholder="如 HKU CS / NUS Analytics" /></label>
        <label>地区<select value={props.filters.region} onChange={(event) => props.setFilters({ ...props.filters, region: event.target.value })}><option value="">港新全部</option><option value="HK">香港</option><option value="SG">新加坡</option></select></label>
        <label>方向<select value={props.filters.discipline} onChange={(event) => props.setFilters({ ...props.filters, discipline: event.target.value })}><option value="">全部方向</option>{disciplineOptions.map((item) => <option value={item.code} key={item.code}>{item.label}</option>)}</select></label>
        <label>信息状态<select value={props.filters.verification_status} onChange={(event) => props.setFilters({ ...props.filters, verification_status: event.target.value })}><option value="">全部状态</option><option value="VERIFIED">官网当前季已核验</option><option value="EXTRACTED">官网信息需补充</option><option value="NOT_PUBLISHED">官网当前季未发布</option><option value="STALE">{previousCycleLabel("2027-fall")}</option><option value="CHANGED">来源冲突</option></select></label>
        <label>截止状态<select value={props.filters.deadline_status} onChange={(event) => props.setFilters({ ...props.filters, deadline_status: event.target.value })}><option value="">全部</option><option value="published">当前季已核验日期</option><option value="not_published">未发布 / 未核验</option></select></label>
      </div>
      <CatalogRows programs={visibleCatalogSlice} selectedIds={props.selectedProgramIds} schemeIds={editableMatches.map((item) => item.program.id)} onToggle={props.onToggle} onInspect={props.onInspect} onAddToScheme={addCatalogToScheme} onRequestSourceUpdate={props.onRequestSourceUpdate} loading={props.loading} emptyReason={catalogEmptyReason(props.catalogTotal, props.catalogError, props.filters)} />
      {props.catalog.length > visibleCatalogSlice.length ? <div className="center-actions"><IslandButton type="default" onClick={() => setCatalogLimit((value) => value + 18)}>再显示 18 个项目（当前 {visibleCatalogSlice.length}/{props.catalog.length}）</IslandButton></div> : null}
    </IslandCard>
  </div>;
}

function PlanTrustGate({ stats }: { stats: PlanTrustStats }) {
  if (!stats.total) return null;
  const officialReady = stats.currentOfficial > 0;
  return <IslandCard className="panel-card plan-trust-gate" type="dashed">
    <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="方案可信度闸门" />
    <section className="status-grid four">
      <Metric label="当前季官方" value={String(stats.currentOfficial)} detail="可进入当前季日期安排" />
      <Metric label="往届参考" value={String(stats.previousReference)} detail="只用于材料准备和节奏安排" />
      <Metric label="待官网核验" value={String(stats.needsReview)} detail="不能当作正式提交结论" />
      <Metric label="已选需复核" value={String(stats.selectedNeedsReview)} detail="保存清单后仍会进入来源更新任务" />
    </section>
    <p className="form-note"><strong>{officialReady ? "已有部分项目可按当前季官方字段安排。" : "当前仍是预评估 / 待官网核验。"}</strong> 没有当前季官方字段时，页面只给筛选、比较和准备动作，不把它写成可提交结论。</p>
  </IslandCard>;
}

function CatalogReadinessPanel({ stats }: { stats: CatalogReadinessStats }) {
  if (!stats.total) return <IslandCard className="panel-card" type="dashed"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title={programCatalogCopy.readinessTitle} /><EmptyState text={programCatalogCopy.readinessEmpty} /></IslandCard>;
  return <IslandCard className="panel-card catalog-readiness-panel">
    <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title={programCatalogCopy.readinessTitle} />
    <p className="form-note">{programCatalogCopy.readinessBody}</p>
    <section className="status-grid three">
      <Metric label={programCatalogCopy.readinessCurrent} value={String(stats.currentOfficial)} detail={programCatalogCopy.readinessCurrentDetail} />
      <Metric label={programCatalogCopy.readinessReference} value={String(stats.referenceReady)} detail={programCatalogCopy.readinessReferenceDetail} />
      <Metric label={programCatalogCopy.readinessIncomplete} value={String(stats.incomplete)} detail={programCatalogCopy.readinessIncompleteDetail} />
    </section>
  </IslandCard>;
}

function buildCatalogReadinessStats(programs: CatalogProgram[]): CatalogReadinessStats {
  return programs.reduce<CatalogReadinessStats>((stats, program) => {
    const status = readinessKind(program);
    return {
      total: stats.total + 1,
      currentOfficial: stats.currentOfficial + (status === "current" ? 1 : 0),
      referenceReady: stats.referenceReady + (status === "reference" ? 1 : 0),
      incomplete: stats.incomplete + (status === "incomplete" ? 1 : 0),
    };
  }, { total: 0, currentOfficial: 0, referenceReady: 0, incomplete: 0 });
}

function buildPlanTrustStats(matches: ProgramMatch[], selectedIds: string[]): PlanTrustStats {
  const activeMatches = matches.filter((item) => bandKey(item) !== "blocked");
  const selectedSet = new Set(selectedIds);
  return activeMatches.reduce<PlanTrustStats>((stats, item) => {
    const currentOfficial = formalReady(item);
    const previousReference = !currentOfficial && hasReferenceFields(item);
    const needsReview = !currentOfficial && !previousReference;
    return {
      total: stats.total + 1,
      currentOfficial: stats.currentOfficial + (currentOfficial ? 1 : 0),
      previousReference: stats.previousReference + (previousReference ? 1 : 0),
      needsReview: stats.needsReview + (needsReview ? 1 : 0),
      selectedNeedsReview: stats.selectedNeedsReview + (selectedSet.has(item.program.id) && !currentOfficial ? 1 : 0),
    };
  }, { total: 0, currentOfficial: 0, previousReference: 0, needsReview: 0, selectedNeedsReview: 0 });
}

function mergeProgramMatches(matches: ProgramMatch[]) {
  const byId = new Map<string, ProgramMatch>();
  matches.forEach((item) => { if (!byId.has(item.program.id)) byId.set(item.program.id, item); });
  return Array.from(byId.values()).sort((a, b) => bandOrder(bandKey(a)) - bandOrder(bandKey(b)) || b.fit_score - a.fit_score);
}

function groupByBand(matches: ProgramMatch[]): Record<StrategyBand, ProgramMatch[]> {
  return {
    reach: matches.filter((item) => bandKey(item) === "reach"),
    target: matches.filter((item) => bandKey(item) === "target"),
    safer: matches.filter((item) => bandKey(item) === "safer"),
    candidate: matches.filter((item) => bandKey(item) === "candidate"),
    blocked: matches.filter((item) => bandKey(item) === "blocked"),
  };
}

function bandKey(item: ProgramMatch): StrategyBand {
  if (item.strategy_band) return item.strategy_band;
  if (item.tier === "not_recommended") return "blocked";
  if (["reach", "target", "safer", "candidate"].includes(item.tier)) return item.tier as StrategyBand;
  return "candidate";
}
function bandOrder(value: StrategyBand) { return { reach: 0, target: 1, safer: 2, candidate: 3, blocked: 4 }[value]; }
function tierForBand(band: StrategyBand): ProgramMatch["tier"] { return band === "blocked" ? "not_recommended" : band; }
function applyBandOverride(item: ProgramMatch, band?: StrategyBand): ProgramMatch { return band ? { ...item, strategy_band: band, tier: tierForBand(band) } : item; }

function catalogProgramToEditableMatch(program: CatalogProgram): ProgramMatch {
  return { program, tier: "candidate", fit_score: 0, score_breakdown: { academic: 0, language: 0, experience: 0, discipline_fit: 0, budget_fit: 0, data_trust: 0 }, match_category: "general", intent_alignment: 0, intent_reasons: ["学生从项目库加入方案"], hard_rule_passed: false, formal_recommendation: false, data_status: program.data_status, reasons: ["学生从项目库补充到候选方案，需要结合背景评估再比较。"], risks: [studentTrustWarning(program.trust_detail, "需要核对项目页、申请入口、日期和材料。")], actions: ["打开项目详情页和申请入口，核对轮次、DDL、材料和提交方式。"], strategy_band: "candidate", consultant_note: "学生手动加入的候选项目", source_warning: studentTrustWarning(program.trust_detail, "需要核对项目页、申请入口、日期和材料。") };
}

function EditablePlanTable({ matches, bandedMatches, selectedIds, onToggle, onInspect, onBandChange, onRemove, loading }: { matches: ProgramMatch[]; bandedMatches: Record<StrategyBand, ProgramMatch[]>; selectedIds: string[]; onToggle: (id: string) => void; onInspect: (id: string) => void; onBandChange: (id: string, band: StrategyBand) => void; onRemove: (id: string) => void; loading: ProgramCatalogLoading }) {
  const [activeBand, setActiveBand] = useState<StrategyBand>("reach");
  const visible = bandedMatches[activeBand] ?? [];
  if (!matches.length) return <IslandCard className="panel-card" type="dashed"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="择校方案表" /><EmptyState text={programCatalogCopy.noPlan} /></IslandCard>;
  return <IslandCard className="panel-card plan-editor"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="可编辑择校方案（预评估）" />
    <div className="scheme-band-tabs">{bandKeys.map((band) => <button type="button" className={activeBand === band ? "active" : ""} onClick={() => setActiveBand(band)} key={band}><span>{strategyLabel(band)}</span><strong>{bandedMatches[band].length}</strong></button>)}</div>
    <p className="plan-table-scroll-hint" id="plan-table-scroll-hint">左右滑动查看完整分档</p>
    <div className="plan-table-wrap" tabIndex={0} aria-describedby="plan-table-scroll-hint"><table className="plan-table editable"><thead><tr><th>分档</th><th>学校 / 项目</th><th>推荐依据</th><th>主要风险</th><th>关键申请信息</th><th>操作</th></tr></thead><tbody>{visible.map((item) => <tr key={item.program.id}>
      <td><select value={bandKey(item)} onChange={(event) => onBandChange(item.program.id, event.target.value as StrategyBand)}><option value="reach">冲刺</option><option value="target">主申</option><option value="safer">相对稳妥</option><option value="candidate">候选</option><option value="blocked">不建议</option></select></td>
      <td><strong>{displayProgram(item.program)}</strong><small>{displayProgramSecondary(item.program)}</small><small>{programMeta(item.program)}</small><small>{formalUseLabel(item)}</small></td>
      <td><p>{item.consultant_note ?? item.explanation?.decision_basis?.[0] ?? item.reasons[0]}</p><small>匹配分 {Math.round(item.fit_score)} / 100</small></td>
      <td><p>{item.risks[0] ?? programCatalogCopy.defaultRisk}</p><small>{item.actions[0] ?? programCatalogCopy.defaultAction}</small></td>
      <td><div className="scheme-info-stack"><span>DDL：{formatDeadlineForProgram(item.program, item.decision_facts)}</span><span>语言：{formatLanguageRequirement(item.program, item.decision_facts)}</span><span>材料：{formatMaterials(item.program, item.decision_facts)}</span></div></td>
      <td><div className="table-actions"><IslandButton type={selectedIds.includes(item.program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(item.program.id)}>{selectedIds.includes(item.program.id) ? "已加入" : "加入清单"}</IslandButton><IslandButton type="default" size="small" loading={loading === "package"} onClick={() => onInspect(item.program.id)}>详情</IslandButton><button className="text-danger-button" type="button" onClick={() => onRemove(item.program.id)}>删除</button></div></td>
    </tr>)}</tbody></table></div>
    {!visible.length ? <EmptyState text="这个分档暂时没有项目，可以从下方推荐卡片或搜索结果加入。" /> : null}
  </IslandCard>;
}

function buildSelectedPrograms(ids: string[], matches: ProgramMatch[], catalog: CatalogProgram[]): ProgramContext[] {
  const byId = new Map<string, ProgramContext>();
  catalog.forEach((program) => byId.set(program.id, { program }));
  matches.forEach((item) => byId.set(item.program.id, { program: item.program, decision_facts: item.decision_facts, formal_gate_status: item.formal_gate_status, formal_use_ready: item.formal_use_ready, formal_recommendation: item.formal_recommendation }));
  return ids.map((id) => byId.get(id)).filter((item): item is ProgramContext => Boolean(item));
}

function SelectedProgramShelf({ programs, onToggle, onInspect, loading }: { programs: ProgramContext[]; onToggle: (id: string) => void; onInspect: (id: string) => void; loading: ProgramCatalogLoading }) {
  return <IslandCard className="panel-card selected-shelf"><PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="已保存的最终申请清单" />{programs.length ? <div className="selected-program-grid">{programs.map((context) => <article className="selected-program-card" key={context.program.id}><DataBadge status={sourceStatus(context)} /><h3>{displayProgram(context.program)}</h3><p>{programMeta(context.program)}</p><small>{context.formal_recommendation ? "正式推荐" : context.formal_gate_status === "PASS" ? "字段已核验，仍需按方案确认" : "预评估 / 待官网核验"}</small><div className="card-actions"><IslandButton type="default" size="small" onClick={() => onInspect(context.program.id)} loading={loading === "package"}>项目信息</IslandButton><IslandButton type="default" size="small" onClick={() => onToggle(context.program.id)}>移出清单</IslandButton></div></article>)}</div> : <EmptyState text="还没有保存项目。先在下方 Agent 分档结果里点击“加入清单”。" />}</IslandCard>;
}

function ProgramRows({ matches, selectedIds, onToggle, onInspect, onRequestSourceUpdate, loading, muted = false }: { matches: ProgramMatch[]; selectedIds: string[]; onToggle: (id: string) => void; onInspect: (id: string) => void; onRequestSourceUpdate?: (id: string) => void; loading: ProgramCatalogLoading; muted?: boolean }) {
  if (!matches.length) return <EmptyState text={programCatalogCopy.noMatches} />;
  return <div className="program-list">{matches.map((item) => <article className={("program-row " + (muted ? "muted" : "")).trim()} key={item.program.id}>
    <div className="program-main"><div className="program-title-row"><DataBadge status={sourceStatus(item)} /><span className={("band-pill " + (item.strategy_band ?? "candidate")).trim()}>{strategyLabel(item.strategy_band)} · {tierLabel(item)}</span></div><h3>{displayProgram(item.program)}</h3><p>{displayProgramSecondary(item.program)} · {programMeta(item.program)}</p>{item.consultant_note ? <p className="consultant-note">{item.consultant_note}</p> : null}<div className="program-signals"><Signal label="硬门槛" value={item.explanation?.hard_condition ?? (item.hard_rule_passed ? "通过" : "未通过")} /><Signal label="学术匹配" value={item.explanation?.academic_match ?? band(item.score_breakdown.academic)} /><Signal label="课程匹配" value={item.explanation?.course_match ?? band(item.score_breakdown.discipline_fit)} /><Signal label="经历匹配" value={item.explanation?.experience_match ?? band(item.score_breakdown.experience)} /><Signal label="预算匹配" value={item.explanation?.budget_match ?? band(item.score_breakdown.budget_fit)} /><Signal label="截止状态" value={formatDeadlineForProgram(item.program, item.decision_facts)} /><Signal label="语言要求" value={formatLanguageRequirement(item.program, item.decision_facts)} /><Signal label="材料清单" value={formatMaterials(item.program, item.decision_facts)} /><Signal label="项目官网" value={programDetailStatus(item.program, item.decision_facts)} /></div></div>
    <div className="program-evidence"><AdviceList title="推荐依据" items={(item.explanation?.decision_basis ?? item.reasons).slice(0, 3)} /><AdviceList title="主要风险" items={[studentTrustWarning(item.program.trust_detail, item.source_warning ?? programCatalogCopy.defaultRisk), ...(item.explanation?.uncertainties ?? item.risks)].filter((value): value is string => Boolean(value)).slice(0, 4)} /></div>
    <div className="program-actions"><IslandButton type={selectedIds.includes(item.program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(item.program.id)}>{selectedIds.includes(item.program.id) ? programCatalogCopy.selected : programCatalogCopy.addToList}</IslandButton><IslandButton type="default" size="small" loading={loading === "package"} onClick={() => onInspect(item.program.id)}>{programCatalogCopy.inspect}</IslandButton><ProgramLinks program={item.program} decisionFacts={item.decision_facts} onRequestSourceUpdate={onRequestSourceUpdate} /></div>
  </article>)}</div>;
}

function CatalogRows({ programs, selectedIds, schemeIds, onToggle, onInspect, onAddToScheme, onRequestSourceUpdate, loading, emptyReason }: { programs: CatalogProgram[]; selectedIds: string[]; schemeIds: string[]; onToggle: (id: string) => void; onInspect: (id: string) => void; onAddToScheme: (id: string) => void; onRequestSourceUpdate?: (id: string) => void; loading: ProgramCatalogLoading; emptyReason: string }) {
  if (!programs.length) return <EmptyState text={emptyReason} />;
  return <div className="catalog-list">{programs.map((program) => <article className="catalog-row" key={program.id}>
    <div><DataBadge status={studentSourceStatus(program)} /><h3>{displayProgram(program)}</h3><p>{displayProgramSecondary(program)} · {programMeta(program)} · {program.category_zh || program.discipline_tags.join(" / ")}</p></div>
    <div className="catalog-evidence-cell"><div className="program-signals compact-signals"><Signal label="学费" value={formatProgramMoney(program)} /><Signal label="学制" value={String(program.duration_months) + " 个月（目录信息）"} /><Signal label="截止" value={formatDeadlineForProgram(program)} /><Signal label="语言要求" value={formatLanguageRequirement(program)} /><Signal label="材料清单" value={formatMaterials(program)} /><Signal label="项目官网" value={programDetailStatus(program)} /></div><ProgramTrustPanel trust={program.trust_detail} /></div>
    <div className="program-actions"><IslandButton type="default" size="small" onClick={() => onAddToScheme(program.id)}>{schemeIds.includes(program.id) ? "已在方案" : "加入方案"}</IslandButton><IslandButton type={selectedIds.includes(program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(program.id)}>{selectedIds.includes(program.id) ? programCatalogCopy.selected : programCatalogCopy.addToList}</IslandButton><IslandButton type="default" size="small" loading={loading === "package"} onClick={() => onInspect(program.id)}>{programCatalogCopy.inspect}</IslandButton><ProgramLinks program={program} onRequestSourceUpdate={onRequestSourceUpdate} /></div>
  </article>)}</div>;
}

function ProgramTrustPanel({ trust }: { trust?: CatalogProgram["trust_detail"] }) {
  if (!trust) return <p className="form-note">{programCatalogCopy.trustLoading}</p>;
  const records = trust.field_records.filter((record) => ["official_program_url", "deadline", "tuition_hkd", "language_requirement", "materials", "application_url"].includes(record.field_name));
  return <div className="trust-panel"><div className="trust-panel-head"><DataBadge status={trust.production_ready || trust.formal_use_ready ? "OFFICIAL_VERIFIED_CURRENT" : trust.reference_ready ? "OFFICIAL_PREVIOUS_CYCLE" : "MODEL_INFERRED"} /><span>{trust.status_label}</span></div><p>{studentTrustWarning(trust)}</p><div className="trust-field-list">{orderedTrustRecords(records).map((record, index) => { const readiness = trustFieldReadiness(trust, record.field_name, record); return <div className="trust-field-card" key={record.field_name + "-" + String(record.source_url ?? record.value ?? index)}><div className="trust-field-card-head"><span>{fieldLabels[record.field_name] ?? record.field_name}</span><DataBadge status={readiness === "current" ? "OFFICIAL_VERIFIED_CURRENT" : readiness === "reference" ? "OFFICIAL_PREVIOUS_CYCLE" : "PENDING_REVIEW"} /></div><strong>{fieldRecordValue(record, readiness)}</strong><small>申请季 {record.cycle || trust.cycle}</small>{record.evidence_snippet ? <p>{fieldRecordExcerpt(record.evidence_snippet)}</p> : null}{record.source_url ? <a href={record.source_url} target="_blank" rel="noreferrer">{readiness === "current" || readiness === "reference" ? "打开已记录来源" : "查看候选来源（待核验）"}</a> : null}</div>; })}</div></div>;
}

function orderedTrustRecords(records: NonNullable<CatalogProgram["trust_detail"]>["field_records"]) { const order = ["official_program_url", "application_url", "deadline", "language_requirement", "materials", "tuition_hkd"]; return [...records].sort((a, b) => order.indexOf(a.field_name) - order.indexOf(b.field_name)); }
function ProgramLinks({ program, decisionFacts, onRequestSourceUpdate }: { program: ProgramLike; decisionFacts?: DecisionFacts; onRequestSourceUpdate?: (id: string) => void }) {
  const verifiedDetailUrl = verifiedFieldUrl(program, "official_program_url", decisionFacts);
  const candidateDetailUrl = verifiedDetailUrl ? null : candidateFieldUrl(program, "official_program_url");
  const verifiedApplicationUrl = verifiedFieldUrl(program, "application_url", decisionFacts);
  const candidateApplicationUrl = verifiedApplicationUrl ? null : candidateFieldUrl(program, "application_url");
  return <div className="link-row">{verifiedDetailUrl ? <a href={verifiedDetailUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />{programCatalogCopy.detailPage}（当前季已核验）</a> : candidateDetailUrl ? <a href={candidateDetailUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />项目页线索（待核验）</a> : <><span className="link-warning">{programCatalogCopy.missingDetailPage}</span>{onRequestSourceUpdate ? <button className="text-link source-update-button" type="button" onClick={() => onRequestSourceUpdate(program.id)}>{programCatalogCopy.queueSourceUpdate}</button> : null}</>}{verifiedApplicationUrl ? <a href={verifiedApplicationUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />{programCatalogCopy.applicationEntry}（当前季已核验）</a> : candidateApplicationUrl ? <a href={candidateApplicationUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />申请入口线索（待核验）</a> : <span className="link-warning">{programCatalogCopy.missingApplicationEntry}</span>}</div>;
}
function absoluteHttpUrl(value: unknown) { try { const url = new URL(String(value ?? "")); return ["http:", "https:"].includes(url.protocol) ? url.toString() : null; } catch { return null; } }
function isLikelyProgramDetailUrl(urlValue: string) {
  const url = urlValue.toLowerCase();
  if (url.includes("masters.smu.edu.sg/programmes/") && !url.endsWith("/programmes")) return true;
  if (url.includes("www.ntu.edu.sg") && url.includes("/admissions/graduate-studies/") && url.split("/").length > 6) return true;
  if (url.includes("prog-crs.hkust.edu.hk/pgprog/")) return true;
  if (url.includes("www.sutd.edu.sg/programme-listing/")) return true;
  const generic = ["programme-list", "taught-postgraduate-programmes", "/admissions", "/graduate-admissions", "/programmes?", "/programs?", "/programme/index"];
  return !generic.some((pattern) => url.includes(pattern));
}
type FieldReadiness = "current" | "reference" | "candidate" | "missing";
type TrustRecord = NonNullable<CatalogProgram["trust_detail"]>["field_records"][number];

function hasProgramDetailPage(program: ProgramLike, decisionFacts?: DecisionFacts) { return Boolean(verifiedFieldUrl(program, "official_program_url", decisionFacts) || candidateFieldUrl(program, "official_program_url")); }
function programDetailStatus(program: ProgramLike, decisionFacts?: DecisionFacts) {
  if (verifiedFieldUrl(program, "official_program_url", decisionFacts)) return "项目详情页（当前季已核验）";
  return candidateFieldUrl(program, "official_program_url") ? "项目页线索（待官网核验）" : "未找到项目详情页";
}
function readinessKind(program: ProgramLike): "current" | "reference" | "incomplete" {
  if (program.trust_detail?.production_ready || program.trust_detail?.formal_use_ready) return "current";
  if (program.trust_detail?.reference_ready) return "reference";
  return "incomplete";
}
function studentSourceStatus(program: ProgramLike) {
  const readiness = readinessKind(program);
  if (readiness === "current") return "OFFICIAL_VERIFIED_CURRENT";
  if (readiness === "reference") return "OFFICIAL_PREVIOUS_CYCLE";
  return "MODEL_INFERRED";
}
function sourceStatus(context: ProgramContext | ProgramMatch) {
  const program = context.program;
  const formal = "formal_use_ready" in context && context.formal_use_ready === true
    || "formal_gate_status" in context && context.formal_gate_status === "PASS"
    || Boolean(program.trust_detail?.production_ready || program.trust_detail?.formal_use_ready);
  if (formal) return "OFFICIAL_VERIFIED_CURRENT";
  if (hasReferenceFields(context)) return "OFFICIAL_PREVIOUS_CYCLE";
  return "MODEL_INFERRED";
}
function formalReady(item: ProgramMatch) {
  return item.formal_use_ready === true || item.formal_gate_status === "PASS" || Boolean(item.program.trust_detail?.production_ready || item.program.trust_detail?.formal_use_ready);
}
function hasReferenceFields(context: ProgramContext | ProgramMatch) {
  const program = context.program;
  const facts = "decision_facts" in context ? context.decision_facts : undefined;
  if (program.trust_detail?.reference_ready) return true;
  const states = criticalDecisionFields(program).map((field) => fieldReadiness(program, field, facts));
  return states.some((state) => state === "reference") && states.every((state) => state === "current" || state === "reference");
}
function criticalDecisionFields(program: ProgramLike) { void program; return decisionFieldOrder; }
function trustFieldReadiness(trust: NonNullable<ProgramLike["trust_detail"]>, field: string, record?: TrustRecord): FieldReadiness {
  if (trust.official_current_fields.includes(field) || (trust.production_ready && !trust.official_current_fields.length && record?.status === "OFFICIAL_VERIFIED_CURRENT")) return "current";
  if (trust.stale_or_reference_fields.includes(field) || (trust.reference_ready && record?.status === "OFFICIAL_PREVIOUS_CYCLE")) return "reference";
  if (record?.value && record.value !== "NOT_PUBLISHED") return "candidate";
  return "missing";
}
function fieldReadiness(program: ProgramLike, field: string, decisionFacts?: DecisionFacts): FieldReadiness {
  const fact = decisionFacts?.[field];
  if (fact?.formal_use_ready && fact.decision_status === "PASS") return "current";
  if (fact?.provenance_status === "REVIEWED_PREVIOUS") return "reference";
  const record = program.trust_detail?.field_records.find((item) => item.field_name === field);
  if (program.trust_detail) return trustFieldReadiness(program.trust_detail, field, record);
  if (record?.value && record.value !== "NOT_PUBLISHED") return "candidate";
  return "missing";
}
function factValue(facts: DecisionFacts | undefined, field: string, readiness: FieldReadiness) {
  const fact = facts?.[field];
  if (!fact || (readiness !== "current" && readiness !== "reference")) return null;
  const value = fact.normalized_value ?? fact.raw_value;
  return value === null || value === undefined || value === "" || value === "NOT_PUBLISHED" ? null : value;
}
function verifiedFieldUrl(program: ProgramLike, field: "official_program_url" | "application_url", decisionFacts?: DecisionFacts) {
  const readiness = fieldReadiness(program, field, decisionFacts);
  if (readiness !== "current") return null;
  const factValueUrl = absoluteHttpUrl(factValue(decisionFacts, field, readiness));
  if (factValueUrl) return field === "official_program_url" && !isLikelyProgramDetailUrl(factValueUrl) ? null : factValueUrl;
  const record = program.trust_detail?.field_records.find((item) => item.field_name === field);
  if (!record || record.status !== "OFFICIAL_VERIFIED_CURRENT") return null;
  const recordUrl = absoluteHttpUrl(record.value);
  return recordUrl && (field !== "official_program_url" || isLikelyProgramDetailUrl(recordUrl)) ? recordUrl : null;
}
function candidateFieldUrl(program: ProgramLike, field: "official_program_url" | "application_url") {
  const value = absoluteHttpUrl(field === "official_program_url" ? program.official_program_url : program.application_url);
  if (!value) return null;
  return field === "official_program_url" && !isLikelyProgramDetailUrl(value) ? null : value;
}
function legacyStatusMatches(program: ProgramLike, value: string) {
  return program.data_status === value;
}
function DataBadge({ status }: { status?: string | null }) { const value = status ?? "MODEL_INFERRED"; return <span className={("data-badge " + value.toLowerCase()).trim()}>{dataStatusLabels[value] ?? value}</span>; }
function AdviceList({ title, items }: { title: string; items: string[] }) { if (!items.length) return null; return <div className="advice-list"><h3>{title}</h3>{items.slice(0, 6).map((item) => <Rule text={item} key={item} />)}</div>; }
function Rule({ text }: { text: string }) { return <div><CheckCircle2 size={15} aria-hidden /><span>{text}</span></div>; }
function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) { return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>; }
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function Signal({ label, value }: { label: string; value: ReactNode }) { return <span className="signal"><small>{label}</small><strong>{value}</strong></span>; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>; }

function catalogEmptyReason(total: number, error: string | null, filters: ProgramCatalogFilters) { if (error) return programCatalogCopy.catalogError; if (total === 0) return programCatalogCopy.catalogEmptyDb; if (Object.values(filters).filter(Boolean).length) return programCatalogCopy.catalogEmptyFiltered; return programCatalogCopy.catalogEmptyDefault; }
export function filterCatalog(programs: CatalogProgram[], filters: ProgramCatalogFilters) { return programs.filter((program) => { const haystack = [program.name, program.name_zh, program.institution, program.institution_zh, program.school, program.school_zh].filter(Boolean).join(" ").toLowerCase(); if (filters.q && !haystack.includes(filters.q.toLowerCase())) return false; if (filters.region && program.country !== filters.region) return false; if (filters.discipline && ![program.category_zh, ...program.discipline_tags].filter(Boolean).join(" ").toLowerCase().includes(filters.discipline.toLowerCase())) return false; if (filters.verification_status) { const status = readinessKind(program); if (filters.verification_status === "VERIFIED" && status !== "current") return false; if (filters.verification_status === "STALE" && status !== "reference") return false; if (filters.verification_status === "EXTRACTED" && status !== "incomplete") return false; if (!["VERIFIED", "STALE", "EXTRACTED"].includes(filters.verification_status) && !legacyStatusMatches(program, filters.verification_status)) return false; } const currentDeadline = hasVerifiedCurrentDeadline(program); if (filters.deadline_status === "published" && !currentDeadline) return false; if (filters.deadline_status === "not_published" && currentDeadline) return false; return true; }); }

function displayProgram(program: ProgramLike) { return program.name_zh || program.name || "未找到项目名称"; }
function displayProgramSecondary(program: ProgramLike) { return program.name_zh && program.name && program.name_zh !== program.name ? program.name : program.institution || programCatalogCopy.fallbackEnglishName; }
function programMeta(program: ProgramLike) { return [program.institution_zh || program.institution, program.school_zh || program.school || programCatalogCopy.fallbackSchool, regionLabel(program.country)].filter(Boolean).join(" · "); }
function regionLabel(country: ProgramLike["country"]) { return country === "HK" ? "香港" : "新加坡"; }
function tierLabel(item: ProgramMatch) { if (item.tier === "not_recommended") return "不建议"; if (!item.formal_recommendation) return "预评估"; return { reach: "冲刺", target: "主申", safer: "相对稳妥", candidate: "候选" }[item.tier]; }
function formalUseLabel(item: ProgramMatch) {
  if (item.formal_recommendation && formalReady(item)) return "正式推荐（字段已核验；提交前仍需打开官网复核）";
  if (formalReady(item)) return "字段已核验，但当前结果仍是方案候选";
  return "预评估 / 待官网核验";
}
function strategyLabel(value?: ProgramMatch["strategy_band"]) { return { reach: "冲刺", target: "主申", safer: "相对稳妥", candidate: "候选", blocked: "不建议" }[value ?? "candidate"]; }
function intentLabel(intent: string) { return { "computer science": "计算机", "business analytics": "商业分析", artificial_intelligence: "人工智能", computer_science: "计算机科学", data_science: "数据科学", fintech: "金融科技", software_engineering: "软件工程", cyber_security: "网络安全", finance: "金融", management: "商科管理", education_language: "教育/语言", interdisciplinary: "跨学科" }[intent] ?? intent; }
function band(value?: number) { if (value === undefined) return "未知"; if (value >= 78) return "高"; if (value >= 62) return "中"; return "低"; }
function formatMoney(value: number | null | undefined) { return value ? String(Math.round(value / 10000)) + " 万港币" : programCatalogCopy.unverifiedMoney; }
function deadlineRecord(program: ProgramLike) { return program.trust_detail?.field_records.find((record) => record.field_name === "deadline"); }
function hasVerifiedCurrentDeadline(program: ProgramLike) { const record = deadlineRecord(program); return fieldReadiness(program, "deadline") === "current" && Boolean(record?.value && record.value !== "NOT_PUBLISHED"); }
function formatDeadlineForProgram(program: ProgramLike, decisionFacts?: DecisionFacts) {
  const fallback = program.deadline && program.deadline !== "NOT_PUBLISHED" ? String(program.deadline) : null;
  return formatProgramField(program, "deadline", fallback, "当前季未发布 / 待官网核验", decisionFacts);
}
function formatLanguageRequirement(program: ProgramLike, decisionFacts?: DecisionFacts) { const language = program.requirements?.language ?? {}; const parts = Object.entries(language).filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => key.toUpperCase() + " " + String(value)); const fallback = parts.length ? parts.slice(0, 2).join(" / ") : null; return formatProgramField(program, "language_requirement", fallback, "打开项目页核对", decisionFacts); }
function formatMaterials(program: ProgramLike, decisionFacts?: DecisionFacts) { const materials = program.materials ?? []; const fallback = materials.length ? materials.slice(0, 3).map((item) => materialLabels[item] ?? item).join(" / ") : null; return formatProgramField(program, "materials", fallback, "成绩单 / 语言 / 推荐信 / CV / PS（待官网核验）", decisionFacts); }
function formatProgramMoney(program: ProgramLike, decisionFacts?: DecisionFacts) {
  const readiness = fieldReadiness(program, "tuition_hkd", decisionFacts);
  const tuitionRecord = program.trust_detail?.field_records.find((item) => item.field_name === "tuition_hkd");
  const value = factValue(decisionFacts, "tuition_hkd", readiness) ?? (readiness === "current" ? tuitionRecord?.value : null);
  const amount = typeof value === "number" ? value : Number.parseFloat(String(value ?? ""));
  if (readiness === "current" && Number.isFinite(amount) && amount > 0) return formatMoney(amount);
  if (program.tuition_hkd) return `待官网核验（库内参考：${formatMoney(program.tuition_hkd)}）`;
  return programCatalogCopy.unverifiedMoney;
}
function formatProgramField(program: ProgramLike, field: string, fallback: string | null, empty: string, decisionFacts?: DecisionFacts) {
  const readiness = fieldReadiness(program, field, decisionFacts);
  const fact = factValue(decisionFacts, field, readiness);
  const record = program.trust_detail?.field_records.find((item) => item.field_name === field);
  const value = fact ?? (readiness === "current" || readiness === "reference" ? record?.value : null);
  if (value && value !== "NOT_PUBLISHED") return readiness === "current" ? String(value) : `${String(value)}（${previousCycleLabel(record?.cycle ?? decisionFacts?.[field]?.cycle ?? program.cycle)}）`;
  return fallback ? `待官网核验（库内参考：${fallback}）` : empty;
}
function fieldRecordValue(record: TrustRecord, readiness: FieldReadiness) {
  if (!record.value || record.value === "NOT_PUBLISHED") return readiness === "reference" ? `${previousCycleLabel(record.cycle)}可用于安排材料` : "当前季未发布 / 待官网核验";
  const compact = String(record.value).replace(/\s+/g, " ").trim();
  const value = compact.length > 120 ? compact.slice(0, 120) + "..." : compact;
  if (readiness === "current") return value;
  if (readiness === "reference") return `${value}（${previousCycleLabel(record.cycle)}）`;
  return `待官网核验（目录/抓取线索：${value}）`;
}
function fieldRecordExcerpt(value: string) { const compact = value.replace(/\s+/g, " ").trim(); return compact.length > 150 ? compact.slice(0, 150) + "..." : compact; }
