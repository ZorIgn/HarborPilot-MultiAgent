<div align="center">

# ⚓ HarborPilot Multi-Agent

**面向港新授课型硕士申请的可信、多角色 Agent 工作流**

从学生背景评估到项目匹配、官方证据核验、申请规划与事实约束写作。<br>
用一个可暂停、可恢复、可追溯的 Supervisor-based Multi-Agent Runtime 串联完整流程。

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![Runtime](https://img.shields.io/badge/Runtime-Supervisor--based-6C5CE7)](#-系统架构)

[项目简介](#-项目简介) · [业务流程](#-业务流程) · [系统架构](#-系统架构) · [可信证据与人审](#-可信证据与人审) · [快速开始](#-快速开始) · [验证](#-验证)

</div>

---

## 📖 项目简介

HarborPilot 是一个留学申请辅助系统，围绕四类核心任务组织业务：

- **学生画像与背景评估**：归一化教育背景、GPA、语言、课程、经历、预算和职业目标，并发现关键信息缺口。
- **项目召回与匹配**：从项目目录中召回候选，分别计算招生资格、财务可行性、个人偏好和 applicant fit，再形成选校组合。
- **官方证据核验**：对当前申请季的截止日期、学费、语言、GPA、背景、作品集和材料要求建立字段级证据链。
- **规划与写作**：基于已核验事实生成申请时间线、故事卡和文书草稿，并由 ClaimGraph 与 Critic 检查事实绑定。

系统采用中央 Supervisor 管理模式。每个 Specialist 只负责一个边界明确的任务，完成后将控制权交回 Supervisor；不存在 Specialist 之间直接接管流程的 peer handoff。

## 🔄 业务流程

~~~mermaid
flowchart LR
    P["学生档案"] --> A["背景评估"]
    A -->|"缺少关键资料"| U["WAITING_USER"]
    U --> A
    A --> R["项目召回"]
    R --> M["资格 / 预算 / 偏好 / Fit"]
    M --> V["官方证据核验"]
    V -->|"高风险工具或证据冲突"| H["WAITING_HUMAN"]
    H --> V
    V --> D["DecisionFact / ResolvedProgramView"]
    D --> L["申请规划"]
    D --> W["事实约束写作"]
    L --> C["Critic"]
    W --> C
    C -->|"探索结果可交付，保留 blocker"| P0["PRELIMINARY_COMPLETE"]
    C -->|"正式门禁通过"| F["FORMAL_PASS"]
    C -->|"正式目标仍缺事实"| B["BLOCKED → FAILED_RETRYABLE"]
~~~

<code>WAITING_USER</code> 用于补充学生资料；<code>WAITING_HUMAN</code> 只用于存在明确操作对象的工具批准或证据冲突处理。选校建议和准备计划可以用 <code>PRELIMINARY_COMPLETE</code> 返回带 blocker 的探索结果；写作、完整申请计划或其他正式目标缺少必要事实时，Critic 返回 <code>BLOCKED</code>，工作流持久化为 <code>FAILED_RETRYABLE</code>，等待新的官方证据后重试。

## 🏗️ 系统架构

~~~mermaid
flowchart TB
    UI["Next.js Web / Runtime API"] --> RT["MultiAgentRuntime"]
    RT --> S["SupervisorAgent<br/>任务拆分与动态路由"]

    S --> A["AssessmentAgent"]
    S --> R["ResearchAgent"]
    S --> M["MatchingAgent"]
    S --> V["VerificationAgent"]
    S --> P["PlanningAgent"]
    S --> W["WritingAgent"]
    S --> C["CriticAgent"]

    A --> E["AgentExecutor"]
    R --> E
    M --> E
    V --> E
    P --> E
    W --> E
    C --> E

    E --> T["ToolRegistry<br/>参数校验 · 权限校验 · 一次性批准"]
    T --> SV["Deterministic Services<br/>规则 · 证据 · ClaimGraph"]
    SV --> DB[("SQLite / Snapshot Store")]

    E <--> ST[("Typed AgentState")]
    S <--> ST
    RT --> CP["Checkpoint / Resume"]
    E --> TR["Runtime Trace"]
    T --> HG{"Human Gate"}
    HG --> CP
    E -->|"HANDOFF"| S
~~~

### Agent、Tool 与 Runtime 的分工

| 层 | 负责什么 | 关键约束 |
| --- | --- | --- |
| **Supervisor** | 根据目标和实时状态选择下一位 Specialist，处理询问、阻断与结束 | 不直接调用工具；只能选择当前策略暴露的合法路线 |
| **Specialist Agent** | 在自己的领域内提出一个强类型 <code>AgentDecision</code> | 只能使用声明的工具和状态字段；不能直接终止工作流 |
| **AgentExecutor** | 校验决策、执行工具、写入状态、记录 trace | 二次检查工具序列、handoff 图、状态 ACL 和终止权限 |
| **ToolRegistry** | 校验 Pydantic 输入/输出并调用确定性服务 | 高风险工具必须携带与具体调用完全一致的一次性批准 |
| **AgentState** | 保存工作流共享状态、证据缺口、任务、暂停信息和最终结果 | 顶层字段强类型校验；运行时字段不允许 Specialist 修改 |
| **Checkpoint / Trace** | 支持暂停恢复并记录 Agent、Tool、错误和模型用量 | 恢复后仍需重新经过同一套策略与门禁 |

### 八个运行时 Agent

| Agent | 主要职责 |
| --- | --- |
| <code>SupervisorAgent</code> | 任务拆分、动态路由、暂停恢复、正式结束 |
| <code>AssessmentAgent</code> | 档案归一化、资料缺口检查、背景评估 |
| <code>ResearchAgent</code> | 项目目录召回、候选收窄、受限官方来源计划 |
| <code>MatchingAgent</code> | 招生资格、预算、偏好、Fit 与项目组合 |
| <code>VerificationAgent</code> | 官方字段缺口、来源快照、证据比较和冲突识别 |
| <code>PlanningAgent</code> | 准备时间线与证据门控的正式时间线 |
| <code>WritingAgent</code> | 故事卡、事实绑定、草稿生成和 grounding 校验 |
| <code>CriticAgent</code> | 推荐、来源、写作与 formal gate 的最终检查 |

ResearchAgent 负责目录检索和来源计划，不执行开放式网页研究；真实来源抓取、抽取、项目绑定和审核候选保存只会在 VerificationAgent 的受控路径中发生。

## 🧠 模型如何参与

默认的 Agent proposal 模式为 <code>mock</code>，使用可复现的确定性策略，不调用外部模型。配置 OpenAI-compatible provider 后，HTTP Runtime 会启用受约束的模型 proposal 模式，但模型只拥有“提议权”：

- Specialist 模型只能从当前策略给出的精确工具调用中选择一个**非空有序前缀**，不能改工具名、参数或顺序。
- Specialist 模型不能返回共享 <code>state_patch</code>，也不能把流程直接交给其他 Specialist。
- Supervisor 模型只能从当前状态暴露的合法路线中选择，不能调用工具、虚构 Agent 或自行结束未满足门禁的流程。
- Executor 会在执行前重新校验决策、工具 ACL、handoff 图、状态字段和终止权限。

因此，模型可以参与路由选择与工具批次选择，但工具参数、共享状态和正式门禁仍由运行时控制。Runtime API 中的写作正文由事实约束的确定性工具生成；外部 provider 不会直接写共享状态、正式事实或最终文书。

模型连接和来源连接是两个独立开关：<code>HARBOR_AGENT_LLM_MODE</code> 控制是否调用外部模型；每个工作流的 <code>source_connection_mode</code> 与 <code>refresh_official_sources</code> 控制是否请求真实官方来源。两者都保持默认 <code>mock</code> 时，工作流完全离线；也可以在确定性 Agent proposal 下单独启用受控来源刷新。

## 🔍 可信证据与人审

### 字段级事实链

~~~text
项目目录 / 历史参考
        ↓
官方来源快照（URL + snapshot_id + page_hash）
        ↓
字段抽取候选
        ↓
来源与具体项目绑定（人工批准）
        ↓
Review Candidate（人工批准）
        ↓
Reviewer 发布或解决冲突
        ↓
DecisionFact → ResolvedProgramView
        ↓
匹配 / 时间线 / 写作 / Critic
~~~

目录值、网页抓取结果和模型抽取结果都不能直接成为正式事实。一个字段只有满足当前申请季、正式来源范围、项目绑定、快照与页面哈希、原文片段、reviewer、review decision 和验证时间等条件，才可进入正式使用。

Critic 不复用核验前缓存的招生资格结论，而是根据当前 <code>DecisionFact</code> 重新计算所选项目的硬性资格。新事实使普通候选不再满足要求时，流程回到 MatchingAgent；创建请求中的 <code>selected_program_ids</code> 会被记录为用户显式选择，这类项目即使保留，也只能作为带 blocker 的准备对象，不能进入正式推荐。

字段级结果分为：

| 状态 | 含义 |
| --- | --- |
| <code>PASS</code> | 当前、已审核、可正式使用的事实支持该结论 |
| <code>FAIL</code> | 当前、已审核、可正式使用的事实明确不满足要求 |
| <code>UNKNOWN</code> | 缺失、过期、往届、冲突或来源信息不完整，不能形成硬结论 |

Formal recommendation 会检查 <code>official_program_url</code>、<code>application_url</code>、<code>deadline</code>、<code>tuition_hkd</code>、<code>min_gpa</code>、<code>language_requirement</code>、<code>required_backgrounds</code>、<code>portfolio_required</code> 和 <code>materials</code> 等字段。缺少任一必要事实时，系统保留初步结果或 blocker，不把目录数据包装成当前季正式结论。

### 精确、一次性 Human Review

高风险 Tool 批准绑定以下信息：

~~~text
workflow_id + agent_name + tool_name + tool_call_id
+ canonical arguments + arguments_sha256 + expires_at
~~~

批准具有有效期且只能消费一次，不能用工具名级别的旧批准重放其他参数。来源绑定与审核候选还必须匹配当前 <code>snapshot_id</code> 和 <code>page_hash</code>。

证据冲突按“项目 + 字段 + 申请季 + 成员记录”生成稳定 conflict-group ID。一个可操作冲突组至少包含两条唯一的持久化证据记录：

- <code>accept</code> 必须选择组内具体 <code>selected_record_id</code>；
- <code>reject</code> 拒绝整个冲突组，不能同时选择成员；
- reviewer 身份来自服务端管理员上下文；
- 当 workflow owner 与 reviewer 使用同一审计身份时，运行时拒绝该决策；
- review decision、选中记录升级和其他成员降级在同一个 SQLite 事务中完成。

## ✍️ ClaimGraph 与交付状态

WritingAgent 生成的学生事实必须引用服务端 story-card registry 中的真实 ID；项目事实必须引用当前 <code>DecisionFact</code>。ClaimGraph 会检查项目、申请季、URL、日期、金额、GPA、语言成绩、布尔值、列表值和正文中的数字是否与证据一致。

Critic 的 <code>critic_readiness</code> 使用三类交付结果：

| <code>critic_readiness</code> | 含义 |
| --- | --- |
| <code>PRELIMINARY_COMPLETE</code> | 可以展示探索性建议或准备计划，但仍携带来源 blocker，<code>formal_use_ready=false</code> |
| <code>FORMAL_PASS</code> | 必要字段、招生资格、来源门禁和 ClaimGraph 均通过，<code>formal_use_ready=true</code>，可以进入系统的正式结果链路 |
| <code>BLOCKED</code> | 写作或完整申请计划仍缺正式事实；工作流的 <code>status</code> 以 <code>FAILED_RETRYABLE</code> 保存 |

字段证据另有 <code>decision_status=PASS / FAIL / UNKNOWN</code>：<code>FAIL</code> 表示当前正式证据明确不满足某项要求，不是工作流失败；<code>UNKNOWN</code> 表示证据不足，不能生成硬结论。这里的“正式”表示通过系统内证据门禁，不替代学校官网或招生办公室的最终权威判断。

<code>PRELIMINARY_COMPLETE</code> 与 <code>FORMAL_PASS</code> 都会让工作流的生命周期 <code>status</code> 进入 <code>COMPLETED</code>，区别由 <code>critic_readiness</code>、<code>formal_use_ready</code> 和 blocker 明确表达；<code>BLOCKED</code> 则对应 <code>FAILED_RETRYABLE</code>。

## 🛠️ 技术栈

| 领域 | 技术 |
| --- | --- |
| 后端 | Python 3.11+、FastAPI、Pydantic、Uvicorn |
| 前端 | Next.js 15、React 19、TypeScript |
| 数据 | SQLite、字段级证据记录、来源快照 |
| Agent Runtime | Supervisor 路由、Typed State、Tool Registry、Checkpoint、Trace |
| 模型 | OpenAI-compatible Tool Calling Provider |
| 部署 | Docker Compose |

## 🚀 快速开始

### 1. 后端

~~~powershell
git clone https://github.com/ZorIgn/HarborPilot-MultiAgent.git
cd HarborPilot-MultiAgent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,llm]"

Copy-Item .env.example .env
# 在 .env 中设置 HARBOR_AGENT_ADMIN_TOKEN 后，Human Review 写操作才能鉴权
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
~~~

默认后端地址：<http://127.0.0.1:8000>，OpenAPI：<http://127.0.0.1:8000/docs>。

### 2. 前端

另开一个 PowerShell 终端并保持后端运行：

~~~powershell
cd web
npm install
npm run dev
~~~

默认前端地址：<http://localhost:3001>。开发服务使用独立的 <code>next-dev</code> 输出目录，生产构建与启动使用 <code>next-build</code>，避免两种运行模式相互覆盖。

### 3. Docker

~~~bash
docker compose up --build
~~~

### 4. 可选模型配置

<code>.env.example</code> 默认使用确定性 Agent proposal。启用 OpenAI-compatible provider 时设置：

~~~dotenv
HARBOR_AGENT_LLM_MODE=openai
HARBOR_AGENT_LLM_PROVIDER=openai
HARBOR_AGENT_OPENAI_API_KEY=your_api_key
HARBOR_AGENT_OPENAI_MODEL=gpt-4.1-mini
HARBOR_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
~~~

模型配置只改变 proposal 的生成方式，不改变工具权限、状态 ACL、证据门禁或 Human Review 规则。

来源连接由工作流请求单独控制：<code>mock</code> 不联网；当前 Runtime 将 <code>real</code> 和 <code>hybrid</code> 都视为显式允许真实来源请求的模式，二者使用相同的绑定、审核和发布门禁。<code>refresh_official_sources=true</code> 配合 <code>mock</code> 会被请求校验拒绝；<code>real</code> 或 <code>hybrid</code> 配合 <code>refresh_official_sources=false</code> 只记录模式，不发起网络请求。真实刷新还必须限定具体项目并通过管理员授权。

## 🔌 Runtime API

### 创建工作流

~~~json
POST /api/agent/workflows
{
  "goal": "program_recommendation",
  "profile": {
    "education": {
      "school": "Example University",
      "major": "Computer Science",
      "gpa": "3.6/4.0"
    },
    "discipline_interests": ["data science"]
  },
  "user_request": "寻找香港和新加坡的数据相关硕士项目",
  "selected_program_ids": [],
  "document_type": "PS",
  "source_connection_mode": "mock",
  "refresh_official_sources": false
}
~~~

完整学生档案示例见 [examples/sample_profile.json](examples/sample_profile.json)。

### 补充学生资料

~~~json
POST /api/agent/workflows/{workflow_id}/resume
{
  "user_message": "{\"language\": {\"test\": \"IELTS\", \"overall\": 7.0}}",
  "human_resolution": null
}
~~~

### 批准精确工具调用

~~~json
POST /api/agent/workflows/{workflow_id}/resume
{
  "human_resolution": {
    "action": "approve_tool",
    "approval_id": "approval_...",
    "note": "已核对本次调用的项目、URL、字段、snapshot_id 与 page_hash"
  }
}
~~~

### 解决证据冲突

~~~json
POST /api/agent/workflows/{workflow_id}/resume
{
  "human_resolution": {
    "action": "resolve_conflicts",
    "conflict_resolutions": [
      {
        "conflict_id": "conflict_group_...",
        "action": "accept",
        "selected_record_id": "evidence_record_...",
        "reviewer_note": "当前项目页与申请季信息一致"
      }
    ]
  }
}
~~~

管理员提交 Human Review 时需携带与 <code>HARBOR_AGENT_ADMIN_TOKEN</code> 对应的 <code>x-harbor-admin-token</code>。本地工作流 owner 来自创建请求的签名 profile cookie，reviewer 来自管理员令牌对应的服务端审计身份；两者相同时请求会被拒绝。<code>approval_id</code>、<code>conflict_id</code> 和 <code>selected_record_id</code> 均应从当前工作流的 <code>human_review_item</code> 读取，示例中的省略号不是固定值。

常用接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| <code>POST</code> | <code>/api/agent/workflows</code> | 创建并运行工作流 |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}</code> | 读取工作流状态 |
| <code>POST</code> | <code>/api/agent/workflows/{workflow_id}/resume</code> | 补充资料或提交 Human Review |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}/trace</code> | 查看 Agent、Tool 与模型事件 |
| <code>GET</code> | <code>/api/agent/workflows/{workflow_id}/state</code> | 查看最近 checkpoint |
| <code>GET</code> | <code>/api/agent-system</code> | 查看 Agent、Tool、权限和执行图 |
| <code>GET</code> | <code>/api/admin/decision-coverage</code> | 查看正式 DecisionFact 覆盖率 |

