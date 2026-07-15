from __future__ import annotations

import re
from typing import Literal

from harbor_agent.core.llm import LLMProvider
from harbor_agent.core.rules import display_gpa
from harbor_agent.models import (
    NormalizedProfile,
    ProgramMatch,
    QuestionnaireAnswer,
    StoryCard,
    WritingDraft,
    WritingInterviewQuestion,
    WritingReviewRubric,
)

DocumentType = Literal["PS", "SOP", "CV", "ESSAY", "REFERENCE_PACKAGE"]

STYLE_GUIDE = [
    "只抽象参考文书的口吻、结构、表达密度和段落推进方式；不得复制句子，不得复用案例中的个人事实。",
    "以学生自己的真实材料开篇，用课程、项目、实习、研究问题或职业观察推动叙事。",
    "每段经历遵循情境、任务、行动、结果、反思，但写成自然段，不机械列 STAR 标题。",
    "英文稿保持正式、克制、具体，避免模板句、夸张形容词和无法证明的判断。",
    "Why Program 只绑定项目官网、申请系统或官方 PDF 中可确认的信息；未核验课程、教授、就业数据和录取概率不得写入。",
    "中文稿用于学生和顾问审阅逻辑，英文稿用于后续润色，任何最终提交前都要逐句核对事实。",
    "模板文件只提供提问结构和写作框架，不得把模板案例、示例事实、旧服务话术写入学生文书。",
    "输出顺序固定为素材缺口、故事卡、大纲、段落草稿、事实绑定表；事实不足时先补问，不用流畅文字掩盖缺口。",
    "推荐信草稿只写推荐人可观察或可确认的事实，最终必须由推荐人本人确认、修改和提交。",
    "严格按当前 document_type 输出：PS/SOP/Essay 写申请叙事，CV 写履历 bullet，推荐信只写推荐人可确认材料；不同文书类型不得互相混用结构。",
]

DOCUMENT_TYPE_RULES = {
    "PS": [
        "用个人动机、学术能力、实践经历、Why Program 和职业规划构成申请主线。",
        "英文稿应是可继续精修的申请陈述，不写未证实课程、教授、就业数据或录取概率。",
    ],
    "SOP": [
        "更强调学术/专业目标、方法训练、研究或项目问题，以及目标项目如何承接下一阶段。",
        "减少抒情动机，增加问题意识、方法、证据和目标路径。",
    ],
    "CV": [
        "输出可扫描的履历 bullet，优先动作动词、工具、方法、结果和量化指标。",
        "不收集也不写入护照、身份证、家庭住址、账号密码等敏感申请表信息。",
    ],
    "ESSAY": [
        "先回应学校指定题目，再组织观点、证据、反思和项目连接。",
        "题目不完整时只给结构和补充问题，不替学生假设题意。",
    ],
    "REFERENCE_PACKAGE": [
        "只写推荐人能够直接观察或确认的事实：课程、展示、小组活动、研究项目和具体印象。",
        "推荐信草稿必须由推荐人确认、修改并提交；不得要求学生代签或伪造推荐人身份。",
    ],
}
DOCUMENT_OUTPUT_CONTRACTS = {
    "PS": "按个人动机、学术准备、核心经历、Why Program、职业规划组织申请叙事；输出不得写成 CV bullet。",
    "SOP": "按专业目标、方法训练、项目问题意识、目标项目承接关系组织；减少抒情，强调证据。",
    "CV": "输出可扫描的履历 bullet、技能分组和取舍建议；不写散文化个人陈述。",
    "ESSAY": "先回应学校原题和字数限制，再组织观点、证据和反思；原题缺失时只生成结构和补充问题。",
    "REFERENCE_PACKAGE": "只生成推荐人可核对的材料包和草稿；最终必须由推荐人确认、修改和提交。",
}

QUESTIONNAIRE_TEMPLATE_CONTRACTS = {
    "PS": "《个人陈述调查问卷》只用于开篇动机、学术能力、核心课程、实践经历、职业规划、Why Program、补充信息和特殊题目的提问顺序；不得复用模板示例事实或旧服务话术。",
    "SOP": "SOP 只抽取学术目标、方法训练、项目问题意识和职业路径问题；不得把泛泛兴趣写成研究能力，不得虚构项目课程或教授。",
    "CV": "《个人信息表 硕士》只用于教育、课程、经历、科研、奖项和技能的公开履历素材；护照、身份证、家庭地址、账号密码不进入写作模型。",
    "ESSAY": "Essay 必须先绑定学校原题、字数和格式；原题缺失时只输出结构和补充问题，不生成看似可提交的段落。",
    "REFERENCE_PACKAGE": "《推荐信调查表（学校）》只用于推荐人关系、课程表现、presentation/小组活动/研究项目、具体印象和综合能力事件；推荐信最终必须由推荐人本人确认和提交。",
}

_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_RISKY_SCHOOL_CLAIM_PATTERNS = [
    re.compile(r"\bprof(?:essor)?\.?\b|\u6559\u6388|\u5bfc\u5e08", re.IGNORECASE),
    re.compile(r"\bemployment rate\b|\bplacement rate\b|\bsalary\b|\u5c31\u4e1a\u7387|\u5c31\u4e1a\u6570\u636e|\u85aa\u8d44", re.IGNORECASE),
    re.compile(r"\badmission (?:odds|chance|rate|probability)\b|\bacceptance rate\b|\u5f55\u53d6\u6982\u7387|\u5f55\u53d6\u7387|\u4fdd\u5f55", re.IGNORECASE),
    re.compile(r"\b(?:course|courses|module|modules|curriculum)\b|\u8bfe\u7a0b|\u6a21\u5757|\u57f9\u517b\u76ee\u6807", re.IGNORECASE),
]
_SOURCE_BOUNDARY_TERMS = [
    "unverified",
    "unless",
    "until",
    "should not",
    "must not",
    "do not",
    "cannot",
    "without a source",
    "before final submission",
    "\u4e0d\u5f97",
    "\u4e0d\u80fd",
    "\u7981\u6b62",
    "\u672a\u6838\u9a8c",
    "\u6838\u9a8c",
    "\u6765\u6e90",
    "\u8bc1\u636e",
    "\u5b98\u7f51",
]


