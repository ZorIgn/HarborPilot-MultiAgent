"use client";

import {
  Button as IslandButton,
  Card as IslandCard,
  Cursor,
  Divider,
  Footer,
  Tabs as IslandTabs,
  Title as IslandTitle,
  Tooltip as IslandTooltip,
} from "animal-island-ui";
import {
  AlertTriangle,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Database,
  ExternalLink,
  FileText,
  GraduationCap,
  KeyRound,
  ListChecks,
  PanelRightOpen,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  configureLLM,
  getEvidenceGraphSummary,
  getHealth,
  getPrograms,
  getQuestionnaireSchema,
  getSourceRegistry,
  runApplicationPlan,
  runBackgroundStage,
  runDataRefresh,
  runProgramPlan,
  runWritingInterview,
  runWritingPlan,
  runWritingReview,
} from "@/lib/api";
import { demoPayload } from "@/lib/demoPayload";
import type {
  AgentTrace,
  ApplicantPayload,
  CatalogProgram,
  ConsultantSchoolPlan,
  DataRefreshReport,
  DimensionFinding,
  EvidenceGraphSummary,
  FieldEvidenceRecord,
  LayeredProgramPlanResult,
  ProgramMatch,
  QuestionnaireResponse,
  QuestionnaireSchema,
  SourceRegistry,
  StoryCard,
  TimelineTask,
  WorkflowResult,
  WritingInterviewQuestion,
  WritingReviewRubric,
} from "@/lib/types";

type ViewMode = "home" | "assessment" | "programs" | "timeline" | "writing" | "agent" | "settings";
type StageLoading = "background" | "programs" | "timeline" | "writing" | "interview" | "data" | "llm" | null;
type Provider = "mock" | "deepseek" | "openai" | "compatible";
type DocumentType = "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";
type QuestionnaireValues = Record<string, string>;
type AppState = Partial<WorkflowResult & LayeredProgramPlanResult> & {
  selected_programs?: ProgramMatch[];
  source_refresh?: DataRefreshReport | null;
  story_cards?: StoryCard[];
};

const STORAGE_PAYLOAD = "harborpilot.payload.v3";
const STORAGE_RESULT = "harborpilot.result.v3";
const STORAGE_SELECTED = "harborpilot.selectedProgramIds.v3";
const STORAGE_QUESTIONNAIRE = "harborpilot.writingQuestionnaire.v3";

const navItems = [
  { href: "/", label: "我的申请", view: "home" },
  { href: "/assessment", label: "背景资料", view: "assessment" },
  { href: "/programs", label: "项目探索", view: "programs" },
  { href: "/timeline", label: "任务与材料", view: "timeline" },
  { href: "/writing", label: "文书工作台", view: "writing" },
  { href: "/agent-lab", label: "资料中心", view: "agent" },
  { href: "/settings", label: "设置", view: "settings" },
] as const;

const disciplineOptions = [
  { code: "computer_science", label: "计算机" },
  { code: "artificial_intelligence", label: "人工智能" },
  { code: "data_science", label: "数据科学" },
  { code: "business analytics", label: "商业分析 / 信息系统" },
  { code: "fintech", label: "金融科技" },
  { code: "finance", label: "金融 / 会计" },
  { code: "communication", label: "传媒 / 传播" },
  { code: "public policy", label: "公共政策" },
  { code: "education", label: "教育 / 语言" },
  { code: "design", label: "建筑 / 城市 / 设计" },
];

const schoolTiers: Array<{ code: ApplicantPayload["education"]["school_tier"]; label: string }> = [
  { code: "C9", label: "C9" },
  { code: "985", label: "985" },
  { code: "211", label: "211" },
  { code: "double_first_class", label: "双一流" },
  { code: "regular", label: "双非 / 普通本科" },
  { code: "overseas", label: "海外本科" },
];

const dataStatusLabels: Record<string, string> = {
  DISCOVERED: "已找到来源",
  EXTRACTED: "待学校确认",
  PENDING_REVIEW: "待确认",
  VERIFIED: "学校已确认",
  STALE: "待刷新",
  CHANGED: "发现变化",
  NOT_PUBLISHED: "本季未发布",
  OFFICIAL_VERIFIED_CURRENT: "学校已确认",
  OFFICIAL_PREVIOUS_CYCLE: "上一申请季参考",
  COMMUNITY_ONLY: "仅经验参考",
  CONFLICTED: "来源冲突",
  MODEL_INFERRED: "系统推测",
};

const fieldLabels: Record<string, string> = {
  deadline: "截止日期",
  tuition_hkd: "学费",
  materials: "材料清单",
  language_requirement: "语言要求",
  application_url: "申请入口",
  essay_prompts: "文书题目",
};

const materialLabels: Record<string, string> = {
  transcript: "正式成绩单",
  degree_certificate: "在读 / 毕业证明",
  core_courses: "核心课程清单",
  cv: "通用 CV",
  recommendation: "推荐信素材",
  language_score: "语言成绩单",
  experience_proof: "经历证明",
  personal_statement: "个人陈述 / SOP",
  essay_prompts: "文书题目",
  official_program_page: "官方项目页",
  official_pdf_or_faq: "官方 PDF / FAQ",
  application_system: "网申系统",
};

const taskTypeLabels: Record<string, string> = {
  profile: "背景",
  source_review: "官网确认",
  materials: "通用材料",
  language: "语言",
  recommendation: "推荐信",
  writing: "文书",
  submission: "网申",
  scholarship: "奖学金",
};

const documentTypeOptions: Array<{ value: DocumentType; label: string; detail: string }> = [
  { value: "PS", label: "PS 个人陈述", detail: "强调故事、动机、项目匹配和职业目标" },
  { value: "SOP", label: "SOP 目的陈述", detail: "适合技术、学术或职业目标更清晰的项目" },
  { value: "CV", label: "CV / Resume", detail: "优化项目、实习和技能 bullet" },
  { value: "ESSAY", label: "Essay", detail: "学校指定小文书或补充题" },
  { value: "REFERENCE_PACKAGE", label: "推荐信素材包", detail: "整理推荐人能观察到的事实" },
];

