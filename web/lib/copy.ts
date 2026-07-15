import type { ApplicantPayload } from "./types";

export const studentNavItems = [
  { href: "/", label: "我的申请", view: "home" },
  { href: "/assessment", label: "背景评估", view: "assessment" },
  { href: "/programs", label: "项目库", view: "programs" },
  { href: "/timeline", label: "时间线", view: "timeline" },
  { href: "/writing", label: "文书工作台", view: "writing" },
  { href: "/settings", label: "AI 设置", view: "settings" },
] as const;

export const adminNavItems = [
  { href: "/agent-lab", label: "Admin 数据中心", view: "agent" },
] as const;

export const navItems = studentNavItems;

export const disciplineOptions = [
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

export const schoolTiers: Array<{ code: ApplicantPayload["education"]["school_tier"]; label: string }> = [
  { code: "C9", label: "C9" },
  { code: "985", label: "985" },
  { code: "211", label: "211" },
  { code: "double_first_class", label: "双一流" },
  { code: "regular", label: "双非 / 普通本科" },
  { code: "overseas", label: "海外本科" },
  { code: "unknown", label: "暂不确定" },
];

export const dataStatusLabels: Record<string, string> = {
  DISCOVERED: "已找到来源",
  EXTRACTED: "已提取，待发布",
  PENDING_REVIEW: "运营审核中",
  VERIFIED: "官网当前季已核验",
  STALE: "2026 Fall 往届参考",
  CHANGED: "来源冲突",
  NOT_PUBLISHED: "官网当前季未发布",
  REJECTED: "不纳入学生端",
  ARCHIVED: "已归档",
  OFFICIAL_VERIFIED_CURRENT: "官网当前季已核验",
  OFFICIAL_PREVIOUS_CYCLE: "2026 Fall 往届参考",
  COMMUNITY_ONLY: "公开经验参考",
  CONFLICTED: "来源冲突",
  MODEL_INFERRED: "缺少项目详情页",
  QUEUED: "队列中",
  RUNNING: "运行中",
  NEEDS_HUMAN: "需要人工处理",
  FAILED: "失败",
  COMPLETED: "已完成",
  RETRY_REQUESTED: "已请求重试",
  ROLLED_BACK: "已回退",
  ROLLBACK_TARGET: "回退节点",
};

export function previousCycleLabel(cycle?: string | null): string {
  const raw = String(cycle ?? "").trim();
  const yearMatch = raw.match(/(20\d{2})/);
  const year = yearMatch ? Number(yearMatch[1]) : 2027;
  const previousYear = /\d{4}-\d{2}-\d{2}/.test(raw) ? year : year - 1;
  const lower = raw.toLowerCase();
  const term = lower.includes("spring") || lower.includes("-spring") ? "Spring" : "Fall";
  return previousYear + " " + term + " 往届参考";
}

export const fieldLabels: Record<string, string> = {
  official_program_url: "项目详情页",
  deadline: "截止日期",
  tuition_hkd: "学费",
  materials: "材料清单",
  language_requirement: "语言要求",
  application_url: "申请入口",
  essay_prompts: "文书题目",
};

export const materialLabels: Record<string, string> = {
  transcript: "正式成绩单",
  degree_certificate: "在读 / 毕业证明",
  core_courses: "核心课程清单",
  cv: "CV",
  recommendation: "推荐信",
  language_score: "语言成绩单",
  experience_proof: "经历证明",
  personal_statement: "PS / SOP",
  essay_prompts: "文书题目",
  official_program_page: "官方项目页",
  official_pdf_or_faq: "官方 PDF / FAQ",
  application_system: "网申系统",
};

export const taskTypeLabels: Record<string, string> = {
  profile: "背景",
  source_review: "来源复核",
  materials: "通用材料",
  language: "语言",
  recommendation: "推荐信",
  writing: "文书",
  submission: "网申",
  scholarship: "奖学金",
};

export const documentTypeOptions = [
  { value: "PS", label: "PS 个人陈述", detail: "围绕动机、学术能力、实践经历、项目适配和职业规划整理素材。" },
  { value: "SOP", label: "SOP 目的陈述", detail: "适合技术、学术或职业目标更清晰的项目。" },
  { value: "CV", label: "CV / Resume", detail: "优化项目、实习、科研、技能和成果表达。" },
  { value: "ESSAY", label: "Essay", detail: "处理学校指定小文书或补充题。" },
  { value: "REFERENCE_PACKAGE", label: "推荐信草稿", detail: "按推荐信调查表整理推荐人可确认的事实，并生成中英文草稿。" },
] as const;

export const pageTitles: Record<string, string> = {
  home: "我的申请",
  assessment: "背景竞争力评估",
  programs: "港新项目清单与申请分档",
  timeline: "逐项目时间线",
  writing: "文书问卷工作台",
  agent: "Admin 数据中心",
  settings: "AI 模型连接",
};

export const appErrorCopy = {
  profileSaveFailed: "背景资料暂时无法写入本地档案库，请确认本地服务已启动。",
  workspaceSaveFailed: "本地申请状态暂时无法写入，请确认本地服务已启动。",
  catalogLoadFailed: "项目库暂时未返回数据。",
  backgroundFailed: "背景评估暂时没有完成，请稍后重试。",
  programsFailed: "项目分档暂时没有完成，请稍后重试。",
  selectProgramFirst: "请先在项目库中勾选要申请的项目。",
  timelineFailed: "时间线暂时没有完成，请稍后重试。",
  packageFailed: "项目信息暂时未读取完成。",
  sourceRefreshFailed: "项目来源暂时没有核对完成。",
  crawlQueueFailed: "来源队列暂时没有整理完成。",
  catalogUpdateFailed: "项目详情页候选暂时没有整理完成。",
  reviewQueueFailed: "审核队列暂时未加载。",
  scenarioAuditFailed: "场景自检暂时未完成。",
  reviewPreviewFailed: "审核预览暂时未完成。",
  writingQuestionsFailed: "素材问题暂时未生成。",
  writingFailed: "文书工作台暂时没有完成输出。",
  modelKeyRequired: "请先输入 API Key。",
  modelConnecting: "正在连接本地后端模型配置...",
  modelConnectFailed: "模型连接失败。",
} as const;

export const studentCopy = {
  sourcePanel: "推荐依据与来源",
  modelManagedByAdmin: "当前还在示例模式。你可以到 AI 设置里选择模型并填写自己的 API Key，Key 只提交给本机后端用于本次连接，不写入浏览器存储。",
  noFormalTimeline: "缺少项目详情页或关键官网信息时，不能生成正式申请时间线。",
  previousCycleNote: "如果学校尚未发布当前季信息，页面会标明具体往届申请季，并给出可执行准备动作。",
};

export const dashboardCopy = {
  navReady: "AI 模型已连接",
  navConfigured: "示例模式运行中",
  navNote: "硬门槛由规则和来源判断，模型负责解释、排序和草稿辅助。",
  heroEyebrow: "申请流程从这里开始",
  heroTitle: "先评估背景，再生成择校分档，最后排时间线和做文书。",
  heroBody: "把学生背景、项目库、官网来源和文书素材放在同一条流程里：先判断是否适配，再给出可追踪的申请安排。",
  runBackground: "开始背景评估",
  runPrograms: "生成项目清单",
  refreshSources: "核对项目来源",
  metrics: {
    profile: { label: "表单填写", detail: "只代表已填写，不代表已验证" },
    decision: { label: "决策信息覆盖", detail: "影响最终项目判断" },
    evidence: { label: "证据覆盖", detail: "官网或材料证明比例" },
    source: { label: "来源记录", verifiedSuffix: "条已核验" },
  },
  nextTitle: "今天先做什么",
  nextSteps: [
    { key: "assessment", title: "补充背景资料", detail: "先判断语言、专业背景、先修课和预算硬门槛。", href: "/assessment" },
    { key: "programs", title: "生成项目分档", detail: "优先看 Agent 择校方案，再用项目库搜索补充。", href: "/programs" },
    { key: "selection", title: "确认申请清单", detail: "时间线只使用你自己勾选保存的项目。", href: "/programs" },
    { key: "timeline", title: "生成逐项目时间线", detail: "查看每个项目的轮次、DDL、材料和提交入口。", href: "/timeline" },
    { key: "writing", title: "整理文书素材", detail: "按问卷生成故事卡、大纲、段落草稿和确认清单。", href: "/writing" },
  ],
  applicationList: "申请清单",
  runTimeline: "生成时间线与材料",
  adjustPrograms: "调整项目",
  trustTitle: "信息可信度说明",
} as const;

export const progressCopy = {
  background: { title: "正在生成背景竞争力评估", steps: ["读取申请背景", "判断硬门槛", "识别资料缺口", "生成竞争力评估"] },
  programs: { title: "正在生成项目分档", steps: ["读取背景", "调用港新项目库", "按院校层级、GPA、语言和经历分档", "输出冲刺、主申、保底、候选和不建议"] },
  timeline: { title: "正在生成时间线", steps: ["读取已选项目", "核对项目来源", "合并通用材料", "生成日期任务"] },
  writing: { title: "正在生成文书草稿", steps: ["整理问卷", "生成故事卡", "绑定目标项目", "输出大纲和段落草稿"] },
  interview: { title: "正在补全素材问题", steps: ["读取目标项目", "发现素材缺口", "生成补充问题"] },
  data: { title: "正在核对项目来源", steps: ["匹配学校官网入口", "查找项目详情页", "区分官网和公开经验来源", "输出可确认信息清单"] },
  crawl: { title: "正在整理来源队列", steps: ["整理官网和公开经验来源", "检查访问规则和快照状态", "标记解析和审核要求", "公开经验仅作参考"] },
  catalog: { title: "正在整理项目页候选", steps: ["筛选缺少详情页的项目", "匹配官方项目页线索", "排除学校首页和泛目录页", "生成审核队列候选"] },
  review: { title: "正在加载审核队列", steps: ["读取需复核信息", "检查来源链接和页面记录", "区分可发布和待补充项目", "预览审核结果"] },
  scenario: { title: "正在运行场景自检", steps: ["读取测试背景", "检查目标项目明细", "检查可信度和更新时间", "检查流程记录和来源边界"] },
  package: { title: "正在加载项目数据", steps: ["读取官网来源", "整理项目内容", "生成公开经验线索", "准备采集计划"] },
  llm: { title: "正在连接模型", steps: ["提交到本地后端", "验证模型配置", "准备工作流调用"] },
  doneMessage: "请稍等，完成后页面会自动更新。",
} as const;

export const assessmentCopy = {
  dimensionEmpty: "完成背景评估后，每个维度都会显示结论、依据和动作。",
} as const;

export const programCatalogCopy = {
  heroEyebrow: "先看 Agent 择校方案，再搜索全量项目库",
  heroTitle: "生成港新项目清单与申请分档",
  heroBody: "系统结合院校层级、GPA、语言、专业方向、经历、预算和官网信息，先输出冲刺、主申、保底、候选和不建议。学生可以编辑分档、删除项目，也可以从项目库继续加入。",
  trustBoundaryTitle: "当前是预评估，不是最终提交依据",
  trustBoundaryBody: "冲刺、主申、保底用于缩小选择范围；只有字段显示为官网当前季已核验，或明确标注为具体往届参考时，才可进入后续日期安排。",
  trustBoundaryAction: "保存项目后，时间线仍会按字段来源区分当前季官方、往届参考和待官网核验。",
  runButton: "生成项目分档",
  runningButton: "正在分档",
  fullCatalogTitle: "全量港新项目库",
  planOverviewTitle: "项目分档概览",
  readinessTitle: "项目资料可用性",
  readinessBody: "当前没有足够证据时，页面只把项目作为筛选参考；只有关键字段完成当前季官网核验后，才进入正式日期和提交入口安排。",
  readinessCurrent: "当前季官网字段",
  readinessReference: "往届参考完整",
  readinessIncomplete: "信息不完整",
  readinessCurrentDetail: "可进入正式申请日历",
  readinessReferenceDetail: "可用于择校筛选和材料安排",
  readinessIncompleteDetail: "先补项目页、入口、日期、语言、材料或学费",
  readinessEmpty: "项目库还没有返回可计算的资料状态。",
  noPlan: "还没有项目分档。请先生成项目分档。",
  selected: "已加入清单",
  addToList: "加入清单",
  inspect: "项目详情",
  detailPage: "项目详情页",
  missingDetailPage: "未找到项目详情页",
  queueSourceUpdate: "加入信息更新队列",
  sourceUpdateQueued: "已提交给信息更新 Agent",
  applicationEntry: "申请入口",
  missingApplicationEntry: "申请入口待补充",
  noMatches: "暂无匹配结果。请先补充背景并重新分档。",
  trustLoading: "项目信息正在加载。",
  defaultRisk: "关键项目信息还没有当前季官网来源。",
  defaultAction: "打开项目详情页或申请系统核对日期、材料和入口。",
  defaultDisclaimer: "当前推荐用于筛选和排序；截止日期、学费、语言、材料和申请入口按官网来源逐项展示。",
  catalogError: "项目库暂时没有返回结果，请确认本地服务已启动。",
  catalogEmptyDb: "项目库尚未加载到本地数据库。请先运行数据入库或刷新项目库。",
  catalogEmptyFiltered: "没有找到项目：当前筛选条件太窄，请放宽地区、方向、信息状态或关键词。",
  catalogEmptyDefault: "项目库暂无可展示记录。",
  fallbackEnglishName: "英文项目名待补充",
  fallbackSchool: "学院待核对",
  unverifiedMoney: "官网学费待补充",
};

export const timelineCopy = {
  heroEyebrow: "只根据学生确认的项目生成",
  heroTitle: "逐项目展示开放时间、截止时间、材料和提交入口",
  heroBody: "正式截止日期、奖学金优先轮、推荐信系统截止和网申入口都按官网来源判断。当前季未发布时，只生成带往届年份标注的准备安排。",
  boundaryTitle: "时间线先给可执行准备动作",
  boundaryBody: "日期、申请入口、语言、材料和学费会按字段来源展示；没有当前季官网来源时，任务会标为往届参考或待官网核验。",
  currentReady: "已有项目可使用当前季官方信息。",
  previousReady: "已有往届官方信息，可先安排材料动作。",
  needsOfficial: "当前清单还需要补充官网信息。",
  refreshButton: "核对项目来源",
  runButton: "生成时间线",
  selectedProgramsTitle: "已选项目",
  emptyTasks: "暂无任务。选择项目并生成时间线后显示。",
  noSelectedPrograms: "还没有加入申请清单的项目。",
  defaultTaskBasis: "先安排可执行准备动作；正式提交日期必须等关键官网信息确认后再使用。",
  applicationEntry: "打开申请入口",
  schoolSource: "打开官网页面",
};

export const writingCopy = {
  title: "文书问卷工作台",
  intro: "这里先按问卷收集课程、项目、科研、实习、动机和职业规划等文书素材，再生成素材缺口、故事卡、大纲和段落草稿。风格只抽象口吻、结构和表达密度，不复制案例事实。",
  documentType: "文书类型",
  targetProgram: "目标项目",
  firstSelectedProgram: "使用已选第一个项目",
  loadingSchema: "正在读取文书问卷结构",
  materialQuestions: "补全素材问题",
  runDraft: "生成大纲草稿",
  materialGaps: "素材缺口",
  storyCards: "故事卡",
  outline: "文书大纲",
  paragraphDraft: "段落草稿",
  factBinding: "确认清单",
  customizationSources: "项目定制来源",
  promptRequirements: "题目和格式要求",
  boundaryControls: "边界控制",
  storyCardEmpty: "填写问卷后，系统会整理故事卡，再生成大纲和段落草稿。",
  materialGapEmpty: "生成大纲草稿后，这里会列出还需要补充的课程、经历、项目来源和事实证据。",
  paragraphDraftEmpty: "生成后会按段落展示草稿，便于逐句核对事实和表达。",
  factBindingEmpty: "还没有可绑定的事实。请先补充问卷中的课程、经历、项目来源。",
  interviewEmpty: "点击“补全素材问题”后，系统会按目标项目和素材缺口列出问题。",
};

type StudentTrustLike = {
  production_ready?: boolean | null;
  reference_ready?: boolean | null;
  cycle?: string | null;
  status_label?: string | null;
} | null | undefined;

export function studentTrustWarning(trust: StudentTrustLike, fallback = "关键信息需要按项目详情页、申请入口和字段来源逐项复核。"): string {
  if (!trust) return fallback;
  if (trust.production_ready) return "关键字段已有当前申请季学校官方来源；提交前仍建议打开项目官网页面和申请入口确认一次。";
  if (trust.reference_ready) return previousCycleLabel(trust.cycle) + "：可先安排材料准备，当前季开放和截止日期以官网发布后更新为准。";
  const label = String(trust.status_label ?? "");
  if (label.includes("冲突")) return "不同来源之间存在冲突，先不要把日期、学费或材料当作正式结论。";
  if (label.includes("未发布")) return "当前申请季官网信息尚未完整发布；可先准备材料，发布后再确认日期和入口。";
  return fallback;
}