class WritingAgent:
    name = "WritingAgent"

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, profile: NormalizedProfile, matches: list[ProgramMatch]) -> WritingDraft:
        return self.run_from_story_cards(profile, matches, _story_cards_from_profile(profile), document_type="PS")

    def run_from_story_cards(
        self,
        profile: NormalizedProfile,
        matches: list[ProgramMatch],
        story_cards: list[StoryCard],
        document_type: str = "PS",
    ) -> WritingDraft:
        doc_type = _normalize_document_type(document_type)
        target = matches[0] if matches else None
        target_name = _target_name(target)
        school_name = _school_name(target)
        outline = _outline_for(doc_type)
        fact_bindings = [
            {"claim": card.title, "fact_id": ",".join(card.evidence_ids) or card.id}
            for card in story_cards
        ]
        draft_zh, draft_en = _local_draft(profile, target, story_cards, doc_type)
        flags = _review_flags(story_cards, target)
        school_customization = _school_customization(target, doc_type)
        prompt_requirements = _prompt_requirements(target, doc_type)
        cv_bullets = _cv_bullets(story_cards)
        reference_package = _reference_package(story_cards)
        risk_controls = _risk_controls(story_cards, target)
        material_gaps = _material_gaps(story_cards, target, doc_type)
        paragraph_drafts = _paragraph_drafts(draft_zh, draft_en)

        if self.llm.name != "mock":
            try:
                completion = self.llm.complete_json(
                    system=(
                        "You are an admissions writing agent for Hong Kong and Singapore taught-master applications. "
                        "Use only the student facts, story cards and target-program fields provided. "
                        "Do not fabricate awards, internships, professors, course names, employment outcomes, admission odds or official requirements. Treat the local questionnaire templates as question structure only; never reuse template examples, case facts, or service-promise wording as student facts. "
                        "For any school-specific or programme-specific claim, either bind it to an official URL already present in the selected_program payload or move it to material_gaps. "
                        "If the questionnaire lacks evidence, ask for missing information instead of filling the gap with plausible prose. "
                        "Learn only tone, structure and expression density from the supplied guide; never copy case facts or sentences. "
                        "Return JSON only."
                    ),
                    user=(
                        f"document_type={doc_type}\n"
                        f"target_school={school_name}\n"
                        f"target_program={target_name}\n"
                        f"profile={profile.model_dump_json()}\n"
                        f"selected_program={target.model_dump_json() if target else '{}'}\n"
                        f"story_cards={[card.model_dump(mode='json') for card in story_cards]}\n"
                        f"style_guide={STYLE_GUIDE}\n"
                        f"document_rules={DOCUMENT_TYPE_RULES.get(doc_type, [])}\n"
                        f"document_output_contract={DOCUMENT_OUTPUT_CONTRACTS.get(doc_type, '')}\n"
                        f"questionnaire_template_contract={QUESTIONNAIRE_TEMPLATE_CONTRACTS.get(doc_type, '')}\n"
                        "Write one Chinese version and one English version. For PS/SOP/ESSAY, the English version should be "
                        "submission-oriented and normally 750-950 words unless the prompt says otherwise; for CV, return polished bullets; "
                        "for reference package, return recommender-ready evidence notes. The Chinese version should help the student review logic and facts. "
                        "If facts are insufficient, ask for missing information instead of inventing content. For recommendation letters, write only recommender-observable facts and state that the recommender must confirm and submit the final letter."
                    ),
                    schema_hint={
                        "title": "string",
                        "outline": ["string"],
                        "draft_zh": "string",
                        "draft_en": "string",
                        "school_customization": ["string"],
                        "prompt_requirements": ["string"],
                        "cv_bullets": ["string"],
                        "reference_package": ["string"],
                        "risk_controls": ["string"],
                        "material_gaps": ["string"],
                        "paragraph_drafts": ["string"],
                        "review_flags": ["string"],
                    },
                )
                outline = _string_list(completion.get("outline"), outline)[:8]
                draft_zh = _string_value(completion.get("draft_zh"), draft_zh)
                draft_en = _string_value(completion.get("draft_en"), draft_en)
                if doc_type in {"PS", "SOP", "ESSAY"} and len(draft_en.split()) < 620:
                    flags.append("真实模型返回的英文稿偏短，已标记为需要二次扩写。")
                flags.extend(_string_list(completion.get("review_flags"), []))
                school_customization = _string_list(
                    completion.get("school_customization"),
                    school_customization,
                )[:8]
                prompt_requirements = _string_list(
                    completion.get("prompt_requirements"),
                    prompt_requirements,
                )[:8]
                cv_bullets = _string_list(completion.get("cv_bullets"), cv_bullets)[:10]
                reference_package = _string_list(
                    completion.get("reference_package"),
                    reference_package,
                )[:10]
                risk_controls = _string_list(
                    completion.get("risk_controls"),
                    risk_controls,
                )[:8]
                material_gaps = _string_list(
                    completion.get("material_gaps"),
                    material_gaps,
                )[:10]
                paragraph_drafts = _string_list(
                    completion.get("paragraph_drafts"),
                    paragraph_drafts,
                )[:8]
            except Exception as exc:  # Keep the workflow usable even when a live model is temporarily unavailable.
                flags.append(f"真实模型调用失败，已保留本地草稿：{type(exc).__name__}")

        draft_zh, draft_en, school_customization = _guard_writing_outputs(
            draft_zh,
            draft_en,
            school_customization,
            target,
            doc_type,
            flags,
        )
        if doc_type in {"PS", "SOP", "ESSAY"}:
            draft_en = _ensure_minimum_application_draft(draft_en, profile, target, story_cards)
            draft_zh, draft_en, school_customization = _guard_writing_outputs(
                draft_zh,
                draft_en,
                school_customization,
                target,
                doc_type,
                flags,
            )
        paragraph_drafts = _paragraph_drafts(draft_zh, draft_en)
        doc_label = {"REFERENCE_PACKAGE": "推荐信", "PS": "PS", "SOP": "SOP", "CV": "CV", "ESSAY": "Essay"}.get(doc_type, doc_type)
        title = f"{school_name} {target_name} {doc_label} 中英文草稿"
        return WritingDraft(
            document_type=doc_type,
            version_id="v1-student-story",
            title=title,
            outline=outline,
            draft=draft_zh,
            draft_zh=draft_zh,
            draft_en=draft_en,
            material_gaps=material_gaps,
            paragraph_drafts=paragraph_drafts,
            fact_bindings=fact_bindings,
            target_program_ids=[target.program.id] if target else [],
            school_customization=school_customization,
            prompt_requirements=prompt_requirements,
            cv_bullets=cv_bullets,
            reference_package=reference_package,
            risk_controls=risk_controls,
            review_flags=flags,
        )

    def interview_questions(
        self,
        profile: NormalizedProfile,
        matches: list[ProgramMatch],
        document_type: str = "PS",
    ) -> list[WritingInterviewQuestion]:
        target = matches[0] if matches else None
        target_tags = set(target.program.discipline_tags if target else [])
        profile_tags = set(profile.discipline_tags)
        focus = _writing_focus(target_tags, profile_tags, profile)
        questions = [
            WritingInterviewQuestion(
                id="prompt_original",
                question="目标项目的文书题目、字数限制和上传格式是什么？如果还没有，请粘贴官网或网申系统原文。",
                why_it_matters="未读取题目时只能生成通用大纲，不能判断是否覆盖学校要求。",
                target_section="项目题目",
            ),
            WritingInterviewQuestion(
                id="best_story_problem",
                question="请选一段最想写进文书的经历：当时要解决的具体问题是什么？为什么这个问题重要？",
                why_it_matters="文书需要从真实问题进入，而不是从抽象热爱进入。",
                target_section="故事卡",
            ),
            WritingInterviewQuestion(
                id="role_actions",
                question=focus["action_question"],
                why_it_matters=focus["action_reason"],
                target_section=focus["section"],
            ),
            WritingInterviewQuestion(
                id="result_validation",
                question="结果是什么？有没有数字、作品、报告、反馈、排名、复盘结论或其他可以被推荐人/材料证明的证据？",
                why_it_matters="文书不能只写经历过程，还要写可验证结果；没有结果时需要写清楚学习和反思边界。",
                target_section="事实核验",
            ),
            WritingInterviewQuestion(
                id="why_program_binding",
                question="你最想绑定该项目的哪类课程、培养目标、实验室/方向或就业路径？请只写已经在官网看到的内容。",
                why_it_matters="Why Program 必须绑定学校官网可确认的信息，不能编造课程或教授。",
                target_section="Why Program",
            ),
            WritingInterviewQuestion(
                id="career_transfer",
                question="这段经历为什么让你更需要申请该项目？它如何连接你的三到五年职业目标？",
                why_it_matters="需要把过去经历、目标项目和未来目标连成一条申请主线。",
                target_section="职业目标",
            ),
        ]
        if {"computer_science", "data_science"} & target_tags and "business" in profile_tags:
            questions.insert(
                3,
                WritingInterviewQuestion(
                    id="discipline_bridge",
                    question="如果经历来自商业分析、会计或运营场景，请说明其中真正体现目标技术能力的部分：算法、数据库、自动化、统计建模、工程协作或系统设计分别有哪些？",
                    why_it_matters="避免把非技术场景直接拼进技术项目文书，需要完成能力转译。",
                    target_section="技术深度",
                ),
            )
        elif focus["bridge_question"]:
            questions.insert(
                3,
                WritingInterviewQuestion(
                    id="discipline_bridge",
                    question=focus["bridge_question"],
                    why_it_matters=focus["bridge_reason"],
                    target_section=focus["section"],
                ),
            )
        if document_type == "CV":
            questions.append(
                WritingInterviewQuestion(
                    id="cv_bullet_metrics",
                    question="每段 CV bullet 是否能写出动作动词、工具、结果和数字？请补充可公开的量化指标。",
                    why_it_matters="CV 需要可扫描的结果，不需要个人地址、护照或家庭信息。",
                    target_section="事实核验",
                )
            )
        if document_type == "REFERENCE_PACKAGE":
            return [
                WritingInterviewQuestion(
                    id="recommender_identity",
                    question="推荐人的姓名或称呼、职称、所在学院/单位、职务是什么？如果暂时拿不准，请写明还需要向谁补充确认。",
                    why_it_matters="推荐信草稿需要基本身份框架，但手机号、家庭住址、邮箱密码不应进入写作模型。",
                    target_section="推荐人基本信息",
                ),
                WritingInterviewQuestion(
                    id="recommender_official_role",
                    question="推荐人和申请方向的关系是什么：任课老师、导师、课题指导老师、院系领导或工作上级？",
                    why_it_matters="推荐信的可信度来自推荐人可观察事实，不来自泛泛身份背书。",
                    target_section="推荐人关系",
                ),
                WritingInterviewQuestion(
                    id="relationship",
                    question="你与推荐人何时、何地、通过什么课程/项目/研究认识？推荐人能观察到哪些表现？",
                    why_it_matters="推荐信开头需要交代推荐关系和观察基础。",
                    target_section="推荐人关系",
                ),
                WritingInterviewQuestion(
                    id="presentation_group_research",
                    question="是否有 presentation、小组活动或研究项目？请写主题、人数、持续时间、你的工作和结果。",
                    why_it_matters="推荐信需要具体事件，而不是空泛评价。",
                    target_section="课程/项目观察",
                ),
                WritingInterviewQuestion(
                    id="impression_examples",
                    question="推荐人可能记得的 1-2 个具体印象是什么？例如课堂展示、提问、报告修改或研究互动。",
                    why_it_matters="具体印象决定推荐信是否可信、有画面感。",
                    target_section="具体印象",
                ),
                WritingInterviewQuestion(
                    id="recommender_submission_boundary",
                    question="这封推荐信是否需要推荐人本人确认、上传或直接提交？是否有不能代写、代签的要求？",
                    why_it_matters="系统只能辅助整理草稿，最终必须由推荐人确认和提交。",
                    target_section="提交边界",
                ),
            ]
        return questions

    def outline_from_answers(
        self,
        profile: NormalizedProfile,
        matches: list[ProgramMatch],
        document_type: str,
        answers: list[QuestionnaireAnswer],
    ) -> WritingDraft:
        cards = _story_cards_from_answers(answers) or _story_cards_from_profile(profile)
        return self.run_from_story_cards(profile, matches, cards, document_type=document_type)

    def review_rubric(self, draft: WritingDraft, story_cards: list[StoryCard]) -> WritingReviewRubric:
        text = draft.draft_en or draft.draft or ""
        word_count = len(text.split())
        unsupported = _unsupported_school_claim_count(
            "\n".join([text, draft.draft_zh or "", *draft.school_customization])
        )
        issues = list(draft.review_flags)
        if unsupported:
            issues.append("\u6587\u4e66\u4e2d\u4ecd\u6709\u672a\u7ed1\u5b9a\u5b98\u7f51\u8bc1\u636e\u7684\u5b66\u6821\u5b9a\u5236\u58f0\u660e\uff0c\u5bfc\u51fa\u524d\u9700\u8981\u5220\u9664\u6216\u8865\u6765\u6e90\u3002")
        if not draft.prompt_requirements:
            issues.append("尚未读取项目文书题目和字数限制。")
        if any(card.completeness < 60 for card in story_cards):
            issues.append("部分故事卡缺少行动、结果或反思。")
        return WritingReviewRubric(
            prompt_coverage="2/4" if draft.prompt_requirements else "1/4",
            program_specificity="2/5" if draft.school_customization else "1/5",
            fact_coverage=f"{len(draft.fact_bindings)}/{max(1, len(story_cards))}",
            unsupported_claims=unsupported,
            cv_conflicts=0,
            word_count_status=_word_count_status(word_count),
            template_language="中" if word_count else "高",
            export_recommendation="修改后导出" if issues else "建议导出",
            issues=issues[:8],
            next_actions=[
                "先粘贴项目 prompt 原文和字数限制。",
                "补充每段经历的技术动作、数据规模和验证方法。",
                "导出前逐句检查事实绑定，不写未经确认的课程、教授或录取概率。",
            ],
        )




