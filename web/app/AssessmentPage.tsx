"use client";

import { Button as IslandButton, Card as IslandCard, Title as IslandTitle } from "animal-island-ui";
import { AlertTriangle, CheckCircle2, ClipboardCheck, GraduationCap, ListChecks, Save, ShieldCheck, Sparkles } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { assessmentCopy, disciplineOptions, schoolTiers } from "@/lib/copy";
import type { ApplicantPayload, DimensionFinding, WorkflowResult } from "@/lib/types";

type AssessmentLoading = string | null;
type ProfileSaveStatus = "idle" | "saving" | "saved" | "error";
type AssessmentState = {
  assessment?: WorkflowResult["assessment"];
  profile?: WorkflowResult["profile"];
} | null;

const assessmentSteps = [
  { id: "intent", label: "个人与意向", detail: "目标地区、申请季、方向和预算" },
  { id: "education", label: "教育与语言", detail: "学校、GPA、排名和语言单项" },
  { id: "experience", label: "课程与经历", detail: "先修课、科研、实习和技能" },
  { id: "materials", label: "材料核验", detail: "记录材料状态后再生成评估" },
] as const;

const materialStatusItems = [
  { key: "transcript", label: "正式成绩单", detail: "GPA、排名、核心课程成绩会影响竞争力判断。" },
  { key: "degree_certificate", label: "在读 / 毕业证明", detail: "用于确认就读状态、毕业时间和学位信息。" },
  { key: "language_score", label: "语言成绩单", detail: "总分和阅读、听力、口语、写作单项都需要核对。" },
  { key: "core_courses", label: "核心课程说明", detail: "转专业或先修课要求较强的项目尤其需要。" },
  { key: "cv", label: "CV / 经历证明", detail: "实习、科研、项目和活动要能回到真实材料。" },
  { key: "recommender", label: "推荐人信息", detail: "只记录关系和可确认事实，不收集账号密码。" },
] as const;

function materialFlag(key: string) {
  return "material_ready:" + key;
}

