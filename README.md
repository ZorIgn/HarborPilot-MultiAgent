# HarborPilot MultiAgent

HarborPilot 是一个面向港新授课型硕士申请的信息辅助平台。项目目标不是用 Agent 包装不确定结论，而是把学生背景、项目库、学校官网来源、公开社区经验、文书素材和人工审核门禁串成一条可追踪的申请准备链路。

当前版本定位为：可信申请信息辅助原型。它可以用于项目发现、初步选校、材料规划、文书素材整理和数据可信度审计；还不能替代正式顾问或学校官网最终确认。

## 核心原则

- 官方字段优先：截止日期、学费、语言要求、材料清单、申请入口、文书题目必须来自学校公开页面、官方 PDF/FAQ 或公开申请系统入口。
- 社区信息分层：GitHub、GradCafe、论坛、公开视频/笔记等只用于经验参考、项目别名、笔试面试线索和准备建议，不能覆盖官方要求。
- 字段级证据：每个关键字段都保留来源 URL、申请季、采集时间、page hash、证据片段、状态和人工审核标记。
- Review-first：未经过人工审核的字段不会成为 `OFFICIAL_VERIFIED_CURRENT`，也不会被包装成正式推荐或正式时间线。
- Multi-agent 可审计：每个 Agent 有职责、输入、输出、工具、上游依赖和人工门禁，可通过 `/api/agent-system` 查看。

## 主要功能

- 背景评估：读取学校层级、GPA 标尺、语言成绩、方向、预算、经历和职业目标，输出背景竞争力等级、硬门槛和资料缺口。
- 项目推荐：基于港新项目库、方向识别、硬规则和数据可信度，生成冲刺、主申、保底、候选和暂不建议项目。
- 项目数据包：项目详情中展示官方要求、字段覆盖审计、项目内容、文书与时间线字段、公开社区经验和采集计划。
- 数据获取 Agent：支持官方来源计划、robots 检查、快照 hash、字段候选、公开社区经验信号和人工发布队列。
- 审核发布门禁：`/api/admin/review-queue` 生成字段审核队列，`/api/admin/review-queue/publish` 只有在人工确认后才生成官方确认记录。
- 文书工作台：通过问卷、故事卡、事实绑定和审核量表生成 PS/SOP/CV/Essay/推荐信素材包草稿。
- 场景自审：`scripts/run_scenario_audit.py` 会用 985 IELTS 6.5、211 AI IELTS 7.0、普通一本 BA+Data IELTS 6.5 等背景跑质量门槛。

## 学生主流程

```text
学生档案与材料状态
  -> Profile / Evidence / Evaluation Agents
  -> 背景评估（资料不足时返回 NEEDS_DATA，不生成虚假分档）
  -> Program Intelligence / Matching Agents
  -> 6-10 个主要候选 + 少量明确不建议项目
  -> 学生保存最终申请清单
  -> Source / Review / Timeline Agents
  -> 当前季官网字段、往届参考、待核验字段分层展示
  -> Story Card / Writing / Review Agents
  -> 经历问卷、事实绑定、素材缺口、可编辑草稿与导出门禁
```

时间线和文书只读取学生明确保存的项目，不会在没有选择时自动挑一个项目。即使学生选择了系统标为高风险的项目，后续 Agent 也会保留该选择并展示预算、专业背景或来源风险，而不是静默丢弃。

## 信息真实性门禁

- 项目库里的原始日期、学费、材料和语言字段只可显示为“库内参考 / 待官网核验”，不能直接作为当前季官方结论。
- 当前季日期必须包含目标申请季年份、来自允许的学校官方 HTTPS 域名，并经人工逐条审核后才可发布；批量发布只能预览。
- 新抓取来源拒绝 HTTP、localhost、私网/保留地址、非 443 端口和跳转到不安全地址，降低 SSRF 风险。
- 新的来源冲突会覆盖较旧的已核验值并阻断正式使用；只有更新的人工核验记录才能解除冲突。
- 学生端来源更新一次最多处理 3 个已知项目，只抓官方来源，不把社区内容混入学校要求。
- 文书英文事实尚未完成翻译或项目来源不足时，Word 导出会被阻断；Markdown 会保留复核标记。