def _guard_writing_outputs(
    draft_zh: str,
    draft_en: str,
    school_customization: list[str],
    target: ProgramMatch | None,
    document_type: DocumentType,
    flags: list[str],
) -> tuple[str, str, list[str]]:
    draft_zh, removed_zh = _remove_unsupported_school_claims(draft_zh, target)
    draft_en, removed_en = _remove_unsupported_school_claims(draft_en, target)
    guarded_customization, removed_items = _source_bound_school_customization(
        school_customization,
        target,
        document_type,
    )
    removed_total = removed_zh + removed_en + removed_items
    if removed_total:
        flags.append(
            f"\u5df2\u79fb\u9664 {removed_total} \u5904\u672a\u7ed1\u5b9a\u5b98\u7f51\u8bc1\u636e\u7684\u5b66\u6821\u5b9a\u5236\u58f0\u660e\uff1b\u8bfe\u7a0b\u3001\u6559\u6388\u3001\u5c31\u4e1a\u6570\u636e\u548c\u5f55\u53d6\u6982\u7387\u5fc5\u987b\u5148\u8865\u6765\u6e90\u3002"
        )
    return draft_zh, draft_en, guarded_customization


def _source_bound_school_customization(
    items: list[str],
    target: ProgramMatch | None,
    document_type: DocumentType,
) -> tuple[list[str], int]:
    fallback = _school_customization(target, document_type)
    kept: list[str] = []
    removed = 0
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if _is_unsupported_school_claim(text, target):
            removed += 1
            continue
        kept.append(text)
    for item in fallback:
        if item not in kept and (_is_source_item(item) or not _is_unsupported_school_claim(item, target)):
            kept.append(item)
    if target and not any(_is_source_item(item) for item in kept):
        kept.append("\u5b66\u6821\u5b9a\u5236\u53e5\u8bc1\u636e\u6765\u6e90\uff1a\u672a\u627e\u5230\u9879\u76ee\u8be6\u60c5\u9875\uff0c\u6b63\u5f0f\u7a3f\u4e0d\u5f97\u5199\u5177\u4f53\u8bfe\u7a0b\u3001\u6559\u6388\u3001\u5c31\u4e1a\u6570\u636e\u6216\u5f55\u53d6\u6982\u7387\u3002")
    return _dedupe(kept)[:8], removed