export function AssessmentPage({ payload, setPayload, result, loading, profileSaveStatus, onRun, onRunPrograms }: {
  payload: ApplicantPayload;
  setPayload: (payload: ApplicantPayload) => void;
  result: AssessmentState;
  loading: AssessmentLoading;
  profileSaveStatus: ProfileSaveStatus;
  onRun: () => void;
  onRunPrograms: () => void;
}) {
  const [activeStep, setActiveStep] = useState(0);
  const assessment = result?.assessment;
  const needsDecisionData = assessment?.overall_level === "NEEDS_DATA";
  const materialReadyCount = materialStatusItems.filter((item) => payload.risk_flags.includes(materialFlag(item.key))).length;
  const stepSummary = useMemo(() => assessmentStepSummary(payload, materialReadyCount), [payload, materialReadyCount]);

  function patchPersonalInfo(patch: Partial<ApplicantPayload["personal_info"]>) {
    setPayload({ ...payload, personal_info: { ...payload.personal_info, ...patch } });
  }
  function patchAdditionalBackground(patch: Partial<ApplicantPayload["additional_background"]>) {
    setPayload({ ...payload, additional_background: { ...payload.additional_background, ...patch } });
  }
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
  function toggleMaterialStatus(key: string) {
    const flag = materialFlag(key);
    const nextFlags = payload.risk_flags.includes(flag) ? payload.risk_flags.filter((item) => item !== flag) : [...payload.risk_flags, flag];
    setPayload({ ...payload, risk_flags: nextFlags });
  }
  function goNextStep() {
    setActiveStep((step) => Math.min(step + 1, assessmentSteps.length - 1));
  }
  function goPreviousStep() {
    setActiveStep((step) => Math.max(step - 1, 0));
  }

  return (
    <div className="assessment-page-shell">
      <IslandCard className="panel-card assessment-form-card">
        <div className="assessment-form-head">
          <PanelTitle icon={<GraduationCap size={19} aria-hidden />} title="申请背景信息" />
          <SaveStatusBadge status={profileSaveStatus} />
        </div>
        <div className="assessment-stepper" aria-label="背景评估填写步骤">
          {assessmentSteps.map((step, index) => (
            <button className={index === activeStep ? "active" : stepSummary[index].ready ? "done" : ""} type="button" key={step.id} onClick={() => setActiveStep(index)}>
              <span>{index + 1}</span>
              <strong>{step.label}</strong>
              <small>{stepSummary[index].detail || step.detail}</small>
            </button>
          ))}
        </div>

        {activeStep === 0 ? (
          <section className="assessment-step-panel">
            <StepHeader title="个人信息与申请意向" detail="先填影响项目筛选的基础信息。证件号、家庭住址、账号密码不进入学生端表单。" />
            <section className="profile-evidence-editor compact">
              <div className="program-title-row"><strong>个人信息</strong><span>只记录申请判断需要的基础信息。</span></div>
              <div className="form-grid">
                <label>称呼 / 姓名<input value={payload.personal_info.preferred_name} onChange={(event) => patchPersonalInfo({ preferred_name: event.target.value })} placeholder="可选" /></label>
                <label>国籍 / 身份<input value={payload.personal_info.citizenship} onChange={(event) => patchPersonalInfo({ citizenship: event.target.value })} placeholder="如中国大陆、海外本科等" /></label>
                <label>当前所在地<input value={payload.personal_info.current_location} onChange={(event) => patchPersonalInfo({ current_location: event.target.value })} placeholder="如广州、香港、新加坡" /></label>
                <label className="wide-field">补充说明<textarea rows={2} value={payload.personal_info.application_notes} onChange={(event) => patchPersonalInfo({ application_notes: event.target.value })} placeholder="例如交换计划、毕业时间、特殊申请限制。" /></label>
              </div>
            </section>
            <section className="profile-evidence-editor compact">
              <div className="program-title-row"><strong>申请意向</strong><span>用于项目库筛选和分档，不替学生直接定案。</span></div>
              <div className="form-grid">
                <label>申请季<select value={payload.target_cycle} onChange={(event) => setPayload({ ...payload, target_cycle: event.target.value })}><option value="2027-fall">2027 Fall</option></select></label>
                <label>学位类型<select value={payload.target_degree} onChange={(event) => setPayload({ ...payload, target_degree: event.target.value as ApplicantPayload["target_degree"] })}><option value="taught_master">授课型硕士</option><option value="research_master" disabled>研究型硕士（暂未开放）</option></select></label>
                <label>目标地区<select value={payload.target_regions.join(",")} onChange={(event) => setPayload({ ...payload, target_regions: event.target.value.split(",").filter(Boolean) as ApplicantPayload["target_regions"] })}><option value="HK,SG">香港 + 新加坡</option><option value="HK">香港</option><option value="SG">新加坡</option></select></label>
                <label>总预算上限 HKD<input type="number" value={payload.budget_hkd ?? ""} onChange={(event) => setPayload({ ...payload, budget_hkd: event.target.value ? Number(event.target.value) : null })} /><small>至少需要覆盖学费；生活、签证、保险和交通还要另行核算。</small></label>
                <label className="wide-field">职业目标<textarea rows={3} value={payload.career_goal} onChange={(event) => setPayload({ ...payload, career_goal: event.target.value })} placeholder="尽量具体到方向、岗位、地区和三到五年目标。" /></label>
              </div>
            </section>
            <div className="chip-group">
              {disciplineOptions.map((item) => <button className={payload.discipline_interests.includes(item.code) ? "chip selected" : "chip"} type="button" key={item.code} onClick={() => updateInterest(item.code)}>{item.label}</button>)}
            </div>
          </section>
        ) : null}

        {activeStep === 1 ? (
          <section className="assessment-step-panel">
            <StepHeader title="教育经历、GPA 口径和语言单项" detail="硬门槛主要由学校层级、GPA、排名、语言总分和单项共同判断。" />
            <div className="form-grid">
              <label>学校层级<select value={payload.education.school_tier} onChange={(event) => patchEducation({ school_tier: event.target.value as ApplicantPayload["education"]["school_tier"] })}>{schoolTiers.map((item) => <option value={item.code} key={item.code}>{item.label}</option>)}</select></label>
              <label>本科院校<input value={payload.education.school} onChange={(event) => patchEducation({ school: event.target.value })} /></label>
              <label>本科专业<input value={payload.education.major} onChange={(event) => patchEducation({ major: event.target.value })} /></label>
              <label>GPA / 均分<input type="number" value={payload.education.gpa} onChange={(event) => patchEducation({ gpa: Number(event.target.value) })} /></label>
              <label>GPA 口径<select value={payload.education.gpa_scale} onChange={(event) => patchEducation({ gpa_scale: event.target.value as ApplicantPayload["education"]["gpa_scale"] })}><option value="100">百分制</option><option value="4.0">4.0 制</option><option value="5.0">5.0 制</option></select></label>
              <label>专业排名百分比<input type="number" min="0" max="100" value={payload.education.ranking_percentile ?? ""} onChange={(event) => patchEducation({ ranking_percentile: event.target.value ? Number(event.target.value) : null })} placeholder="例如 18 表示前 18%" /></label>
              <label>语言考试<select value={payload.language.test} onChange={(event) => patchLanguage({ test: event.target.value as ApplicantPayload["language"]["test"] })}><option value="IELTS">IELTS</option><option value="TOEFL">TOEFL</option><option value="PTE">PTE</option><option value="NONE">暂未考试</option></select></label>
              <label>总分<input type="number" value={payload.language.overall ?? ""} onChange={(event) => patchLanguage({ overall: event.target.value ? Number(event.target.value) : null })} /></label>
              <label>阅读<input type="number" value={payload.language.reading ?? ""} onChange={(event) => patchLanguage({ reading: event.target.value ? Number(event.target.value) : null })} /></label>
              <label>听力<input type="number" value={payload.language.listening ?? ""} onChange={(event) => patchLanguage({ listening: event.target.value ? Number(event.target.value) : null })} /></label>
              <label>口语<input type="number" value={payload.language.speaking ?? ""} onChange={(event) => patchLanguage({ speaking: event.target.value ? Number(event.target.value) : null })} /></label>
              <label>写作单项<input type="number" value={payload.language.writing ?? ""} onChange={(event) => patchLanguage({ writing: event.target.value ? Number(event.target.value) : null })} /></label>
            </div>
          </section>
        ) : null}

        {activeStep === 2 ? (
          <ProfileEvidenceEditor payload={payload} setRawInterest={(raw_interest_text) => setPayload({ ...payload, raw_interest_text })} patchAdditionalBackground={patchAdditionalBackground} patchExperience={patchExperience} addExperience={addExperience} />
        ) : null}

        {activeStep === 3 ? (
          <section className="assessment-step-panel">
            <StepHeader title="材料核验入口" detail="这里先记录材料状态，帮助系统区分自填信息和可核对材料。正式提交仍要打开原件和项目官网要求逐项核对。" />
            <MaterialVerificationPanel readyKeys={payload.risk_flags} onToggle={toggleMaterialStatus} />
            <div className="card-actions assessment-final-actions">
              <IslandButton type="primary" loading={loading === "background"} onClick={onRun}>{loading === "background" ? "评估中" : "生成背景评估"}</IslandButton>
              <IslandButton type="default" disabled={!assessment || needsDecisionData} loading={loading === "programs"} onClick={onRunPrograms}>{needsDecisionData ? "补齐关键信息后择校" : "按这个背景去择校"}</IslandButton>
            </div>
          </section>
        ) : null}

        <div className="assessment-step-actions">
          <IslandButton type="default" disabled={activeStep === 0} onClick={goPreviousStep}>上一步</IslandButton>
          {activeStep < assessmentSteps.length - 1 ? <IslandButton type="primary" onClick={goNextStep}>下一步</IslandButton> : null}
        </div>
      </IslandCard>

      <div className="page-stack assessment-result-stack">
        <IslandCard className="panel-card">
          <PanelTitle icon={<ShieldCheck size={19} aria-hidden />} title="背景竞争力评估" />
          <section className="status-grid four">
            <Metric label="竞争力等级" value={needsDecisionData ? "信息不足" : assessment?.competitiveness_level ?? "待评估"} detail={assessment?.competitiveness_summary ?? "填写背景后会给出强 / 中强 / 中 / 弱判断。"} />
            <Metric label="硬门槛状态" value={assessment?.qualification_status ?? "待评估"} detail={assessment?.scope_note ?? "语言、专业背景、先修课和预算会单独判断。"} />
            <Metric label="决策信息完整度" value={String(assessment?.decision_field_coverage ?? 0) + "%"} detail="表示自填字段是否齐全，不等于材料已经核验。" />
            <Metric label="材料证据覆盖" value={String(assessment?.evidence_coverage ?? 0) + "%"} detail="成绩单、语言证明和经历材料未核验时不会冒充已确认事实。" />
          </section>
          {assessment && !needsDecisionData ? (
            <div className="assessment-detail-grid">
              <AdviceList title="可申请层级" items={Object.entries(assessment.application_positioning).map(([bandName, detail]) => bandName + ": " + detail)} />
              <AdviceList title="硬门槛" items={assessment.hard_thresholds} />
              <AdviceList title="补强动作" items={assessment.strengthening_actions} />
            </div>
          ) : needsDecisionData ? <div className="assessment-detail-grid"><AdviceList title="暂不分档" items={["关键信息不足时不输出冲刺、主申或相对稳妥结论，避免制造虚假的确定性。"]} /><AdviceList title="先补齐" items={result?.profile?.missing_fields ?? assessment?.actions ?? []} /></div> : null}
        </IslandCard>
        <IslandCard className="panel-card" type="dashed">
          <PanelTitle icon={<ListChecks size={19} aria-hidden />} title="维度结论" />
          <DimensionFindings items={assessment?.dimension_findings ?? []} />
        </IslandCard>
        <IslandCard className="panel-card">
          <PanelTitle icon={<AlertTriangle size={19} aria-hidden />} title="还缺什么" />
          <AdviceList title="信息缺口" items={result?.profile?.missing_fields ?? ["正式成绩单", "核心课程成绩", "语言单项成绩", "实习或项目细节"]} />
          <AdviceList title="下一步动作" items={assessment?.actions ?? []} />
        </IslandCard>
      </div>
    </div>
  );
}