export function HarborPilotApp({ view }: { view: ViewMode }) {
  const [payload, setPayload] = useState<ApplicantPayload>(demoPayload);
  const [result, setResult] = useState<AppState | null>(null);
  const [catalog, setCatalog] = useState<CatalogProgram[]>([]);
  const [sourceRegistry, setSourceRegistry] = useState<SourceRegistry | null>(null);
  const [evidenceGraph, setEvidenceGraph] = useState<EvidenceGraphSummary | null>(null);
  const [questionnaireSchema, setQuestionnaireSchema] = useState<QuestionnaireSchema | null>(null);
  const [questionnaireValues, setQuestionnaireValues] = useState<QuestionnaireValues>({});
  const [selectedProgramIds, setSelectedProgramIds] = useState<string[]>([]);
  const [interviewQuestions, setInterviewQuestions] = useState<WritingInterviewQuestion[]>([]);
  const [writingReview, setWritingReview] = useState<WritingReviewRubric | null>(null);
  const [health, setHealth] = useState<{ status: string; llm_mode: string; llm_provider?: string } | null>(null);
  const [loading, setLoading] = useState<StageLoading>(null);
  const [error, setError] = useState<string | null>(null);
  const [activityOpen, setActivityOpen] = useState(false);
  const [filters, setFilters] = useState({ q: "", region: "", discipline: "", verification_status: "", deadline_status: "" });
  const [provider, setProvider] = useState<Provider>("deepseek");
  const [model, setModel] = useState("deepseek-chat");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [llmMessage, setLlmMessage] = useState("请先配置模型 Key。Key 只提交给本地后端，不会写入前端存储。");
  const [writingDocumentType, setWritingDocumentType] = useState<DocumentType>("PS");
  const [writingTargetProgramId, setWritingTargetProgramId] = useState("");

  useEffect(() => {
    setPayload(readStorage<ApplicantPayload>(STORAGE_PAYLOAD) ?? demoPayload);
    setResult(readStorage<AppState>(STORAGE_RESULT));
    setSelectedProgramIds(readStorage<string[]>(STORAGE_SELECTED) ?? []);
    setQuestionnaireValues(readStorage<QuestionnaireValues>(STORAGE_QUESTIONNAIRE) ?? {});
    getHealth().then(setHealth).catch(() => setHealth(null));
    getPrograms({ limit: 180 }).then(setCatalog).catch(() => setCatalog([]));
    getSourceRegistry().then(setSourceRegistry).catch(() => setSourceRegistry(null));
    getEvidenceGraphSummary().then(setEvidenceGraph).catch(() => setEvidenceGraph(null));
    getQuestionnaireSchema().then(setQuestionnaireSchema).catch(() => setQuestionnaireSchema(null));
  }, []);

  const recommendations = result?.recommendations ?? [];
  const focusList = result?.focus_list?.length ? result.focus_list : recommendations.filter((item) => item.tier !== "not_recommended").slice(0, 15);
  const applicationMix = result?.application_mix?.length ? result.application_mix : focusList.slice(0, 8);
  const selectedMatches = useMemo(() => {
    const byId = new Map<string, ProgramMatch>();
    recommendations.forEach((item) => byId.set(item.program.id, item));
    (result?.selected_programs ?? []).forEach((item) => byId.set(item.program.id, item));
    return selectedProgramIds.map((id) => byId.get(id)).filter((item): item is ProgramMatch => Boolean(item));
  }, [recommendations, result?.selected_programs, selectedProgramIds]);
  const visibleCatalog = useMemo(() => filterCatalog(catalog, filters), [catalog, filters]);
  const selectedProgram = selectedMatches[0]?.program ?? focusList[0]?.program ?? null;
  const realModel = health?.llm_provider && health.llm_provider !== "mock";

  function persistPayload(next: ApplicantPayload) {
    setPayload(next);
    window.localStorage.setItem(STORAGE_PAYLOAD, JSON.stringify(next));
  }

  function mergeResult(patch: Partial<AppState>) {
    setResult((previous) => {
      const merged = { ...(previous ?? {}), ...patch };
      window.localStorage.setItem(STORAGE_RESULT, JSON.stringify(merged));
      return merged;
    });
  }

  function persistSelected(ids: string[]) {
    const unique = Array.from(new Set(ids));
    setSelectedProgramIds(unique);
    window.localStorage.setItem(STORAGE_SELECTED, JSON.stringify(unique));
  }

  function toggleProgram(id: string) {
    persistSelected(selectedProgramIds.includes(id) ? selectedProgramIds.filter((item) => item !== id) : [...selectedProgramIds, id]);
  }

  function updateQuestionnaire(fieldId: string, value: string) {
    const next = { ...questionnaireValues, [fieldId]: value };
    setQuestionnaireValues(next);
    window.localStorage.setItem(STORAGE_QUESTIONNAIRE, JSON.stringify(next));
  }

  async function runBackground(nextPayload = payload) {
    setLoading("background");
    setError(null);
    try {
      const response = await runBackgroundStage(nextPayload);
      persistPayload(nextPayload);
      mergeResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "背景评估接口调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function runPrograms(nextPayload = payload, redirectToPrograms = false) {
    setLoading("programs");
    setError(null);
    try {
      const response = await runProgramPlan(nextPayload);
      persistPayload(nextPayload);
      mergeResult(response);
      if (!selectedProgramIds.length) {
        persistSelected(response.application_mix.slice(0, 3).map((item) => item.program.id));
      }
      if (redirectToPrograms && typeof window !== "undefined") {
        window.location.href = "/programs";
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "项目推荐接口调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function runTimeline() {
    if (!selectedProgramIds.length) {
      setError("请先在项目探索中把项目加入申请方案。");
      return;
    }
    setLoading("timeline");
    setError(null);
    try {
      const response = await runApplicationPlan({ profile: payload, selected_program_ids: selectedProgramIds });
      mergeResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务与材料接口调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function refreshSources(liveFetch = false) {
    setLoading("data");
    setError(null);
    try {
      const response = await runDataRefresh({
        region: "ALL",
        selected_program_ids: selectedProgramIds,
        dry_run: !liveFetch,
        use_llm: Boolean(realModel),
        max_sources: selectedProgramIds.length ? 24 : 16,
      });
      mergeResult({ source_refresh: response });
      setEvidenceGraph(await getEvidenceGraphSummary());
    } catch (err) {
      setError(err instanceof Error ? err.message : "数据刷新工作流调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function runInterview() {
    setLoading("interview");
    setError(null);
    try {
      const questions = await runWritingInterview({
        profile: payload,
        selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || selectedProgram?.id || ""].filter(Boolean),
        document_type: writingDocumentType,
      });
      setInterviewQuestions(questions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文书访谈接口调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function runWriting() {
    setLoading("writing");
    setError(null);
    try {
      const response = await runWritingPlan({
        profile: payload,
        questionnaire: buildQuestionnaireResponse(questionnaireSchema, questionnaireValues),
        selected_program_ids: [writingTargetProgramId || selectedProgramIds[0] || selectedProgram?.id || ""].filter(Boolean),
        document_type: writingDocumentType,
      });
      mergeResult(response);
      const rubric = await runWritingReview({ draft: response.writing, story_cards: response.story_cards });
      setWritingReview(rubric);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文书工作流调用失败");
    } finally {
      setLoading(null);
    }
  }

  async function connectLLM() {
    if (!apiKey.trim()) {
      setLlmMessage("请先输入 API Key。");
      return;
    }
    setLoading("llm");
    setLlmMessage("正在连接本地后端模型配置...");
    try {
      const config = await configureLLM({
        provider,
        api_key: apiKey.trim(),
        model,
        base_url: provider === "compatible" ? baseUrl.trim() : undefined,
      });
      setHealth({ status: "ok", llm_mode: config.model, llm_provider: config.provider });
      setLlmMessage(config.message);
      setApiKey("");
    } catch (err) {
      setLlmMessage(err instanceof Error ? err.message : "模型连接失败");
    } finally {
      setLoading(null);
    }
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
          <Link className="brand" href="/">
            <span className="brand-mark"><GraduationCap size={22} aria-hidden /></span>
            <span>
              <strong>HarborPilot</strong>
              <small>港新硕士信息辅助平台</small>
            </span>
          </Link>
          <nav aria-label="主导航">
            {navItems.map((item) => (
              <Link className={view === item.view ? "active" : ""} href={item.href} key={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="nav-footnote">
            <span className={`status-dot ${realModel ? "real" : "mock"}`} />
            <div>
              <strong>{realModel ? "AI 助手已连接" : "请先填写模型 Key"}</strong>
              <small>学校信息未确认前，只做准备建议。</small>
            </div>
          </div>
        </aside>

        <section className="island-workspace">
          <header className="workspace-topbar">
            <div>
              <span className="eyebrow">2027 Fall · Hong Kong / Singapore</span>
              <h1>{pageTitle(view)}</h1>
            </div>
            <IslandTooltip title="查看本次分析用了哪些资料、哪些结论仍需你确认。" variant="island">
              <button className="activity-button" type="button" onClick={() => setActivityOpen(true)}>
                <PanelRightOpen size={18} aria-hidden />
                AI 决策依据
              </button>
            </IslandTooltip>
          </header>

          {error ? (
          <div className="error-strip">
            <AlertTriangle size={18} aria-hidden />
            <span>{error}</span>
          </div>
        ) : null}

          {loading ? <GlobalProgress stage={loading} /> : null}

          {!realModel ? (
            <KeySetupCard
              provider={provider}
              model={model}
              baseUrl={baseUrl}
              apiKey={apiKey}
              message={llmMessage}
              loading={loading === "llm"}
              compact={view !== "home" && view !== "settings"}
              onProviderChange={setProvider}
              onModelChange={setModel}
              onBaseUrlChange={setBaseUrl}
              onApiKeyChange={setApiKey}
              onConnect={connectLLM}
              onSample={useSampleProfile}
            />
          ) : null}

          {view === "home" ? (
            <DashboardView
              result={result}
              selectedMatches={selectedMatches}
              evidenceGraph={evidenceGraph}
              sourceRefresh={result?.source_refresh ?? null}
              loading={loading}
              hasModel={Boolean(realModel)}
              onSample={useSampleProfile}
              onBackground={() => runBackground()}
              onPrograms={() => runPrograms()}
              onTimeline={runTimeline}
              onRefresh={refreshSources}
            />
          ) : null}

          {view === "assessment" ? (
            <AssessmentView payload={payload} setPayload={setPayload} result={result} loading={loading} onRun={() => runBackground()} onRunPrograms={() => runPrograms(payload, true)} />
          ) : null}

          {view === "programs" ? (
            <ProgramsView
              payload={payload}
              catalog={visibleCatalog}
              result={result}
              focusList={focusList}
              applicationMix={applicationMix}
              filters={filters}
              setFilters={setFilters}
              selectedProgramIds={selectedProgramIds}
              onToggle={toggleProgram}
              onRun={() => runPrograms()}
              loading={loading}
            />
          ) : null}

          {view === "timeline" ? (
            <TimelineView selectedMatches={selectedMatches} timeline={result?.timeline ?? []} loading={loading} onRun={runTimeline} onRefresh={() => refreshSources(false)} />
          ) : null}

          {view === "writing" ? (
            <WritingView
              schema={questionnaireSchema}
              values={questionnaireValues}
              onChange={updateQuestionnaire}
              selectedProgramIds={selectedProgramIds}
              recommendations={recommendations}
              documentType={writingDocumentType}
              setDocumentType={setWritingDocumentType}
              targetProgramId={writingTargetProgramId}
              setTargetProgramId={setWritingTargetProgramId}
              questions={interviewQuestions}
              storyCards={result?.story_cards ?? []}
              writing={result?.writing}
              rubric={writingReview}
              loading={loading}
              onInterview={runInterview}
              onRun={runWriting}
            />
          ) : null}

          {view === "agent" ? (
            <DataCenterView evidenceGraph={evidenceGraph} sourceRegistry={sourceRegistry} sourceRefresh={result?.source_refresh ?? null} onRefresh={() => refreshSources(false)} onLiveRefresh={() => refreshSources(true)} loading={loading} />
          ) : null}

          {view === "settings" ? (
            <SettingsView
              provider={provider}
              model={model}
              baseUrl={baseUrl}
              apiKey={apiKey}
              message={llmMessage}
              loading={loading === "llm"}
              currentProvider={health?.llm_provider ?? "mock"}
              currentModel={health?.llm_mode ?? "mock"}
              onProviderChange={setProvider}
              onModelChange={setModel}
              onBaseUrlChange={setBaseUrl}
              onApiKeyChange={setApiKey}
              onConnect={connectLLM}
            />
          ) : null}
        </section>

        <ActivityDrawer open={activityOpen} onClose={() => setActivityOpen(false)} result={result} evidenceGraph={evidenceGraph} sourceRefresh={result?.source_refresh ?? null} />
      </main>
      <Footer type="sea" />
    </Cursor>
  );
}

function KeySetupCard(props: {
  provider: Provider;
  model: string;
  baseUrl: string;
  apiKey: string;
  message: string;
  loading: boolean;
  compact?: boolean;
  onProviderChange: (value: Provider) => void;
  onModelChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onConnect: () => void;
  onSample: () => void;
}) {
  return (
    <IslandCard className={`key-card ${props.compact ? "compact" : ""}`} color="app-yellow" pattern="default">
      <div className="key-card-copy">
        <span className="mini-label"><KeyRound size={16} aria-hidden />开始使用</span>
        <h2>{props.compact ? "连接你的 AI Key" : "先连接 AI Key，再让助手查项目、做评估、排时间线。"}</h2>
        <p>Key 只发送到本地后端用于本次运行。也可以先用示例档案体验流程；正式择校、官网信息确认和文书建议使用你自己的 Key。</p>
      </div>
      <div className="key-form">
        <label>
          AI 服务
          <select value={props.provider} onChange={(event) => props.onProviderChange(event.target.value as Provider)}>
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="compatible">OpenAI 兼容接口</option>
            <option value="mock">示例模式</option>
          </select>
        </label>
        <label>
          模型名称（可选）
          <input value={props.model} onChange={(event) => props.onModelChange(event.target.value)} placeholder="默认即可，例如 deepseek-chat" />
        </label>
        {props.provider === "compatible" ? (
          <label className="wide-field">
            接口地址（兼容服务时填写）
            <input value={props.baseUrl} onChange={(event) => props.onBaseUrlChange(event.target.value)} placeholder="https://api.example.com/v1" />
          </label>
        ) : null}
        <label className="wide-field">
          API Key（不会显示明文）
          <input value={props.apiKey} type="password" onChange={(event) => props.onApiKeyChange(event.target.value)} placeholder="sk-..." />
        </label>
        <div className="key-actions">
          <IslandButton type="primary" loading={props.loading} onClick={props.onConnect}>{props.loading ? "连接中" : "连接 AI 助手"}</IslandButton>
          <IslandButton type="default" onClick={props.onSample}>使用示例档案体验</IslandButton>
        </div>
        <p className="form-note">{props.message}</p>
      </div>
    </IslandCard>
  );
}

function GlobalProgress({ stage }: { stage: StageLoading }) {
  const detail = {
    background: {
      title: "正在生成背景诊断",
      steps: ["读取学生资料", "判断硬门槛", "识别资料缺口", "生成可解释结论"],
    },
    programs: {
      title: "正在生成择校方案",
      steps: ["读取背景", "召回港新项目库", "按院校层级/GPA/语言/经历分档", "输出冲刺/主申/保底名单"],
    },
    timeline: {
      title: "正在生成时间线",
      steps: ["读取已选项目", "检查学校官网信息", "合并通用材料", "生成日程表"],
    },
    writing: {
      title: "正在生成文书草稿",
      steps: ["整理经历表", "生成故事卡", "绑定目标项目", "输出中文逻辑稿和英文申请稿"],
    },
    interview: {
      title: "正在生成追问",
      steps: ["读取目标专业", "发现素材缺口", "生成专业化追问"],
    },
    data: {
      title: "正在检查学校官网信息",
      steps: ["匹配学校官网入口", "查找项目详情页", "区分官网和经验来源", "输出可确认的信息清单"],
    },
    llm: {
      title: "正在连接模型",
      steps: ["提交到本地后端", "验证模型配置", "准备 Agent 调用"],
    },
  }[stage ?? "background"];
  if (!stage) return null;
  return (
    <IslandCard className="progress-card" color="app-teal">
      <div className="progress-head">
        <strong>{detail.title}</strong>
        <span>请稍等，完成后页面会自动更新。</span>
      </div>
      <div className="progress-track"><span /></div>
      <div className="progress-steps">
        {detail.steps.map((step) => <span key={step}>{step}</span>)}
      </div>
    </IslandCard>
  );
}

function DashboardView(props: {
  result: AppState | null;
  selectedMatches: ProgramMatch[];
  evidenceGraph: EvidenceGraphSummary | null;
  sourceRefresh: DataRefreshReport | null;
  loading: StageLoading;
  hasModel: boolean;
  onSample: () => void;
  onBackground: () => void;
  onPrograms: () => void;
  onTimeline: () => void;
  onRefresh: () => void;
}) {
  const assessmentReady = Boolean(props.result?.assessment);
  const planReady = Boolean(props.result?.focus_list?.length || props.result?.recommendations?.length);
  const timelineReady = Boolean(props.result?.timeline?.length);
  return (
    <div className="page-stack">
      <IslandCard className="hero-card" color="app-teal" pattern="app-yellow">
        <div>
          <span className="mini-label"><Sparkles size={16} aria-hidden />申请流程从这里开始</span>
          <h2>先评估背景，再生成择校方案，最后排时间线和做文书。</h2>
          <p>这个平台的目标不是展示技术概念，而是像留学顾问一样把学生资料、项目数据库、学校官网信息和文书素材串起来，给出一份能解释、能追踪的申请执行方案。</p>
        </div>
        <div className="hero-actions">
          <IslandButton type="primary" loading={props.loading === "background"} onClick={props.onBackground}>开始背景评估</IslandButton>
          <IslandButton type="default" loading={props.loading === "programs"} onClick={props.onPrograms}>生成顾问式择校方案</IslandButton>
          <IslandButton type="dashed" loading={props.loading === "data"} onClick={props.onRefresh}>刷新学校官网信息</IslandButton>
        </div>
      </IslandCard>

      <section className="status-grid">
        <Metric label="表单填写" value={`${props.result?.profile?.profile_completeness ?? 0}%`} detail="只代表已填写，不代表可信" />
        <Metric label="决策信息覆盖" value={`${props.result?.assessment?.decision_field_coverage ?? 0}%`} detail="决定能否正式择校" />
        <Metric label="证据覆盖" value={`${props.result?.assessment?.evidence_coverage ?? Math.round((props.result?.evidence?.verified_fact_ratio ?? 0) * 100)}%`} detail="官网或材料证明比例" />
        <Metric label="来源记录" value={`${props.evidenceGraph?.field_record_count ?? 0}`} detail={`${props.evidenceGraph?.verified_field_count ?? 0} 条已确认`} />
      </section>

      <IslandCard className="panel-card">
        <PanelTitle icon={<ClipboardList size={19} aria-hidden />} title="今天应该做什么" />
        <div className="next-step-list">
          <StepItem done={props.hasModel} title="连接模型 Key" detail="让 Agent 能调用你的模型做信息抽取、追问和文书生成。" href="/settings" />
          <StepItem done={assessmentReady} title="补充背景资料" detail="先判断硬门槛和材料缺口，不急着给 A-/B+ 这种假确定结论。" href="/assessment" />
          <StepItem done={planReady} title="生成候选池和重点项目" detail="默认重点项目控制在 12-15 个，未确认项目只进入候选池。" href="/programs" />
          <StepItem done={timelineReady} title="生成准备建议" detail="只有学校确认截止日期后才生成正式提交倒排时间线。" href="/timeline" />
        </div>
      </IslandCard>

      <section className="two-column">
        <IslandCard className="panel-card">
          <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="申请方案" />
          <ProgramMiniList matches={props.selectedMatches} />
          <div className="card-actions">
            <IslandButton type="primary" loading={props.loading === "timeline"} onClick={props.onTimeline}>生成时间线与材料</IslandButton>
            <Link className="text-link" href="/programs">去调整项目</Link>
          </div>
        </IslandCard>
        <IslandCard className="panel-card" type="dashed">
          <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="信息可信度说明" />
          <SourceRefreshSummary report={props.sourceRefresh} evidenceGraph={props.evidenceGraph} />
        </IslandCard>
      </section>
    </div>
  );
}

function AssessmentView({
  payload,
  setPayload,
  result,
  loading,
  onRun,
  onRunPrograms,
}: {
  payload: ApplicantPayload;
  setPayload: (payload: ApplicantPayload) => void;
  result: AppState | null;
  loading: StageLoading;
  onRun: () => void;
  onRunPrograms: () => void;
}) {
  function patchEducation(patch: Partial<ApplicantPayload["education"]>) {
    setPayload({ ...payload, education: { ...payload.education, ...patch } });
  }
  function patchLanguage(patch: Partial<ApplicantPayload["language"]>) {
    setPayload({ ...payload, language: { ...payload.language, ...patch } });
  }
  function patchExperience(index: number, patch: Partial<ApplicantPayload["experiences"][number]>) {
    const next = payload.experiences.length ? [...payload.experiences] : [emptyExperience()];
    next[index] = { ...next[index], ...patch };
    setPayload({ ...payload, experiences: next });
  }
  function addExperience() {
    setPayload({ ...payload, experiences: [...payload.experiences, emptyExperience()] });
  }
  function updateInterest(code: string) {
    const exists = payload.discipline_interests.includes(code);
    setPayload({ ...payload, discipline_interests: exists ? payload.discipline_interests.filter((item) => item !== code) : [...payload.discipline_interests, code] });
  }
  const assessment = result?.assessment;
  return (
    <div className="two-column">
      <IslandCard className="panel-card sticky-panel">
        <PanelTitle icon={<GraduationCap size={19} aria-hidden />} title="学生背景资料" />
        <div className="form-grid">
          <label>学校层级<select value={payload.education.school_tier} onChange={(event) => patchEducation({ school_tier: event.target.value as ApplicantPayload["education"]["school_tier"] })}>{schoolTiers.map((item) => <option value={item.code} key={item.code}>{item.label}</option>)}</select></label>
          <label>本科学校<input value={payload.education.school} onChange={(event) => patchEducation({ school: event.target.value })} /></label>
          <label>本科专业<input value={payload.education.major} onChange={(event) => patchEducation({ major: event.target.value })} /></label>
          <label>GPA / 均分<input type="number" value={payload.education.gpa} onChange={(event) => patchEducation({ gpa: Number(event.target.value) })} /></label>
          <label>语言考试<select value={payload.language.test} onChange={(event) => patchLanguage({ test: event.target.value as ApplicantPayload["language"]["test"] })}><option value="IELTS">IELTS</option><option value="TOEFL">TOEFL</option><option value="PTE">PTE</option><option value="NONE">暂未考试</option></select></label>
          <label>总分<input type="number" value={payload.language.overall ?? ""} onChange={(event) => patchLanguage({ overall: event.target.value ? Number(event.target.value) : null })} /></label>
          <label>写作单项<input type="number" value={payload.language.writing ?? ""} onChange={(event) => patchLanguage({ writing: event.target.value ? Number(event.target.value) : null })} /></label>
          <label>预算 HKD<input type="number" value={payload.budget_hkd ?? ""} onChange={(event) => setPayload({ ...payload, budget_hkd: event.target.value ? Number(event.target.value) : null })} /></label>
          <label className="wide-field">职业目标<textarea rows={3} value={payload.career_goal} onChange={(event) => setPayload({ ...payload, career_goal: event.target.value })} /></label>
        </div>
        <ProfileEvidenceEditor payload={payload} setRawInterest={(raw_interest_text) => setPayload({ ...payload, raw_interest_text })} patchEducation={patchEducation} patchLanguage={patchLanguage} patchExperience={patchExperience} addExperience={addExperience} />
        <div className="chip-group">
          {disciplineOptions.map((item) => <button className={payload.discipline_interests.includes(item.code) ? "chip selected" : "chip"} type="button" key={item.code} onClick={() => updateInterest(item.code)}>{item.label}</button>)}
        </div>
        <div className="card-actions">
          <IslandButton type="primary" loading={loading === "background"} onClick={onRun}>{loading === "background" ? "分析中" : "生成背景诊断"}</IslandButton>
          <IslandButton type="default" loading={loading === "programs"} onClick={onRunPrograms}>带着背景去择校</IslandButton>
        </div>
      </IslandCard>

      <div className="page-stack">
        <IslandCard className="panel-card">
          <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="诊断报告，不做过度承诺" />
          <section className="status-grid three">
            <Metric label="资格状态" value={assessment?.qualification_status ?? "待评估"} detail={assessment?.scope_note ?? "缺少成绩单和课程细节前，只能做初步方向探索"} />
            <Metric label="决策信息覆盖" value={`${assessment?.decision_field_coverage ?? 0}%`} detail="影响项目级资格判断" />
            <Metric label="证据覆盖" value={`${assessment?.evidence_coverage ?? 0}%`} detail="正式材料或官网依据比例" />
          </section>
        </IslandCard>
        <IslandCard className="panel-card" type="dashed">
          <PanelTitle icon={<ListChecks size={19} aria-hidden />} title="维度结论" />
          <DimensionFindings items={assessment?.dimension_findings ?? []} />
        </IslandCard>
        <IslandCard className="panel-card">
          <PanelTitle icon={<AlertTriangle size={19} aria-hidden />} title="还缺什么" />
          <AdviceList title="资料缺口" items={result?.profile?.missing_fields ?? ["正式成绩单", "核心课程成绩", "排名或成绩趋势", "经历量化结果"]} />
          <AdviceList title="建议动作" items={assessment?.actions ?? []} />
        </IslandCard>
      </div>
    </div>
  );
}

function ProgramsView(props: {
  payload: ApplicantPayload;
  catalog: CatalogProgram[];
  result: AppState | null;
  focusList: ProgramMatch[];
  applicationMix: ProgramMatch[];
  filters: { q: string; region: string; discipline: string; verification_status: string; deadline_status: string };
  setFilters: (filters: { q: string; region: string; discipline: string; verification_status: string; deadline_status: string }) => void;
  selectedProgramIds: string[];
  onToggle: (id: string) => void;
  onRun: () => void;
  loading: StageLoading;
}) {
  const core = props.result?.core_candidates ?? props.focusList.filter((item) => item.match_category === "core");
  const related = props.result?.related_candidates ?? props.focusList.filter((item) => item.match_category !== "core");
  const blocked = props.result?.blocked_candidates ?? [];
  const tabs = [
    { key: "core", label: `核心匹配 ${core.length}`, children: <ProgramRows matches={core.slice(0, 15)} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} /> },
    { key: "related", label: `相关候选 ${related.length}`, children: <ProgramRows matches={related.slice(0, 30)} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} /> },
    { key: "mix", label: `建议组合 ${props.applicationMix.length}`, children: <ProgramRows matches={props.applicationMix} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} /> },
    { key: "blocked", label: `暂不推荐 ${blocked.length}`, children: <ProgramRows matches={blocked.slice(0, 20)} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} muted /> },
  ];
  return (
    <div className="page-stack">
      <IslandCard className="panel-card program-command" color="app-yellow">
        <div>
          <span className="mini-label"><Search size={16} aria-hidden />先缩小范围，再解释原因</span>
          <h2>生成一份能给学生看的择校方案。</h2>
          <p>AI 会结合院校层级、GPA、语言、专业方向、经历、预算和学校官网信息，输出冲刺、主申、保底和候选项目。未确认的信息会明确标为草案，不伪装成最终结论。</p>
        </div>
        <IslandButton type="primary" loading={props.loading === "programs"} onClick={props.onRun}>{props.loading === "programs" ? "方案生成中" : "重新生成择校方案"}</IslandButton>
      </IslandCard>

      <ProgramPlanOverview plan={props.result?.consultant_plan ?? null} matches={props.applicationMix.length ? props.applicationMix : props.focusList.slice(0, 10)} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} />

      <IslandCard className="panel-card">
        <PanelTitle icon={<ClipboardList size={19} aria-hidden />} title="当前意向" />
        <div className="intent-grid">
          <div><span>目标方向</span><strong>{props.payload.discipline_interests.map(intentLabel).join("、") || "待选择"}</strong></div>
          <div><span>学校层级</span><strong>{props.payload.education.school_tier}</strong></div>
          <div><span>预算</span><strong>{formatMoney(props.payload.budget_hkd)}</strong></div>
          <div><span>AI 理解</span><strong>{props.result?.intent_profile?.explanation ?? "运行择校后显示用户意向解析"}</strong></div>
        </div>
      </IslandCard>

      <IslandCard className="panel-card" type="dashed">
        <PanelTitle icon={<Search size={19} aria-hidden />} title="全量项目库筛选" />
        <div className="filters-grid">
          <label className="search-field">学校 / 学院 / 项目名<input value={props.filters.q} onChange={(event) => props.setFilters({ ...props.filters, q: event.target.value })} placeholder="如 HKU CS / NUS Analytics" /></label>
          <label>地区<select value={props.filters.region} onChange={(event) => props.setFilters({ ...props.filters, region: event.target.value })}><option value="">港新全部</option><option value="HK">香港</option><option value="SG">新加坡</option></select></label>
          <label>方向<select value={props.filters.discipline} onChange={(event) => props.setFilters({ ...props.filters, discipline: event.target.value })}><option value="">全部方向</option>{disciplineOptions.map((item) => <option value={item.code} key={item.code}>{item.label}</option>)}</select></label>
          <label>信息状态<select value={props.filters.verification_status} onChange={(event) => props.setFilters({ ...props.filters, verification_status: event.target.value })}><option value="">全部状态</option><option value="OFFICIAL_VERIFIED_CURRENT">学校已确认</option><option value="EXTRACTED">待学校确认</option><option value="NOT_PUBLISHED">本季未发布</option><option value="COMMUNITY_ONLY">仅经验参考</option></select></label>
          <label>截止状态<select value={props.filters.deadline_status} onChange={(event) => props.setFilters({ ...props.filters, deadline_status: event.target.value })}><option value="">全部</option><option value="published">已有日期</option><option value="not_published">未发布 / 待确认</option></select></label>
        </div>
        <CatalogRows programs={props.catalog.slice(0, 50)} selectedIds={props.selectedProgramIds} onToggle={props.onToggle} />
      </IslandCard>

      <IslandTabs className="animal-tabs" items={tabs} defaultActiveKey="core" />
    </div>
  );
}

function TimelineView({ selectedMatches, timeline, loading, onRun, onRefresh }: { selectedMatches: ProgramMatch[]; timeline: TimelineTask[]; loading: StageLoading; onRun: () => void; onRefresh: () => void }) {
  const commonTasks = timeline.filter((task) => (task.linked_program_ids?.length ?? 0) > 1 || task.task_type === "materials" || task.task_type === "language");
  const sourceTasks = timeline.filter((task) => task.task_type === "source_review");
  const projectTasks = timeline.filter((task) => !commonTasks.includes(task) && !sourceTasks.includes(task));
  const weekTasks = timeline.slice(0, 8);
  return (
    <div className="page-stack">
      <IslandCard className="panel-card" color="app-teal">
        <div className="split-head">
          <div>
            <span className="mini-label"><CalendarDays size={16} aria-hidden />时间线必须先讲清楚依据</span>
            <h2>学校还没确认本季截止日期时，先给你准备清单。</h2>
            <p>正式截止、奖学金优先轮次、推荐信系统截止和网申入口都要以学校官网为准。当前页面会把“学校要求”和“内部准备建议”分开。</p>
          </div>
          <div className="card-actions">
            <IslandButton type="default" loading={loading === "data"} onClick={onRefresh}>刷新学校官网信息</IslandButton>
            <IslandButton type="primary" loading={loading === "timeline"} onClick={onRun}>生成任务</IslandButton>
          </div>
        </div>
      </IslandCard>
      <IslandCard className="panel-card">
        <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="已选项目" />
        <ProgramMiniList matches={selectedMatches} />
      </IslandCard>
      <IslandTabs
        className="animal-tabs"
        defaultActiveKey="week"
        items={[
          { key: "week", label: `本周优先 ${weekTasks.length}`, children: <TaskList tasks={weekTasks} /> },
          { key: "common", label: `通用材料 ${commonTasks.length}`, children: <TaskList tasks={commonTasks} /> },
          { key: "project", label: `按项目 ${projectTasks.length}`, children: <TaskList tasks={projectTasks} /> },
          { key: "sources", label: `官网确认 ${sourceTasks.length}`, children: <TaskList tasks={sourceTasks} /> },
        ]}
      />
    </div>
  );
}

function WritingView({
  schema,
  values,
  onChange,
  recommendations,
  documentType,
  setDocumentType,
  targetProgramId,
  setTargetProgramId,
  questions,
  storyCards,
  writing,
  rubric,
  loading,
  onInterview,
  onRun,
}: {
  schema: QuestionnaireSchema | null;
  values: QuestionnaireValues;
  onChange: (fieldId: string, value: string) => void;
  selectedProgramIds: string[];
  recommendations: ProgramMatch[];
  documentType: DocumentType;
  setDocumentType: (value: DocumentType) => void;
  targetProgramId: string;
  setTargetProgramId: (value: string) => void;
  questions: WritingInterviewQuestion[];
  storyCards: StoryCard[];
  writing?: WorkflowResult["writing"];
  rubric: WritingReviewRubric | null;
  loading: StageLoading;
  onInterview: () => void;
  onRun: () => void;
}) {
  const currentDoc = documentTypeOptions.find((item) => item.value === documentType);
  return (
    <div className="two-column writing-layout">
      <IslandCard className="panel-card sticky-panel">
        <PanelTitle icon={<FileText size={19} aria-hidden />} title="访谈式文书素材" />
        <p className="form-note">文书阶段只收集课程、经历、动机、项目题目和事实依据。联系方式、护照、家庭住址不会进入模型上下文。</p>
        <div className="form-grid">
          <label>文书类型<select value={documentType} onChange={(event) => setDocumentType(event.target.value as DocumentType)}>{documentTypeOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
          <label>目标项目<select value={targetProgramId} onChange={(event) => setTargetProgramId(event.target.value)}><option value="">使用已选第一个项目</option>{recommendations.slice(0, 40).map((item) => <option value={item.program.id} key={item.program.id}>{displayProgram(item.program)}</option>)}</select></label>
        </div>
        <div className="hint-box">{currentDoc?.detail}</div>
        {schema ? <QuestionnaireForm schema={schema} values={values} onChange={onChange} /> : <EmptyState text="正在读取文书问卷结构" />}
        <div className="card-actions sticky-actions">
          <IslandButton type="default" loading={loading === "interview"} onClick={onInterview}>生成追问</IslandButton>
          <IslandButton type="primary" loading={loading === "writing"} onClick={onRun}>生成大纲与草稿</IslandButton>
        </div>
      </IslandCard>

      <div className="page-stack">
        <IslandCard className="panel-card">
          <PanelTitle icon={<Sparkles size={19} aria-hidden />} title="Agent 追问" />
          <InterviewQuestions questions={questions} />
        </IslandCard>
        <IslandCard className="panel-card" type="dashed">
          <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="故事卡与事实绑定" />
          <StoryCardList cards={storyCards} />
          {!storyCards.length ? <EmptyState text="填写经历后，系统会先生成故事卡，再生成草稿。" /> : null}
        </IslandCard>
        {writing ? (
          <IslandCard className="panel-card">
            <PanelTitle icon={<FileText size={19} aria-hidden />} title="文书草稿" />
            <OutlineList items={writing.outline} />
            {writing.draft_zh ? <DraftPanel title="中文逻辑稿" body={writing.draft_zh} /> : null}
            {writing.draft_en ? <DraftPanel title="英文申请稿" body={writing.draft_en} /> : null}
            <RubricPanel rubric={rubric} />
          </IslandCard>
        ) : null}
      </div>
    </div>
  );
}

function DataCenterView({ evidenceGraph, sourceRegistry, sourceRefresh, onRefresh, onLiveRefresh, loading }: { evidenceGraph: EvidenceGraphSummary | null; sourceRegistry: SourceRegistry | null; sourceRefresh: DataRefreshReport | null; onRefresh: () => void; onLiveRefresh: () => void; loading: StageLoading }) {
  return (
    <div className="page-stack">
      <IslandCard className="panel-card" color="app-yellow">
        <div className="split-head">
          <div>
            <span className="mini-label"><Database size={16} aria-hidden />数据治理，不把社区信息当官网</span>
            <h2>当前数据库的问题要直接告诉用户。</h2>
            <p>已有项目可以做发现和初筛，但很多信息仍来自目录页或上一申请季参考。截止日期、学费、语言、材料、申请入口必须逐项绑定学校官网来源。</p>
          </div>
          <div className="card-actions">
            <IslandButton type="default" loading={loading === "data"} onClick={onRefresh}>检查学校来源</IslandButton>
            <IslandButton type="primary" loading={loading === "data"} onClick={onLiveRefresh}>{loading === "data" ? "抓取中" : "联网抓取官网快照"}</IslandButton>
          </div>
        </div>
      </IslandCard>
      <section className="status-grid">
        <Metric label="项目总数" value={`${evidenceGraph?.program_count ?? 0}`} detail="港新授课硕士 MVP 库" />
        <Metric label="信息记录" value={`${evidenceGraph?.field_record_count ?? 0}`} detail="逐项绑定来源" />
        <Metric label="本季已确认" value={`${evidenceGraph?.verified_field_count ?? 0}`} detail="正式推荐依赖此指标" />
        <Metric label="待确认信息" value={`${evidenceGraph?.pending_review_field_count ?? 0}`} detail="需要查看学校原文" />
      </section>
      <section className="two-column">
        <IslandCard className="panel-card">
          <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="来源优先级" />
          <SourcePriorityList />
        </IslandCard>
        <IslandCard className="panel-card" type="dashed">
          <PanelTitle icon={<RefreshCcw size={19} aria-hidden />} title="数据刷新工作流" />
          <WorkflowStageList />
        </IslandCard>
      </section>
      <IslandTabs
        className="animal-tabs"
        defaultActiveKey="records"
        items={[
          { key: "records", label: "来源证据", children: <EvidenceRecordList records={evidenceGraph?.sample_records ?? []} /> },
          { key: "sources", label: "来源注册表", children: <SourceRegistryList registry={sourceRegistry} /> },
          { key: "refresh", label: "本次检查", children: <SourceRefreshSummary report={sourceRefresh} evidenceGraph={evidenceGraph} /> },
          { key: "extract", label: "抽取结果", children: <ExtractionResultList report={sourceRefresh} /> },
        ]}
      />
    </div>
  );
}

function SettingsView(props: {
  provider: Provider;
  model: string;
  baseUrl: string;
  apiKey: string;
  message: string;
  loading: boolean;
  currentProvider: string;
  currentModel: string;
  onProviderChange: (value: Provider) => void;
  onModelChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onConnect: () => void;
}) {
  return (
    <div className="page-stack">
      <IslandCard className="panel-card" color="app-teal">
        <PanelTitle icon={<Settings size={19} aria-hidden />} title="模型设置" />
        <p className="form-note">这是实验功能 / 管理员设置。普通申请流程只展示“AI 分析中、已完成、待确认”等业务状态，不在核心页面暴露模型名和 Token。</p>
      </IslandCard>
      <KeySetupCard {...props} onSample={() => undefined} />
      <IslandCard className="panel-card">
        <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="当前连接" />
        <section className="status-grid two">
          <Metric label="Provider" value={props.currentProvider} detail="后端当前模型供应商" />
          <Metric label="Model" value={props.currentModel} detail="后端当前模型或 mock 模式" />
        </section>
      </IslandCard>
    </div>
  );
}

function ProgramPlanOverview({ plan, matches, selectedIds, onToggle }: { plan: ConsultantSchoolPlan | null; matches: ProgramMatch[]; selectedIds: string[]; onToggle: (id: string) => void }) {
  if (!matches.length) {
    return (
      <IslandCard className="panel-card" type="dashed">
        <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="择校方案概览" />
        <EmptyState text="还没有方案。请先点击“重新生成择校方案”。" />
      </IslandCard>
    );
  }
  const counts = matches.reduce<Record<string, number>>((acc, item) => {
    const key = item.strategy_band ?? "candidate";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const rows = plan?.items?.length ? plan.items : null;
  return (
    <IslandCard className="panel-card">
      <PanelTitle icon={<BookOpenCheck size={19} aria-hidden />} title="择校方案概览" />
      {plan ? (
        <div className="consultant-plan-brief">
          <div>
            <span className="mini-label">{plan.title}</span>
            <h3>{plan.profile_summary}</h3>
            <p>{plan.strategy_summary}</p>
          </div>
          <AdviceList title="下一步" items={plan.next_actions} />
        </div>
      ) : null}
      <div className="plan-summary">
        <div><strong>{matches.length}</strong><span>建议组合项目</span></div>
        <div><strong>{plan?.band_counts?.["冲刺"] ?? counts.reach ?? 0}</strong><span>冲刺</span></div>
        <div><strong>{plan?.band_counts?.["主申"] ?? counts.target ?? 0}</strong><span>主申</span></div>
        <div><strong>{plan?.band_counts?.["保底"] ?? counts.safe ?? 0}</strong><span>保底</span></div>
        <div><strong>{plan?.band_counts?.["候选"] ?? counts.candidate ?? 0}</strong><span>候选</span></div>
      </div>
      <div className="plan-table-wrap">
        <table className="plan-table">
          <thead>
            <tr>
              <th>分档</th>
              <th>学校 / 项目</th>
              <th>适配解释</th>
              <th>主要风险</th>
              <th>数据状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? matches.slice(0, 12)).map((row) => {
              const item = "program_id" in row ? matches.find((match) => match.program.id === row.program_id) : row;
              if (!item) return null;
              const planRow = "program_id" in row ? row : null;
              return (
              <tr key={item.program.id}>
                <td><span className={`band-pill ${item.strategy_band ?? "candidate"}`}>{planRow?.band ?? strategyLabel(item.strategy_band)}</span></td>
                <td>
                  <strong>{displayProgram(item.program)}</strong>
                  <small>{displayProgramSecondary(item.program)}</small>
                  <small>{programMeta(item.program)}</small>
                </td>
                <td>
                  <p>{planRow?.why_this_band ?? item.consultant_note ?? item.reasons[0]}</p>
                  <small>{planRow?.student_fit ?? ""}</small>
                </td>
                <td>
                  <p>{planRow?.main_risk ?? item.risks[0] ?? "等待学校确认。"}</p>
                  <small>{planRow?.next_action ?? item.actions[0] ?? "打开学校官网确认。"}</small>
                </td>
                <td><DataBadge status={item.program.data_status} /><small>{planRow?.data_warning ?? item.source_warning}</small></td>
                <td>
                  <IslandButton type={selectedIds.includes(item.program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(item.program.id)}>
                    {selectedIds.includes(item.program.id) ? "已选" : "选择"}
                  </IslandButton>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="form-note">{plan?.data_disclaimer ?? "这是一份择校草案：分档可以用于决策讨论；截止日期、学费、语言、材料和申请入口必须以学校官网为准。"}</p>
      {plan?.rejected_or_deferred?.length ? <AdviceList title="暂不建议放入本轮方案" items={plan.rejected_or_deferred} /> : null}
    </IslandCard>
  );
}

function ProgramRows({ matches, selectedIds, onToggle, muted = false }: { matches: ProgramMatch[]; selectedIds: string[]; onToggle: (id: string) => void; muted?: boolean }) {
  if (!matches.length) return <EmptyState text="暂无匹配结果。请先补充背景并重新推荐。" />;
  return (
    <div className="program-list">
      {matches.map((item) => (
        <article className={`program-row ${muted ? "muted" : ""}`} key={item.program.id}>
          <div className="program-main">
            <div className="program-title-row">
              <DataBadge status={item.program.data_status} />
              <span className={`band-pill ${item.strategy_band ?? "candidate"}`}>{strategyLabel(item.strategy_band)} · {tierLabel(item)}</span>
            </div>
            <h3>{displayProgram(item.program)}</h3>
            <p>{displayProgramSecondary(item.program)} · {programMeta(item.program)}</p>
            {item.consultant_note ? <p className="consultant-note">{item.consultant_note}</p> : null}
            <div className="program-signals">
              <Signal label="硬条件" value={item.explanation?.hard_condition ?? (item.hard_rule_passed ? "通过" : "待确认")} />
              <Signal label="学术匹配" value={item.explanation?.academic_match ?? band(item.score_breakdown.academic)} />
              <Signal label="课程匹配" value={item.explanation?.course_match ?? band(item.score_breakdown.discipline_fit)} />
              <Signal label="经历匹配" value={item.explanation?.experience_match ?? band(item.score_breakdown.experience)} />
              <Signal label="预算匹配" value={item.explanation?.budget_match ?? band(item.score_breakdown.budget_fit)} />
              <Signal label="截止状态" value={formatDeadline(item.program.deadline)} />
            </div>
          </div>
          <div className="program-evidence">
            <AdviceList title="推荐依据" items={(item.explanation?.decision_basis ?? item.reasons).slice(0, 3)} />
            <AdviceList title="主要风险" items={[item.source_warning, ...(item.explanation?.uncertainties ?? item.risks)].filter((value): value is string => Boolean(value)).slice(0, 4)} />
          </div>
          <div className="program-actions">
            <IslandButton type={selectedIds.includes(item.program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(item.program.id)}>
              {selectedIds.includes(item.program.id) ? "已加入方案" : "加入方案"}
            </IslandButton>
            <ProgramLinks program={item.program} />
          </div>
        </article>
      ))}
    </div>
  );
}

function CatalogRows({ programs, selectedIds, onToggle }: { programs: CatalogProgram[]; selectedIds: string[]; onToggle: (id: string) => void }) {
  if (!programs.length) return <EmptyState text="没有找到项目。请放宽筛选条件。" />;
  return (
    <div className="catalog-list">
      {programs.map((program) => (
        <article className="catalog-row" key={program.id}>
          <div>
            <DataBadge status={program.data_status} />
            <h3>{displayProgram(program)}</h3>
            <p>{displayProgramSecondary(program)} · {programMeta(program)} · {program.category_zh || program.discipline_tags.join(" / ")}</p>
          </div>
          <div className="catalog-evidence-cell">
            <div className="program-signals compact-signals">
              <Signal label="学费" value={formatMoney(program.tuition_hkd)} />
              <Signal label="学制" value={`${program.duration_months} 个月`} />
              <Signal label="截止" value={formatDeadline(program.deadline)} />
            </div>
            <ProgramTrustPanel trust={program.trust_detail} />
          </div>
          <div className="program-actions">
            <IslandButton type={selectedIds.includes(program.id) ? "default" : "primary"} size="small" onClick={() => onToggle(program.id)}>{selectedIds.includes(program.id) ? "已加入" : "加入方案"}</IslandButton>
            <ProgramLinks program={program} />
          </div>
        </article>
      ))}
    </div>
  );
}

function ProgramTrustPanel({ trust }: { trust?: CatalogProgram["trust_detail"] }) {
  if (!trust) return <p className="form-note">字段级来源待加载。</p>;
  const records = trust.field_records.filter((record) => ["deadline", "tuition_hkd", "language_requirement", "materials", "application_url"].includes(record.field_name));
  return (
    <div className="trust-panel">
      <div className="trust-panel-head">
        <DataBadge status={trust.production_ready ? "OFFICIAL_VERIFIED_CURRENT" : "PENDING_REVIEW"} />
        <span>{trust.status_label}</span>
      </div>
      <p>{trust.source_warning}</p>
      <div className="trust-field-list">
        {records.slice(0, 4).map((record) => (
          <div key={`${record.field_name}-${record.page_hash ?? "pending"}`}>
            <span>{fieldLabels[record.field_name] ?? record.field_name}</span>
            <DataBadge status={record.status} />
            <small>{record.verified_at ? `确认 ${formatDateTime(record.verified_at)}` : `抓取 ${formatDateTime(record.extracted_at)}`}</small>
            {record.source_url ? <a href={record.source_url} target="_blank" rel="noreferrer">来源</a> : null}
          </div>
        ))}
      </div>
    </div>
  );
}


function ProgramLinks({ program }: { program: ProgramMatch["program"] }) {
  return (
    <div className="link-row">
      {program.official_program_url ? <a href={program.official_program_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />官网</a> : null}
      {program.application_url ? <a href={program.application_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />申请入口</a> : null}
    </div>
  );
}

function TaskList({ tasks }: { tasks: TimelineTask[] }) {
  if (!tasks.length) return <EmptyState text="暂无任务。选择项目并生成时间线后显示。" />;
  return (
    <div className="task-list">
      {tasks.map((task) => (
        <article className="task-row" key={task.id}>
          <div className="task-date">
            <CalendarDays size={17} aria-hidden />
            <strong>{String(task.suggested_due_date ?? task.due_date)}</strong>
            <span>{dateBasisLabel(task.date_basis)}</span>
          </div>
          <div>
            <div className="program-title-row">
              <span className={`priority ${String(task.risk_level ?? task.priority).toLowerCase()}`}>风险：{riskLabel(task.risk_level ?? task.priority)}</span>
              <span className="tier-pill">{taskTypeLabels[task.task_type] ?? task.task_type}</span>
            </div>
            <h3>{task.task_name ?? task.title}</h3>
            <p>{task.basis || "准备建议，等待学校官网确认。"}</p>
            <div className="task-meta">
              <span>官方截止：{task.official_deadline === "NOT_PUBLISHED" || !task.official_deadline ? "尚未确认 / 未发布" : String(task.official_deadline)}</span>
              {task.previous_cycle_reference ? <span>上一季参考：{String(task.previous_cycle_reference)}</span> : null}
              <span>状态：{task.status ?? "待办"}</span>
            </div>
            {task.upload_materials?.length ? <div className="material-chips">{task.upload_materials.map((item) => <span key={item}>{materialLabels[item] ?? item}</span>)}</div> : null}
            {task.source_url ? <a className="text-link" href={task.source_url} target="_blank" rel="noreferrer">查看来源</a> : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function QuestionnaireForm({ schema, values, onChange }: { schema: QuestionnaireSchema; values: QuestionnaireValues; onChange: (fieldId: string, value: string) => void }) {
  return (
    <div className="questionnaire">
      {schema.sections.map((section) => (
        <section className="questionnaire-section" key={section.id}>
          <div className="section-heading">
            <h3>{section.title}</h3>
            {section.repeatable ? <span>可扩展</span> : null}
          </div>
          <p>{section.description}</p>
          <div className="form-grid">
            {section.fields.filter((field) => !field.sensitive).map((field) => <QuestionField field={field} value={values[field.id] ?? ""} onChange={(value) => onChange(field.id, value)} key={field.id} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function QuestionField({ field, value, onChange }: { field: QuestionnaireSchema["sections"][number]["fields"][number]; value: string; onChange: (value: string) => void }) {
  const label = `${field.label}${field.required ? " *" : ""}`;
  if (field.type === "textarea") return <label className="wide-field">{label}<textarea value={value} rows={4} onChange={(event) => onChange(event.target.value)} /></label>;
  if (field.type === "select") {
    return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">请选择</option>{(field.options ?? []).map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
  }
  return <label>{label}<input type={field.type === "date" ? "date" : "text"} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function DimensionFindings({ items }: { items: DimensionFinding[] }) {
  if (!items.length) return <EmptyState text="等待评估。运行后每条结论都会显示依据、不确定项和建议动作。" />;
  return (
    <div className="finding-list">
      {items.map((item) => (
        <article key={item.dimension}>
          <div className="program-title-row"><strong>{item.dimension}</strong><span className="tier-pill">{item.level}</span></div>
          <p>{item.conclusion}</p>
          <div className="fact-grid">
            <Rule text={`依据：${item.basis}`} />
            <Rule text={`适用方向：${item.applicable_to.join("、") || "待确认"}`} />
            <Rule text={`不确定项：${item.uncertainties.join("；") || "暂无"}`} />
            <Rule text={`建议动作：${item.actions.join("；") || "暂无"}`} />
          </div>
        </article>
      ))}
    </div>
  );
}

function InterviewQuestions({ questions }: { questions: WritingInterviewQuestion[] }) {
  if (!questions.length) return <EmptyState text="点击“生成追问”，AI 会根据目标项目和素材缺口追问技术深度、数据规模和 Why Program。" />;
  return (
    <div className="finding-list">
      {questions.map((item) => (
        <article key={item.id}>
          <div className="program-title-row"><strong>{item.question}</strong><span className="tier-pill">{item.target_section}</span></div>
          <p>{item.why_it_matters}</p>
        </article>
      ))}
    </div>
  );
}

function StoryCardList({ cards }: { cards: StoryCard[] }) {
  if (!cards.length) return null;
  return (
    <div className="story-card-list">
      {cards.map((card) => (
        <article className="story-card" key={card.id}>
          <div className="program-title-row"><strong>{card.title}</strong><span className="tier-pill">{card.completeness}%</span></div>
          <p>{card.action || card.situation || "等待补充具体行动与结果。"}</p>
        </article>
      ))}
    </div>
  );
}

function ProfileEvidenceEditor({
  payload,
  setRawInterest,
  patchEducation,
  patchLanguage,
  patchExperience,
  addExperience,
}: {
  payload: ApplicantPayload;
  setRawInterest: (value: string) => void;
  patchEducation: (patch: Partial<ApplicantPayload["education"]>) => void;
  patchLanguage: (patch: Partial<ApplicantPayload["language"]>) => void;
  patchExperience: (index: number, patch: Partial<ApplicantPayload["experiences"][number]>) => void;
  addExperience: () => void;
}) {
  const experiences = payload.experiences.length ? payload.experiences : [emptyExperience()];
  return (
    <section className="profile-evidence-editor">
      <div className="program-title-row">
        <strong>补充关键资料</strong>
        <span>用于减少“信息不足”，不会替代学校官网判断</span>
      </div>
      <div className="form-grid">
        <label>成绩口径<select value={payload.education.gpa_scale} onChange={(event) => patchEducation({ gpa_scale: event.target.value as ApplicantPayload["education"]["gpa_scale"] })}><option value="100">百分制</option><option value="4.0">4.0 制</option><option value="5.0">5.0 制</option></select></label>
        <label>专业排名百分比<input type="number" min="0" max="100" value={payload.education.ranking_percentile ?? ""} onChange={(event) => patchEducation({ ranking_percentile: event.target.value ? Number(event.target.value) : null })} placeholder="例如 18 表示前 18%" /></label>
        <label>阅读<input type="number" value={payload.language.reading ?? ""} onChange={(event) => patchLanguage({ reading: event.target.value ? Number(event.target.value) : null })} /></label>
        <label>听力<input type="number" value={payload.language.listening ?? ""} onChange={(event) => patchLanguage({ listening: event.target.value ? Number(event.target.value) : null })} /></label>
        <label>口语<input type="number" value={payload.language.speaking ?? ""} onChange={(event) => patchLanguage({ speaking: event.target.value ? Number(event.target.value) : null })} /></label>
        <label className="wide-field">核心课程 / 先修课<textarea rows={2} value={payload.raw_interest_text} onChange={(event) => setRawInterest(event.target.value)} placeholder="例如：数据结构 88、算法 90、数据库 86、机器学习项目..." /></label>
      </div>
      <div className="program-title-row compact">
        <strong>经历表</strong>
        <button className="text-button" type="button" onClick={addExperience}>新增经历</button>
      </div>
      {experiences.map((experience, index) => (
        <article className="experience-row" key={index}>
          <label>类型<select value={experience.type} onChange={(event) => patchExperience(index, { type: event.target.value as ApplicantPayload["experiences"][number]["type"] })}><option value="project">课程/项目</option><option value="research">科研</option><option value="internship">实习</option><option value="work">工作</option><option value="competition">竞赛</option><option value="volunteer">活动</option></select></label>
          <label>名称<input value={experience.title} onChange={(event) => patchExperience(index, { title: event.target.value })} placeholder="例如 库存预测系统" /></label>
          <label>机构/课程<input value={experience.organization} onChange={(event) => patchExperience(index, { organization: event.target.value })} /></label>
          <label>时长(月)<input type="number" value={experience.months} onChange={(event) => patchExperience(index, { months: Number(event.target.value) })} /></label>
          <label className="wide-field">职责<textarea rows={2} value={experience.role} onChange={(event) => patchExperience(index, { role: event.target.value })} placeholder="你具体负责什么，写了哪些代码/模型/分析" /></label>
          <label className="wide-field">工具 / 方法<textarea rows={2} value={experience.tools.join("，")} onChange={(event) => patchExperience(index, { tools: splitList(event.target.value) })} placeholder="Python, SQL, PyTorch, Power BI..." /></label>
          <label className="wide-field">结果 / 证据<textarea rows={2} value={experience.outcomes.join("，")} onChange={(event) => patchExperience(index, { outcomes: splitList(event.target.value) })} placeholder="量化结果、作品链接、报告、推荐人可证明的事实" /></label>
        </article>
      ))}
    </section>
  );
}

function ProgramMiniList({ matches }: { matches: ProgramMatch[] }) {
  if (!matches.length) return <EmptyState text="还没有加入申请方案的项目。" />;
  return (
    <div className="mini-program-list">
      {matches.map((item) => (
        <article className="mini-program" key={item.program.id}>
          <DataBadge status={item.program.data_status} />
          <h3>{displayProgram(item.program)}</h3>
          <p>{item.risks[0] ?? "等待学校官网确认。"}</p>
          <span>{tierLabel(item)}</span>
        </article>
      ))}
    </div>
  );
}

function SourceRefreshSummary({ report, evidenceGraph }: { report: DataRefreshReport | null; evidenceGraph?: EvidenceGraphSummary | null }) {
  if (!report) {
    return (
      <div className="source-report">
        <p>尚未检查学校官网来源。当前系统里还有 {evidenceGraph?.pending_review_field_count ?? 0} 条信息需要打开学校原文确认。</p>
        <AdviceList title="当前已知风险" items={["很多项目 URL 仍是学校项目索引页，而不是项目详情页。", "待确认信息不能直接用于正式申请时间线。", "社区与开源项目只能作为经验参考，不能替代学校官网要求。"]} />
      </div>
    );
  }
  const qsImport = report.extraction_results.find((item) => item.source_id === "qs_master_applications_github");
  const qsRaw = (qsImport?.raw_json ?? {}) as {
    matched_candidate_count?: number;
    matched_candidates?: Array<Record<string, unknown>>;
    use_boundary?: string[];
  };
  return (
    <div className="source-report">
      <section className="status-grid">
        <Metric label="检查方式" value={report.mode === "live_fetch" ? "学校官网快照" : "来源策略检查"} detail={report.mode === "live_fetch" ? "已尝试联网获取页面" : "未联网，不保存页面"} />
        <Metric label="学校来源" value={`${report.official_sources_checked}`} detail="可用于官网确认" />
        <Metric label="社区来源" value={`${report.community_sources_checked}`} detail="只作经验信号" />
        <Metric label="待确认" value={`${report.review_queue_size}`} detail="需要查看学校原文" />
      </section>
      <p>{report.summary}</p>
      {qsImport ? (
        <section className="source-import-card">
          <div>
            <strong>GradWindow 官网线索已接入</strong>
            <p>
              本次匹配到 {qsRaw.matched_candidate_count ?? 0} 条港新项目/学校线索。
              这些线索用于定位官网入口、上一申请季窗口和项目页，不会直接覆盖正式申请字段。
            </p>
          </div>
          <div className="material-chips">
            {(qsRaw.matched_candidates ?? []).slice(0, 6).map((candidate, index) => (
              <span key={`${String(candidate.program_id ?? candidate.university_id ?? index)}`}>
                {String(candidate.institution_zh ?? candidate.institution ?? "学校")}
                {candidate.closes_at ? ` · 上季截止 ${String(candidate.closes_at)}` : " · 官网入口线索"}
              </span>
            ))}
          </div>
        </section>
      ) : null}
      <AdviceList title="下一步" items={report.next_actions} />
    </div>
  );
}

function SourcePriorityList() {
  const items = ["官方申请系统", "官方项目详情页", "官方 PDF / FAQ", "官方项目索引", "目录 / 排名", "社区 / GitHub / 小红书"];
  return <div className="priority-list">{items.map((item, index) => <div key={item}><span>{index + 1}</span><strong>{item}</strong></div>)}</div>;
}

function WorkflowStageList() {
  const items = [
    ["SourceDiscoveryAgent", "发现学校官网入口和项目详情链接。"],
    ["OfficialCrawlerAgent", "抓取 HTML / PDF，保存快照和 page hash。"],
    ["FieldExtractionAgent", "只抽取截止日期、学费、语言、材料等候选信息。"],
    ["DiffAgent", "比较历史快照，发现申请季变化。"],
    ["ReviewerGateAgent", "关键信息需要查看学校原文后再发布。"],
    ["CommunitySignalAgent", "整理 GitHub / GradCafe / 小红书经验信号。"],
  ];
  return <div className="workflow-list">{items.map(([name, detail]) => <article key={name}><strong>{name}</strong><p>{detail}</p></article>)}</div>;
}

function SourceRegistryList({ registry }: { registry: SourceRegistry | null }) {
  if (!registry) return <EmptyState text="来源注册表未读取。" />;
  return (
    <div className="source-list">
      {registry.sources.slice(0, 18).map((source) => (
        <article key={source.source_id}>
          <div><strong>{source.name}</strong><span>{source.trust_level}</span></div>
          <p>{source.allowed_uses?.[0] ?? "用途待补充"}</p>
          <a href={source.url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />打开来源</a>
        </article>
      ))}
    </div>
  );
}

function EvidenceRecordList({ records }: { records: FieldEvidenceRecord[] }) {
  if (!records.length) return <EmptyState text="暂无来源证据记录。" />;
  return (
    <div className="evidence-list">
      {records.slice(0, 12).map((record) => (
        <article key={`${record.program_id}-${record.field_name}-${record.page_hash ?? ""}`}>
          <div className="program-title-row"><strong>{fieldLabels[record.field_name] ?? record.field_name}</strong><DataBadge status={record.status} /></div>
          <p>{record.evidence_snippet ?? "等待官方原文摘录。"}</p>
          <div className="task-meta">
            <span>{record.cycle ?? "申请季待确认"}</span>
            <span>优先级 {record.source_priority}</span>
            <span>置信度 {record.confidence}</span>
          </div>
          {record.source_url ? <a className="text-link" href={record.source_url} target="_blank" rel="noreferrer">查看来源</a> : null}
        </article>
      ))}
    </div>
  );
}

function ExtractionResultList({ report }: { report: DataRefreshReport | null }) {
  const results = report?.extraction_results ?? [];
  if (!results.length) return <EmptyState text="刷新学校官网信息后，这里展示候选信息、未解决问题和页面快照。" />;
  return (
    <div className="evidence-list">
      {results.slice(0, 8).map((result) => (
        <article key={`${result.source_id}-${result.page_hash ?? result.parser}`}>
          <div className="program-title-row"><strong>{result.source_id}</strong><span className="tier-pill">{result.parser}</span></div>
          <p>page_hash: {result.page_hash ?? "未生成"} · snapshot: {result.snapshot_path ?? "未保存"}</p>
          <div className="field-grid">
            {result.extracted_fields.length ? result.extracted_fields.map((field) => (
              <div key={field.field_name}>
                <strong>{fieldLabels[field.field_name] ?? field.field_name}</strong>
                <p>{field.evidence_snippet ?? field.value ?? "等待抽取"}</p>
                <span>{field.confidence} / {field.status}</span>
              </div>
            )) : <p className="form-note">该来源尚未抽取出可用信息。</p>}
          </div>
        </article>
      ))}
    </div>
  );
}

function ActivityDrawer({ open, onClose, result, evidenceGraph, sourceRefresh }: { open: boolean; onClose: () => void; result: AppState | null; evidenceGraph: EvidenceGraphSummary | null; sourceRefresh: DataRefreshReport | null }) {
  if (!open) return null;
  const first = result?.focus_list?.[0] ?? result?.recommendations?.[0] ?? null;
  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="decision-drawer" role="dialog" aria-label="AI 决策依据" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <span className="eyebrow">AI 分析依据</span>
            <h2>AI 做了什么</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} aria-hidden /></button>
        </div>
        <section className="status-grid two">
          <Metric label="来源记录" value={`${evidenceGraph?.field_record_count ?? 0}`} detail="证据清单" />
          <Metric label="待确认" value={`${sourceRefresh?.review_queue_size ?? evidenceGraph?.pending_review_field_count ?? 0}`} detail="待查看学校原文" />
        </section>
        {first ? (
          <IslandCard className="panel-card">
            <PanelTitle icon={<ShieldCheck size={18} aria-hidden />} title={`为什么推荐：${displayProgram(first.program)}`} />
            <AdviceList title="依据" items={first.explanation?.decision_basis ?? first.reasons} />
            <AdviceList title="不确定项" items={first.explanation?.uncertainties ?? first.risks} />
          </IslandCard>
        ) : null}
        <TraceList trace={result?.trace ?? []} />
      </aside>
    </div>
  );
}

function TraceList({ trace }: { trace: AgentTrace[] }) {
  if (!trace.length) return <EmptyState text="还没有 AI 分析记录。" />;
  return (
    <div className="trace-list">
      {trace.slice(-10).map((event, index) => (
        <article className="trace-item" key={`${event.node}-${index}`}>
          <div className="trace-index">{index + 1}</div>
          <div>
            <div className="program-title-row"><strong>{agentLabel(event.node)}</strong><span className={`status-pill ${event.status.toLowerCase()}`}>{event.status === "COMPLETED" ? "已完成" : "待确认"}</span></div>
            <p>{event.output_summary}</p>
            <div className="task-meta">{event.tool_calls.slice(0, 4).map((tool) => <span key={tool}>{tool}</span>)}</div>
          </div>
        </article>
      ))}
    </div>
  );
}

function RubricPanel({ rubric }: { rubric: WritingReviewRubric | null }) {
  if (!rubric) return null;
  return (
    <section className="rubric-panel">
      <h3>审核量表：{rubric.export_recommendation}</h3>
      <section className="status-grid two">
        <Metric label="题目覆盖" value={rubric.prompt_coverage} detail="是否回应 prompt" />
        <Metric label="项目特异性" value={rubric.program_specificity} detail="Why Program 绑定程度" />
        <Metric label="事实覆盖" value={rubric.fact_coverage} detail="故事卡绑定" />
        <Metric label="无证据陈述" value={`${rubric.unsupported_claims}`} detail={`CV 冲突 ${rubric.cv_conflicts}`} />
      </section>
      <AdviceList title="问题" items={rubric.issues} />
      <AdviceList title="下一步" items={rubric.next_actions} />
    </section>
  );
}

function DraftPanel({ title, body }: { title: string; body: string }) {
  return (
    <article className="draft-panel">
      <h3>{title}</h3>
      <div>{body.split(/\n{2,}/).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div>
    </article>
  );
}

function OutlineList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return <div className="outline-list">{items.map((item) => <span key={item}>{item}</span>)}</div>;
}

function PanelTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>;
}

function StepItem({ done, title, detail, href }: { done: boolean; title: string; detail: string; href: string }) {
  return (
    <Link className={`step-item ${done ? "done" : ""}`} href={href}>
      <CheckCircle2 size={18} aria-hidden />
      <span><strong>{title}</strong><small>{detail}</small></span>
    </Link>
  );
}

function AdviceList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return <div className="advice-list"><h3>{title}</h3>{items.slice(0, 6).map((item) => <Rule text={item} key={item} />)}</div>;
}

function Rule({ text }: { text: string }) {
  return <div><CheckCircle2 size={15} aria-hidden /><span>{text}</span></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>;
}

function Signal({ label, value }: { label: string; value: React.ReactNode }) {
  return <span className="signal"><small>{label}</small><strong>{value}</strong></span>;
}

function DataBadge({ status }: { status?: string | null }) {
  const value = status ?? "MODEL_INFERRED";
  return <span className={`data-badge ${value.toLowerCase()}`}>{dataStatusLabels[value] ?? value}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>;
}

function filterCatalog(programs: CatalogProgram[], filters: { q: string; region: string; discipline: string; verification_status: string; deadline_status: string }) {
  return programs.filter((program) => {
    const haystack = [program.name, program.name_zh, program.institution, program.institution_zh, program.school, program.school_zh].filter(Boolean).join(" ").toLowerCase();
    if (filters.q && !haystack.includes(filters.q.toLowerCase())) return false;
    if (filters.region && program.country !== filters.region) return false;
    if (filters.discipline && ![program.category_zh, ...program.discipline_tags].filter(Boolean).join(" ").toLowerCase().includes(filters.discipline.toLowerCase())) return false;
    if (filters.verification_status && program.data_status !== filters.verification_status) return false;
    if (filters.deadline_status === "published" && program.deadline === "NOT_PUBLISHED") return false;
    if (filters.deadline_status === "not_published" && program.deadline !== "NOT_PUBLISHED") return false;
    return true;
  });
}

function buildQuestionnaireResponse(schema: QuestionnaireSchema | null, values: QuestionnaireValues): QuestionnaireResponse {
  const answers = (schema?.sections ?? []).flatMap((section) =>
    section.fields
      .filter((field) => !field.sensitive && values[field.id]?.trim())
      .map((field) => ({ field_id: field.id, value: values[field.id], evidence_ids: [] }))
  );
  return { profile_answers: [], statement_answers: answers, recommender_answers: [] };
}

function emptyExperience(): ApplicantPayload["experiences"][number] {
  return {
    type: "project",
    title: "",
    organization: "",
    months: 0,
    role: "",
    outcomes: [],
    tools: [],
    evidence_level: "SELF_REPORTED",
  };
}

function splitList(value: string) {
  return value
    .split(/[,\n，、；;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function readStorage<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function pageTitle(view: ViewMode) {
  return {
    home: "我的申请",
    assessment: "背景资料",
    programs: "项目探索",
    timeline: "任务与材料",
    writing: "文书工作台",
    agent: "资料中心",
    settings: "设置",
  }[view];
}

function displayProgram(program: ProgramMatch["program"]) {
  return program.name_zh || program.name || "项目名称待确认";
}

function displayProgramSecondary(program: ProgramMatch["program"]) {
  if (program.name_zh && program.name && program.name_zh !== program.name) return program.name;
  return program.institution || "英文项目名待学校确认";
}

function programMeta(program: ProgramMatch["program"]) {
  return [
    program.institution_zh || program.institution,
    program.school_zh || program.school || "学院待确认",
    regionLabel(program.country),
  ].filter(Boolean).join(" · ");
}

function regionLabel(country: ProgramMatch["program"]["country"]) {
  return country === "HK" ? "香港" : "新加坡";
}

function tierLabel(item: ProgramMatch) {
  if (item.tier === "insufficient_info") return "信息不足";
  if (item.tier === "not_recommended") return "暂不考虑";
  if (!item.formal_recommendation) return "候选";
  return { reach: "冲刺", match: "匹配", safer: "稳妥" }[item.tier];
}

function strategyLabel(value?: ProgramMatch["strategy_band"]) {
  return {
    reach: "冲刺",
    target: "主申",
    safe: "保底",
    candidate: "候选",
    blocked: "不建议",
  }[value ?? "candidate"];
}

function languageRequirement(program: ProgramMatch["program"]) {
  const language = program.requirements?.language ?? {};
  const ielts = language.IELTS ? `IELTS ${language.IELTS}` : "";
  const toefl = language.TOEFL ? `TOEFL ${language.TOEFL}` : "";
  return [ielts, toefl].filter(Boolean).join(" / ") || "待学校确认";
}

function intentLabel(intent: string) {
  return {
    "computer science": "计算机",
    "business analytics": "商业分析",
    "artificial_intelligence": "人工智能",
    "computer_science": "计算机科学",
    "data_science": "数据科学",
    "fintech": "金融科技",
    "software_engineering": "软件工程",
    "cyber_security": "网络安全",
    "finance": "金融",
    "management": "商科管理",
    "education_language": "教育/语言",
    "interdisciplinary": "跨学科",
  }[intent] ?? intent;
}

function band(value?: number) {
  if (value === undefined) return "未知";
  if (value >= 78) return "高";
  if (value >= 62) return "中";
  return "低";
}

function formatMoney(value: number | null | undefined) {
  return value ? `${Math.round(value / 10000)} 万港币` : "待确认";
}

function formatDeadline(value?: string | null) {
  return !value || value === "NOT_PUBLISHED" ? "本季未发布 / 待确认" : value;
}

function formatDateTime(value?: string | null) {
  if (!value) return "待确认";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toISOString().slice(0, 10);
}

function dateBasisLabel(value?: string | null) {
  if (!value) return "内部准备建议";
  if (String(value).includes("官方")) return "官方倒推";
  if (String(value).includes("上一")) return "上一季参考";
  if (String(value).includes("人工")) return "人工确认";
  return "内部建议";
}

function riskLabel(value?: string | null) {
  const raw = String(value ?? "");
  if (raw.includes("high") || raw.includes("高")) return "高";
  if (raw.includes("low") || raw.includes("低")) return "低";
  return "中";
}

function agentLabel(node: string) {
  return {
    ProfileAgent: "资料整理助手",
    EvidenceAgent: "事实确认助手",
    EvaluationAgent: "背景诊断助手",
    ProgramIntelligenceAgent: "项目研究助手",
    SchoolMatchingAgent: "择校解释助手",
    TimelineAgent: "任务规划助手",
    WritingAgent: "文书助手",
    StoryCardAgent: "故事卡助手",
    ReviewAgent: "风险审核助手",
    DataRefreshAgent: "信息刷新助手",
  }[node] ?? node;
}