def _remove_unsupported_school_claims(text: str, target: ProgramMatch | None) -> tuple[str, int]:
    if not text:
        return text, 0
    pieces = re.split(r"([\u3002\uff01\uff1f!?]\s*|\.\s+|\n+)", text)
    cleaned: list[str] = []
    removed = 0
    for index in range(0, len(pieces), 2):
        sentence = pieces[index]
        delimiter = pieces[index + 1] if index + 1 < len(pieces) else ""
        if not sentence.strip():
            cleaned.append(sentence + delimiter)
            continue
        if _is_unsupported_school_claim(sentence, target):
            removed += 1
            continue
        cleaned.append(sentence + delimiter)
    sanitized = "".join(cleaned).strip()
    return sanitized or text, removed


def _unsupported_school_claim_count(text: str, target: ProgramMatch | None = None) -> int:
    if not text:
        return 0
    pieces = re.split(r"[\u3002\uff01\uff1f!?]|\.\s+|\n+", text)
    return sum(1 for piece in pieces if _is_unsupported_school_claim(piece, target))


def _is_unsupported_school_claim(text: str, target: ProgramMatch | None) -> bool:
    if not _has_risky_school_claim(text, target):
        return False
    return not (_has_source_url(text) or _is_boundary_warning(text))


def _has_risky_school_claim(text: str, target: ProgramMatch | None) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    for index, pattern in enumerate(_RISKY_SCHOOL_CLAIM_PATTERNS):
        if not pattern.search(stripped):
            continue
        if index == 3 and not _has_school_context(stripped, target):
            continue
        return True
    return False


def _has_school_context(text: str, target: ProgramMatch | None) -> bool:
    lowered = text.lower()
    generic_terms = [
        "programme",
        "program",
        "university",
        "school",
        "faculty",
        "department",
        "official",
        "target",
        "\u8be5\u9879\u76ee",
        "\u76ee\u6807\u9879\u76ee",
        "\u5b66\u6821",
        "\u5b66\u9662",
        "\u5b98\u7f51",
    ]
    if any(term in lowered for term in generic_terms):
        return True
    if not target:
        return False
    names = [
        target.program.name,
        target.program.name_zh or "",
        target.program.institution,
        target.program.institution_zh or "",
        target.program.school,
        target.program.school_zh or "",
    ]
    return any(name and len(name) >= 4 and name.lower() in lowered for name in names)


def _has_source_url(text: str) -> bool:
    return bool(_URL_PATTERN.search(text))


def _is_source_item(text: str) -> bool:
    return "\u5b66\u6821\u5b9a\u5236\u53e5\u8bc1\u636e\u6765\u6e90" in text or "customization evidence source" in text.lower() or _has_source_url(text)


def _is_boundary_warning(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in _SOURCE_BOUNDARY_TERMS)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

def _normalize_document_type(value: str) -> DocumentType:
    if value in {"PS", "SOP", "CV", "ESSAY", "REFERENCE_PACKAGE"}:
        return value  # type: ignore[return-value]
    return "PS"


def _writing_focus(target_tags: set[str], profile_tags: set[str], profile: NormalizedProfile) -> dict[str, str]:
    text = " ".join([*target_tags, *profile_tags, profile.education.major, profile.career_goal]).lower()
    if {"computer_science", "data_science"} & target_tags or any(word in text for word in ["computer", "data", "ai", "人工智能", "数据"]):
        return {
            "section": "技术深度",
            "action_question": "这段经历里你具体写了哪些代码、做了哪些分析、搭建了哪些系统或使用了哪些技术方法？你负责的是需求拆解、数据处理、建模、开发、测试还是可视化？",
            "action_reason": "技术类项目需要判断经历是否能支撑 CS/DS/AI/IS 能力，而不是只写泛泛的参与经历。",
            "bridge_question": "",
            "bridge_reason": "",
        }
    if {"business", "finance"} & target_tags or any(word in text for word in ["finance", "business", "management", "accounting", "金融", "会计", "商业", "管理"]):
        return {
            "section": "事实核验",
            "action_question": "这段经历里你负责了哪些商业分析、财务分析、市场研究、运营优化或管理决策支持？你使用了哪些框架、数据或报告方法？",
            "action_reason": "商科文书需要把经历写成问题、分析、决策影响和商业结果，而不是堆职责。",
            "bridge_question": "这段经历如何证明你适合目标商科方向？请说明行业理解、量化分析、沟通协作、商业判断或领导力证据。",
            "bridge_reason": "商科项目通常看重动机清晰度、职业路径和可迁移能力，需要把经历翻译成目标专业语言。",
        }
    if any(word in text for word in ["communication", "media", "journalism", "传媒", "传播", "新闻"]):
        return {
            "section": "事实核验",
            "action_question": "这段经历里你具体负责了哪些内容策划、用户研究、采访、传播策略、作品制作或效果复盘？",
            "action_reason": "传媒/传播方向需要看到作品意识、受众理解、表达能力和传播效果。",
            "bridge_question": "这段经历如何体现你对目标传播方向的理解？是否有作品、阅读量、转化、调研或复盘证据？",
            "bridge_reason": "需要把经历和作品/传播效果绑定，避免写成泛泛活动总结。",
        }
    if any(word in text for word in ["education", "tesol", "language", "教育", "语言", "英语"]):
        return {
            "section": "事实核验",
            "action_question": "这段经历里你具体做了哪些教学、课程设计、学习支持、语言分析、学生反馈或教育研究相关工作？",
            "action_reason": "教育/语言方向需要看到教学理解、学习者观察、课程设计或研究意识。",
            "bridge_question": "这段经历如何体现你对目标教育/语言项目的适配？是否有课堂、辅导、调研、反思或学习成果证据？",
            "bridge_reason": "教育类文书要避免只写热心助人，需要写清教学方法和反思。",
        }
    if any(word in text for word in ["policy", "public", "law", "公共", "政策", "法律"]):
        return {
            "section": "事实核验",
            "action_question": "这段经历里你具体参与了哪些政策研究、资料分析、利益相关方沟通、报告写作或公共议题判断？",
            "action_reason": "公共政策/法律方向需要看到问题意识、研究方法、证据使用和公共影响。",
            "bridge_question": "这段经历如何连接你的公共议题兴趣和目标项目？请补充议题、方法、结论和影响。",
            "bridge_reason": "政策类文书需要清楚的问题意识和证据链。",
        }
    return {
        "section": "事实核验",
        "action_question": "这段经历里你具体负责什么？做了哪些动作、使用了哪些方法或工具？",
        "action_reason": "系统需要把真实经历拆成可写入文书的行动和证据，而不是生成空泛文本。",
        "bridge_question": "这段经历如何体现你目标专业需要的能力？请用目标专业语言解释。",
        "bridge_reason": "不同专业看重的能力不同，必须先完成经历到专业能力的转译。",
    }


