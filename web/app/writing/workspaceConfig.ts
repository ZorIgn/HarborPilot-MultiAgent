import type { WritingInterviewQuestion } from "@/lib/types";

export type DocumentType = "PS" | "SOP" | "CV" | "ESSAY" | "REFERENCE_PACKAGE";

export type FlowDefinition = {
  label: string;
  shortLabel: string;
  studentGoal: string;
  sections: string[];
  templateBasis: string;
  writingMethod: string;
  agentBoundary: string;
  outputHint: string;
};

export const documentFlows: Record<DocumentType, FlowDefinition> = {
  PS: {
    label: "PS 个人陈述",
    shortLabel: "PS",
    studentGoal: "讲清楚申请动机、学术准备、关键经历、职业目标，以及为什么适合这个项目。",
    sections: ["ps_opening_motivation", "ps_academic_ability", "ps_core_courses", "ps_practice_experience", "ps_career_plan", "ps_why_program", "ps_supplemental_info", "ps_special_prompts"],
    templateBasis: "参考《个人陈述调查问卷》的开篇动机、学术能力、核心课程、实践经历、职业规划、Why Program、补充信息和特殊题目。",
    writingMethod: "先把真实经历整理成故事卡，再生成申请主线、大纲、段落草稿和事实绑定表。",
    agentBoundary: "学校定制句只使用项目官网、网申系统或官方 PDF 中可核验的信息；素材不足时先列缺口，不补写事实。",
    outputHint: "输出素材缺口、故事卡、中文逻辑稿、英文申请稿、段落草稿和事实绑定表。",
  },
  SOP: {
    label: "SOP 目的陈述",
    shortLabel: "SOP",
    studentGoal: "更强调学术目标、方法训练、项目问题意识，以及目标项目如何承接下一阶段规划。",
    sections: ["ps_academic_ability", "ps_core_courses", "ps_practice_experience", "ps_why_program", "ps_career_plan", "ps_special_prompts"],
    templateBasis: "参考《个人陈述调查问卷》中学术能力、核心课程、实践经历、Why Program 和职业目标问题。",
    writingMethod: "减少泛泛动机，增加问题意识、方法、证据和目标路径。",
    agentBoundary: "不把兴趣写成研究能力，不编造课程、教授、就业数据，也不推测录取结果。",
    outputHint: "输出偏学术和目标导向的大纲、段落草稿、事实绑定表和补充问题。",
  },
  CV: {
    label: "CV / Resume",
    shortLabel: "CV",
    studentGoal: "把教育、课程、项目、实习、科研、奖项和技能整理成可扫描的履历素材。",
    sections: ["cv_education", "cv_experience", "cv_research_projects", "cv_awards_skills"],
    templateBasis: "参考《个人信息表 硕士》的教育经历、标准考试、实习、科研、活动、奖项和技能模块。",
    writingMethod: "按动作动词、工具方法、结果指标和项目相关性组织 bullet。",
    agentBoundary: "只整理可公开提交的教育与经历事实；护照、身份证、家庭住址、账号密码不进入写作模型。",
    outputHint: "输出 CV bullet、技能排序、经历取舍建议和可核对事实表。",
  },
  ESSAY: {
    label: "Essay / 小文书",
    shortLabel: "Essay",
    studentGoal: "先贴学校原题，再围绕题目拆回答结构、可用事实和项目匹配点。",
    sections: ["essay_prompt_response", "ps_practice_experience", "ps_why_program"],
    templateBasis: "参考《个人陈述调查问卷》的特殊题目模块，先记录原题、字数限制、格式和回答重点。",
    writingMethod: "先拆题，再用经历证据回应每个问题点，最后检查是否覆盖原题。",
    agentBoundary: "题目不完整时只生成结构和补充问题，不替学生假设题意或虚构项目要求。",
    outputHint: "输出针对题目的回答框架、段落草稿、补充问题和事实绑定表。",
  },
  REFERENCE_PACKAGE: {
    label: "推荐信草稿",
    shortLabel: "推荐信",
    studentGoal: "按推荐信调查表收集推荐人关系、课程表现、展示/小组/研究项目和具体印象。",
    sections: ["reference_recommender_profile", "reference_relationship", "reference_course_performance", "reference_activity_project", "reference_specific_impression", "reference_competency_events"],
    templateBasis: "参考《推荐信调查表（学校）》的推荐人信息、关系、课程表现、presentation/小组活动/研究项目、具体印象和综合能力事件。",
    writingMethod: "只写推荐人能观察或确认的事实，先生成给推荐人核对的材料包。",
    agentBoundary: "推荐信必须由推荐人确认、修改并提交；禁止代签或伪造推荐人身份。",
    outputHint: "输出推荐人确认清单、中英文推荐信草稿、可用事实和风险提示。",
  },
};

export const wizardSteps = [
  { id: "setup", label: "选项目", detail: "确定项目和文书" },
  { id: "collect", label: "填问卷", detail: "逐页收集素材" },
  { id: "review", label: "生成初稿", detail: "检查后调用写作" },
  { id: "export", label: "下载文档", detail: "导出可编辑稿" },
] as const;

export const fallbackGapQuestions: WritingInterviewQuestion[] = [
  { id: "prompt_original", target_section: "题目要求", question: "请粘贴目标项目的文书题目、字数限制和上传格式。", why_it_matters: "没有官方题目时，只能生成通用结构，不能判断是否覆盖学校要求。", required: true, sensitive: false },
  { id: "best_story_problem", target_section: "核心经历", question: "选择一段最想写进文书的经历：当时要解决的具体问题是什么？", why_it_matters: "文书需要从真实问题进入，而不是从抽象热爱进入。", required: true, sensitive: false },
  { id: "result_validation", target_section: "事实证据", question: "结果是什么？有没有数字、作品、报告、反馈、排名或可验证材料？", why_it_matters: "结果和证据决定草稿能否从泛泛描述变成可信叙事。", required: true, sensitive: false },
];