function StepHeader({ title, detail }: { title: string; detail: string }) {
  return <header className="assessment-step-head"><h2>{title}</h2><p>{detail}</p></header>;
}

function SaveStatusBadge({ status }: { status: ProfileSaveStatus }) {
  const label = status === "saving" ? "正在保存到本地档案" : status === "saved" ? "已保存" : status === "error" ? "保存失败" : "本地档案";
  return <span className={"profile-save-badge " + status}><Save size={14} aria-hidden />{label}</span>;
}

function MaterialVerificationPanel({ readyKeys, onToggle }: { readyKeys: string[]; onToggle: (key: string) => void }) {
  return (
    <div className="material-verification-grid">
      {materialStatusItems.map((item) => {
        const ready = readyKeys.includes(materialFlag(item.key));
        return (
          <button className={ready ? "ready" : ""} type="button" key={item.key} onClick={() => onToggle(item.key)}>
            <ClipboardCheck size={18} aria-hidden />
            <span>{ready ? "已记录" : "需补充"}</span>
            <strong>{item.label}</strong>
            <small>{item.detail}</small>
          </button>
        );
      })}
    </div>
  );
}

function ProfileEvidenceEditor({ payload, setRawInterest, patchAdditionalBackground, patchExperience, addExperience }: {
  payload: ApplicantPayload;
  setRawInterest: (value: string) => void;
  patchAdditionalBackground: (patch: Partial<ApplicantPayload["additional_background"]>) => void;
  patchExperience: (index: number, patch: Partial<ApplicantPayload["experiences"][number]>) => void;
  addExperience: () => void;
}) {
  const experiences = payload.experiences.length ? payload.experiences : [emptyExperience()];
  return (
    <section className="profile-evidence-editor assessment-step-panel">
      <StepHeader title="成绩、课程和经历素材" detail="这些信息会直接影响学校层级、硬门槛和专业匹配判断。" />
      <div className="form-grid">
        <label className="wide-field">核心课程 / 先修课<textarea rows={2} value={listValue(payload.additional_background.core_courses) || payload.raw_interest_text} onChange={(event) => { const items = splitList(event.target.value); patchAdditionalBackground({ core_courses: items }); setRawInterest(event.target.value); }} placeholder="例如：数据结构 88，算法 90，数据库 86，机器学习项目..." /></label>
        <label className="wide-field">交换 / 海外经历<textarea rows={2} value={listValue(payload.additional_background.exchange_experiences)} onChange={(event) => patchAdditionalBackground({ exchange_experiences: splitList(event.target.value) })} placeholder="学校、课程、时间、成果。" /></label>
        <label className="wide-field">科研 / 论文 / 报告<textarea rows={2} value={listValue(payload.additional_background.research_outputs)} onChange={(event) => patchAdditionalBackground({ research_outputs: splitList(event.target.value) })} placeholder="课题、导师、论文、报告、方法和结果。" /></label>
        <label className="wide-field">活动 / 领导力<textarea rows={2} value={listValue(payload.additional_background.activities)} onChange={(event) => patchAdditionalBackground({ activities: splitList(event.target.value) })} placeholder="社团、志愿、组织、竞赛团队等。" /></label>
        <label className="wide-field">奖项<textarea rows={2} value={listValue(payload.additional_background.awards)} onChange={(event) => patchAdditionalBackground({ awards: splitList(event.target.value) })} placeholder="奖学金、竞赛、荣誉、排名。" /></label>
        <label className="wide-field">技能<textarea rows={2} value={listValue(payload.additional_background.skills)} onChange={(event) => patchAdditionalBackground({ skills: splitList(event.target.value) })} placeholder="Python, SQL, R, MATLAB, SPSS, Tableau, Figma..." /></label>
      </div>
      <div className="program-title-row compact">
        <strong>经历素材</strong>
        <button className="text-button" type="button" onClick={addExperience}>添加经历</button>
      </div>
      {experiences.map((experience, index) => (
        <article className="experience-row" key={index}>
          <label>类型<select value={experience.type} onChange={(event) => patchExperience(index, { type: event.target.value as ApplicantPayload["experiences"][number]["type"] })}><option value="project">课程/项目</option><option value="research">科研</option><option value="internship">实习</option><option value="work">工作</option><option value="competition">竞赛</option><option value="volunteer">活动</option></select></label>
          <label>名称<input value={experience.title} onChange={(event) => patchExperience(index, { title: event.target.value })} placeholder="例如 智能预测系统" /></label>
          <label>机构/课程<input value={experience.organization} onChange={(event) => patchExperience(index, { organization: event.target.value })} /></label>
          <label>时长(月)<input type="number" value={experience.months} onChange={(event) => patchExperience(index, { months: Number(event.target.value) })} /></label>
          <label className="wide-field">职责<textarea rows={2} value={experience.role} onChange={(event) => patchExperience(index, { role: event.target.value })} placeholder="你负责什么，写了哪些分析、模型或交付物。" /></label>
          <label className="wide-field">技能 / 工具<textarea rows={2} value={experience.tools.join("，")} onChange={(event) => patchExperience(index, { tools: splitList(event.target.value) })} placeholder="Python, SQL, PyTorch, Power BI..." /></label>
          <label className="wide-field">成果 / 证明<textarea rows={2} value={experience.outcomes.join("，")} onChange={(event) => patchExperience(index, { outcomes: splitList(event.target.value) })} placeholder="报告、论文、产品链接、推荐人可证明的事实。" /></label>
        </article>
      ))}
    </section>
  );
}

