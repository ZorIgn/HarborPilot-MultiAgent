<div align="center">

# ⚓ HarborPilot Multi-Agent

**面向港新授课型硕士申请的、可追溯的 Supervisor-based Multi-Agent System**

把学生背景、项目目录、证据状态、确定性申请规则和人工审核组织为一个可暂停、可恢复、可审计的申请准备运行时。

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![Runtime](https://img.shields.io/badge/runtime-Supervisor--based-6C5CE7)](#️-系统架构)

[项目简介](#-项目简介) · [核心能力](#-核心能力) · [系统架构](#️-系统架构) · [快速开始](#-快速开始) · [数据与使用边界](#️-数据与正式使用边界)

</div>

---

## 📖 项目简介

HarborPilot 协助学生完成背景评估、项目研究、择校、证据核验、申请规划和文书准备。它的主路径是一个 **Supervisor-based Multi-Agent Runtime**：Supervisor 根据共享状态选择下一位专职 Agent，而不是按固定 Python 函数链依次调用多个类。

它不是多个聊天机器人自由对话，也不把每个确定性函数都包装成 Agent。模型（在模型驱动模式启用时）负责判断、路由、信息取舍、冲突处理与写作；可重复的计算、检索、规则检查和证据操作由强类型 Tool 执行。

系统不会给出录取保证或“保录”结论。匹配结果中的策略分数是 <code>heuristic strategy score</code>，不是录取概率；预算、个人偏好、招生资格、申请人匹配度和数据可信度也被刻意分开表示。

## 🏗️ 系统架构

~~~mermaid
flowchart TB
    U["学生资料 / 目标 / 补充消息"] --> R["Workflow Runtime"]
    R --> S["SupervisorAgent<br/>动态路由与任务拆解"]
    S --> A["专职 Agent<br/>Assessment · Research · Matching"]
    S --> V["专职 Agent<br/>Verification · Planning · Writing · Critic"]
    A --> X["Agent Executor"]
    V --> X
    X --> T["Tool Registry<br/>Pydantic 参数 / 结果校验"]
    T --> D["确定性服务与项目目录<br/>证据图 / SQLite"]
    T --> O["经安全网关访问的外部官方来源"]
    X <--> ST[("Typed Shared AgentState")]
    S <--> ST
    V -->|"PASS / REPLAN / REVERIFY / REWRITE"| S
    R --> C["Checkpoint / Resume"]
    X --> TR["真实 Runtime Trace"]
    V --> H{"Human Gate"}
    H -->|"批准或人工结论"| C
~~~

运行时以 Pydantic <code>AgentState</code> 作为唯一共享状态，并在每个 Agent turn 后保存 checkpoint。默认上限为：40 个 workflow step、每个 Agent 8 turn、每个 turn 6 轮 Tool、总计 80 次 Tool Call、8 次 Supervisor replan。超过限制会明确失败，而不会无限循环。

<code>MultiAgentRuntime</code> 支持注入 OpenAI-compatible provider 并开启 <code>model_driven=True</code>：真实 provider 的 tool calls 会被解析后送入同一个执行器。当前 HTTP Runtime API 的默认构造路径不注入 provider，使用可复现的确定性决策策略；这让本地运行、测试和 deterministic eval 不会把 mock 结果宣称为真实模型质量。

## 🛠️ 技术栈

| 领域 | 选型 |
| --- | --- |
| 后端 | Python 3.11+、FastAPI、Pydantic、Uvicorn |
| 前端 | Next.js 15、React 19、TypeScript、Lucide |
| 数据 | SQLite、项目快照、字段级证据记录 |
| 模型 | OpenAI-compatible API；可使用确定性本地策略或受控 provider |
| 来源处理 | HTTPS 安全网关、robots 检查、页面哈希、字段抽取与冲突比较 |
| 部署 | Docker Compose |

## ✨ 核心能力

- 👤 **背景评估** —— 整理学校、GPA、语言、课程、经历、预算与职业目标，提示资料缺口和需要优先核对的条件。
- 🧭 **项目研究与择校** —— 结合项目目录、招生资格、偏好、费用和数据可信度，形成有依据的申请组合。
- 🔍 **官方来源核验** —— 把官网页面、申请轮次、字段候选、冲突与人工审核状态放在同一条证据链中。
- 📅 **申请规划** —— 区分准备时间线与正式时间线，避免把未核验的日期当作递交依据。
- ✍️ **文书工作台** —— 通过经历问卷、故事卡、事实绑定和写作审查组织 PS、CV、Essay 等材料。
- 🧩 **可恢复的协作过程** —— 资料不足时询问学生，来源冲突或高风险操作时交由人工判断，再从 checkpoint 继续。

### 运行时中的八个 Agent

运行时中的专职角色由 <code>build_agent_registry()</code> 组装，并在实际执行 trace 中体现：

| Agent | 负责什么 | 明确不负责什么 |
| --- | --- | --- |
| <code>SupervisorAgent</code> | 根据目标和共享状态拆分任务、动态选择下一站、处理暂停与结束 | 不直接执行 Tool；不跳过招生资格检查 |
| <code>AssessmentAgent</code> | 归一化背景、发现资料缺口、调用确定性背景评估 | 不编造 GPA、语言成绩或竞争力数据 |
| <code>ResearchAgent</code> | 通过项目目录召回和收窄候选项目 | 不把目录结果说成已核验的官方事实 |
| <code>MatchingAgent</code> | 分别评估招生资格、财务可行性、用户偏好与 applicant fit，并构建项目组合 | 不修改官方门槛；不把预算当招生资格 |
| <code>VerificationAgent</code> | 核查官方字段缺口、证据可信度和冲突，必要时请求人工结论 | 不把社区信息发布为官方要求；不自行覆盖冲突 |
| <code>PlanningAgent</code> | 生成证据门控的申请准备与官方时间线 | 不把未核验字段写成正式截止日期 |
| <code>WritingAgent</code> | 组织学生事实、项目证据、故事卡和文书草稿 | 不编造申请人经历或无来源的项目事实 |
| <code>CriticAgent</code> | 对推荐、来源与写作执行确定性审查，并要求 replan / reverify / rewrite | 不自动解决冲突证据 |

确定性的归一化、审计、时间线与数据维护能力位于 Tool、Policy、Service 和 Eval 层；兼容入口只把既有 API 转发到同一运行时，不把这些能力另行包装成 Agent 角色。

### Agent、Tool、Policy 与人工审核

| 层 | 运行方式 | 边界 |
| --- | --- | --- |
| **Agent** | 返回强类型 <code>AgentDecision</code>：调用 Tool、handoff、询问用户、人工审核、完成或失败 | 选择下一步，不能直接访问任意服务或直接改写 state |
| **Tool** | 由 <code>ToolRegistry</code> 执行；输入与输出均为 Pydantic 模型 | 负责确定性操作，如背景归一化、目录检索、资格检查、证据比较、时间线和故事卡 |
| **Policy** | 权限、来源安全、正式使用门禁和运行限制 | 限制每个 Agent 可用的 Tool；拒绝不安全 URL；防止无穷循环与无依据正式结论 |
| **Human Gate** | Tool 或 Agent 返回 <code>WAITING_HUMAN</code>，保存 checkpoint | 高风险证据绑定 / 审核候选需要批准；官方来源冲突不能自动解决 |
| **Eval** | 独立 deterministic suite，从 trace 断言运行行为 | 评估路由、Tool 使用、暂停恢复、预算与资格分离、证据门禁等；不把 mock 当作真实 LLM 质量 |

每次 Tool Call 都先检查 Agent allowlist、再校验参数、执行、校验输出，并自动写入 <code>TOOL_CALL</code> 与 <code>TOOL_RESULT</code> trace。外部网页内容始终视为不可信数据；来源网关仅允许安全 HTTPS URL，并防范 localhost、私网、保留地址、非标准端口与不安全跳转。API key 不应进入 trace、state、checkpoint 或前端存储。

## 🔄 运行示例

图中的边是能力边，不是固定 DAG。系统会依据资料完整度、项目匹配、来源可信度和用户目标选择下一步，例如：

- <code>AssessmentAgent → ASK_USER</code>：正式建议缺少语言等关键资料；
- <code>MatchingAgent → ResearchAgent</code>：需要扩大或修正项目召回；
- <code>VerificationAgent → VerificationAgent</code>：逐项目多轮核验；
- <code>CriticAgent → MatchingAgent / VerificationAgent / WritingAgent</code>：分别触发重新匹配、重新核验或重写；
- 任意需要人类判断的来源冲突：<code>WAITING_HUMAN → resume</code>。

下面以“语言成绩缺失、补充后继续形成项目建议”为例说明运行形态。具体候选项目、Tool 数量和路径由状态决定，系统只呈现实际发生的执行步骤与关联关系。

~~~text
WORKFLOW_STARTED
SUPERVISOR_ROUTE       selected=AssessmentAgent
HANDOFF                SupervisorAgent -> AssessmentAgent
AGENT_STARTED          AssessmentAgent
TOOL_CALL / RESULT     normalize_profile
TOOL_CALL / RESULT     find_profile_gaps
TOOL_CALL / RESULT     inspect_evidence_readiness
TOOL_CALL / RESULT     calculate_profile_assessment
AGENT_DECISION         ASK_USER（缺少语言成绩）
CHECKPOINT
USER_WAIT              status=WAITING_USER

POST /api/agent/workflows/{id}/resume
RETRY                  workflow resumed
SUPERVISOR_ROUTE       selected=AssessmentAgent
...                    reassess with the supplemented profile
SUPERVISOR_ROUTE       selected=ResearchAgent
TOOL_CALL / RESULT     search_program_catalog
SUPERVISOR_ROUTE       selected=MatchingAgent
TOOL_CALL / RESULT     evaluate_admissions_eligibility
TOOL_CALL / RESULT     evaluate_financial_feasibility
TOOL_CALL / RESULT     evaluate_user_preference
TOOL_CALL / RESULT     calculate_applicant_fit
TOOL_CALL / RESULT     build_program_portfolio
SUPERVISOR_ROUTE       selected=VerificationAgent
TOOL_CALL / RESULT     get_program_trust_detail
TOOL_CALL / RESULT     list_missing_official_fields
TOOL_CALL / RESULT     compare_evidence_records
SUPERVISOR_ROUTE       selected=CriticAgent
AGENT_DECISION         PASS
WORKFLOW_COMPLETED
~~~

<code>GET /api/agent/workflows/{id}/trace</code> 返回来源于这些真实操作的事件，包括 Agent、Tool、Tool Call ID、简要输入/输出、错误、时间和可用的 provider 元数据。成本仅按 provider 报告的 token 与 <code>data/model_pricing.json</code> 中的显式价格计算；未知价格或未知 token 保持 <code>null</code>，绝不根据耗时估算成本。

## 🖥️ 页面与 API

### 主要页面

| 页面 | 用途 |
| --- | --- |
| <code>/assessment</code> | 背景竞争力评估与资料缺口 |
| <code>/programs</code> | 项目目录、匹配维度与信息可信度 |
| <code>/timeline</code> | 逐项目准备时间线与材料 |
| <code>/writing</code> | 故事卡、事实绑定与文书草稿 |
| <code>/agent-lab</code> | workflow 状态、来源证据与运行轨迹 |

### Agent Runtime API

工作流接口用于创建、查看、恢复和追溯一次申请准备过程；既有 <code>/api/workflows/*</code> 接口继续为已有客户端保留响应兼容性。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| <code>POST</code> | <code>/api/agent/workflows</code> | 创建并立即运行一个 workflow |
| <code>GET</code> | <code>/api/agent/workflows</code> | 列出 workflow（管理员） |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}</code> | 读取当前持有者可访问的工作流快照 |
| <code>POST</code> | <code>/api/agent/workflows/{workflow_id}/resume</code> | 提供用户补充或人工结论并恢复 |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}/trace</code> | 读取真实 Runtime Trace |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}/state</code> | 读取最近 checkpoint 的 typed state |

创建请求的 <code>goal</code> 支持 <code>BACKGROUND_ASSESSMENT</code>、<code>PROGRAM_RECOMMENDATION</code>、<code>APPLICATION_PLANNING</code>、<code>WRITING</code> 和 <code>FULL_APPLICATION_PLAN</code>，也接受对应的小写值。<code>profile</code> 可先提交部分资料；缺少专业、GPA、语言等关键字段时，AssessmentAgent 会保存 checkpoint 并返回 <code>WAITING_USER</code>，而不是在 HTTP 层丢弃请求。完整档案可从 [examples/sample_profile.json](examples/sample_profile.json) 开始。

~~~json
POST /api/agent/workflows
{
  "goal": "PROGRAM_RECOMMENDATION",
  "profile": { "...": "可先提交部分学生档案，完整示例见 examples/sample_profile.json" },
  "user_request": "希望寻找香港和新加坡的数据分析硕士项目",
  "selected_program_ids": [],
  "document_type": "PS"
}
~~~

当返回状态为 <code>WAITING_USER</code> 或 <code>WAITING_HUMAN</code> 时，使用同一 workflow ID 恢复。用户消息可包含小型 JSON 背景补丁；人工结论可包含 <code>approved_tools</code> 或冲突处理信息。

~~~json
POST /api/agent/workflows/{workflow_id}/resume
{
  "user_message": "{\"language\": {\"test\": \"IELTS\", \"overall\": 7.0, \"writing\": 6.5}}",
  "human_resolution": null
}
~~~

## 🚀 快速开始

### 1. 后端

~~~bash
git clone https://github.com/ZorIgn/HarborPilot-MultiAgent.git
cd HarborPilot-MultiAgent

python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev,llm]"
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
~~~

### 2. 前端

~~~bash
cd web
npm install
npm run dev
~~~

默认前端地址为 <http://localhost:3001>，后端为 <http://127.0.0.1:8000>。运行生产构建前可先运行 <code>npm run typecheck</code>。Windows 的 <code>npm run build</code> 使用独立的 <code>next-build</code> 输出目录，避免开发服务与生产构建互相污染。

### 3. Docker

~~~bash
docker compose up --build
~~~

## 🛡️ 数据与正式使用边界

- 招生资格只检查明确招生条件，例如最低 GPA、接受的语言考试与分数、先修背景、学位、作品集或明确工作经验要求。
- 预算属于财务可行性，用户偏好属于策略选择；二者都不等于招生资格。
- 官方字段缺失是 <code>UNKNOWN</code> / 需要核验，不等于申请人不合格。
- 社区来源可用于准备建议和线索，不能自动覆盖或发布为官方要求。
- 截止日期支持申请轮次；冲突证据必须留给人工审核。
- 正式时间线或正式建议会经过证据与 formal gate；任何未核验字段都应保留待复核标记。

## 🔄 数据维护

项目目录、证据快照和审核记录可以分开维护。创建 workflow 时，<code>refresh_official_sources</code> 默认为 <code>false</code>；只有明确开启后才会触发官方来源刷新。刷新得到的内容先作为待核验来源和字段候选使用，不会直接覆盖已发布的官方信息。

## 📂 项目结构

现有客户端可继续使用 <code>/api/workflows/background</code>、<code>/api/workflows/program-plan</code>、<code>/api/workflows/application-plan</code>、<code>/api/workflows/writing-plan</code> 与 <code>/api/workflows/assessment</code>。这些入口通过 <code>WorkflowOrchestrator</code> 与 <code>MultiAgentRuntime</code> 共享同一套工作流状态和证据边界。

~~~text
src/harbor_agent/agents/          八个 Runtime Agent 与兼容 façade
src/harbor_agent/runtime/         State、Decision、Graph、Executor、Checkpoint、Limits
src/harbor_agent/tools/           强类型 Tool 定义与 Registry
src/harbor_agent/policies/        权限、来源安全、正式使用与执行策略
src/harbor_agent/llm/             OpenAI-compatible provider、结构化输出、定价
src/harbor_agent/observability/   Runtime trace、event、usage 与 metrics
src/harbor_agent/evals/           Deterministic Agent Eval runner / assertions
data/agent_eval_cases.json        可重复的评估用例
web/                              Next.js 学生端与 Agent Lab
~~~

## 🧪 验证

如需检查本地环境，可按需要运行：

~~~bash
python -m pytest -q
python -B scripts/run_agent_evals.py

cd web
npm run typecheck
npm run build
~~~

其中 deterministic eval 用于检查路由、工具权限和来源门禁等可重复行为；真实 LLM 的质量、延迟和成本应在受控环境中单独评估，不能用 mock 结果替代。

## ⚠️ 当前边界

HarborPilot 是可信申请信息辅助系统，不替代学校官网、招生办公室、签约顾问或正式法律 / 财务建议。项目库可能包含上一申请季参考、抽取候选或待人工确认字段；在做正式申请决策前，请以当前申请季的官方来源和人工审核结论为准。
