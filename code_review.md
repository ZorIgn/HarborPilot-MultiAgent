# HarborPilot 完整 Code Review 报告
## 多 Agent 留学辅助平台 — 全模块问题清单与改进参考

> **审计日期**：2026-07-10 | **代码库路径**：`e:\multi_agent` | **覆盖范围**：全部 5 个核心模块

---

## 执行摘要

HarborPilot 的整体架构方向正确：多 Agent 分工、字段级证据溯源、人工审核门禁、写作风格隔离。但在**产品完整性、数据真实性、用户体验**三个维度存在大量系统性缺陷。具体而言：

- **背景评估**：维度权重硬编码，LLM 只改文字不改结论，缺少分专业评估
- **择校推荐**：机构权重写死代码，`formal_recommendation` 因数据永远 EXTRACTED 而永远为 False，推荐结果学生无法看懂
- **时间线**：几乎所有 deadline 均为 NOT_PUBLISHED，时间线全为估算，没有任何自动监控
- **文书写作**：Mock 模式下输出模板框架占位文本，无版本控制，无字数统计，无抄袭检测
- **前端 UI**：全部逻辑集中在一个 42KB 的 `HarborPilotApp.tsx`，没有路由，状态散乱

---

## 一、背景评估模块（ProfileAgent + EvaluationAgent + rules.py）

### 1.1 问题清单

#### 🔴 P0：维度权重永久硬编码，无法按专业调整
```python
# rules.py L20 — 四个维度固定权重，不区分专业方向
average = round((academic * 0.34) + (language * 0.22) + (experience * 0.28) + (readiness * 0.16))
```
**问题**：CS/AI 方向的学生代码作品集重要性远超语言成绩，商科学生的工作经验权重应该更高。用同一套权重给所有方向学生打分，结论不准确。

