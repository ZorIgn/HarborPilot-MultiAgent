# HarborPilot AI 港新多 Agent 留学申请辅助平台

HarborPilot AI 是一个面向香港、新加坡授课型硕士申请的信息辅助与多 Agent 协作项目。它不是静态前端，而是 Next.js 多页面产品工作台 + FastAPI 后端 + 项目数据目录 + 来源证据图 + 规则引擎 + LLM Adapter 的完整项目。

项目覆盖学生视角的快速评估入口、择校定具体项目、选定项目后的时间线与材料、文书问卷素材整理，以及“决策依据”式 Agent 审计。项目数据优先来自学校官方入口；GitHub 和社区资料只作为项目发现、别名、分类和经验线索，不能替代官方要求。

## 功能模块

- 背景评估：输入学校层级、GPA、语言、方向、预算和职业目标，生成初步评估与资料缺口。
- 择校定项目：内置港新主流授课硕士项目库，按冲刺、主申、相对稳妥、信息不足、暂不建议分档。
- 时间线与材料：支持多选目标项目，生成学校官网确认、语言送分、奖学金检查、推荐信、文书和最终递交任务。
- 数据刷新 Agent：内置可信源注册表，优先检查学校官方入口，社区/目录来源只保留为线索和方法参考；输出待确认信息清单。
- 来源证据图：把截止日期、学费、材料、语言要求、申请入口等信息拆开记录状态、来源、hash 和证据片段。
- 文书材料生产：按个人信息表、个人陈述问卷、推荐信调查表拆成在线问卷，支持指定学校/项目，选择 PS、SOP、CV、Essay 或推荐信素材包，并生成中文稿、英文稿、CV bullet、推荐信素材包、项目定制点和提交前风控项。
- 决策依据页：把 Agent Trace 转成用户能理解的推荐原因、风险、官网依据、社区线索和人工闸门；技术 Trace 作为审计信息保留。
- 模型连接：设置页支持 DeepSeek、OpenAI、OpenAI-compatible API 和 Mock Provider。

## 页面入口

启动后打开：

```text
http://localhost:3000
```

主要页面：

```text
/assessment   背景评估
/programs     择校定具体项目
/timeline     选定项目时间线与材料
/writing      文书 AI 辅助
/agent-lab    决策依据与来源确认
/settings     设置与模型连接
```

## CMD 启动方式

如果你使用的是 `cmd.exe`，不要写 `$env:...`，那是 PowerShell 语法。

第一个 CMD 窗口启动后端：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

第二个 CMD 窗口启动前端：

```cmd
cd /d E:\multi_agent\web
npm.cmd install
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm.cmd run dev
```

也可以使用脚本：

```cmd
cd /d E:\multi_agent
scripts\start-api.cmd
```

另开一个 CMD：

```cmd
cd /d E:\multi_agent
scripts\start-web.cmd
```

## PowerShell 启动方式

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

另开一个 PowerShell：

```powershell
cd E:\multi_agent\web
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
npm.cmd run dev
```

## 是否需要 API Key

不一定需要。默认可以选择首页的“使用体验模式”，体验模式走 Mock Provider，不需要 API Key，适合演示完整业务流程。

如果要测试真实大模型，需要先安装可选依赖：

```cmd
cd /d E:\multi_agent
pip install -r requirements-llm.txt
```

然后重启后端，打开：

```text
http://localhost:3000/settings
```

在“模型连接”里填写：

- DeepSeek：后端会使用 `https://api.deepseek.com`，模型名可按账号可用模型填写。
- OpenAI：使用 OpenAI 官方接口。
- 兼容 OpenAI 接口：需要额外填写 base URL。

API Key 只提交到后端模型适配器；前端不会写入 localStorage、sessionStorage 或 Agent Trace。当前开源演示版在后端进程内存中保存连接，重启后需要重新输入；生产版可以扩展为加密存储。

## Agent 工作流

顶部“查看工作流”只打开状态抽屉，不会直接运行所有 Agent。Agent 只在用户完成某个业务阶段并点击该阶段按钮后运行。

阶段按钮：

```text
保存并生成背景评估
ProfileAgent -> EvidenceAgent -> EvaluationAgent

根据背景生成项目方案
ProgramIntelligenceAgent -> Eligibility Engine -> SchoolMatchingAgent

确认项目并生成申请计划
ProgramIntelligenceAgent -> Requirement Verification -> TimelineAgent -> ReviewAgent

整理故事并生成中英文文书
StoryCardAgent -> WritingAgent -> ReviewAgent
```

用户看到的不是“有几个 Agent”，而是这些 Agent 带来的实际价值：

- 少查多少信息：来源注册表会把官方源、目录源、社区源分层。
- 少踩哪些坑：未完成学校官网确认的信息会在项目卡、时间线和审核结果里提示。
- 结论从哪里来：项目卡和时间线展示官网链接、字段状态和倒推依据。
- 哪些地方要人工确认：DataRefreshAgent 输出待确认信息清单，关键信息需要查看学校原文后再发布。

## 数据真实性说明

项目目录位于：

