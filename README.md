# HarborPilot MultiAgent

HarborPilot 是一个面向港新授课型硕士申请的信息辅助平台。项目目标不是用 Agent 包装不确定结论，而是把学生背景、项目库、学校官网来源、公开社区经验、文书素材和人工审核门禁串成一条可追踪的申请准备链路。

当前版本定位为：可信申请信息辅助原型。它可以用于项目发现、初步选校、材料规划、文书素材整理和数据可信度审计；还不能替代正式顾问或学校官网最终确认。

## 核心原则

- 官方字段优先：截止日期、学费、语言要求、材料清单、申请入口、文书题目必须来自学校公开页面、官方 PDF/FAQ 或公开申请系统入口。
- 社区信息分层：GitHub、GradCafe、论坛、公开视频/笔记等只用于经验参考、项目别名、笔试面试线索和准备建议，不能覆盖官方要求。
- 字段级证据：每个关键字段都保留来源 URL、申请季、抓取时间、page hash、证据片段、状态和人工审核标记。
- Review-first：未经过人工审核的字段不会成为 `OFFICIAL_VERIFIED_CURRENT`，也不会被包装成正式推荐或正式时间线。
- Multi-agent 可审计：每个 Agent 有职责、输入、输出、工具、上游依赖和人工门禁，可通过 `/api/agent-system` 查看。

## 主要功能

- 背景评估：读取学校层级、GPA 标尺、语言成绩、方向、预算、经历和职业目标，输出低承诺的背景诊断和资料缺口。
- 项目推荐：基于港新项目库、方向识别、硬规则和数据可信度，生成冲刺、主申、保底、候选和暂不建议项目。
- 项目数据包：项目详情中展示官方要求、项目内容、文书与时间线字段、公开社区经验和采集计划。
- 数据获取 Agent：支持官方来源计划、robots 检查、快照 hash、字段候选、公开社区经验信号和人工发布队列。
- 审核发布门禁：`/api/admin/review-queue` 生成字段审核队列，`/api/admin/review-queue/publish` 只有在人工确认后才生成官方确认记录。
- 文书工作台：通过问卷、故事卡、事实绑定和审核量表生成 PS/SOP/CV/Essay/推荐信素材包草稿。
- 场景自审：`scripts/run_scenario_audit.py` 会用 985 IELTS 6.5、211 AI IELTS 7.0、普通一本 BA+Data IELTS 6.5 等背景跑质量门槛。

## 页面入口

启动后打开：

```text
http://localhost:3000
```

主要页面：

```text
/assessment   背景资料
/programs     项目探索
/timeline     任务与材料
/writing      文书工作台
/agent-lab    资料中心 / 来源证据 / Agent 契约
/settings     模型连接
```

## 后端启动

CMD：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

PowerShell：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

## 前端启动

CMD：

```cmd
cd /d E:\multi_agent\web
npm.cmd install
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm.cmd run dev
```

PowerShell：

```powershell
cd E:\multi_agent\web
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
npm.cmd run dev
```

## 模型配置

默认可以使用 mock 模式体验完整流程，不需要 API Key。

如果要测试真实模型，可以在 `/settings` 中配置 DeepSeek、OpenAI 或 OpenAI-compatible endpoint。LLM 只用于解释润色、文书生成和可选摘要；GPA、语言硬门槛、项目方向、未确认字段门禁等关键逻辑由确定性规则执行。

## 关键 API

```text
GET  /api/health
GET  /api/programs
GET  /api/programs/{program_id}/trust
GET  /api/programs/{program_id}/data-package
GET  /api/evidence-graph/summary
GET  /api/source-registry
GET  /api/agent-system
GET  /api/admin/review-queue
POST /api/admin/review-queue/publish
POST /api/workflows/background
POST /api/workflows/program-plan
POST /api/workflows/application-plan
POST /api/workflows/data-refresh
POST /api/workflows/data-acquisition
POST /api/workflows/writing-plan
POST /api/workflows/writing-review
```

## 验证命令

后端测试：

```cmd
cd /d E:\multi_agent
python -m pytest -q
```

场景自审：

```cmd
cd /d E:\multi_agent
python scripts\run_scenario_audit.py
```

前端类型检查：

```cmd
cd /d E:\multi_agent\web
npx.cmd tsc --noEmit --incremental false
```

前端构建：

```cmd
cd /d E:\multi_agent\web
npm.cmd run build
```

## 当前可信度边界

项目已经具备字段级证据、数据包、公开来源采集计划、审核发布门禁、Agent 契约和场景质量门槛。但项目库仍有大量字段处于上一申请季参考、抽取候选或待人工确认状态。

正式使用前必须继续补齐：

- 学校官网当前申请季字段的人工发布记录。
- Playwright/PDF parser 队列化采集。
- 更完整的项目详情页和审核后台。
- 用户可见中文文案的全量清洗。
- 用户档案 API 和加密存储，替代长期 localStorage。

## GitHub

仓库地址：<https://github.com/ZorIgn/HarborPilot-MultiAgent>