function DimensionFindings({ items }: { items: DimensionFinding[] }) {
  if (!items.length) return <EmptyState text={assessmentCopy.dimensionEmpty} />;
  return (
    <div className="finding-list">
      {items.map((item) => (
        <article key={item.dimension}>
          <div className="program-title-row"><strong>{item.dimension}</strong><span className="tier-pill">{item.level}</span></div>
          <p>{item.conclusion}</p>
          <div className="fact-grid">
            <Rule text={"依据：" + item.basis} />
            <Rule text={"适用方向：" + (item.applicable_to.join("，") || "未匹配到具体方向")} />
            <Rule text={"不确定项：" + (item.uncertainties.join("，") || "无")} />
            <Rule text={"建议动作：" + (item.actions.join("，") || "无")} />
          </div>
        </article>
      ))}
    </div>
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

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return <div className="panel-title">{icon}<IslandTitle size="small" color="app-yellow">{title}</IslandTitle></div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state"><Sparkles size={18} aria-hidden /><span>{text}</span></div>;
}

function assessmentStepSummary(payload: ApplicantPayload, materialReadyCount: number) {
  return [
    { ready: Boolean(payload.career_goal && payload.discipline_interests.length), detail: payload.discipline_interests.length + " 个方向" },
    { ready: Boolean(payload.education.school && payload.education.major && payload.education.gpa), detail: payload.language.test === "NONE" ? "语言待补" : payload.language.test + " " + (payload.language.overall ?? "") },
    { ready: Boolean(payload.additional_background.core_courses.length || payload.experiences.length), detail: payload.experiences.length + " 段经历" },
    { ready: materialReadyCount > 0, detail: materialReadyCount + "/" + materialStatusItems.length + " 项材料" },
  ];
}

function emptyExperience(): ApplicantPayload["experiences"][number] {
  return { type: "project", title: "", organization: "", months: 0, role: "", outcomes: [], tools: [], evidence_level: "SELF_REPORTED" };
}

function listValue(items: string[]) {
  return items.join("，");
}

function splitList(value: string) {
  return value.split(/[,\uFF0C\u3001;\uFF1B\n]/).map((item) => item.trim()).filter(Boolean);
}
