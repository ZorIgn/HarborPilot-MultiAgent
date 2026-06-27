# HarborPilot 下一窗口交付说明

最后整理日期：2026-06-27  
工作目录：`E:\multi_agent`

## 1. 项目定位

HarborPilot 是一个面向港新授课型硕士申请的多 Agent 留学信息辅助平台。产品目标不是炫技展示 Agent，而是让学生完成一条可信申请辅助链路：

1. 学生输入模型 API Key，或使用 mock 示例档案体验。
2. 学生填写背景资料、成绩、语言、方向、经历、预算和职业目标。
3. Profile / Evidence / Evaluation Agent 生成低过度承诺的背景诊断。
4. Program / Matching Agent 根据港新项目库、学生背景和方向，给出冲刺、主申、保底、候选和暂不建议项目。
5. 用户选择项目后，Timeline / DataRefresh Agent 整理官网入口、上一申请季参考窗口、当前申请季待确认字段、材料清单和准备任务。
6. Writing Agent 根据经历表、故事卡、目标项目和文书类型生成中文/英文草稿，并给出事实绑定和风险审核。

当前更准确的包装口径是：**港新授课型硕士申请信息辅助原型**。不能包装成已经可正式替代顾问的生产平台，因为项目库关键字段仍未完成当前申请季官网人工发布。

## 2. 已完成的核心工作

### 产品与 UI

- 前端已经改为多页面任务流：
  - `/` 我的申请
  - `/assessment` 背景资料
  - `/programs` 项目探索
  - `/timeline` 任务与材料
  - `/writing` 文书工作台
  - `/agent-lab` 资料中心 / 来源证据
  - `/settings` 模型连接
- 引入 `animal-island-ui` 风格，整体偏动森岛屿风，但仍有中文编码和信息密度问题待清理。
- “Agent 协作”已弱化为右上角“AI 决策依据”，避免主流程像技术调试台。
- 背景资料页新增关键输入：
  - GPA 标尺：百分制 / 4.0 / 5.0
  - 专业排名百分比
  - 语言阅读、听力、口语、写作单项
  - 核心课程 / 先修课
  - 经历表：类型、名称、机构、时长、职责、工具方法、结果证据

关键文件：

- `web/app/HarborPilotApp.tsx`
- `web/app/globals.css`
- `web/lib/types.ts`
- `web/lib/demoPayload.ts`

### 后端 Agent 流程

已有主要 Agent：

- `ProfileAgent`：规范化学生背景。
- `EvidenceAgent`：识别事实证据状态和推荐上传材料。
- `EvaluationAgent`：生成背景诊断。
- `ProgramIntelligenceAgent`：项目意向和项目信息层处理。
- `SchoolMatchingAgent`：择校分档、解释和 LLM 顾问式润色。
- `DataRefreshAgent`：来源检查、字段抽取候选、GradWindow 线索接入。
- `TimelineAgent`：任务与材料规划，区分官方截止和内部准备建议。
- `StoryCardAgent`：把问卷素材整理成故事卡。
- `WritingAgent`：文书访谈、草稿、审核量表。
- `ReviewAgent`：最终风险闸门。

关键文件：

- `src/harbor_agent/agents/*.py`
- `src/harbor_agent/core/rules.py`
- `src/harbor_agent/core/llm.py`
- `src/harbor_agent/services/intent.py`
- `src/harbor_agent/services/evidence_graph.py`
- `src/harbor_agent/services/external_candidates.py`

### 数据与来源治理

- 主项目库：`data/programs_2027_fall.json`
- 来源注册表：`data/source_registry.json`
- 社区来源：`data/community_sources.json`
- 字段级证据图服务：`src/harbor_agent/services/evidence_graph.py`
- GradWindow / QS Master Applications 导入包：
  - `data/external_candidates/qs_master_applications_candidates.json`
  - `scripts/import_qs_master_applications.py`

已接入 `lione12138/qs-master-applications` 的港新线索，覆盖 HKU、CUHK、HKUST、CityUHK、PolyU、NUS、NTU。用途边界已经写清楚：只用于项目发现、官网入口候选和上一申请季窗口线索，不直接覆盖正式项目库字段。

### 已修复的重要 bug

- GPA 标尺 bug：
  - 之前 `3.7/4.0` 会被当成 `3.7/100`。
  - 现在通过 `normalized_gpa_100()` 统一折算。
  - 文件：`src/harbor_agent/core/rules.py`

- 语言硬门槛 bug：
  - 之前 TOEFL 90 可能被显示成 IELTS 90。
  - 现在按 IELTS / TOEFL / PTE 分开判断。
  - 没有同种考试要求时，只提示“需官网确认是否接受该考试”。
  - 文件：`src/harbor_agent/core/rules.py`

- ReviewAgent 过度通过 bug：
  - 之前只看硬规则和文书 flags。
  - 现在只要选中项目的官网字段未确认，整体 `passed=false`，状态为“仍需确认后再使用”。
  - 文件：`src/harbor_agent/agents/review.py`

- 择校方向污染：
  - 用户选 CS / AI / Data 时，career goal 不再把主方向污染成 business。
  - 相关文件：`src/harbor_agent/services/intent.py`、`src/harbor_agent/agents/profile.py`、`src/harbor_agent/agents/matching.py`

## 3. 关键 API

- `GET /api/health`
- `POST /api/admin/llm-config`
- `GET /api/programs`
- `GET /api/evidence-graph/summary`
- `GET /api/source-registry`
- `GET /api/external-candidates/qs-master-applications`
- `POST /api/workflows/background`
- `POST /api/workflows/program-plan`
- `POST /api/workflows/application-plan`
- `POST /api/workflows/data-refresh`
- `POST /api/workflows/writing-interview`
- `POST /api/workflows/writing-plan`
- `POST /api/workflows/writing-review`