def _target_name(target: ProgramMatch | None) -> str:
    if not target:
        return "目标项目"
    return target.program.name_zh or target.program.name


def _school_name(target: ProgramMatch | None) -> str:
    if not target:
        return "目标学校"
    return target.program.institution_zh or target.program.institution



def _target_name_en(target: ProgramMatch | None) -> str:
    if not target:
        return "the target programme"
    return target.program.name or target.program.name_zh or "the target programme"


def _school_name_en(target: ProgramMatch | None) -> str:
    if not target:
        return "the target university"
    return target.program.institution or target.program.institution_zh or "the target university"

def _outline_for(document_type: DocumentType) -> list[str]:
    if document_type == "CV":
        return ["教育背景", "核心课程与技能", "项目/科研经历", "实习/工作经历", "奖项与活动", "语言与工具"]
    if document_type == "REFERENCE_PACKAGE":
        return ["推荐人关系", "课程或项目观察", "具体事件", "能力评价", "推荐结论"]
    if document_type == "SOP":
        return ["学术兴趣形成", "课程与方法基础", "研究/项目问题", "目标项目匹配", "职业与学术目标"]
    if document_type == "ESSAY":
        return ["题目回应", "核心故事", "行动与结果", "反思", "与项目连接"]
    return ["申请动机", "学术基础", "实践故事", "Why Program", "职业规划"]


def _local_draft(
    profile: NormalizedProfile,
    target: ProgramMatch | None,
    story_cards: list[StoryCard],
    document_type: DocumentType,
) -> tuple[str, str]:
    target_name = _target_name(target)
    school_name = _school_name(target)
    target_name_en = _target_name_en(target)
    school_name_en = _school_name_en(target)
    best = max(story_cards, key=lambda item: item.completeness, default=None)
    academic = next((card for card in story_cards if card.category == "education"), best)
    practical = next((card for card in story_cards if card.category in {"internship", "project", "research"}), best)
    motivation = next((card for card in story_cards if card.category == "motivation"), best)
    recommender = next((card for card in story_cards if card.category == "recommender"), None)
    why_program = _why_program_sentence(target)
    why_program_en = _why_program_sentence_en(target)
    raw_career_goal = profile.career_goal or (motivation.result if motivation else "")
    career_goal_zh = _career_goal_zh(raw_career_goal)
    career_goal_en = _career_goal_en(raw_career_goal)

    if document_type == "CV":
        zh = (
            f"【中文 CV 素材】\n"
            f"教育背景：{profile.education.school}，{profile.education.major}，GPA {display_gpa(profile)}。\n\n"
            f"核心课程与技能：{_card_text(academic, '请补充与申请方向相关的课程、成绩和工具。')}\n\n"
            f"项目/实习经历：{_card_text(practical, '请补充一段最能体现能力的项目、科研或实习故事。')}\n\n"
            f"目标项目：{school_name} {target_name}。{why_program}\n\n"
            f"职业目标：{career_goal_zh}。"
        )
        en = (
            f"CV Draft\n"
            f"Education: {profile.education.school}, {profile.education.major}, GPA {display_gpa(profile)}.\n\n"
            f"Relevant Coursework and Skills: {_card_text_en(academic)}\n\n"
            f"Project / Internship Experience: {_card_text_en(practical)}\n\n"
            f"Target Programme: {school_name_en} {target_name_en}. {why_program_en}\n\n"
            f"Career Objective: {career_goal_en}."
        )
        return zh, en

    if document_type == "REFERENCE_PACKAGE":
        source_card = recommender or academic or practical or best
        relation = _reference_relation(source_card)
        observation = _reference_observation(source_card)
        ability = _reference_ability_sentence(source_card)
        applicant = "该同学"
        zh = (
            f"【推荐信中文初稿】\n"
            f"尊敬的招生委员会：\n\n"
            f"我很高兴推荐{applicant}申请{school_name}{target_name}。{relation}\n\n"
            f"在我能够直接观察到的课程、展示或项目互动中，{observation}\n\n"
            f"这段经历体现出{applicant}{ability}。这些评价均来自推荐人能够观察到的课堂、项目或研究互动，正式提交前应由推荐人核对、修改并确认。\n\n"
            f"基于以上观察，我认为{applicant}具备继续攻读相关硕士项目的学习基础和发展潜力。若推荐人认可上述事实，可在此基础上补充其个人评价和签名信息。"
        )
        en = (
            "Dear Members of the Admissions Committee,\n\n"
            f"I am pleased to recommend the applicant for {school_name_en} {target_name_en}. "
            "I know the applicant through the academic interaction described in the questionnaire, and my comments below should be checked and confirmed by the recommender before submission.\n\n"
            f"In the course, presentation, group activity or research setting that I directly observed, {_reference_observation_en(source_card)}\n\n"
            f"This experience shows the applicant's {_reference_strengths_en(source_card)}. "
            "The recommendation remains evidence-based: each evaluation should be tied to a course, project, presentation, research meeting or other interaction the recommender actually observed.\n\n"
            "Based on these observations, I believe the applicant has the academic discipline, problem-solving ability and motivation to contribute to graduate study.\n\n"
            "Sincerely,\n[Recommender Name]"
        )
        return zh, en

    zh = (
        f"我申请 {school_name} {target_name} 的主线，来自我在 {profile.education.major} 学习中逐渐形成的方向判断。"
        f"{_card_text(motivation, '')}\n\n"
        f"本科阶段，我通过课程和训练建立了申请该方向所需的基础。"
        f"{_card_text(academic, '')}"
        "这一部分在正式稿中不应只罗列课程名称，而要说明这些训练如何改变了我理解问题、拆解问题和验证结论的方式。\n\n"
        f"更重要的是，我在实践中把这些知识转化为解决问题的能力。"
        f"{_card_text(practical, '')}"
        "正式版本需要继续补充我在其中承担的具体角色、使用的方法或工具、遇到的限制、如何验证结果，以及这段经历为什么能证明我适合目标专业。\n\n"
        f"选择 {target_name}，是因为我希望把已有训练推进到更系统的研究生阶段。{why_program} "
        "在正式提交前，Why Program 部分必须继续绑定到项目官网中的课程、培养目标或申请要求。\n\n"
        f"毕业后，我希望{career_goal_zh}。因此，这份文书不只是回顾已有经历，也是在说明我为什么需要这个项目，以及我能如何把过去的训练转化为下一阶段的贡献。"
    )
    en = (
        f"My decision to apply for {target_name_en} at {school_name_en} has grown out of my training in {profile.education.major} "
        "and my gradual understanding of the problems I hope to solve. "
        f"{_card_text_en(motivation)}\n\n"
        "During my undergraduate study, I built the academic foundation required for this direction through relevant coursework, analytical training and repeated project practice. "
        f"{_card_text_en(academic)} "
        "Rather than treating these courses as isolated requirements, I began to understand them as a connected toolkit for asking sharper questions, selecting appropriate methods, and checking whether a conclusion is supported by evidence.\n\n"
        "Beyond classroom learning, I became increasingly aware that meaningful practical work requires the ability to define a problem, choose appropriate methods, execute carefully and evaluate outcomes honestly. "
        f"{_card_text_en(practical)} "
        "The final version should develop the student's exact responsibility, methods or tools, constraints, validation process and measurable outcome.\n\n"
        "This experience also clarified the gap between current preparation and the level of training needed next. "
        f"I am therefore drawn to {target_name_en} because it can provide a more systematic graduate-level environment for my next stage of development. "
        f"{why_program_en} Any unverified course, professor, admission preference or career outcome should remain outside the final draft until it has a source.\n\n"
        f"In the long term, I hope to {career_goal_en}. I see this application not only as a summary of what I have done, "
        "but also as a reasoned step toward the kind of work I am prepared to pursue with greater depth and responsibility."
    )
    return zh, en