## 页面入口

启动后打开：

```text
http://localhost:3001
```

3000 端口可能被其他本地服务占用；HarborPilot 前端统一使用 3001。

主要页面：

```text
/assessment   背景竞争力评估
/programs     港新项目库与申请分档
/timeline     逐项目时间线与材料
/writing      文书工作台
/agent-lab    Admin 数据中心 / 来源证据 / Agent 契约
/settings     Admin 模型设置
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

前端 `dev` 使用独立的 `next-dev` 输出目录，`build/start` 使用 `next-build`，避免开发服务和生产构建共用 `.next` 后出现缺 chunk 的 500。若 3001 曾经跑过旧进程，先停止旧 Node 进程再重新执行 `npm.cmd run dev` 或 `npm.cmd run start`。

后端默认允许 `localhost:3001` 和 `127.0.0.1:3001` 跨端口访问。若使用其他前端端口，请同步设置 `HARBOR_AGENT_CORS_ORIGINS`。

## 模型配置

默认可以使用 mock 模式体验完整流程，不需要 API Key。

真实模型通过 Admin 设置或环境变量配置；学生端不会要求填写 API Key。LLM 只用于解释润色、文书生成和可选摘要；GPA、语言硬门槛、项目方向、待核验字段门禁等关键逻辑由确定性规则执行。

Admin 写操作默认需要管理员令牌，尤其是 `/api/admin/llm-config` 这类会修改模型供应商、Base URL 或 API Key 的接口。开发或部署前先在后端进程设置：

```powershell
$env:HARBOR_AGENT_ADMIN_TOKEN="change-this-local-admin-token"
```

然后在 `/settings` 的 Admin Token 输入框填写同一个值，再连接真实模型。只在一次性本机演示时才可以显式开启无 token 写操作：`HARBOR_AGENT_ALLOW_INSECURE_LOCAL_ADMIN=true`；不要在客户验收或部署环境使用这个开关。

## 本地数据层

项目库通过 SQLite 本地库读取，首次启动会从 `data/programs_2027_fall.json` 导入到 `data/harborpilot.sqlite3` 的 `program_catalog` 表。表内保留学校、学院、项目、地区、方向、学制、学费、申请入口、项目详情页、语言要求、先修课、材料、轮次日期、文书题目和字段级来源证据，同时保存完整 JSON payload 以兼容现有 Agent。

显式重建项目库：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python scripts\seed_program_store.py
```


项目信息自动更新 Agent（默认 dry-run，不写入数据）：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python scripts\run_harborpilot_update.py --max-programs 48
```

写入 SQLite 审核队列（仍然不会自动发布为官网已核验字段）：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python scripts\run_harborpilot_update.py --write --max-programs 48
```

只跑单个项目：

```powershell
python scripts\run_harborpilot_update.py --program-id hku-master-of-science-in-computer-science-2027
```


把资料更新交给 Agent 队列处理：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python scripts\run_agent_worker.py --enqueue-catalog-refresh --write --max-jobs 20
```

上面命令会先排入 `catalog_auto_update`、`data_acquisition` 和 `crawl_queue`，再由 worker 依次执行。`--write` 只会把候选证据写入 Admin review queue，不会自动发布到学生端。学生端要看到当前季官方信息，仍需要在 Admin Data Center 人工审核并 publish field。
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
POST /api/admin/crawl-queue
POST /api/admin/catalog-auto-update
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
- 剩余项目详情页的官方原文核验和发布。
- Playwright/PDF parser 结果进入 Admin 审核队列后的批量操作体验。
- 用户档案、问卷和申请状态已经写入本地 SQLite；后续补字段级加密和权限分级。

## GitHub

仓库地址：<https://github.com/ZorIgn/HarborPilot-MultiAgent>