## 4. 启动方式

后端 CMD：

```cmd
cd /d E:\multi_agent
set PYTHONPATH=src
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

前端 CMD：

```cmd
cd /d E:\multi_agent\web
npm.cmd install
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm.cmd run dev
```

PowerShell 注意不要在 CMD 里写 `$env:...`。如果用 PowerShell：

```powershell
cd E:\multi_agent
$env:PYTHONPATH="src"
python -m uvicorn harbor_agent.app:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd E:\multi_agent\web
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
npm.cmd run dev
```

## 5. 验证方式

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

生产构建：

```cmd
cd /d E:\multi_agent\web
npm.cmd run build
```

注意：在 Codex Windows 沙箱内，普通 `npm run build` 多次卡在 Next build 启动阶段 180 秒；提升权限后约 20 秒构建通过。这更像沙箱 / Next tracing 权限问题，不是项目代码错误。

最近一次已知验证结果：

- `python -m pytest -q`：20 passed
- `npx.cmd tsc --noEmit --incremental false`：通过
- `npm.cmd run build`：提升权限后通过

## 6. 当前已知问题

### P0 数据可信度仍未达正式产品

项目库仍大量处于 `EXTRACTED / PENDING_REVIEW / NOT_PUBLISHED`。系统已经不再把这些字段包装成正式结论，但要真正给客户用，必须跑 live fetch + 人工发布字段：

- deadline
- tuition
- language
- materials
- application_url
- essay_prompts

下一窗口最重要任务是把官网字段从“线索”推进到“当前申请季学校官网已确认”。

### P0 中文编码污染

多个文件早期保存过乱码中文，尤其：

- `README.md`
- `web/app/HarborPilotApp.tsx`
- `web/lib/types.ts`
- 部分 agent 文案

功能可运行，但用户界面可能出现乱码或不自然文案。建议下一轮专门做“中文文案和编码清洗”，把所有用户可见文案集中成干净中文常量。

### P1 前端仍是巨大客户端组件

`web/app/HarborPilotApp.tsx` 太大，后续应该拆成：

- `components/layout`
- `components/profile`
- `components/programs`
- `components/timeline`
- `components/writing`
- `components/evidence`

### P1 localStorage 不适合长期资料管理

当前学生背景、问卷、结果、选校仍存在浏览器 localStorage。生产化需要本地用户档案 API、加密存储和敏感字段分级。

### P1 LLM 配置仍是本地 demo 级

`/api/admin/llm-config` 是无鉴权本地设置，API key 保存在后端进程内存中，重启后失效。真实部署需要鉴权和加密存储。

### P2 爬取能力只是 MVP

当前 DataRefreshAgent 主要是 urllib + regex_html + 手工导入线索。真实官网需要：

- Playwright
- PDF parser
- snapshot hash
- diff
- robots / 限流
- 人工审核后台

## 7. 下一步建议 TODO

优先级按顺序做。

1. 建立官网字段发布后台
   - 读取 DataRefreshAgent 的候选字段。
   - 人工确认原文后写入字段级 evidence。
   - 只让 `OFFICIAL_VERIFIED_CURRENT` 进入正式推荐和正式时间线。

2. 做项目详情页
   - 每个项目展示 deadline、tuition、language、materials、application_url。
   - 每个字段显示来源 URL、原文摘录、申请季、抓取时间、状态。

3. 清洗中文 UI 文案
   - 去掉乱码。
   - 去掉 `live fetch`、`application_mix`、`复核字段` 等面向开发者的话。
   - 学生端统一说“学校官网确认”“上一申请季参考”“准备建议”。

4. 拆分前端组件
   - 先拆 Assessment / Programs / Timeline / Writing 四个模块。
   - 保持 animal-island-ui，但压低大标题，提高列表信息密度。

5. 增强文书工作台
   - 版本管理。
   - 字数限制。
   - 逐句事实绑定。
   - Prompt 原文校验。
   - 导出 docx / markdown。

6. 增强 Agent 编排
   - 参考 LangGraph / AutoGen，把现在顺序流升级成状态机。
   - 资料不足时主动追问。
   - 推荐被用户否定时重新规划。

7. 数据源继续扩展
   - 官方优先：HKU、CUHK、HKUST、CityUHK、PolyU、NUS、NTU、SMU。
   - 开源参考：GlobalCS、WaterCS、QS Master Applications。
   - 社区经验只进“案例与经验”，不能写入官方字段。

## 8. Git / 环境注意事项

当前在某些环境下运行 `git status` 会出现：

```text
fatal: detected dubious ownership in repository at 'E:/multi_agent'
```

原因是 `.git` 所有者和当前 Windows 用户不同。下个窗口如果需要 Git 状态，可以先执行：

```cmd
git config --global --add safe.directory E:/multi_agent
```

如果不想改全局配置，也可以跳过 Git，只按文件系统交付继续开发。

## 9. 下个窗口接手提示词

可以把下面这段直接贴给下一个 Codex 窗口：

```text
请接着 E:\multi_agent 的 HarborPilot 项目继续做。先阅读 docs/HANDOFF_NEXT_WINDOW.md 和 docs/product-trust-todo.md。当前重点不是再堆 demo，而是把平台做成可信的港新硕士申请信息辅助产品。优先级：
1. 修复中文乱码和用户可见文案；
2. 做项目详情页的字段级官网证据展示；
3. 增强 DataRefreshAgent 的官网抓取、候选字段、人工发布闸门；
4. 把未确认字段继续严格限制为准备建议，不允许包装成正式推荐；
5. 拆分 web/app/HarborPilotApp.tsx；
6. 跑 python -m pytest -q、npx.cmd tsc --noEmit --incremental false、npm.cmd run build。
```