## 🧪 验证

~~~powershell
# Python 回归测试
python -m pytest -q

# 确定性 Agent Eval
python -B scripts/run_agent_evals.py

# 完整模型驱动路径的可复现回放
python -B scripts/run_agent_evals.py --model-replay

# 可选：使用已配置的真实模型运行指定用例
python -B scripts/run_agent_evals.py --live-model --case-id normal_background_assessment

# 前端类型检查与生产构建
cd web
npm run typecheck
npm run build
~~~

确定性 Eval 检查路由、工具权限、暂停恢复、预算与招生资格分离、来源安全和 formal gate。<code>--model-replay</code> 会经过完整的模型驱动 Supervisor/Specialist 代码路径，但不用于衡量外部模型质量；<code>--live-model</code> 才会调用已配置的外部 provider。

## 📂 项目结构

~~~text
src/harbor_agent/agents/          八个运行时 Agent
src/harbor_agent/runtime/         State、Decision、Executor、Graph、Checkpoint
src/harbor_agent/tools/           强类型 Tool 与 ToolRegistry
src/harbor_agent/policies/        工具权限、来源安全与正式使用策略
src/harbor_agent/services/        业务规则、证据、ClaimGraph 与持久化
src/harbor_agent/llm/             OpenAI-compatible provider 与结构化响应
src/harbor_agent/observability/   Runtime Trace、事件与用量
src/harbor_agent/evals/           Agent Eval runner、断言与指标
data/agent_eval_cases.json        可重复的评测用例
web/                              Next.js 前端与 Agent Lab
~~~

更详细的执行拓扑与门禁说明见 [docs/agent-workflow.md](docs/agent-workflow.md)。

## ⚠️ 使用边界

- HarborPilot 不提供录取保证；匹配分数是策略评分，不是录取概率。
- 招生资格、财务预算、个人偏好和申请人 Fit 分开计算，预算或偏好不会改写学校要求。
- 默认 <code>mock</code> 模式不联网；真实来源刷新必须显式选择 <code>real</code> 或 <code>hybrid</code>、指定项目范围并通过管理员授权。
- 网页内容始终视为不可信数据；抓取、抽取或保存 candidate 不等于审核发布。
- 正式申请决策仍应以当前申请季学校官网、招生办公室和独立人工核验结果为准。