**参考**：[open-source-cs](https://github.com/ossu/computer-science) 的课程评估按领域分权重；[CollegeAI](https://github.com/topics/college-admission) 类项目均支持 profile-specific weights。

---

#### 🔴 P0：EvaluationAgent 只是 LLM 改写文字，不改分数
```python
# evaluation.py L17-28 — LLM 调用只修改 strengths/weaknesses/actions 文本
result.strengths = completion.get("strengths", result.strengths)[:5]
# 分数从未被 LLM 修改，永远来自 rules.py 的纯规则计算
```
**问题**：名为"多 Agent"，实际上 EvaluationAgent 只是把 LLM 当成文字润色器。GPA 评分函数是固定阶梯（如 85分对应固定分段），完全无法捕捉"双非 Top 5%"vs"985 Bottom 30%"的差异。

---

#### 🔴 P0：profile_completeness 计算公式荒谬
```python
# profile.py L59
completeness = max(30, 100 - len(missing) * 8)
```
**问题**：8个缺失字段 → completeness = 36；0个缺失 → 100。但"缺少预算"和"缺少语言成绩"的严重性完全不同。用缺失字段数乘8这种线性公式，没有任何区分度。

---

#### 🟡 P1：学校层级 Tier 映射不完整
```python
# profile.py L95 — school_tier 只有固定枚举
school_tier: Literal["C9", "985", "211", "double_first_class", "regular", "overseas", "unknown"]
```
**问题**：海外学校没有进一步细分（如 QS 100 海外 vs 普通海外），`overseas` 和 `unknown` 在 rules.py 里获得相同 bonus = 0，不合理。

---

#### 🟡 P1：缺少跨专业背景评估
**问题**：一个学金融的学生申请 CS 程序，ProfileAgent 不会生成任何"跨专业风险"提示，只有 DISCIPLINE_KEYWORDS 的简单匹配。跨专业是港新申请中最常见的场景，但系统完全无视。

---

#### 🟢 P2：语言成绩缺单项分析
**问题**：`LanguageScore` 模型收集了 writing/speaking/reading/listening 四项，但 `_score_language()` 只看 overall。部分项目（如 CUHK 某些项目）对单项有强制要求，系统完全忽略。

---

### 1.2 GitHub 参考项目
| 参考项目 | 用途 |
|----------|------|
| [admissions-data](https://github.com/yunlongzhang0626/us-grad-application) | 参考实际录取数据驱动的评估维度设计 |
| [GPACalculator](https://github.com/topics/gpa-calculator) | GPA 跨制度换算参考 |
| [university-ranking-data](https://github.com/yuhao-yang/qs-ranking) | QS 排名数据结构化处理 |

---

## 二、择校推荐模块（SchoolMatchingAgent + intent.py + matching_strategy）

### 2.1 问题清单

#### 🔴 P0：formal_recommendation 永远为 False
```python
# matching.py L79
formal = recommendable and program.data_status == DataStatus.verified
```
**问题**：`programs_2027_fall.json` 中所有程序的 `data_status` 均为 `"EXTRACTED"`，因此 `formal_recommendation` 永远是 `False`。这意味着**系统从未给出过任何正式推荐**，所有推荐都带有 "数据未核验" 的 source_warning。学生看到的推荐列表完全是"建议性的"，但界面上没有清楚说明这一点。

---

#### 🔴 P0：机构权重完全写死在代码里
```python
# matching.py L19-38
ELITE_INSTITUTIONS = {
    "national university of singapore": 5.25,
    "the university of hong kong": 5.15,
    ...
}
```
**问题**：NUS > HKU > NTU > HKUST > CUHK 这套排序是开发者主观判断写入代码的。没有任何 UI 让管理员调整，没有版本控制，每次排名变化都需要改代码。这与 `matching_strategy.json` 的设计意图矛盾。

---

#### 🔴 P0：fit_score 公式不透明，学生无法理解
```python
# matching.py L68-76
fit = (
    _weighted_fit(score_breakdown, base)
    - risk_penalty     # -12 if hard rule fails
    + _intent_fit_adjustment(intent)     # -10 to +8
    + _institution_priority_adjustment(...)  # -5 to +5
)
fit = max(10, min(96, fit))
```
**问题**：最终 fit_score 是多项叠加的结果，但学生只看到一个数字（如 "78分"），完全不知道为什么是这个分数，哪个维度拉低了，如何改进。虽然有 `score_breakdown`，但前端没有展示维度详情。

---

#### 🟡 P1：硬规则 "失败" 只扣 12 分，不淘汰
```python
# matching.py L67,74-75
risk_penalty = 12 if not hard_ok else 0
if intent.category == "blocked":
    fit = min(fit, 38)
```
**问题**：语言不达标（严格硬规则）的学生，仍然会看到该项目出现在推荐列表中（只是分数低了 12 分，上限 38 分）。对学生来说，这造成误导：他们可能认为自己有机会，但实际上被硬性拒绝了。

---

#### 🟡 P1：discipline 匹配只用 tag overlap，忽略 Why Program 逻辑
```python
# matching.py L63
overlap = len(set(program.discipline_tags) & set(profile.discipline_tags))
```
**问题**：一个 AI 方向的学生的 `discipline_tags` 和 Business Analytics 项目有 0 重叠，但该学生可能有充分的理由申请 BA 项目（如产品经理转型）。这种简单集合交集完全无法处理跨领域申请的合理性。

---

#### 🟡 P1：推荐结果缺少"为什么推荐这个项目"的具体化
**问题**：`reasons` 最多返回 5 条，但内容都是模板化文字（如"学术成绩可支撑...项目"），没有具体到"你的 GPA 85.7 达到该项目 83 的要求，但排名未提供会导致不确定性"。学生无法从推荐结果中学到任何有价值的信息。

---

#### 🟡 P1：没有"我为什么不能申请"的解释
**问题**：被 block 的程序只有一个 `not_recommended` tier，没有清晰解释"你的 IELTS 6.0 低于该项目 6.5 要求"。这是用户体验的核心需求，完全缺失。

---

#### 🟢 P2：推荐列表没有对比视图
**问题**：用户选了 10 个学校后，无法并排对比截止日期、学费、语言要求等关键字段。现有的数据结构支持这种展示，但前端和 API 都没有提供对比功能。

---

### 2.2 GitHub 参考项目
| 参考项目 | 用途 |
|----------|------|
| [qs-master-applications](https://github.com/lione12138/qs-master-applications) | 项目已在 source_registry 中，可参考数据结构和评估方法 |
| [gradschool-scorecard](https://github.com/topics/graduate-school) | 参考多维度分项展示方式 |
| [college-match](https://github.com/topics/college-application) | 参考 match/safety/reach 分层展示 |
| [openai-college-counselor](https://github.com/topics/college-counselor) | 参考 LLM + rule-based hybrid 的推荐架构 |

---

## 三、时间线模块（TimelineAgent + timeline.py）

### 3.1 问题清单

#### 🔴 P0：几乎所有截止日期均为 NOT_PUBLISHED
```python
# timeline.py L136
official_deadline="NOT_PUBLISHED",
# 大量任务的 round_deadline 都是 "NOT_PUBLISHED"
```
**问题**：由于 `programs_2027_fall.json` 的 `last_verified_at` 全为 null，`formal_timeline_ready()` 对所有程序返回 False。这意味着时间线上的所有具体程序任务都走 `not formal_ready` 分支，没有任何官方截止日期，全是"参考"。

**用户体验**：学生打开时间线，看到的是一堆"请核验官网"的任务，没有任何具体的提交截止日期。这个时间线功能对学生来说几乎没有实际价值。

---

#### 🔴 P0：时间线任务的 due_date 来自去年日期 +1 年的推算
```python
# timeline.py L311-315
while shifted < today:
    try:
        shifted = shifted.replace(year=shifted.year + 1)
```
**问题**：`_planning_reference_date()` 把上一申请季的日期直接加一年来推算。这对于申请系统开放时间不固定的学校（如部分 NUS 项目）会产生严重偏差。

---

#### 🔴 P0：时间线任务没有 iCal / 日历导出
**问题**：所有截止日期都在系统内，学生无法一键导出到 Google Calendar / Apple Calendar。这是留学申请平台的标配功能，完全缺失。

---

#### 🟡 P1：多轮次申请完全未支持
**问题**：许多学校有 Round 1/2/3 的申请轮次（如 NUS 3 轮），但 `TimelineTask` 模型只有 `program_round: str` 一个字段（且基本都填"主轮次"）。系统无法展示多轮次申请的战略选择（如"R1 冲刺 A，R2 保底 B"）。

---

#### 🟡 P1：共有任务和程序任务混在一起，优先级不清晰
**问题**：`source_review`、`common_transcript`、`common_cv` 等共有任务和各项目的 `prepare_X`、`essay_X` 任务排在同一个平铺列表中（按 due_date 排序）。学生看到一个 20+ 条的混杂任务列表，不知道先做什么。

---

#### 🟡 P1：没有任务完成状态的持久化
**问题**：`TimelineTask.status` 字段有"未开始"/"准备中"/"需复核"等状态，但这个状态从不被保存。每次刷新页面，所有任务都重新生成，之前标记的"已完成"全部丢失。

---

#### 🟢 P2：没有截止日期预警机制
**问题**：距离 deadline 14 天/7 天/3 天没有任何主动提醒。用 `reminder_at = due_date - 7 days` 计算了提醒时间，但没有任何机制实际发出提醒（邮件/推送/站内信）。

---

#### 🟢 P2：材料 checklist 是字符串列表，不是可交互的 checkbox
```python
# timeline.py L216
materials=["transcript", "degree_certificate", "language_score", "recommendation", "cv", "personal_statement"],
```
**问题**：materials 是字符串列表，前端只能展示文字，不能让学生勾选"已完成"。

---

### 3.2 GitHub 参考项目
| 参考项目 | 用途 |
|----------|------|
| [grad-application-tracker](https://github.com/topics/grad-school-application) | 参考申请跟踪系统的任务状态管理 |
| [application-deadline-tracker](https://github.com/topics/college-application-tracker) | 截止日期跟踪 + 提醒功能 |
| [ical.js](https://github.com/niccokunzmann/python-recurring-ical-events) | iCal 日历生成（Python 端） |
| [react-big-calendar](https://github.com/jquense/react-big-calendar) | 前端日历视图参考 |

---

## 四、文书写作模块（WritingAgent + StoryCardAgent + writing.py）

### 4.1 问题清单

#### 🔴 P0：Mock 模式输出模板占位文字，学生以为是真实草稿
```python
# writing.py L124
draft_zh, draft_en = _local_draft(profile, target, story_cards, doc_type)
# 当 llm.name == "mock" 时，直接返回这个本地草稿
```
**问题**：`_local_draft()` 在 Mock 模式下返回的是模板框架文字（如"[请根据你的实际经历补充开篇触发事件]"）。但如果用户不知道系统处于 Mock 模式，他们会误以为这是 AI 生成的真实草稿。界面上没有任何明显的"演示模式"提示。

---

#### 🔴 P0：WritingDraft 没有版本控制，修改后旧版消失
```python
# writing.py L232-250
return WritingDraft(
    version_id="v1-student-story",  # 永远是 v1
    ...
)
```
**问题**：每次调用 writing-plan 接口，都生成一个全新的 `version_id="v1-student-story"` 的草稿，覆盖之前的内容。学生如果对草稿进行了手动修改，重新运行后会全部丢失。缺少版本历史功能是文书写作工具的致命缺陷。

---

#### 🔴 P0：故事卡生成完全依赖 questionnaire 格式，但问卷是静态的
```python
# story_card.py L12-13
grouped = _answers_by_id(questionnaire)
academic = _first(grouped, "academic_strength", "core_courses", "gpa_rank")
```
**问题**：StoryCardAgent 的故事卡生成依赖特定的问卷 ID（如 `academic_strength`、`practice_problem`）。如果问卷没有这些字段，故事卡就是空的。但问卷设计和故事卡生成之间没有任何文档化的 mapping，维护时极易出错。

---

#### 🔴 P0：Why Program 部分没有真实官网数据支撑
```python
# writing.py L25
"Why Program 只绑定项目官网、申请系统或官方 PDF 中可确认的信息；未核验课程、教授、就业数据和录取概率不得写入。"
```
**问题**：规则写得很好，但由于项目的 `official_program_url` 指向目录页而非详情页，`essay_prompts` 字段全为空，系统实际上没有任何真实的学校信息可以绑定。写出来的 Why Program 只能靠 LLM 虚构，与规则完全矛盾。

---

#### 🟡 P1：单一 LLM 调用生成全部内容，质量难以控制
```python
# writing.py L136-176 — 一次 complete_json 调用生成 8 个字段
schema_hint={
    "title": "string",
    "outline": ["string"],
    "draft_zh": "string",
    "draft_en": "string",
    ...
}
```
**问题**：一次 LLM 调用要同时生成大纲、中文草稿、英文草稿、风险控制等 8 个输出。这种做法导致每个输出的质量都无法单独控制，且 token 限制使得输出经常被截断。参考 [LangChain multi-step chains](https://github.com/langchain-ai/langchain) 的做法，应该拆分为多个专注的 LLM 调用。

---

#### 🟡 P1：没有字数统计和字数控制
**问题**：代码中只有一个简单检查：
```python
if doc_type in {"PS", "SOP", "ESSAY"} and len(draft_en.split()) < 620:
    flags.append("真实模型返回的英文稿偏短...")
```
但不同学校对字数要求差异极大（500-1500词），系统没有按具体学校的 `essay_prompts` 字段调整目标字数。

---

#### 🟡 P1：文书草稿没有抄袭检测
**问题**：系统声明"不得复制句子"，但没有任何机制检测最终输出是否包含模板文字或常见套话。

---

#### 🟡 P1：推荐信模块（REFERENCE_PACKAGE）功能不完整
**问题**：推荐信类型的规则写了很多（只写推荐人能观察的事实），但 `_reference_package()` 函数只返回一个字符串列表，没有：
- 推荐人填写界面
- 不同推荐人（学术/工作）的模板区分
- 推荐信提交方式（邮件/系统上传）的说明

---

#### 🟢 P2：面试问题（WritingInterviewQuestion）没有保存机制
```python
# writing.py L252-280 — interview_questions 每次重新生成
```
**问题**：学生每次进入 Writing Interview 都会看到重新生成的问题。之前的回答没有保存，学生需要重新填写。

---

#### 🟢 P2：缺少文书对比功能（不同学校版本）
**问题**：PS 面向不同学校需要定制（Why Program 不同），但系统没有支持"为 HKU CS 版本"和"为 NUS CS 版本"分别维护的功能。

---

### 4.2 GitHub 参考项目
| 参考项目 | 用途 |
|----------|------|
| [essay-grader](https://github.com/topics/essay-grader) | 文书评分和反馈机制 |
| [langchain-writing-assistant](https://github.com/langchain-ai/langchain) | 多步 chain 生成高质量文书 |
| [notion-clone](https://github.com/topics/notion-clone) | 块编辑器实现版本历史 |
| [plagiarism-detector](https://github.com/plagiarismcheck/plagiarism-check) | 文书抄袭/套话检测 |
| [quill](https://github.com/quilljs/quill) | 富文本编辑器（支持内联批注） |

---

## 五、前端与整体产品体验（HarborPilotApp.tsx + 其他页面）

### 5.1 问题清单

#### 🔴 P0：全部核心逻辑集中在一个 42KB 的文件
```
web/app/HarborPilotApp.tsx  — 42,072 字节，单个组件
```
**问题**：背景评估、择校、时间线、文书写作的全部状态管理和 UI 逻辑都在同一个文件里。这导致：
- 任何一个功能的修改都可能破坏其他功能
- 代码不可测试
- 新功能无法独立开发
- 性能问题（整个应用在每次状态变化时重渲染）

---

#### 🔴 P0：用户填写的表单数据通过 Cookie + 本地文件保存，没有账户系统
```python
# app.py L258-268 — 基于 Cookie 的 profile_id
candidate = "student_" + secrets.token_urlsafe(18)
response.set_cookie(PROFILE_COOKIE_NAME, ...)
```
**问题**：学生的所有数据（profile、择校结果、草稿）存在 Cookie 和服务器本地文件中。换一台设备，所有数据丢失。没有账户注册/登录系统。这对于一个要保存"文书草稿"的平台是无法接受的。

---

#### 🔴 P0：没有引导式 Onboarding 流程
**问题**：用户进入平台后，面对一个大表单（个人信息、教育背景、语言成绩、经历...）没有任何引导。留学申请是一个复杂的多步骤过程，用户需要：
1. 明确知道平台能做什么
2. 一步一步填写信息
3. 即时看到部分结果来保持动力

---

#### 🔴 P0：数据可信度提示对学生不友好
**问题**：当数据 `data_status = EXTRACTED` 时，前端只是在某些字段旁显示一个小图标或文字"数据未核验"。但对于一个可能因为看到错误截止日期而误申请的学生来说，这种提示远远不够。应该用明显的 Banner 标注哪些数据是估算的。

---

#### 🟡 P1：程序目录页（ProgramCatalogPage）缺少关键功能
- ❌ 没有"对比选中项目"功能（选 A、B、C 后并排对比）
- ❌ 没有收藏夹 / Wishlist（只能整个 selected_program_ids 一起保存）
- ❌ 搜索只是简单的字符串包含，没有模糊搜索
- ❌ 没有分页，全量加载（200+ 项目全部返回）
- ❌ 语言成绩筛选的逻辑有 Bug：`language_min` 过滤的是 `IELTS <= language_min`（含义是接受该分数），逻辑反向

```python
# app.py L676 — 这里的逻辑有问题
items = [program for program in items if program.requirements.language.get("IELTS", 0) <= language_min]
```

---

#### 🟡 P1：没有 Loading 状态管理
**问题**：所有 API 调用（背景评估、择校、时间线生成）可能需要 5-30 秒（LLM 调用）。如果没有明显的 Loading 指示器和进度提示，用户会不知道系统是否在工作，可能多次点击导致重复请求。

---

#### 🟡 P1：错误处理用户不友好
```python
# app.py L380-381
except Exception as exc:
    raise HTTPException(status_code=400, detail=f"模型连接失败：{exc}")
```
**问题**：后端抛出的错误消息直接展示给用户（包含技术细节如 `ConnectionError: ...`）。前端需要将错误转换为用户能理解的语言。

---

#### 🟡 P1：移动端体验未考虑
**问题**：整个平台基于桌面端布局设计（表单字段、多列对比、时间线）。但许多中国学生在手机上查看留学信息，移动端体验完全未被测试或优化。

---

#### 🟡 P1：写作工作区（WritingWorkspace.tsx 55KB）同样过大
**问题**：55KB 的单文件组件，包含问卷、故事卡、草稿编辑、审核的全部逻辑。和 HarborPilotApp.tsx 一样的问题。

---

#### 🟢 P2：没有帮助文档 / FAQ
**问题**：GPA 换算规则、申请材料说明、语言成绩要求——这些都有学生会问的问题，平台没有提供任何内联帮助文档。

---

#### 🟢 P2：API 接口重复（admin 和 student）
```python
# app.py L393-400 — 两个功能完全相同的接口
@app.post("/api/admin/llm-config")
def configure_llm(payload: LLMConfigRequest)
@app.post("/api/llm-config")
def configure_student_llm(payload: LLMConfigRequest)
    return _configure_llm_provider(payload)  # 完全相同
```
**问题**：大量 API 端点存在 admin/student 两个版本，但实现完全相同。这会导致安全配置被绕过（如学生可以调用 `/api/llm-config` 修改 API Key）。

---

### 5.2 GitHub 参考项目
| 参考项目 | 用途 |
|----------|------|
| [yuanrenannie selector](https://yuanrenannie.com/selector) | 已在 source_registry，参考选校工具 UX |
| [next-auth](https://github.com/nextauthjs/next-auth) | Next.js 账户系统 |
| [react-hook-form](https://github.com/react-hook-form/react-hook-form) | 表单状态管理（替代当前手动 state） |
| [tanstack-query](https://github.com/TanStack/query) | API 请求状态管理（loading/error/cache） |
| [zustand](https://github.com/pmndrs/zustand) | 轻量状态管理（替代 prop drilling） |
| [react-big-calendar](https://github.com/jquense/react-big-calendar) | 时间线日历视图 |

---

## 六、多 Agent 架构问题

### 6.1 问题清单

#### 🔴 P0：Agent 名字是字符串标签，不是真实并行 Agent
```python
# data_acquisition.py L104-111
agent_chain=[
    "SourceDiscoveryAgent",
    "OfficialCrawlerAgent",
    "PdfFaqExtractionAgent",
    "CommunitySignalAgent",
    "EvidenceMergeAgent",
    "HumanReviewGateAgent",
]
```
**问题**：这些都只是报告中的字符串标签，不是真实运行的独立 Agent。整个系统实际上是一个单线程同步调用链，不是多 Agent 系统。称为"多 Agent 平台"名不副实。

---

#### 🔴 P0：WorkflowOrchestrator 是同步顺序执行，无并行
```python
# orchestrator.py L64
profile, evidence, assessment = self._profile_evidence_assessment(payload, trace)
```
**问题**：所有 Agent 是串行调用的。对于一个有 10 个目标学校的学生，每个学校的匹配、时间线生成都是顺序执行的。没有利用异步或并行能力。

---

#### 🟡 P1：Agent Worker 系统（SQLite 队列）过于复杂，缺少监控
**问题**：实现了一个基于 SQLite 的 agent job queue，但：
- 没有 Web UI 监控队列状态
- 没有 Worker 进程（需要手动调用 `/api/admin/agent-queue/run-next`）
- 没有 Dead Letter Queue（失败任务的处理）
- SQLite 并发写入限制

---

### 6.2 参考架构
| 参考项目 | 用途 |
|----------|------|
| [crewai](https://github.com/crewAIInc/crewAI) | 真正的多 Agent 协作框架 |
| [autogen](https://github.com/microsoft/autogen) | Microsoft 多 Agent 对话框架 |
| [langchain-agents](https://github.com/langchain-ai/langchain) | LLM Agent 工具调用框架 |
| [celery](https://github.com/celery/celery) | 生产级任务队列（替代 SQLite worker） |

---

## 七、代码质量与工程问题

### 7.1 具体 Bug 清单

| 位置 | Bug | 严重性 |
|------|-----|--------|
| `app.py L676` | `language_min` 筛选逻辑反向（`<=` 应为 `>=`） | 🔴 P0 |
| `app.py L273` | `hmac.new()` 应为 `hmac.new()` 但 Python 标准库是 `hmac.new()` → 实际应为 `hmac.HMAC()` | 🟡 P1 |
| `profile.py L59` | completeness 公式 `max(30, 100 - len(missing) * 8)` 不合理 | 🟡 P1 |
| `source_snapshot.py L253-261` | PyPDF2 fallback 但 requirements.txt 中没有 PyPDF2 | 🔴 P0 |
| `matching.py L79` | `formal_recommendation` 永远 False | 🔴 P0 |
| `catalog_auto_update.py` | 只有 7 个程序有 seed URL，3 个已经 404 | 🔴 P0 |
| `program_url_overrides.json` | HKUST 2 个程序 URL 是 2025-26 旧链接 | 🟡 P1 |

---

### 7.2 架构问题

| 问题 | 详情 |
|------|------|
| **无数据库迁移** | 修改 SQLite schema 需要手动 ALTER TABLE 或重建 |
| **全局可变状态** | `app.py L351: global llm_provider` — 全局变量在多请求环境中不安全 |
| **无测试覆盖率** | `tests/` 目录存在但没有看到针对核心业务逻辑的单元测试 |
| **无 API 文档** | FastAPI 自动生成 OpenAPI，但没有描述每个字段的含义 |
| **配置管理混乱** | 部分配置在 `config.py`，部分在 `.env`，部分硬编码在各 agent 文件中 |
| **日志不规范** | 没有统一的日志格式，错误信息散落各处 |

---

## 八、综合优先级矩阵

```
紧急 × 重要（P0）  →  立即修复
├── 数据可信度：所有数据标注 EXTRACTED，formal_recommendation 永远 False
├── 语言筛选 Bug（app.py L676）
├── PyPDF2 依赖缺失
├── Mock 模式无明显提示
└── 用户数据 Cookie-only，无账号系统

重要但不紧急（P1） → 本次迭代
├── 机构权重外移到配置文件
├── fit_score 维度展示给用户
├── 时间线任务持久化
├── 文书版本控制
├── 程序对比功能
└── 多轮次支持

有价值但可推迟（P2） → 下一迭代
├── iCal 导出
├── 截止日期预警
├── 移动端优化
├── 文书抄袭检测
└── 帮助文档
```

---

## 九、数据真实性专项评级

> 这是影响学生利益最核心的问题

| 字段 | 数据质量 | 用户风险 |
|------|---------|---------|
| 项目名称、院校 | ✅ 真实 | 低 |
| 截止日期 | ⚠️ 估算（全部 2027-01-31） | **极高** — 错过申请 |
| 学费 | ⚠️ 参考（未核验） | 中 — 预算偏差 |
| 语言要求 | ⚠️ 参考（部分准确） | 高 — 申请资格错误 |
| 申请材料清单 | ⚠️ 通用模板 | 高 — 材料不全 |
| 项目页 URL | ❌ 大部分指向目录页 | 高 — 无法获取真实信息 |
| 申请系统 URL | ⚠️ 部分已覆盖（portals.json） | 中 |
| 社区信号 | ❌ 全空 | 低（缺失而非错误） |

**核心结论**：当前平台不应向学生展示截止日期数据，或必须在每个截止日期旁边加明显红色警告"此日期为估算，请核验官网"。

---

## 十、推荐立即行动的 3 件事

1. **前端**：在所有 `data_status != VERIFIED` 的字段旁加红色 Banner："⚠️ 此数据为系统估算，申请前请务必查看[学校官网链接]"
2. **数据**：打开 `HARBORPILOT_USE_PLAYWRIGHT=1`，立即对 HKU/NUS/CUHK 前 5 个热门项目做真实爬取，验证截止日期准确性
3. **文书**：在 Mock 模式下，所有文书输出页面顶部加明显提示"当前处于演示模式，需配置 API Key 才能生成真实内容"
