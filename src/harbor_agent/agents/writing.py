from __future__ import annotations

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
    "以学生自己的故事开篇，不空喊热爱；用具体课程、项目、实习或研究问题推动叙事。",
    "每段经历遵循情境、任务、行动、结果、反思，但写成自然段，不机械列 STAR 标题。",
    "英文稿保持正式、克制、具体，避免模板句和夸张形容词。",
    "Why Program 只绑定已知项目名称、学院和官方来源；未验证课程或教授不得编造。",
    "中文稿用于学生和顾问审阅，英文稿用于进一步润色提交。",
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
        target = next((item for item in matches if item.tier != "not_recommended"), None)
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

        if self.llm.name != "mock":
            try:
                completion = self.llm.complete_json(
                    system=(
                        "You are an admissions writing agent for Hong Kong and Singapore taught-master applications. "
                        "Use only the student facts, story cards and target-program fields provided. "
                        "Do not fabricate awards, internships, professors, course names, admission odds or official requirements. "
                        "Learn the style pattern from the supplied guide: story-led, concrete, polished, formal and evidence-bound. "
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
                        "Write one Chinese version and one English version. For PS/SOP/ESSAY, the English version should be "
                        "submission-oriented and normally 750-950 words unless the prompt says otherwise; for CV, return polished bullets; "
                        "for reference package, return recommender-ready evidence notes. The Chinese version should help the student review logic and facts. "
                        "If facts are insufficient, ask for missing information instead of inventing content."
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
            except Exception as exc:  # Keep the workflow usable even when a live model is temporarily unavailable.
                flags.append(f"真实模型调用失败，已保留本地草稿：{type(exc).__name__}")

        if doc_type in {"PS", "SOP", "ESSAY"}:
            draft_en = _ensure_minimum_application_draft(draft_en, profile, target, story_cards)
        title = f"{school_name} {target_name} {doc_type} 中英文草稿"
        return WritingDraft(
            document_type=doc_type,
            version_id="v1-student-story",
            title=title,
            outline=outline,
            draft=draft_zh,
            draft_zh=draft_zh,
            draft_en=draft_en,
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
        target = next((item for item in matches if item.tier != "not_recommended"), None)
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
        unsupported = max(0, len(draft.school_customization) - len(draft.target_program_ids))
        issues = list(draft.review_flags)
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


def _outline_for(document_type: DocumentType) -> list[str]:
    if document_type == "CV":
        return ["教育背景", "核心课程与技能", "项目/科研经历", "实习/工作经历", "奖项与活动", "语言与工具"]
    if document_type == "REFERENCE_PACKAGE":
        return ["推荐人与关系", "可观察场景", "能力证据", "具体事件", "推荐信素材边界"]
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
    best = max(story_cards, key=lambda item: item.completeness, default=None)
    academic = next((card for card in story_cards if card.category == "education"), best)
    practical = next((card for card in story_cards if card.category in {"internship", "project", "research"}), best)
    motivation = next((card for card in story_cards if card.category == "motivation"), best)
    why_program = _why_program_sentence(target)
    career_goal = profile.career_goal or (motivation.result if motivation else "在相关行业中继续发展")

    if document_type == "CV":
        zh = (
            f"【中文 CV 素材】\n"
            f"教育背景：{profile.education.school}，{profile.education.major}，GPA {display_gpa(profile)}。\n\n"
            f"核心课程与技能：{_card_text(academic, '请补充与申请方向相关的课程、成绩和工具。')}\n\n"
            f"项目/实习经历：{_card_text(practical, '请补充一段最能体现能力的项目、科研或实习故事。')}\n\n"
            f"目标项目：{school_name} {target_name}。{why_program}\n\n"
            f"职业目标：{career_goal}。"
        )
        en = (
            f"CV Draft\n"
            f"Education: {profile.education.school}, {profile.education.major}, GPA {display_gpa(profile)}.\n\n"
            f"Relevant Coursework and Skills: {_card_text_en(academic)}\n\n"
            f"Project / Internship Experience: {_card_text_en(practical)}\n\n"
            f"Target Programme: {school_name} {target_name}. {why_program}\n\n"
            f"Career Objective: {career_goal}."
        )
        return zh, en

    if document_type == "REFERENCE_PACKAGE":
        zh = (
            f"【推荐信素材包】\n"
            f"推荐信应围绕申请者在 {profile.education.major} 学习中的可观察表现展开。"
            f"可使用的核心事件是：{_card_text(practical or academic, '请补充推荐人实际观察到的课程、项目或研究事件。')}\n\n"
            "推荐人可以强调：学习能力、问题拆解、团队协作、表达能力和持续改进。"
            "所有评价都应回到具体事件，避免泛泛称赞。"
        )
        en = (
            "Reference Package\n"
            f"The recommender may focus on observable performance in {profile.education.major}, especially "
            f"{_card_text_en(practical or academic)}\n\n"
            "Recommended themes include analytical ability, problem-solving, collaboration, communication and resilience. "
            "Each claim should be tied to a concrete course, project, presentation or research interaction."
        )
        return zh, en

    zh = (
        f"我申请 {school_name} {target_name} 的主线，来自我在 {profile.education.major} 学习中逐渐形成的方向判断。"
        f"{_card_text(motivation, '最初的兴趣并不是一句抽象的热爱，而需要由课程、项目或行业观察来支撑。')}\n\n"
        f"本科阶段，我通过课程和训练建立了申请该方向所需的基础。"
        f"{_card_text(academic, '这里应写入核心课程、成绩、方法训练，以及它们如何支撑目标项目。')}"
        "这一部分在正式稿中不应只罗列课程名称，而要说明这些训练如何改变了我理解问题、拆解问题和验证结论的方式。"
        "如果后续能补充成绩单、核心课程成绩或课程项目，系统应继续把这些事实绑定到文书句子中。\n\n"
        f"更重要的是，我在实践中把这些知识转化为解决问题的能力。"
        f"{_card_text(practical, '这里应写入一段最强故事：问题是什么、你做了什么、结果如何、你学到什么。')}"
        "正式版本需要继续补充我在其中承担的具体角色、使用的方法或工具、遇到的限制、如何验证结果，以及这段经历为什么能证明我适合目标专业。"
        "这样文书才不会停留在经历拼接，而是能形成清楚的能力证据链。\n\n"
        f"选择 {target_name}，是因为我希望把已有训练推进到更系统的研究生阶段。{why_program} "
        "在正式提交前，我会继续把 Why Program 部分绑定到项目官网中的课程、培养目标或申请要求，确保每一处项目匹配都有来源。\n\n"
        f"毕业后，我希望{career_goal}。因此，这份文书不只是回顾已有经历，也是在说明我为什么需要这个项目，以及我能如何把过去的训练转化为下一阶段的贡献。"
    )
    en = (
        f"My decision to apply for {target_name} at {school_name} has grown out of my training in {profile.education.major} "
        "and my gradual understanding of the problems I hope to solve. "
        f"{_card_text_en(motivation)}\n\n"
        "During my undergraduate study, I built the academic foundation required for this direction through relevant coursework, "
        "analytical training and repeated project practice. "
        f"{_card_text_en(academic)} "
        "Rather than treating these courses as isolated requirements, I began to understand them as a connected toolkit: they helped me move from observing a phenomenon to asking a sharper question, selecting an appropriate method, and checking whether my conclusion was supported by evidence. "
        "This academic preparation is still incomplete, and the final version of this statement should be strengthened with transcript-backed course names, grades and project details, but it already gives the application a concrete academic base.\n\n"
        "Beyond classroom learning, I became increasingly aware that meaningful professional or research work requires the ability to define a problem, "
        "choose appropriate methods, execute carefully and evaluate outcomes honestly. "
        f"{_card_text_en(practical)} "
        "What matters most in this experience is not simply that I participated in a project, but that I learned to connect context, action and result. "
        "For the submission-ready draft, this paragraph should be further developed with the exact responsibility I held, the methods or tools I used, the scale of the work, the difficulty I encountered, and the evidence that the outcome was meaningful.\n\n"
        "This experience also clarified the gap between my current preparation and the level of training I need next. "
        "I do not want to use graduate study as a decorative credential; I need a structured environment where I can deepen my disciplinary foundation, test my ideas against more rigorous standards, and learn how people in the field frame problems at a higher level. "
        "That is why the target programme must be discussed through verified curriculum, learning outcomes, project requirements or official application information rather than generic praise.\n\n"
        f"I am therefore drawn to {target_name} because it can provide a more systematic graduate-level environment for my next stage of development. "
        f"{why_program} Before final submission, the Why Programme paragraph should be further tied to verified official courses, learning outcomes, capstone options, laboratories, professional tracks or application requirements. "
        "Any unverified course, professor, admission preference or career outcome should remain outside the final draft until it has a source.\n\n"
        f"In the long term, I hope to {career_goal}. I see this application not only as a summary of what I have done, "
        "but also as a reasoned step toward the kind of work I am prepared to pursue with greater depth and responsibility. "
        "The next revision should therefore focus on three things: making each story more specific, binding the programme-fit paragraph to official evidence, and removing any claim that cannot be supported by the student's own materials."
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
    target_name = _target_name(target)
    school_name = _school_name(target)
    evidence_notes = []
    for card in story_cards[:4]:
        evidence_notes.append(
            f"In revising this statement, the experience titled '{card.title}' should be developed with its situation, "
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
    status = target.program.data_status.value
    source_note = "学校信息已确认" if status == "VERIFIED" else "当前项目信息仍需回到学校官网确认"
    return (
        f"目前可确认的目标是 {target.program.institution_zh or target.program.institution} "
        f"{target.program.name_zh or target.program.name}，数据状态为 {status}，{source_note}。"
    )


def _card_text(card: StoryCard | None, fallback: str) -> str:
    if not card:
        return fallback
    parts = [card.situation, card.task, card.action, card.result, card.reflection]
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return text or fallback


def _card_text_en(card: StoryCard | None) -> str:
    if not card:
        return "This section needs a concrete student-provided story before it can become submission-ready."
    text = _card_text(card, "")
    return text or "This section needs a concrete student-provided story before it can become submission-ready."


def _review_flags(story_cards: list[StoryCard], target: ProgramMatch | None) -> list[str]:
    flags: list[str] = []
    if not story_cards:
        flags.append("尚未填写足够故事素材，当前稿件只能作为结构示例。")
    if target is None:
        flags.append("尚未指定具体学校/项目，Why Program 不能进入最终稿。")
    elif target.program.data_status.value != "VERIFIED":
        flags.append("目标项目信息尚未完成学校官网确认，Why Program 需要人工绑定课程、培养目标或申请要求。")
    return flags


def _school_customization(target: ProgramMatch | None, document_type: DocumentType) -> list[str]:
    if not target:
        return ["尚未选定学校/项目，不能写最终版 Why Program。"]
    program = target.program
    items = [
        f"目标项目：{program.institution_zh or program.institution} - {program.name_zh or program.name}",
        f"学院/开设单位：{program.school_zh or program.school}",
        f"数据状态：{program.data_status.value}，未确认信息不得写成确定事实。",
    ]
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
        items.append("目标项目信息待学校官网确认，Why Program 只保留为草稿。")
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


def _risk_controls(story_cards: list[StoryCard], target: ProgramMatch | None) -> list[str]:
    controls = [
        "不得编造奖项、实习、课程、教授或录取概率。",
        "英文稿提交前需要人工降重、查重和 AI 痕迹检查。",
        "所有项目匹配论述必须绑定官网、申请系统或项目 PDF。",
    ]
    if any(card.completeness < 60 for card in story_cards):
        controls.append("部分故事卡完整度不足，当前稿件更适合做结构样例。")
    if target and target.program.data_status.value != "VERIFIED":
        controls.append("目标项目信息尚未完成学校官网确认，Why Program 暂不能进入最终稿。")
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
    story_text = str(
        by_id.get("best_story_problem")
        or by_id.get("practical_examples")
        or by_id.get("experience_process")
        or ""
    )
    technical = str(by_id.get("role_actions") or by_id.get("technical_role") or by_id.get("discipline_bridge") or by_id.get("ba_to_cs_bridge") or "")
    result = str(by_id.get("result_validation") or by_id.get("data_scale_validation") or by_id.get("experience_result") or "")
    reflection = str(by_id.get("career_transfer") or by_id.get("why_program_binding") or by_id.get("discipline_bridge") or "")
    if not any([story_text, technical, result, reflection]):
        return []
    return [
        StoryCard(
            id="interview_story_1",
            title="学生访谈故事卡",
            category="project",
            situation=story_text,
            task=story_text,
            action=technical,
            result=result,
            reflection=reflection,
            related_skills=[item for item in ["Python", "SQL", "建模", "系统设计", "研究", "沟通", "分析", "写作"] if item.lower() in technical.lower()],
            target_program_relevance=[str(by_id.get("why_program_binding") or "")],
            evidence_ids=["writing-interview"],
            completeness=80 if technical and result and reflection else 55,
        )
    ]


def _word_count_status(word_count: int) -> str:
    if word_count == 0:
        return "尚未生成英文草稿"
    if word_count < 450:
        return f"约 {word_count} 词，可能偏短"
    if word_count > 1000:
        return f"约 {word_count} 词，通常需要压缩"
    return f"约 {word_count} 词，需按目标项目要求微调"