```text
data/programs_2027_fall.json
data/community_sources.json
data/source_registry.json
```

关键信息保存来源状态，学生端会显示为“已找到来源、待学校确认、学校已确认、本季未发布、来源冲突”等。只有学校官网已确认的信息才适合进入正式推荐；其他状态会在界面和审核结果里提示确认。

来源证据结构可以通过接口查看：

```text
GET /api/evidence-graph/summary
GET /api/programs/{program_id}/trust
```

`/api/programs` 会在每个项目对象中返回 `trust_detail`。它把 deadline、tuition、language、materials、application_url 等关键字段拆成字段级证据，展示来源 URL、申请季、抓取时间、人工确认时间、证据状态和发布闸门。只有 `production_ready=true` 且字段状态为 `OFFICIAL_VERIFIED_CURRENT` 的信息，才适合作为正式申请计划依据；其他字段只进入准备建议和待确认清单。

核心记录结构：

```text
program_id, field_name, value, source_url, source_type,
extracted_at, verified_at, page_hash, confidence,
reviewer_id, evidence_snippet, status
```

官方来源优先级：

```text
official application system
> official programme page
> official PDF/FAQ
> official programme index
> directory/ranking
> community/GitHub/小红书
```

`data/source_registry.json` 把来源分成几类：

- 官方项目索引/项目页/申请系统/PDF/FAQ：用于项目名称、截止日期、学费、材料、语言要求等正式信息的确认。
- CollegeBoard、College Navigator、Niche、TopUniversities、Peterson's 等目录/排名：只参考检索、筛选和字段组织方式，不用于港新硕士官方要求。
- TheGradCafe、College Confidential、GitHub 留学项目：只作为录取经验、项目别名、社区信号和信息组织方法。
- yuanrenannie selector：只参考选校产品的信息架构和分档方法。
- 用户提供案例/公开文书样例：只抽象叙事风格，不复制句子、不编造经历。

刷新入口：

```text
GET  /api/source-registry
POST /api/workflows/data-refresh
```

如果需要把 `lione12138/qs-master-applications` 作为项目发现和产品框架参考，先把仓库放到 `.agents/qs-master-applications`，再运行：

```cmd
cd /d E:\multi_agent
python scripts\import_qs_master_applications.py
```

脚本会输出 `data/external_candidates/qs_master_applications_candidates.json`。这些记录只作为项目发现、官网链接候选和日期线索，不会自动写入正式项目库。

`/api/workflows/data-refresh` 默认建议传 `dry_run: true`。它会根据已选项目匹配官方来源，输出待确认信息清单和下一步动作；即使传 `dry_run: false` 做联网可达性检查，也不会自动覆盖 `programs_2027_fall.json`。时间线生成前会自动运行一次 dry-run，并把来源 URL、截止日期依据、材料清单和确认状态写入时间线任务。

当前实现是 MVP 级数据治理：JSON 仍是主数据源，但已经保留 PostgreSQL/pgvector 迁移所需的逐项 evidence schema、确认清单、parser plan 和人工发布闸门。后续生产化建议接入 PostgreSQL、Redis 队列、Playwright crawler、HTML/PDF 快照、hash diff 和人工 reviewer 后台。

参考的开源留学项目用于信息组织和线索发现，例如 Global CS Application、GIS Info、欧港新 CS 留学项目指北、WaterCS、QS Master Applications。正式信息仍必须回到学校官网、学院页面、官方 PDF、FAQ 或申请系统确认。

## 验证命令

后端测试：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python -m pytest -q
```

前端类型检查：

```cmd
cd /d E:\multi_agent\web
npx.cmd tsc --noEmit --incremental false
```

Demo workflow：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python scripts\run_demo_workflow.py
```

## 常见错误

### 文件名、目录名或卷标语法不正确

你在 CMD 里用了 PowerShell 写法：

```powershell
$env:PYTHONPATH="src"
```

CMD 应该写：

```cmd
set PYTHONPATH=src
```

### ModuleNotFoundError: No module named 'harbor_agent'

说明后端没有设置 `PYTHONPATH`：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

### DeepSeek 或 OpenAI 连接失败

先确认三件事：

- 已执行 `pip install -r requirements-llm.txt`
- 后端已经重启
- 在 `/settings` 页面选择了正确供应商，并填写账号可用的模型名

### npm run build 卡住或失败

开发演示不需要先 build，直接运行：

```cmd
npm.cmd run dev
```

如果要生产构建，先关闭正在运行的 Next dev 窗口，再执行：

```cmd
cd /d E:\multi_agent\web
npm.cmd run build
```

## 项目结构

```text
src/harbor_agent/
  agents/          多 Agent：背景、证据、评估、项目情报、匹配、时间线、文书、审核
  core/            LLM Adapter、规则和 Trace
  services/        数据加载
  app.py           FastAPI 入口

web/
  app/             Next.js 多页面工作台
  lib/             API 请求与类型

data/
  programs_2027_fall.json
  community_sources.json
  questionnaire_schema.json

docs/
  architecture.md
  agent-workflow.md
  resume-bullets.md

tests/
  API 与工作流测试
```
