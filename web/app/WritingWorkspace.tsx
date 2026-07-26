"use client";

import { Button as IslandButton, Card as IslandCard } from "animal-island-ui";
import { ArrowLeft, ArrowRight, CheckCircle2, ClipboardCheck, Copy, Download, FileText, NotebookPen, PlayCircle, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { writingCopy } from "@/lib/copy";
import { documentFlows, fallbackGapQuestions, wizardSteps, type DocumentType, type FlowDefinition } from "./writing/workspaceConfig";
import type { ProgramMatch, QuestionnaireSchema, StoryCard, WorkflowResult, WritingDraftHistoryItem, WritingInterviewQuestion, WritingReviewRubric } from "@/lib/types";

type QuestionnaireValues = Record<string, string>;
type WritingLoading = string | null;
type SchemaSection = QuestionnaireSchema["sections"][number];
type SchemaField = SchemaSection["fields"][number];
type DraftHistoryItem = WritingDraftHistoryItem;
type WritingExportGateState = {
  level: "ready" | "marked" | "blocked";
  title: string;
  summary: string;
  items: string[];
  markdownLabel: string;
  wordLabel: string;
  canDownloadWord: boolean;
};


export function WritingWorkspace({
  schema, values, onChange, selectedProgramIds, recommendations, documentType, setDocumentType, targetProgramId, setTargetProgramId, questions, storyCards, writing, rubric, draftHistory, onDraftHistoryChange, loading, onInterview, onRun,
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
  draftHistory: DraftHistoryItem[];
  onDraftHistoryChange: (history: DraftHistoryItem[]) => void;
  loading: WritingLoading;
  onInterview: () => void;
  onRun: () => void;
}) {
  const [activeStep, setActiveStep] = useState(0);
  const [activeSectionIndex, setActiveSectionIndex] = useState(0);
  const [activeFieldIndex, setActiveFieldIndex] = useState(0);
  const [copyMessage, setCopyMessage] = useState("");
  const [awaitingExport, setAwaitingExport] = useState(false);
  const lastDraftSignatureRef = useRef("");
  const flow = documentFlows[documentType];
  const programOptions = useMemo(() => recommendations.slice(0, 80), [recommendations]);
  const targetProgram = programOptions.find((item) => item.program.id === targetProgramId) ?? programOptions[0] ?? null;
  const sections = useMemo(() => sectionsForFlow(schema, flow), [schema, flow]);
  const activeSection = sections[Math.min(activeSectionIndex, Math.max(sections.length - 1, 0))] ?? null;
  const completion = completionStats(sections, values);
  const activeCompletion = activeSection ? completionStats([activeSection], values) : emptyCompletion();
  const visibleQuestions = questions.length ? questions : fallbackGapQuestions;
  const questionnaireReady = completion.total > 0;
  const canGenerate = Boolean(targetProgram) && completion.total > 0 && completion.requiredMissing === 0;
  const generated = Boolean(writing);

  useEffect(() => {
    if (!programOptions.length) return;
    if (!targetProgramId || !programOptions.some((item) => item.program.id === targetProgramId)) setTargetProgramId(programOptions[0].program.id);
  }, [programOptions, targetProgramId, setTargetProgramId]);

  useEffect(() => {
    if (activeSectionIndex > Math.max(sections.length - 1, 0)) setActiveSectionIndex(0);
  }, [activeSectionIndex, sections.length]);

  useEffect(() => {
    const fieldCount = activeSection?.fields.filter((field) => !field.sensitive).length ?? 0;
    if (activeFieldIndex > Math.max(fieldCount - 1, 0)) setActiveFieldIndex(0);
  }, [activeFieldIndex, activeSection]);

  useEffect(() => {
    if (awaitingExport && writing && loading !== "writing") {
      setActiveStep(3);
      setAwaitingExport(false);
    }
  }, [awaitingExport, writing, loading]);

  useEffect(() => {
    if (!writing) return;
    const signature = [documentType, targetProgram?.program.id ?? "", writing.title, writing.draft_en, writing.draft_zh, writing.fact_bindings.length, writing.material_gaps.length].join("|");
    if (lastDraftSignatureRef.current === signature) return;
    lastDraftSignatureRef.current = signature;
    const item: DraftHistoryItem = {
      id: "draft-" + Date.now().toString(36),
      createdAt: new Date().toISOString(),
      title: cleanTitle(writing.title, documentType),
      documentType,
      targetProgram: targetProgram ? programTitle(targetProgram.program) : "未绑定项目",
      factCount: writing.fact_bindings.length,
      gapCount: cleanMaterialGaps(writing, documentType).length,
      wordCount: countDraftWords(writing),
    };
    onDraftHistoryChange([item, ...draftHistory.filter((draft) => draft.id !== item.id)].slice(0, 6));
  }, [documentType, draftHistory, onDraftHistoryChange, targetProgram, writing]);

  function chooseDocumentType(value: DocumentType) {
    setDocumentType(value);
    setActiveSectionIndex(0);
    setActiveFieldIndex(0);
  }

  function startCollection() {
    if (targetProgram) setTargetProgramId(targetProgram.program.id);
    setActiveSectionIndex(0);
    setActiveFieldIndex(0);
    setActiveStep(1);
  }

  function goNextQuestion() {
    const fields = activeSection?.fields.filter((field) => !field.sensitive) ?? [];
    if (activeFieldIndex < fields.length - 1) {
      setActiveFieldIndex(activeFieldIndex + 1);
      return;
    }
    if (activeSectionIndex < sections.length - 1) {
      setActiveSectionIndex(activeSectionIndex + 1);
      setActiveFieldIndex(0);
      return;
    }
    setActiveStep(2);
  }

  function generateDraft() {
    setAwaitingExport(true);
    onRun();
  }

  async function copyDraft() {
    if (!writing) return;
    await navigator.clipboard.writeText(buildDraftMarkdown(writing, targetProgram, documentType, rubric));
    setCopyMessage("已复制全文");
    window.setTimeout(() => setCopyMessage(""), 1800);
  }

  function downloadMarkdown() {
    if (!writing) return;
    downloadTextFile(downloadBaseName(writing, targetProgram, documentType) + ".md", buildDraftMarkdown(writing, targetProgram, documentType, rubric), "text/markdown;charset=utf-8");
  }

  function downloadWord() {
    if (!writing) return;
    downloadDocxFile(downloadBaseName(writing, targetProgram, documentType) + ".docx", buildDraftMarkdown(writing, targetProgram, documentType, rubric));
  }
  return (
    <div className="writing-workbench page-stack">
      <IslandCard className="writing-workbench-hero" color="app-yellow">
        <div>
          <span className="mini-label"><NotebookPen size={16} aria-hidden /> {writingCopy.title}</span>
          <h2>{targetProgram ? `${programTitle(targetProgram.program)} 文书工作台` : "按项目生成可下载文书初稿"}</h2>
          <p>先选择申请清单里的项目，再按问卷逐页补充素材。完成后生成初稿、素材缺口、故事卡和事实绑定表，可直接下载继续修改。</p>
          <div className="writing-hero-tags" aria-label="文书工作台能力">
            <span>模板化问题</span>
            <span>逐步填写</span>
            <span>事实绑定</span>
            <span>DOCX 下载</span>
          </div>
        </div>
        <ProgressCard completion={completion} ready={questionnaireReady} />
      </IslandCard>

      <section className="writing-flow-shell">
        <aside className="writing-flow-steps" aria-label="文书流程">
          {wizardSteps.map((step, index) => (
            <button className={stepClass(index, activeStep, generated)} key={step.id} type="button" onClick={() => setActiveStep(index)}>
              <span>{index + 1}</span>
              <strong>{step.label}</strong>
              <small>{step.detail}</small>
            </button>
          ))}
        </aside>

        <main className="writing-flow-main">
          {activeStep === 0 ? (
            <SetupStep documentType={documentType} onDocumentType={chooseDocumentType} targetProgramId={targetProgram?.program.id ?? ""} onTargetProgram={setTargetProgramId} programOptions={programOptions} selectedProgramCount={selectedProgramIds.length} questionnaireReady={questionnaireReady} onStart={startCollection} />
          ) : null}
          {activeStep === 1 ? (
            <CollectStep flow={flow} sections={sections} activeSection={activeSection} activeSectionIndex={activeSectionIndex} setActiveSectionIndex={setActiveSectionIndex} activeFieldIndex={activeFieldIndex} setActiveFieldIndex={setActiveFieldIndex} values={values} onChange={onChange} completion={completion} activeCompletion={activeCompletion} onBack={() => setActiveStep(0)} onNext={goNextQuestion} />
          ) : null}
          {activeStep === 2 ? (
            <ReviewStep targetProgram={targetProgram} flow={flow} completion={completion} questions={visibleQuestions} questionSourceReady={questions.length > 0} storyCards={storyCards} writing={writing} loading={loading} canGenerate={canGenerate} onInterview={onInterview} onRun={generateDraft} onBack={() => setActiveStep(1)} onExport={() => setActiveStep(3)} />
          ) : null}
          {activeStep === 3 ? (
            <ExportStep writing={writing} rubric={rubric} storyCards={storyCards} draftHistory={draftHistory} targetProgram={targetProgram} documentType={documentType} copyMessage={copyMessage} onBack={() => setActiveStep(2)} onCopy={copyDraft} onDownloadMarkdown={downloadMarkdown} onDownloadWord={downloadWord} />
          ) : null}
        </main>
      </section>
    </div>
  );
}

function SetupStep({ documentType, onDocumentType, targetProgramId, onTargetProgram, programOptions, selectedProgramCount, questionnaireReady, onStart }: {
  documentType: DocumentType;
  onDocumentType: (value: DocumentType) => void;
  targetProgramId: string;
  onTargetProgram: (value: string) => void;
  programOptions: ProgramMatch[];
  selectedProgramCount: number;
  questionnaireReady: boolean;
  onStart: () => void;
}) {
  const selectedFlow = documentFlows[documentType];
  const selectedProgram = programOptions.find((item) => item.program.id === targetProgramId) ?? programOptions[0] ?? null;
  const hasPrograms = programOptions.length > 0;

  return (
    <section className="writing-step-card">
      <StepHeader
        eyebrow="Step 1"
        title="先选项目，再开始收集素材"
        detail={hasPrograms ? "文书页只使用你在择校页保存的项目。每次围绕一个项目生成一份 PS、SOP、CV、Essay 或推荐信草稿。" : "先到项目库保存申请项目，回到这里后再进入逐页问卷。"}
      />
      {hasPrograms ? (
        <div className="writing-setup-layout">
          <section className="writing-panel writing-primary-panel">
            <PanelHeading label={`已保存 ${selectedProgramCount} 个项目`} title="目标项目" />
            <div className="writing-program-select-stack">
              <label className="writing-select-field">
                <span>申请清单中的项目</span>
                <select value={selectedProgram?.program.id ?? ""} onChange={(event) => onTargetProgram(event.target.value)}>
                  {programOptions.map((item) => <option value={item.program.id} key={item.program.id}>{programTitle(item.program)}</option>)}
                </select>
              </label>
              {selectedProgram ? <TargetProgramSummary match={selectedProgram} /> : null}
            </div>
          </section>

          <section className="writing-panel writing-document-panel">
            <PanelHeading label="文书类型" title="选择本次要生成的文档" />
            <div className="writing-type-segment" role="list" aria-label="文书类型">
              {(Object.entries(documentFlows) as Array<[DocumentType, FlowDefinition]>).map(([value, flow]) => (
                <button className={value === documentType ? "selected" : ""} key={value} type="button" onClick={() => onDocumentType(value)}>
                  <strong>{flow.label}</strong>
                  <span>{flow.shortLabel}</span>
                </button>
              ))}
            </div>
            <WritingMethodPanel flow={selectedFlow} />
          </section>
        </div>
      ) : (
        <div className="writing-no-project-card">
          <EmptyPanel title="还没有可用项目" text="先到项目库把项目加入申请清单，再回到这里开始文书问卷。" action={<a className="text-link" href="/programs">去项目库添加项目</a>} />
        </div>
      )}

      {hasPrograms ? <div className="writing-start-bar">
        <div>
          <strong>{selectedProgram ? programTitle(selectedProgram.program) : "请先选择项目"}</strong>
          <span>{selectedProgram ? `${selectedFlow.label} · ${programMeta(selectedProgram.program)}` : "项目来自你自己保存的清单。"} {!questionnaireReady ? "问卷结构正在读取。" : "点击开始后逐页填写。"}</span>
        </div>
        <IslandButton type="primary" disabled={!selectedProgram || !questionnaireReady} onClick={onStart}>
          <PlayCircle size={17} aria-hidden /> 开始收集素材
        </IslandButton>
      </div> : null}
    </section>
  );
}

function CollectStep({ flow, sections, activeSection, activeSectionIndex, setActiveSectionIndex, activeFieldIndex, setActiveFieldIndex, values, onChange, completion, activeCompletion, onBack, onNext }: {
  flow: FlowDefinition;
  sections: SchemaSection[];
  activeSection: SchemaSection | null;
  activeSectionIndex: number;
  setActiveSectionIndex: (index: number) => void;
  activeFieldIndex: number;
  setActiveFieldIndex: (index: number) => void;
  values: QuestionnaireValues;
  onChange: (fieldId: string, value: string) => void;
  completion: ReturnType<typeof completionStats>;
  activeCompletion: ReturnType<typeof completionStats>;
  onBack: () => void;
  onNext: () => void;
}) {
  const visibleFields = activeSection?.fields.filter((field) => !field.sensitive) ?? [];
  const fieldIndex = Math.min(activeFieldIndex, Math.max(visibleFields.length - 1, 0));
  const activeField = visibleFields[fieldIndex] ?? null;
  const activeFieldValue = activeField ? String(values[activeField.id] ?? "").trim() : "";
  const currentQuestionReady = !activeField || !activeField.required || Boolean(activeFieldValue);
  const isLastQuestionInSection = fieldIndex >= visibleFields.length - 1;
  const atLastSection = activeSectionIndex >= sections.length - 1;
  const atLastQuestion = atLastSection && isLastQuestionInSection;
  const previousQuestionCount = sections.slice(0, activeSectionIndex).reduce((sum, section) => sum + section.fields.filter((field) => !field.sensitive).length, 0);
  const totalQuestionCount = sections.reduce((sum, section) => sum + section.fields.filter((field) => !field.sensitive).length, 0);
  const currentQuestionNumber = Math.min(previousQuestionCount + fieldIndex + 1, Math.max(totalQuestionCount, 1));
  const questionPercent = Math.round((currentQuestionNumber / Math.max(totalQuestionCount, 1)) * 100);

  function goBackOneStep() {
    if (fieldIndex > 0) {
      setActiveFieldIndex(fieldIndex - 1);
      return;
    }
    if (activeSectionIndex > 0) {
      const previousSection = sections[activeSectionIndex - 1];
      const previousFields = previousSection?.fields.filter((field) => !field.sensitive) ?? [];
      setActiveSectionIndex(activeSectionIndex - 1);
      setActiveFieldIndex(Math.max(previousFields.length - 1, 0));
      return;
    }
    onBack();
  }

  return (
    <section className="writing-step-card writing-questionnaire-step">
      <StepHeader eyebrow="Step 2" title="逐页填写素材问卷" detail="每一页只处理一组问题。填完必填项后再进入下一页，页面不会一次性展开整张长表。" />
      <div className="writing-questionnaire-shell">
        <div className="writing-section-progress">
          <div>
            <span>第 {Math.min(activeSectionIndex + 1, Math.max(sections.length, 1))} / {Math.max(sections.length, 1)} 组</span>
            <strong>{activeSection ? shortSectionTitle(activeSection.title) : flow.label}</strong>
          </div>
          <div className="progress-track static" aria-label="问卷进度"><span style={{ width: `${questionPercent}%` }} /></div>
        </div>

        <div className="writing-section-tabs" aria-label="问卷分区">
          {sections.map((section, index) => {
            const stats = completionStats([section], values);
            const state = index === activeSectionIndex ? "active" : stats.requiredMissing === 0 && stats.filled > 0 ? "done" : "";
            return (
              <button className={state} key={section.id} type="button" onClick={() => { setActiveSectionIndex(index); setActiveFieldIndex(0); }} aria-current={index === activeSectionIndex ? "step" : undefined}>
                <span>{index + 1}</span>
                <strong>{shortSectionTitle(section.title)}</strong>
                <small>{stats.filled}/{stats.total}</small>
              </button>
            );
          })}
        </div>

        <div className="writing-question-card writing-form-paper">
          {activeSection ? (
            <>
              <div className="writing-question-head">
                <div>
                  <span className="mini-label">问题参考：{activeSection.source_template || flow.templateBasis}</span>
                  <h3>{activeSection.title}</h3>
                  <p>{activeSection.description}</p>
                </div>
                <div className="writing-mini-progress"><strong>{activeCompletion.percent}%</strong><span>{activeCompletion.filled}/{activeCompletion.total}</span></div>
              </div>
              <div className="writing-questionnaire-note">
                <strong>{flow.shortLabel} - {currentQuestionNumber}/{Math.max(totalQuestionCount, 1)}</strong>
                <span>{activeField?.help || flow.writingMethod}</span>
              </div>
              <div className="writing-field-list writing-one-question">
                {activeField ? <QuestionField key={activeField.id} field={activeField} value={values[activeField.id] ?? ""} onChange={(value) => onChange(activeField.id, value)} /> : null}
              </div>
            </>
          ) : (
            <EmptyPanel title="问卷结构正在读取" text="请确认本地后端服务已启动，页面会读取模板化问题。" />
          )}

          <div className="writing-form-actions writing-form-actions-sticky">
            <IslandButton type="default" onClick={goBackOneStep}><ArrowLeft size={17} aria-hidden /> {fieldIndex > 0 || activeSectionIndex > 0 ? "上一题" : "返回选择"}</IslandButton>
            <div>
              <span className={currentQuestionReady ? "writing-ready-note ready" : "writing-ready-note"}>{currentQuestionReady ? (atLastQuestion ? "可以进入生成前检查" : "可以进入下一题") : "这题为必填，请先补充"}</span>
              <IslandButton type="primary" disabled={!currentQuestionReady || !activeField} onClick={onNext}>{atLastQuestion ? "进入生成前检查" : isLastQuestionInSection ? "下一组" : "下一题"} <ArrowRight size={17} aria-hidden /></IslandButton>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
function ReviewStep({ targetProgram, flow, completion, questions, questionSourceReady, storyCards, writing, loading, canGenerate, onInterview, onRun, onBack, onExport }: {
  targetProgram: ProgramMatch | null;
  flow: FlowDefinition;
  completion: ReturnType<typeof completionStats>;
  questions: WritingInterviewQuestion[];
  questionSourceReady: boolean;
  storyCards: StoryCard[];
  writing?: WorkflowResult["writing"];
  loading: WritingLoading;
  canGenerate: boolean;
  onInterview: () => void;
  onRun: () => void;
  onBack: () => void;
  onExport: () => void;
}) {
  const statusItems = [
    { ok: Boolean(targetProgram), title: "目标项目", text: targetProgram ? programTitle(targetProgram.program) : "请选择一个已保存项目。" },
    { ok: completion.requiredMissing === 0, title: "必填素材", text: completion.requiredMissing === 0 ? "必填问题已完成。" : `还差 ${completion.requiredMissing} 个必填问题。` },
    { ok: completion.filled > 0, title: "素材数量", text: `${completion.filled}/${completion.total} 个问题已有内容。` },
  ];

  return (
    <section className="writing-step-card writing-generate-step">
      <StepHeader eyebrow="Step 3" title="确认素材后生成初稿" detail="写作助手只基于问卷、学生背景和项目官方来源生成。缺少事实时列缺口，不用顺滑文字补事实。" />
      <div className="writing-generate-layout">
        <section className="writing-generate-summary">
          <PanelHeading label="本次生成" title={targetProgram ? programTitle(targetProgram.program) : "尚未选择项目"} />
          {targetProgram ? <TargetProgramSummary match={targetProgram} /> : <EmptyPanel title="没有目标项目" text="返回第一步选择一个已保存项目。" />}
          <div className="writing-review-status-list">
            {statusItems.map((item) => <CheckBlock key={item.title} ok={item.ok} title={item.title} text={item.text} />)}
          </div>
          <WritingBoundarySummary flow={flow} />
        </section>

        <section className="writing-material-questions">
          <PanelHeading label={writingCopy.materialQuestions} title="生成前建议补充" />
          <div className="writing-gap-list">
            {questions.slice(0, 5).map((item, index) => (
              <article key={item.id}>
                <span>{index + 1}</span>
                <div>
                  <strong>{item.question}</strong>
                  <p>{item.why_it_matters}</p>
                  <small>{item.target_section}{item.required ? " · 建议补充" : ""}</small>
                </div>
              </article>
            ))}
          </div>
          <div className="writing-panel-actions">
            <IslandButton type="default" disabled={loading === "interview"} onClick={onInterview}><ClipboardCheck size={17} aria-hidden /> {loading === "interview" ? "正在整理问题" : writingCopy.materialQuestions}</IslandButton>
            <span>{questionSourceReady ? "已按当前项目整理" : writingCopy.interviewEmpty}</span>
          </div>
        </section>
      </div>

      {storyCards.length ? <StoryPreview cards={storyCards} /> : null}

      <div className="writing-form-actions writing-generate-actions">
        <IslandButton type="default" onClick={onBack}><ArrowLeft size={17} aria-hidden /> 回到问卷</IslandButton>
        <div>
          {writing ? <IslandButton type="default" onClick={onExport}>查看已生成初稿</IslandButton> : null}
          <IslandButton type="primary" disabled={!canGenerate || loading === "writing"} onClick={onRun}><FileText size={17} aria-hidden /> {loading === "writing" ? "正在生成初稿" : "生成可下载初稿"}</IslandButton>
        </div>
      </div>
    </section>
  );
}
function ExportStep({ writing, rubric, storyCards, draftHistory, targetProgram, documentType, copyMessage, onBack, onCopy, onDownloadMarkdown, onDownloadWord }: {
  writing?: WorkflowResult["writing"];
  rubric: WritingReviewRubric | null;
  storyCards: StoryCard[];
  draftHistory: DraftHistoryItem[];
  targetProgram: ProgramMatch | null;
  documentType: DocumentType;
  copyMessage: string;
  onBack: () => void;
  onCopy: () => void;
  onDownloadMarkdown: () => void;
  onDownloadWord: () => void;
}) {
  if (!writing) {
    return (
      <section className="writing-step-card">
        <StepHeader eyebrow="Step 4" title="还没有文档初稿" detail="先完成问卷并生成初稿，下载区会在这里显示。" />
        <EmptyPanel title="等待生成" text={writingCopy.paragraphDraftEmpty} />
        <div className="writing-form-actions"><IslandButton type="default" onClick={onBack}><ArrowLeft size={17} aria-hidden /> 回到检查</IslandButton></div>
      </section>
    );
  }

  const exportGate = writingExportGate(writing, rubric, targetProgram, documentType);
  const markdown = buildDraftMarkdown(writing, targetProgram, documentType, rubric);
  const checklist = cleanMaterialGaps(writing, documentType);
  const bindingItems = factBindingItems(writing);
  const materialItems = studentMaterialItems(writing, documentType);

  return (
    <section className="writing-step-card">
      <StepHeader eyebrow="Step 4" title="文档初稿已生成" detail={exportGate.summary} />
      <WritingExportGate gate={exportGate} />
      <div className="writing-download-card">
        <div>
          <strong>{cleanTitle(writing.title, documentType)}</strong>
          <span>{targetProgram ? programTitle(targetProgram.program) : "未绑定项目"} · {documentFlows[documentType].label}</span>
        </div>
        <div className="writing-download-actions">
          <button type="button" onClick={onCopy}><Copy size={16} aria-hidden /> {copyMessage || "复制全文"}</button>
          <button type="button" onClick={onDownloadMarkdown}><Download size={16} aria-hidden /> {exportGate.markdownLabel}</button>
          <button type="button" disabled={!exportGate.canDownloadWord} title={exportGate.canDownloadWord ? undefined : "先补齐来源和事实绑定后再导出 Word"} onClick={onDownloadWord}><Download size={16} aria-hidden /> {exportGate.wordLabel}</button>
        </div>
      </div>

      <DraftVersionPanel history={draftHistory} currentTitle={cleanTitle(writing.title, documentType)} />
      <FactLockSummary writing={writing} rubric={rubric} bindingItems={bindingItems} />

      <div className="writing-output-layout">
        <article className="writing-draft-paper">
          <h3>{primaryDraftTitle(documentType)}</h3>
          {paragraphs(writing.draft_en || writing.draft || markdown).map((paragraph, index) => <p key={String(index) + paragraph.slice(0, 12)}>{paragraph}</p>)}
          {writing.draft_zh ? (
            <section>
              <h3>{secondaryDraftTitle(documentType)}</h3>
              {paragraphs(writing.draft_zh).map((paragraph, index) => <p key={"zh-" + String(index) + paragraph.slice(0, 12)}>{paragraph}</p>)}
            </section>
          ) : null}
        </article>

        <aside className="writing-output-side">
          <OutputList title={documentType === "REFERENCE_PACKAGE" ? "推荐人确认清单" : writingCopy.materialGaps} items={checklist} empty={writingCopy.materialGapEmpty} />
          <OutputList title={writingCopy.outline} items={writing.outline} empty={writingCopy.factBindingEmpty} />
          <OutputList title={writingCopy.factBinding} items={bindingItems} empty={writingCopy.factBindingEmpty} />
          <OutputList title={writingCopy.boundaryControls} items={writing.risk_controls.slice(0, 6)} empty="没有额外边界提示。" />
          <OutputList title={documentType === "REFERENCE_PACKAGE" ? "可用推荐素材" : writingCopy.storyCards} items={materialItems} empty={writingCopy.storyCardEmpty} />
        </aside>
      </div>

      {storyCards.length ? <StoryPreview cards={storyCards} compact /> : null}
      <div className="writing-form-actions"><IslandButton type="default" onClick={onBack}><ArrowLeft size={17} aria-hidden /> 回到检查</IslandButton></div>
    </section>
  );
}

function WritingExportGate({ gate }: { gate: WritingExportGateState }) {
  const Icon = gate.level === "ready" ? CheckCircle2 : gate.level === "marked" ? ClipboardCheck : ShieldCheck;
  return (
    <section className={`writing-export-gate ${gate.level}`} aria-label="下载前复核">
      <div>
        <Icon size={18} aria-hidden />
        <strong>{gate.title}</strong>
        <span>{gate.summary}</span>
      </div>
      <ul>
        {gate.items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function DraftVersionPanel({ history, currentTitle }: { history: DraftHistoryItem[]; currentTitle: string }) {
  if (!history.length) return null;
  return <section className="writing-version-panel" aria-label="文书版本历史">
    <div><strong>版本历史</strong><span>当前草稿：{currentTitle}</span></div>
    <div className="writing-version-list">{history.map((item, index) => <article className={index === 0 ? "active" : ""} key={item.id}>
      <span>{index === 0 ? "当前版本" : "历史版本"}</span>
      <strong>{item.title}</strong>
      <small>{formatDraftTime(item.createdAt)} ? {item.targetProgram}</small>
      <p>{item.wordCount} words ? 事实 {item.factCount} 条 ? 缺口 {item.gapCount} 条</p>
    </article>)}</div>
  </section>;
}

function FactLockSummary({ writing, rubric, bindingItems }: { writing: WorkflowResult["writing"]; rubric: WritingReviewRubric | null; bindingItems: string[] }) {
  const unsupported = rubric?.unsupported_claims ?? 0;
  const locked = bindingItems.length;
  const controls = writing.risk_controls.length;
  return <section className="writing-fact-lock-panel" aria-label="事实锁定表">
    <div><ShieldCheck size={18} aria-hidden /><strong>事实锁定</strong><span>{locked} 条确认绑定，{unsupported} 条待核对陈述</span></div>
    <p>草稿只能使用问卷、故事卡和项目来源中可追溯的事实。学校定制句必须绑定项目官网、申请系统或官方 PDF；缺少来源时保留为素材缺口，不写成确定结论。</p>
    <div><span>事实绑定 {locked}</span><span>边界提示 {controls}</span><span>待核对 {unsupported}</span></div>
  </section>;
}

function ProgressCard({ completion, ready }: { completion: ReturnType<typeof completionStats>; ready: boolean }) {
  return (
    <div className="writing-progress-card">
      <strong>{ready ? `${completion.percent}%` : "读取中"}</strong>
      <span>{ready ? "已有素材覆盖度" : writingCopy.loadingSchema}</span>
      <div className="progress-track static"><span style={{ width: `${completion.percent}%` }} /></div>
      <small>{ready ? `${completion.filled}/${completion.total} 已填，${completion.requiredMissing} 个必填缺口` : "问题结构来自三份模板文件"}</small>
    </div>
  );
}

function StepHeader({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <header className="writing-step-header"><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{detail}</p></header>;
}

function PanelHeading({ label, title }: { label: string; title: string }) {
  return <div className="writing-panel-heading"><span className="mini-label">{label}</span><h3>{title}</h3></div>;
}

function WritingMethodPanel({ flow }: { flow: FlowDefinition }) {
  const items = [
    { label: "问题来源", text: flow.templateBasis },
    { label: "写作方法", text: flow.writingMethod },
    { label: "生成边界", text: flow.agentBoundary },
    { label: "输出内容", text: flow.outputHint },
  ];
  return (
    <section className="writing-method-panel" aria-label={`${flow.label} 写作方法`}>
      <strong>{flow.label}</strong>
      <p>{flow.studentGoal}</p>
      <div>
        {items.map((item) => (
          <article key={item.label}>
            <span>{item.label}</span>
            <small>{item.text}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function QuestionField({ field, value, onChange }: { field: SchemaField; value: string; onChange: (value: string) => void }) {
  const label = <span className="question-label"><b>{field.label}</b><em>{field.required ? "必填" : "选填"}</em></span>;
  if (field.type === "textarea") {
    return <label className="writing-question-field">{label}<textarea value={value} rows={6} onChange={(event) => onChange(event.target.value)} placeholder={field.placeholder ?? "按真实经历填写；不适用可以留空。"} />{field.help ? <small>{field.help}</small> : null}</label>;
  }
  if (field.type === "select") {
    return <label className="writing-question-field">{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">请选择</option>{(field.options ?? []).map((option) => <option value={option} key={option}>{option}</option>)}</select>{field.help ? <small>{field.help}</small> : null}</label>;
  }
  return <label className="writing-question-field">{label}<input type={field.type === "date" ? "date" : "text"} value={value} onChange={(event) => onChange(event.target.value)} placeholder={field.placeholder ?? "填写真实信息"} />{field.help ? <small>{field.help}</small> : null}</label>;
}

function WritingBoundarySummary({ flow }: { flow: FlowDefinition }) {
  return (
    <section className="writing-boundary-card">
      <div><ShieldCheck size={18} aria-hidden /><strong>{flow.label} 生成边界</strong></div>
      <ul>
        <li><b>问题参考</b><span>{flow.templateBasis}</span></li>
        <li><b>写作方式</b><span>{flow.writingMethod}</span></li>
        <li><b>事实边界</b><span>{flow.agentBoundary}</span></li>
      </ul>
    </section>
  );
}
function TargetProgramSummary({ match }: { match: ProgramMatch }) {
  const program = match.program;
  const trust = program.trust_detail;
  const sourceLabel = trust?.production_ready ? "当前季官网字段已核验" : trust?.reference_ready ? "仅有往届官方参考" : "项目官网信息待核验";
  return <div className="writing-target-summary"><span>{tierLabel(match.tier)}</span><strong>{program.institution_zh || program.institution}</strong><p>{program.name_zh || program.name}</p><small>{programMeta(program)}</small><small>{sourceLabel}；未核验的项目特色不会写成确定事实。</small>{program.official_program_url ? <a className="text-link" href={program.official_program_url} target="_blank" rel="noreferrer">核对项目官网</a> : null}</div>;
}

function CheckBlock({ ok, title, text }: { ok: boolean; title: string; text: string }) {
  return <article className={ok ? "ready" : ""}><CheckCircle2 size={17} aria-hidden /><strong>{title}</strong><p>{text}</p></article>;
}

function StoryPreview({ cards, compact = false }: { cards: StoryCard[]; compact?: boolean }) {
  return (
    <section className={compact ? "writing-story-preview compact" : "writing-story-preview"}>
      <h3>本次使用的素材卡</h3>
      <div>{cards.slice(0, 6).map((card) => <article key={card.id}><strong>{card.title}</strong><span>{card.completeness}%</span><p>{card.result || card.action || card.situation || "还需要补充事实。"}</p></article>)}</div>
    </section>
  );
}

function OutputList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return <section className="writing-output-list"><h3>{title}</h3>{items.length ? items.slice(0, 8).map((item) => <p key={item}><CheckCircle2 size={14} aria-hidden /> <span>{item}</span></p>) : <p className="writing-muted">{empty}</p>}</section>;
}

function EmptyPanel({ title, text, action }: { title: string; text: string; action?: ReactNode }) {
  return <div className="writing-empty-panel"><FileText size={20} aria-hidden /><strong>{title}</strong><p>{text}</p>{action}</div>;
}
function sectionsForFlow(schema: QuestionnaireSchema | null, flow: FlowDefinition): SchemaSection[] {
  const byId = new Map((schema?.sections ?? []).map((section) => [section.id, section]));
  return flow.sections.map((id) => byId.get(id)).filter((section): section is SchemaSection => Boolean(section));
}

function completionStats(sections: SchemaSection[], values: QuestionnaireValues) {
  const fields = sections.flatMap((section) => section.fields.filter((field) => !field.sensitive));
  const filled = fields.filter((field) => String(values[field.id] ?? "").trim()).length;
  const requiredMissing = fields.filter((field) => field.required && !String(values[field.id] ?? "").trim()).length;
  return { filled, total: fields.length, requiredMissing, percent: Math.round((filled / Math.max(fields.length, 1)) * 100) };
}

function emptyCompletion() {
  return { filled: 0, total: 0, requiredMissing: 0, percent: 0 };
}

function stepClass(index: number, activeStep: number, generated: boolean) {
  if (index === activeStep) return "active";
  if (index < activeStep || (index === 3 && generated)) return "done";
  return "";
}

function shortSectionTitle(title: string) {
  return title.replace(/^PS：/, "").replace(/^CV：/, "").replace(/^推荐信：/, "");
}

function programTitle(program: ProgramMatch["program"]) {
  const school = program.institution_zh || program.institution || "学校";
  const name = program.name_zh || program.name || "项目";
  return `${school} · ${name}`;
}

function programMeta(program: ProgramMatch["program"]) {
  return [program.school_zh || program.school, program.country === "HK" ? "香港" : "新加坡", program.degree_type === "research_master" ? "研究型硕士" : "授课型硕士"].filter(Boolean).join(" · ");
}

function tierLabel(tier: ProgramMatch["tier"]) {
  return ({ reach: "冲刺", target: "主申", safe: "保底", candidate: "候选", not_recommended: "不建议" } as Record<ProgramMatch["tier"], string>)[tier] ?? tier;
}

function writingExportGate(writing: WorkflowResult["writing"], rubric: WritingReviewRubric | null, targetProgram: ProgramMatch | null, documentType: DocumentType): WritingExportGateState {
  const trust = targetProgram?.program.trust_detail;
  const production_ready = trust?.production_ready === true;
  const reference_ready = trust?.reference_ready === true;
  const unsupportedClaims = rubric?.unsupported_claims ?? 0;
  const materialGapCount = cleanMaterialGaps(writing, documentType).length;
  const projectSourceMissing = !targetProgram || (!production_ready && !reference_ready);
  const englishNeedsRevision = writing.draft_en.includes("[English revision required");
  const cycleLabel = trust?.cycle || targetProgram?.program.cycle || "上一申请季";
  const items: string[] = [];

  if (production_ready) items.push("项目来源：当前季官方信息已进入写作复核范围。");
  else if (reference_ready) items.push("项目来源：" + cycleLabel + " 往届参考，提交前需要核对当前季官网。");
  else items.push("项目来源：缺少可用于学校定制句的官方或往届来源，不能作为最终稿。");

  if (unsupportedClaims > 0) items.push("事实绑定：" + unsupportedClaims + " 处学校定制句或结论缺少来源绑定。");
  else items.push("事实绑定：未发现未绑定来源的学校定制句。");

  if (materialGapCount > 0) items.push("素材缺口：还有 " + materialGapCount + " 项需要学生或推荐人补充。");
  else items.push("素材缺口：当前问卷素材足够生成可编辑初稿。");
  if (englishNeedsRevision) items.push("英文状态：中文事实尚未完成英文翻译和润色，不能导出为可提交 Word。");

  if (documentType === "REFERENCE_PACKAGE") items.push("推荐信材料包必须由推荐人确认事实、语气和签名信息后提交。");

  if (projectSourceMissing || unsupportedClaims > 0 || englishNeedsRevision) {
    return {
      level: "blocked",
      title: "不能作为最终稿",
      summary: "可以复制或下载带复核标记的 Markdown 继续修改；Word 导出已暂停，避免误交。",
      items,
      markdownLabel: "下载带复核标记 Markdown",
      wordLabel: "Word 暂停导出",
      canDownloadWord: false,
    };
  }

  if (reference_ready || materialGapCount > 0 || documentType === "REFERENCE_PACKAGE") {
    return {
      level: "marked",
      title: "带复核标记下载",
      summary: "草稿可下载编辑，但文件会保留来源季节、素材缺口和人工复核提醒。",
      items,
      markdownLabel: "下载带复核标记 Markdown",
      wordLabel: "下载带复核标记 Word",
      canDownloadWord: true,
    };
  }

  return {
    level: "ready",
    title: "可下载初稿",
    summary: "当前项目来源与事实绑定满足初稿导出要求，提交前仍需人工润色。",
    items,
    markdownLabel: "下载 Markdown",
    wordLabel: "下载 Word 文档",
    canDownloadWord: true,
  };
}


function buildDraftMarkdown(writing: WorkflowResult["writing"], targetProgram: ProgramMatch | null, documentType: DocumentType, rubric: WritingReviewRubric | null = null) {
  const lines = [
    "# " + cleanTitle(writing.title, documentType),
    "",
    "文书类型：" + documentFlows[documentType].label,
    "目标项目：" + (targetProgram ? programTitle(targetProgram.program) : "未选择"),
    "",
    "## 下载前复核",
    "- 导出状态：" + writingExportGate(writing, rubric, targetProgram, documentType).title,
    ...writingExportGate(writing, rubric, targetProgram, documentType).items.map((item) => "- " + item),
    "",
    documentType === "REFERENCE_PACKAGE" ? "## 推荐人确认清单" : "## 素材缺口",
    ...listLines(cleanMaterialGaps(writing, documentType)),
    "",
    "## 文档结构",
    ...listLines(writing.outline),
    "",
    "## " + primaryDraftTitle(documentType),
    writing.draft_en || writing.draft || "",
    "",
    "## " + secondaryDraftTitle(documentType),
    writing.draft_zh || "暂无中文说明。",
    "",
    "## 段落草稿",
    ...listLines(writing.paragraph_drafts),
    "",
    "## 事实绑定表",
    ...listLines(factBindingItems(writing)),
  ];
  const materials = studentMaterialItems(writing, documentType);
  if (materials.length) lines.push("", documentType === "REFERENCE_PACKAGE" ? "## 可用推荐素材" : "## 可用素材", ...listLines(materials));
  if (writing.risk_controls.length) lines.push("", "## 写作边界", ...listLines(writing.risk_controls));
  return lines.join("\n");
}

function factBindingItems(writing: WorkflowResult["writing"]) {
  return writing.fact_bindings.map((item) => `${item.claim} -> ${item.fact_id}`).slice(0, 10);
}

function countDraftWords(writing: WorkflowResult["writing"]) {
  const text = [writing.draft_en, writing.draft_zh, writing.draft, ...writing.paragraph_drafts].filter(Boolean).join(" ");
  const englishWords = text.match(/[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*/g)?.length ?? 0;
  const chineseChars = text.match(/[一-鿿]/g)?.length ?? 0;
  return englishWords + Math.ceil(chineseChars / 2);
}

function formatDraftTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function listLines(items: string[]) {
  return items.length ? items.map((item) => `- ${item}`) : ["- 暂无"];
}

function downloadTextFile(filename: string, content: string, type: string) {
  downloadBlobFile(filename, new Blob([content], { type }));
}

type ZipEntry = { path: string; data: Uint8Array };

function downloadDocxFile(filename: string, markdown: string) {
  const encoder = new TextEncoder();
  const files: ZipEntry[] = [
    { path: "[Content_Types].xml", data: encoder.encode(docxContentTypesXml()) },
    { path: "_rels/.rels", data: encoder.encode(docxRootRelsXml()) },
    { path: "docProps/core.xml", data: encoder.encode(docxCoreXml()) },
    { path: "docProps/app.xml", data: encoder.encode(docxAppXml()) },
    { path: "word/document.xml", data: encoder.encode(buildDocxDocumentXml(markdown)) },
  ];
  downloadBlobFile(filename, new Blob([buildStoredZip(files)], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
}

function docxContentTypesXml() {
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>' +
    '</Types>';
}

function docxRootRelsXml() {
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>' +
    '</Relationships>';
}

function docxCoreXml() {
  const now = new Date().toISOString();
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
    '<dc:title>HarborPilot Writing Draft</dc:title>' +
    '<dc:creator>HarborPilot</dc:creator>' +
    `<dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>` +
    `<dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>` +
    '</cp:coreProperties>';
}

function docxAppXml() {
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' +
    '<Application>HarborPilot</Application>' +
    '</Properties>';
}

function buildDocxDocumentXml(markdown: string) {
  const body = markdown.split(/\r?\n/).map((rawLine) => {
    const line = rawLine.trim();
    if (!line) return '<w:p/>';
    if (line.startsWith('# ')) return docxParagraph(line.slice(2), 'title');
    if (line.startsWith('## ')) return docxParagraph(line.slice(3), 'heading');
    if (line.startsWith('- ')) return docxParagraph(line.slice(2), 'list');
    return docxParagraph(line, 'body');
  }).join('');
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    `<w:body>${body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body>` +
    '</w:document>';
}

function docxParagraph(text: string, kind: 'title' | 'heading' | 'list' | 'body') {
  const paragraphProps = {
    title: '<w:pPr><w:spacing w:before="120" w:after="240"/></w:pPr>',
    heading: '<w:pPr><w:spacing w:before="280" w:after="120"/></w:pPr>',
    list: '<w:pPr><w:spacing w:after="80"/><w:ind w:left="420"/></w:pPr>',
    body: '<w:pPr><w:spacing w:after="120"/></w:pPr>',
  }[kind];
  const runProps = {
    title: '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:b/><w:sz w:val="32"/></w:rPr>',
    heading: '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:b/><w:sz w:val="24"/></w:rPr>',
    list: '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr>',
    body: '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr>',
  }[kind];
  return `<w:p>${paragraphProps}<w:r>${runProps}<w:t>${escapeXml(text)}</w:t></w:r></w:p>`;
}

let docxCrcTable: Uint32Array | null = null;

function buildStoredZip(files: ZipEntry[]) {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;

  files.forEach((file) => {
    const name = encoder.encode(file.path);
    const crc = crc32(file.data);
    const local = new Uint8Array(30 + name.length + file.data.length);
    writeUint32(local, 0, 0x04034b50);
    writeUint16(local, 4, 20);
    writeUint16(local, 6, 0);
    writeUint16(local, 8, 0);
    writeUint16(local, 10, 0);
    writeUint16(local, 12, 0);
    writeUint32(local, 14, crc);
    writeUint32(local, 18, file.data.length);
    writeUint32(local, 22, file.data.length);
    writeUint16(local, 26, name.length);
    writeUint16(local, 28, 0);
    local.set(name, 30);
    local.set(file.data, 30 + name.length);
    localParts.push(local);

    const central = new Uint8Array(46 + name.length);
    writeUint32(central, 0, 0x02014b50);
    writeUint16(central, 4, 20);
    writeUint16(central, 6, 20);
    writeUint16(central, 8, 0);
    writeUint16(central, 10, 0);
    writeUint16(central, 12, 0);
    writeUint16(central, 14, 0);
    writeUint32(central, 16, crc);
    writeUint32(central, 20, file.data.length);
    writeUint32(central, 24, file.data.length);
    writeUint16(central, 28, name.length);
    writeUint16(central, 30, 0);
    writeUint16(central, 32, 0);
    writeUint16(central, 34, 0);
    writeUint16(central, 36, 0);
    writeUint32(central, 38, 0);
    writeUint32(central, 42, offset);
    central.set(name, 46);
    centralParts.push(central);

    offset += local.length;
  });

  const centralStart = offset;
  const centralSize = centralParts.reduce((sum, item) => sum + item.length, 0);
  const end = new Uint8Array(22);
  writeUint32(end, 0, 0x06054b50);
  writeUint16(end, 4, 0);
  writeUint16(end, 6, 0);
  writeUint16(end, 8, files.length);
  writeUint16(end, 10, files.length);
  writeUint32(end, 12, centralSize);
  writeUint32(end, 16, centralStart);
  writeUint16(end, 20, 0);

  return concatBytes([...localParts, ...centralParts, end]);
}

function crc32(bytes: Uint8Array) {
  if (!docxCrcTable) {
    docxCrcTable = new Uint32Array(256);
    for (let index = 0; index < 256; index += 1) {
      let value = index;
      for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      docxCrcTable[index] = value >>> 0;
    }
  }
  let crc = 0xffffffff;
  bytes.forEach((byte) => {
    crc = (crc >>> 8) ^ docxCrcTable![(crc ^ byte) & 0xff];
  });
  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint16(target: Uint8Array, offset: number, value: number) {
  target[offset] = value & 0xff;
  target[offset + 1] = (value >>> 8) & 0xff;
}

function writeUint32(target: Uint8Array, offset: number, value: number) {
  target[offset] = value & 0xff;
  target[offset + 1] = (value >>> 8) & 0xff;
  target[offset + 2] = (value >>> 16) & 0xff;
  target[offset + 3] = (value >>> 24) & 0xff;
}

function concatBytes(parts: Uint8Array[]) {
  const output = new Uint8Array(parts.reduce((sum, item) => sum + item.length, 0));
  let offset = 0;
  parts.forEach((part) => {
    output.set(part, offset);
    offset += part.length;
  });
  return output;
}

function escapeXml(value: string) {
  return value.replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char] ?? char));
}
function downloadBlobFile(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function cleanTitle(title: string, documentType: DocumentType) {
  if (documentType === "REFERENCE_PACKAGE") return title.replace("REFERENCE_PACKAGE", "推荐信").replace("素材包", "草稿");
  return title.replace("REFERENCE_PACKAGE", "推荐信");
}

function primaryDraftTitle(documentType: DocumentType) {
  if (documentType === "REFERENCE_PACKAGE") return "英文推荐信草稿";
  if (documentType === "CV") return "英文 CV 草稿";
  return "英文草稿";
}

function secondaryDraftTitle(documentType: DocumentType) {
  if (documentType === "REFERENCE_PACKAGE") return "中文推荐信说明";
  if (documentType === "CV") return "中文 CV 素材";
  return "中文逻辑稿";
}

function exportStatusText(rubric: WritingReviewRubric | null, documentType: DocumentType) {
  if (documentType === "REFERENCE_PACKAGE") return "推荐信草稿已生成。请推荐人确认事实、语气和签名信息后再提交。";
  if (!rubric) return "草稿已生成，提交前请逐句核对事实。";
  return rubric.unsupported_claims > 0 ? "草稿已生成，个别学校定制句提交前需要补来源。" : "草稿已生成，提交前请人工润色并核对事实。";
}

function cleanMaterialGaps(writing: WorkflowResult["writing"], documentType: DocumentType) {
  const blocked = ["真实模型调用失败", "已移除", "数据状态"];
  const internalTokens = ["reviewagent", "data_status", "official_"];
  const items = writing.material_gaps.filter((item) => {
    const lower = item.toLowerCase();
    return !blocked.some((word) => item.includes(word)) && !internalTokens.some((word) => lower.includes(word));
  });
  if (documentType === "REFERENCE_PACKAGE") return items.length ? items : ["请推荐人确认所有课程、项目、评价和签名信息后再提交。"];
  return items;
}

function studentMaterialItems(writing: WorkflowResult["writing"], documentType: DocumentType) {
  if (documentType === "CV") return writing.cv_bullets.map(friendlyMaterialText).slice(0, 8);
  if (documentType === "REFERENCE_PACKAGE") return writing.reference_package.map(friendlyMaterialText).slice(0, 8);
  return writing.school_customization.filter((item) => item.includes("http") || item.includes("项目") || item.includes("学校")).map(friendlyMaterialText).slice(0, 5);
}

function friendlyMaterialText(item: string) {
  return item.replace(/：推荐人可观察的行动=/g, "：可观察行动：").replace(/；结果/g, "；结果：").replace(/证据来源：/g, "来源：");
}

function downloadBaseName(writing: WorkflowResult["writing"], targetProgram: ProgramMatch | null, documentType: DocumentType) {
  const program = targetProgram ? programTitle(targetProgram.program) : writing.title;
  return `${documentFlows[documentType].shortLabel}-${program}`.replace(/[\/:*?"<>|]+/g, "-").replace(/\s+/g, "-").slice(0, 96);
}

function paragraphs(text: string) {
  return text.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
}