def _ensure_minimum_application_draft(
    draft: str,
    profile: NormalizedProfile,
    target: ProgramMatch | None,
    story_cards: list[StoryCard],
) -> str:
    if len(draft.split()) >= 650:
        return draft
    if any(_contains_cjk(_card_text(card, "")) for card in story_cards):
        return (
            draft.rstrip()
            + "\n\n[English revision required: the source stories are in Chinese. Keep the original facts bound to the story cards, "
            "then translate and polish them before submission; do not replace them with generic filler.]"
        )
    target_name = _target_name_en(target)
    school_name = _school_name_en(target)
    evidence_notes = []
    for card in story_cards[:4]:
        evidence_notes.append(
            f"In revising this statement, this {card.category} story should be developed with its situation, "
            f"the student's exact responsibility, the methods used, measurable result, and reflection. "
            f"The currently available facts are: {_card_text_en(card)}"
        )
    if not evidence_notes:
        evidence_notes.append(
            "Before this draft can become submission-ready, the student should provide at least two substantial stories: "
            "one academic or project-based example and one practical example with observable results."
        )
    addendum = (
        "\n\nRevision-ready expansion notes:\n"
        f"This draft is being prepared for {target_name} at {school_name}. It should not make claims about courses, professors, "
        "deadlines or admissions preferences unless those claims are supported by an official programme page, PDF/FAQ or application system. "
        f"The student's current profile is {profile.education.school_tier}, {profile.education.major}, GPA {display_gpa(profile)}. "
        "The final statement should convert these facts into a coherent argument: why the student is academically prepared, "
        "which problems they have already tried to solve, why graduate study is the necessary next step, and how the selected programme fits that plan.\n\n"
        + "\n\n".join(evidence_notes)
        + "\n\nThe next revision should replace any placeholder-like sentence with student-provided evidence. "
        "For a technical programme, this means naming the concrete code, model, database, system, experiment, dataset scale, validation method, "
        "or engineering trade-off involved. For a business, education, policy or communication programme, it means naming the analytical framework, "
        "stakeholders, output, feedback and professional insight. This evidence-first approach keeps the writing credible and avoids generic AI-style language."
    )
    return draft.rstrip() + addendum


def _why_program_sentence(target: ProgramMatch | None) -> str:
    if not target:
        return "当前还没有选定项目，因此 Why Program 只能保留为待补充段落。"
    source_label = _student_source_status_label(target.program.data_status.value)
    source_note = "项目来源已可用于草稿定制" if target.program.data_status.value == "VERIFIED" else "学校定制句只能引用已绑定的项目页、申请系统或官方 PDF 来源"
    return (
        f"目前可确认的目标是 {target.program.institution_zh or target.program.institution} "
        f"{target.program.name_zh or target.program.name}，项目来源为{source_label}，{source_note}。"
    )


def _why_program_sentence_en(target: ProgramMatch | None) -> str:
    if not target:
        return "No target programme has been selected, so this section should remain a structure note."
    source_label = _student_source_status_label_en(target.program.data_status.value)
    return (
        f"The selected programme is {_target_name_en(target)} at {_school_name_en(target)}. "
        f"The current source coverage is {source_label}; programme-specific claims must be tied to the official programme page, application system or official PDF before final submission."
    )


def _student_source_status_label(status: str | None) -> str:
    labels = {
        "VERIFIED": "官网当前季已核验",
        "STALE": "2026 Fall 往届参考",
        "NOT_PUBLISHED": "官网当前季未发布",
        "CHANGED": "来源冲突",
        "DISCOVERED": "已找到官方来源，内容待整理",
        "EXTRACTED": "官网信息已提取，等待发布",
        "PENDING_REVIEW": "运营审核中",
        "REJECTED": "暂不纳入学生端",
        "ARCHIVED": "已归档",
        "MODEL_INFERRED": "缺少项目详情页",
    }
    return labels.get(status or "", "来源仍需补充")


def _student_source_status_label_en(status: str | None) -> str:
    labels = {
        "VERIFIED": "verified for the current application cycle",
        "STALE": "a 2026 Fall previous-cycle reference",
        "NOT_PUBLISHED": "not yet published for the current application cycle",
        "CHANGED": "conflicting across sources",
        "DISCOVERED": "an official source has been found and still needs extraction",
        "EXTRACTED": "official information has been extracted and awaits release",
        "PENDING_REVIEW": "under operations review",
        "REJECTED": "not released to the student workflow",
        "ARCHIVED": "archived",
        "MODEL_INFERRED": "missing an official programme-detail page",
    }
    return labels.get(status or "", "still incomplete")

def _card_text(card: StoryCard | None, fallback: str) -> str:
    if not card:
        return fallback
    parts = [card.situation, card.task, card.action, card.result, card.reflection]
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return text or fallback


def _card_text_en(card: StoryCard | None) -> str:
    if not card:
        return "This section needs a concrete student-provided story before it can become submission-ready."
    text = _card_text(card, "").strip()
    if not text:
        return "This section needs a concrete student-provided story before it can become submission-ready."
    if _contains_cjk(text):
        parts = []
        if card.situation:
            parts.append("situation")
        if card.action:
            parts.append("action")
        if card.result:
            parts.append("result")
        if card.reflection:
            parts.append("reflection")
        covered = ", ".join(parts) or "source facts"
        return f"[English revision required; Chinese source facts in story card {card.id} cover {covered}.]"
    return text


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _career_goal_zh(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "在相关行业中继续发展"
    lower = text.lower()
    if "product data analyst" in lower:
        return "成为跨境科技公司的产品数据分析师"
    if _contains_cjk(text):
        normalized = re.sub(r"^(我)?希望", "", text).strip().rstrip("。.!！")
        return normalized or "在相关行业中继续发展"
    return "围绕已填写的职业目标继续发展"


def _career_goal_en(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "continue developing in a relevant professional field"
    if _contains_cjk(text):
        return "pursue the career goal described in the student's questionnaire"
    return text[0].lower() + text[1:] if text and text[0].isupper() else text


def _material_gaps(story_cards: list[StoryCard], target: ProgramMatch | None, document_type: DocumentType) -> list[str]:
    gaps: list[str] = []
    if document_type == "REFERENCE_PACKAGE":
        recommender_cards = [card for card in story_cards if card.category == "recommender"]
        if not recommender_cards:
            gaps.append("补充推荐人与申请者的关系、课程或项目互动，以及推荐人亲眼观察到的具体事件。")
        if recommender_cards and any(card.completeness < 70 for card in recommender_cards):
            gaps.append("补充推荐人可核对的行动、结果或课堂表现，避免只写泛泛评价。")
        return gaps[:6]
    if not story_cards:
        gaps.append("至少补充一段课程、项目、科研或实习经历，写清问题、行动、结果和反思。")
    if document_type in {"PS", "SOP", "ESSAY"} and not any(card.category == "education" for card in story_cards):
        gaps.append("补充核心课程、成绩、方法训练或课程项目，用来支撑学术能力段落。")
    if document_type in {"PS", "SOP", "ESSAY", "CV"} and not any(card.category in {"internship", "project", "research"} for card in story_cards):
        gaps.append("补充一段实践经历，说明你的具体角色、方法工具和可验证结果。")
    if any(card.completeness < 60 for card in story_cards):
        gaps.append("部分故事卡缺少行动、结果或反思，当前只能生成结构草稿。")
    if target is None:
        gaps.append("选择目标项目后，再补充 Why Program 所需的官网课程、培养目标或申请要求。")
    elif document_type in {"PS", "SOP", "ESSAY"} and target.program.data_status.value != "VERIFIED":
        gaps.append("目标项目官网信息还不完整，学校定制内容只能作为草稿方向，不能写成最终事实。")
    return gaps[:8]


def _paragraph_drafts(draft_zh: str, draft_en: str) -> list[str]:
    paragraphs: list[str] = []
    for label, body in [("中文逻辑稿", draft_zh), ("英文申请稿", draft_en)]:
        for index, paragraph in enumerate([part.strip() for part in body.split("\n\n") if part.strip()], start=1):
            paragraphs.append(f"{label} P{index}: {paragraph}")
            if len(paragraphs) >= 8:
                return paragraphs
    return paragraphs
def _review_flags(story_cards: list[StoryCard], target: ProgramMatch | None) -> list[str]:
    flags: list[str] = []
    if not story_cards:
        flags.append("尚未填写足够故事素材，当前稿件只能作为结构示例。")
    if target is None:
        flags.append("尚未指定具体学校/项目，Why Program 不能进入最终稿。")
    elif target.program.data_status.value != "VERIFIED":
        flags.append("Why Program 需要绑定项目页、申请系统或官方 PDF 中能查到的课程、培养目标或申请要求。")
    return flags


def _school_customization(target: ProgramMatch | None, document_type: DocumentType) -> list[str]:
    if not target:
        return ["尚未选定学校/项目，不能写最终版 Why Program。"]
    program = target.program
    evidence_url = program.official_program_url or program.application_url
    items = [
        f"目标项目：{program.institution_zh or program.institution} - {program.name_zh or program.name}",
        f"学院/开设单位：{program.school_zh or program.school}",
        f"项目来源：{_student_source_status_label(program.data_status.value)}；需核验信息不得写成确定事实。",
    ]
    if evidence_url:
        items.append(f"学校定制句证据来源：{evidence_url}")
    else:
        items.append("学校定制句证据来源：未找到项目详情页，正式稿不得写具体课程、教授、就业数据或录取概率。")
    if document_type in {"PS", "SOP", "ESSAY"}:
        items.append("正式稿需绑定官网课程、培养目标、essay prompt 或申请要求。")
    return items


def _prompt_requirements(target: ProgramMatch | None, document_type: DocumentType) -> list[str]:
    items = [
        "读取目标项目官网/网申系统中的 essay prompt、字数限制、上传格式和截止时间。",
        "没有官方 prompt 时，只生成通用结构，不声称满足项目指定题目。",
    ]
    if document_type == "CV":
        items.append("CV 需按项目偏好调整技能顺序、项目标题和量化结果。")
    if document_type == "REFERENCE_PACKAGE":
        items.append("推荐信素材必须来自推荐人能观察到的课程、项目或研究互动。")
    if target and target.program.data_status.value != "VERIFIED":
        items.append("缺少项目页证据时，Why Program 只保留结构，不写具体课程、教授、就业数据或录取概率。")
    return items


def _cv_bullets(story_cards: list[StoryCard]) -> list[str]:
    bullets: list[str] = []
    for card in story_cards[:5]:
        action = card.action or card.task or card.situation
        result = card.result or "补充量化结果"
        if action:
            bullets.append(f"{card.title}：{action}；结果：{result}")
    return bullets or ["补充项目/实习/科研经历后，系统会生成可放入 CV 的 bullet。"]


def _reference_package(story_cards: list[StoryCard]) -> list[str]:
    package: list[str] = []
    for card in story_cards:
        if card.category in {"education", "research", "project", "recommender"}:
            package.append(
                f"{card.title}：推荐人可观察的行动={card.action or card.task or '待补充'}；结果={card.result or '待补充'}"
            )
    return package[:6] or ["请补充推荐人与学生共同参与的课程、项目、研究或汇报场景。"]


def _reference_relation(card: StoryCard | None) -> str:
    if not card or not card.situation:
        return "推荐人与申请者的关系、相识时间和具体场景仍需补充。"
    return f"我与申请者的关系和观察场景为：{card.situation}。"


def _reference_observation(card: StoryCard | None) -> str:
    if not card:
        return "推荐人仍需补充一段可直接观察到的课程、展示、小组活动或研究项目。"
    parts = [card.task, card.action, card.result, card.reflection]
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return text or "推荐人仍需补充课堂表现、项目贡献、结果和具体印象。"


def _reference_ability_sentence(card: StoryCard | None) -> str:
    if not card:
        return "在学习能力、表达能力、协作意识和持续改进方面的潜力"
    skills = [skill for skill in card.related_skills if skill]
    if skills:
        return "在" + "、".join(skills[:4]) + "方面的能力"
    return "在学习能力、问题拆解、团队协作、表达能力和持续改进方面的潜力"


def _reference_observation_en(card: StoryCard | None) -> str:
    if not card:
        return "the applicant still needs a concrete course, presentation, group activity or research example that the recommender can verify."
    text = _card_text(card, "").strip()
    if not text:
        return "the applicant still needs a concrete course, presentation, group activity or research example that the recommender can verify."
    if _contains_cjk(text):
        return "the questionnaire records a concrete observed event; the recommender should translate the verified Chinese facts into English after confirming them."
    return text


def _reference_strengths_en(card: StoryCard | None) -> str:
    if not card or not card.related_skills:
        return "academic discipline, analytical ability, communication and collaborative awareness"
    return ", ".join(card.related_skills[:4])


def _risk_controls(story_cards: list[StoryCard], target: ProgramMatch | None) -> list[str]:
    controls = [
        "不得编造奖项、实习、课程、教授、就业数据或录取概率。",
        "英文稿提交前需要人工润色、查重和机器生成痕迹检查。",
        "所有项目匹配论述必须绑定官网、申请系统或项目 PDF。",
        "问卷模板只提供提问结构和写作边界，不得把模板示例事实、案例人物或旧服务话术写入学生文书。",
        "严格按当前文书类型输出：PS/SOP/Essay 写申请叙事，CV 写履历 bullet，推荐信只写推荐人可确认材料。",
    ]
    if any(card.completeness < 60 for card in story_cards):
        controls.append("部分故事卡完整度不足，当前稿件更适合做结构样例。")
    if target and target.program.data_status.value != "VERIFIED":
        controls.append("Why Program 的学校定制句必须绑定项目页、申请系统或官方 PDF 来源后才能进入最终稿。")
    return controls


def _string_value(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _string_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return fallback


def _story_cards_from_profile(profile: NormalizedProfile) -> list[StoryCard]:
    cards: list[StoryCard] = []
    for index, exp in enumerate(profile.experiences[:3], start=1):
        cards.append(
            StoryCard(
                id=f"profile_experience_{index}",
                title=exp.title,
                category="internship" if exp.type in {"internship", "work"} else "project",
                situation=exp.organization,
                task=exp.role,
                action=", ".join(exp.tools),
                result="; ".join(exp.outcomes),
                related_skills=exp.tools,
                evidence_ids=[f"profile:experience:{index}"],
                completeness=80 if exp.outcomes else 60,
            )
        )
    return cards


def _story_cards_from_answers(answers: list[QuestionnaireAnswer]) -> list[StoryCard]:
    by_id = {answer.field_id: answer.value for answer in answers}

    def value(*keys: str) -> str:
        for key in keys:
            raw = by_id.get(key)
            if isinstance(raw, list):
                text = "; ".join(str(item) for item in raw if str(item).strip())
            else:
                text = str(raw or "")
            if text.strip():
                return text.strip()
        return ""

    cards: list[StoryCard] = []
    academic = value("academic_strength", "core_courses", "gpa_rank")
    if academic:
        cards.append(
            StoryCard(
                id="questionnaire_academic_1",
                title="学术能力素材卡",
                category="education",
                situation=value("major_degree", "gpa_rank"),
                task=value("prerequisite_fit", "core_courses"),
                action=academic,
                result=value("gpa_rank"),
                reflection=value("problem_awareness", "career_transfer"),
                related_skills=[item for item in ["统计", "数据", "Python", "SQL", "研究", "写作"] if item.lower() in academic.lower()],
                evidence_ids=["writing-questionnaire:academic"],
                completeness=80 if value("core_courses") and value("gpa_rank") else 60,
            )
        )

    practice_problem = value("practice_problem", "best_story_problem", "practical_examples", "experience_process")
    practice_action = value("practice_actions", "practice_role", "role_actions", "technical_role", "discipline_bridge", "ba_to_cs_bridge")
    practice_result = value("practice_result", "result_validation", "data_scale_validation", "experience_result")
    practice_reflection = value("practice_reflection", "career_transfer", "why_program_binding", "discipline_bridge")
    if any([practice_problem, practice_action, practice_result, practice_reflection]):
        cards.append(
            StoryCard(
                id="questionnaire_practice_1",
                title="实践经历素材卡",
                category="project",
                situation=practice_problem,
                task=value("practice_role", "practice_problem", "best_story_problem"),
                action=practice_action,
                result=practice_result,
                reflection=practice_reflection,
                related_skills=[item for item in ["Python", "SQL", "建模", "系统设计", "研究", "沟通", "分析", "写作"] if item.lower() in practice_action.lower()],
                target_program_relevance=[value("why_program_binding")],
                evidence_ids=["writing-questionnaire:practice"],
                completeness=85 if practice_action and practice_result and practice_reflection else 55,
            )
        )

    motivation = value("opening_trigger", "problem_awareness", "career_plan")
    if motivation:
        cards.append(
            StoryCard(
                id="questionnaire_motivation_1",
                title="开篇动机素材卡",
                category="motivation",
                situation=value("opening_trigger"),
                task=value("problem_awareness"),
                action=value("career_transfer"),
                result=value("career_plan"),
                reflection=value("special_context"),
                target_program_relevance=[value("why_program_binding")],
                evidence_ids=["writing-questionnaire:motivation"],
                completeness=75 if value("opening_trigger") and value("career_plan") else 55,
            )
        )

    recommender = value("relationship", "course_performance", "presentation_group_research", "impression_examples", "competency_events")
    if recommender:
        cards.append(
            StoryCard(
                id="questionnaire_recommender_1",
                title="推荐信事实素材卡",
                category="recommender",
                situation=value("relationship"),
                task=value("course_performance", "presentation_group_research"),
                action=value("impression_examples", "competency_events"),
                result=value("practice_result", "course_performance"),
                reflection="推荐信只使用推荐人可观察到的事实，不写联系方式和隐私信息。",
                evidence_ids=["writing-questionnaire:reference"],
                completeness=80 if value("relationship") and value("impression_examples", "competency_events") else 55,
            )
        )

    return cards
def _word_count_status(word_count: int) -> str:
    if word_count == 0:
        return "尚未生成英文草稿"
    if word_count < 450:
        return f"约 {word_count} 词，可能偏短"
    if word_count > 1000:
        return f"约 {word_count} 词，通常需要压缩"
    return f"约 {word_count} 词，需按目标项目要求微调"
