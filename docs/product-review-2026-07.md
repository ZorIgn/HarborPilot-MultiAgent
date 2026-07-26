# HarborPilot MultiAgent 完整产品评审报告

> 评审日期：2026-07-26 ｜ 范围：后端（src/、scripts/、tests/）、前端（web/）、产品/UX、同类开源项目参考
> 方法：通读代码 + 本地实测（130 个后端测试全通过 + 场景自审通过 + 四模块 API 真跑 + 安全绕过实测）
> 运行环境：mock LLM 模式（无需 API Key），项目库 142 个港新硕士项目

---

## 一、测试执行结果（我实际跑的）

### 后端测试与自审
- `pytest`：**130 passed**（注：本机默认临时目录权限问题会报 20 个 ERROR，改可写 basetemp 后全通过，非代码缺陷）。
- `run_scenario_audit.py`：**quality gate passed**，三档背景（985/211/双非）分档、数据可信度、Agent 链断言稳定。

### 四模块 API 实测（mock 模式）

**背景评估 `/api/workflows/background`** — 逻辑合理：
| 用例 | 输入 | 输出等级 | 判断 |
|---|---|---|---|
| P1 | 985/CS/GPA88/雅思7.0 | A（规则分88）| 合理 |
| P2 | 211/EE/GPA82/雅思6.5 | B（规则分75）| 合理 |
| P3 | 双非/英语/GPA78/**无语言成绩** | **NEEDS_DATA** | ✅ 正确拒绝分档，要求补数据 |
| P4 | 985/GPA=3.7(4.0制)/托福100 | A-（换算约90）| GPA 换算生效 |

**项目规划 `/api/workflows/program-plan`** — 分档正确、硬门槛生效：
- P1 强背景：推荐池 42，顾问方案 主申5/保底3；GPA/语言全过，仅"偏好背景缺证据"软提示。
- P2 中等：**多个 GPA=82 项目被正确挡在 min_gpa=83 门槛外**（列入 rejected_or_deferred）。
- P3 弱背景：推荐池 0（因 NEEDS_DATA，不硬凑推荐）✅
- **formal_recommendation 全部为 False** ✅ 未核验数据不冒充正式推荐。

**时间线 `/api/workflows/application-plan`** — 结构完整：
- 生成 14 条任务，字段含 due_date/priority/task_type/round_deadline/application_url，`round_deadline: "NOT_PUBLISHED"` 标注清晰。
- 边界防护正确：伪造 program_id → HTTP 422；`target_cycle=2031-fall` → HTTP 422 且提示可用申请季。

**文书写作 `/api/workflows/writing-*`** — 有一个明显缺陷：
- interview 生成 6 道结构化问题（项目题目/故事卡/技术深度/事实核验/Why Program/职业目标），设计良好。
- review_rubric 输出量表（prompt_coverage/program_specificity/unsupported_claims/word_count）合理。
- **❌ 严重问题：outline 生成的草稿把同一段经历机械重复 3-5 次**。实测填入不同答案后，生成的 PS 每个段落都塞进相同的问题句和结果句（"大三时实验室的推荐系统…" 连续出现，见下文 B-1）。这不是可用的文书草稿，是模板占位符的机械拼接。

---

## 二、严重问题（Critical / High）

### A. 安全（已本地实测证实）

**A-1 【Critical，已实测】学生端可匿名劫持全局 LLM Provider**
`app.py:400-402` 的 `POST /api/llm-config` **不在 `/api/admin/` 前缀下**，完全绕过 `admin_api_guard` 中间件（`app.py:228`），与受保护的 `/api/admin/llm-config`（395 行）调用同一个 `_configure_llm_provider`，改写进程级全局变量 `llm_provider`。

实测证据（同一台服务器）：
```
POST /api/admin/llm-config 无token → HTTP 403（被拦）
POST /api/llm-config       无token → HTTP 200（绕过！provider 被改）
```
后果：(1) 任何匿名请求可把全站 provider 切成 `mock` 静默降级，或指向攻击者 `base_url`，则**其他所有用户**后续评估/文书请求（含完整个人档案 JSON）都被 POST 到攻击者服务器；(2) 学生 A 填入的 API Key 变成全站共享（费用盗用）。
修复：该端点必须走 admin 鉴权或改为按会话/档案维度的 provider，禁止学生端指定 base_url。

**A-2 【Critical，已实测】LLM smoke test 构成无防护 SSRF + 响应体回显**
`base_url` 未经任何校验（不走爬虫侧那套 `_unsafe_url_reason` 的 HTTPS/内网 IP 检查），服务器直接向 `{base_url}/chat/completions` 发 POST。

实测证据：
```
base_url=http://169.254.169.254（云元数据地址）→ 服务器实际发起连接（本机无元数据服务才失败）
base_url=http://127.0.0.1:8011（本机服务）→ HTTP 400，错误详情回显内网响应体："模型服务返回 404：{"detail":"Not Found"}"
```
可探测内网服务并从错误信息读回响应内容。项目在爬虫侧做了认真的 SSRF 防护，却在这里开了更大的洞。
修复：对 base_url 复用 `_unsafe_url_reason` 校验，错误信息不回显响应体。

**A-3 【High】Admin 鉴权默认策略脆弱**
`app.py:237-250`：未配 token 时 (a) `client_host == "testclient"` 是写死在生产代码里的测试后门；(b) 本机判断基于 `request.client.host`，部署在 nginx/docker 反向代理后所有外部请求源 IP 都变 127.0.0.1，GET admin 端点对公网裸露（docker-compose.yml 说明代理部署是现实场景）。
修复：默认拒绝、去掉 testclient 分支、文档强制要求 token。

**A-4 【High】学生档案"加密"是自制流密码，密钥与密文同目录明文**
`profile_store.py:268-324`：SHA256 XOR 自制加密，兼容无 HMAC 的旧格式（可剥离完整性校验）且接受裸明文；默认密钥 `data/.harborpilot_profile_secret` 与 sqlite 同目录，对"数据库被拷走"威胁形同虚设。
修复：改用 `cryptography` 的 AES-GCM/Fernet，密钥外部注入。

**A-5 【High，DNS rebinding】SSRF 校验 TOCTOU**
`source_snapshot.py`：校验时 `getaddrinfo` 解析、连接时再次独立解析，攻击者用 TTL=0 rebinding 可绕过。修复：解析后固定 IP 连接（pinned-IP + Host header）。

### B. 正确性 Bug

**B-1 【High，已实测】文书草稿机械重复同一段经历 3-5 次**
`agents/writing.py`（`run_from_story_cards` / 段落装配）：把 story card 的问题句、结果句原样复制进"申请动机/学术基础/实践故事"每个段落。实测生成的 PS 前 400 字里同一句话连续出现 5 次。对以文书为核心交付物的工具，这是可用性硬伤。
修复：段落装配应按角色分配不同素材片段，去重，或改为提纲+引导而非伪造成稿。

**B-2 【High】采集 Agent 在选中 ID 全部无效时静默 fallback 抓无关项目**
`data_acquisition.py:754-759`（`if selected: return selected` 否则 `return programs[:12]`）、`data_refresh.py:283-295`。worker 执行 live job 时（`agent_worker.py` 不做 ID 校验）一个拼错的 program_id 会对 12 个从未被选择的项目发起真实官网抓取和证据写入，违背"最小抓取范围"原则。
修复：selected_ids 非空但无匹配时应报错，而非扩大范围。

**B-3 【High】agent_runtime.sqlite 并发写无保护 + 连接泄漏**
`agent_runtime.py:662-665` 的 `_connect` 无 WAL、无 busy_timeout（对比 `program_store.py:485` 是有的）。`TraceRecorder` 在**每个** `/api/workflows/*` 请求里都写库；并发请求 + 同进程 BackgroundTasks worker 同时写 → `database is locked` 直接 500。全库 `with _connect() as conn` 只 commit 不 close，连接泄漏靠 GC；agent_runs/steps/events 无清理，无限增长。
修复：统一 WAL + busy_timeout + `contextlib.closing`；trace 落库采样化；加保留策略。

**B-4 【Medium】ICS 日历导出时区 off-by-one**
`web/app/TimelinePage.tsx:390-391`：`parseTaskDate` 生成本地零点 Date，`toIcsDate` 用 `toISOString()`。UTC+8 用户导出的所有日历事件**提前一天**——在一个以"截止日期可信"为卖点的产品里，这是高危 bug。

**B-5 【Medium】GPA 换算阶梯悬崖 + 制式校验脱节**
`core/rules.py:365-383`：只支持 100/4.0/5.0（无 4.3/4.5，港澳台韩常见）；4.0 制是 8 级阶梯，3.84→85 vs 3.85→95 之间存在 5 分悬崖，直接改变 min_gpa 过/不过。`models.py:113` `gpa` 校验与 scale 无联动，`gpa=85, scale="4.0"` 是合法输入被 clamp 成 4.0→95（垃圾进良品出）。修复：线性插值替代阶梯，按 scale 校验范围。

**B-6 【Medium】前端多处数据丢失/覆盖**
- `AssessmentPage.tsx:139`：GPA 输入框清空 → `Number("")===0`，静默写成 0，直接影响硬门槛。
- `WritingWorkspace.tsx`：换项目重新生成文书直接覆盖旧稿，"版本历史"只存元数据（标题/字数）无法恢复内容。
- `TimelinePage.tsx:163`：材料勾选是纯本地 state，切 Tab/刷新即丢失。
- 经历列表只能加不能删（`AssessmentPage.tsx`）。

**B-7 【Medium】时间线日期边界**
`agents/timeline.py:31`：`internal_start = max(today, date(year,8,15))` 使 1-7 月运行时兜底任务全被推到 8/15 后；`timeline.py:356` `reminder_at` 误用 `date.today()` 而非传入 today；`formal_gate.py:142` `date.fromisoformat("2027-1-5")` 对非补零日期抛 ValueError 被吞，合法 deadline 反被判为"无日期"而 block。

**B-8 【Medium】`/api/programs` N+1 性能**
`app.py:646-727` + `evidence_graph.py`：每个 program 都全表读一遍 evidence，142 项目 ≈ 300+ 次查询；`load_programs()` 每次都跑 CREATE TABLE + 建索引。修复：批量取 evidence 分组，`init_program_store` 进程级只跑一次。

**B-9 【Medium】其他领域逻辑**
- portfolio 硬规则只搜 `raw_interest_text`，写在 experiences/skills 里的作品集看不到，`severity=hard` 直接误杀设计类项目（`rules.py:192`）。
- `unknown` 学校层级 **-2 分**（`rules.py:427`），系统性惩罚小众海外院校。
- `/api/programs` 的 `language_min` 只看 IELTS，TOEFL-only 项目默认 0 永远通过（`app.py:698`）。
- reviewer_id 来自请求体自报字符串（`models.py:592`），整条人工审核审计链可伪造。

**B-10 【Medium】真实模型 JSON 解析必踩坑**
`core/llm.py:60-88`：未设 `response_format={"type":"json_object"}`，不剥 Markdown 围栏，`json.loads` 失败后**静默**返回 `{"summary":"```json..."}`，下游 `.get()` 拿不到字段就退回规则结果——**真实模型模式大概率在无日志情况下退化成 mock 行为，用户花了 API 费用拿到规则输出**。`evaluation.py:17-28`、`data_refresh.py:261` 两处 LLM 裸调用无 try/except，模型抖动会 500 整条工作流。

---

## 三、产品/UX 问题（学生视角）

**最不友好的三件事：**
1. **内部数据治理术语全量外露**："方案可信度闸门""待官网核验""字段""证据覆盖""事实绑定""全库待审字段"贯穿从首页到文书导出的每个页面。团队在来源治理上的投入本是差异化优势，但学生被迫先学一套数据治理黑话才能申请。应收敛为"✅可信 / ⚠️去官网确认"两级表达。
2. **文书草稿被静默覆盖、"版本历史"无法恢复内容**——对文书工具等于让学生在无存档的编辑器里写申请材料。
3. **日历 DDL 早一天 + GPA 清空变 0**——在以"截止日期可信"为卖点的产品里，这两个最容易实际伤害申请结果。

**其他重点 UX 问题：**
- 首页 Dashboard 放的是给运营看的爬虫健康面板（"来源记录 N 条已核验""索引页只负责发现项目链接…"），不是学生要的下一步动作。
- 选校页信息过载最严重：可信度闸门 + 资料可用性 + 已保存清单 + 可编辑方案表 + 5 个分档 Tab，**同一批项目展示两遍**；"加入方案"vs"加入清单"两个相近概念并存，学生分不清。
- 文书问卷一页一题，PS 有 8 分区几十题要点几十次"下一题"；"还差 N 个必填"不告诉是哪几题。
- `/agent-lab`（Admin 数据中心）无前端权限门，任何学生输入 URL 即见爬虫/审核/发布按钮，且危险操作（Run live crawler / Publish / Rollback）单击即发、无确认。
- `/admin` 路由 bug：渲染的是 AI 设置页而非 Admin 数据中心（`app/admin/page.tsx:4` 传错 view）。
- Admin token 在 UI 上**根本没有输入框**（`setStoredAdminToken` 全项目 0 处调用），管理动作失败提示"检查 Admin token"却无处可填——断头流程。
- 版本历史出现乱码"?"（应为"·"分隔符，`WritingWorkspace.tsx:537`）；源码中英文混杂、部分中文用 `\uXXXX` 转义。

**前端代码问题：**
- `HarborPilotApp.tsx`（711 行）是"上帝组件"，约 35 个 useState + 全部 6 个子页面渲染分支，无路由级代码分割；每次切页整组件重挂载并发约 10 个请求（含学生页调 admin 接口）。
- 路由跳转用 `window.location.assign` 整页刷新（`HarborPilotApp.tsx:397`）而非 `router.push`，丢内存状态。
- `PanelTitle/Metric/DataBadge/EmptyState/tierLabel/formatMoney` 等在 5 个大组件里各复制一份；`WritingWorkspace.tsx` 手写 200 行 DOCX/ZIP/CRC32 生成器（`escapeXml` 漏单引号）。
- `lib/api.ts`：无超时/AbortController；`String(data.detail)` 对 FastAPI 校验错误数组会显示 `[object Object]`；admin token 存 localStorage（XSS 可读）。
- 硬编码换季即错：顶栏写死 `2027 Fall`；`dataStatusLabels` 把 STALE 写死"2026 Fall 往届参考"；前端硬编码 SMU/NTU/HKUST URL 判别规则（数据层逻辑泄漏进 UI）。

---

## 四、架构评价："multi-agent" 名副其实吗？

**结论：当前的"multi-agent"更接近营销修辞而非架构事实，但底层分层设计是扎实的。**

`WorkflowOrchestrator` 是一个普通的顺序函数调用管道，各"Agent"是无状态类方法——没有消息传递、没有规划、没有 Agent 间协商或动态路由。`agent_chain=["SourceDiscoveryAgent", ...]` 里一半的 Agent 名字在代码里根本不存在（是硬编码标签）；`catalog_auto_update` 名为 auto-update、上报 `live_fetch`，实际不联网只回放硬编码种子表；`trace.py:57` 的 `cost_usd` 是用耗时编造的。Profile/Evidence/Evaluation 三个纯函数拆成三个"Agent"意义不大。

但剥掉修辞，**底层是好设计**：确定性规则做评分与硬门槛、LLM 只做措辞润色且被明确限权、字段级证据 + 人工审核门 + 官方域名绑定（source_identity/review_gate/formal_gate）构成一条同类项目里少见的认真可信度管线。真正的问题是职责切得过碎（16 个 agent + 19 个 service 互相耦合，`data_acquisition` 直接 import `data_refresh` 的私有函数），而横切关注点（SQLite 连接、LLM 错误处理、ID 校验）各写各的，导致同类 bug 在多处重复。

**建议**：把"Agent"这个词留给队列 + worker + 审核门那条真正异步、有人工介入的链路（那里确实 agentic）；学生侧同步管道诚实地叫 pipeline。优先修 A-1/A-2/B-1/B-2 —— 这几个与架构叙事无关，是纯粹的安全与正确性缺陷。

---

## 五、GitHub 同类开源项目参考（按模块，均已核实真实存在）

### 模块 1 · 背景评估 / 录取概率
- **[deedy/gradcafe_data](https://github.com/deedy/gradcafe_data)**（~80★）GradCafe 全站 27 万条录取记录 + 脏数据清洗文档。→ 可作评估 Agent 的概率校准基线；实体归一化经验可参考。
- **[jjdelvalle/gradcafe_analysis](https://github.com/jjdelvalle/gradcafe_analysis)** scrape→parse→analyze 三段流水线。→ 可映射到 data_acquisition→information_store 管道。
- 共性提醒：GradCafe 数据都警告"自报幸存者偏差"，与你们 review_gate/证据可信度方向一致，评估输出概率时应做不确定性标注。

### 模块 2 · 择校推荐 / 项目库
- **[Global-CS-application](https://github.com/Global-CS-application/global-cs-application.github.io)**（~780★）**"欧港新CS留学项目指北"，与你们港新定位最直接对口**。→ 其项目条目结构（难度认知/同档对比/回国名气等维度）可直接作 program_store 字段蓝本和初始语料。
- **[opencsapp/opencsapp.github.io](https://github.com/opencsapp/opencsapp.github.io)**（~2.3k★）开源CS申请，选校梯度表 + CS/非CS title 区分标注。→ 择校 Agent 输出结构的最佳参照。
- **[OpenSIST](https://github.com/OpenSIST/OpenSIST.github.io)**（~110★）真正的 Vue Web 应用（非 wiki），项目详情页 + 往届录取 datapoints。→ 与 ProgramCatalogPage 定位最接近。
- **[CS-BAOYAN](https://github.com/CS-BAOYAN/CSSummerCamp2024)**（~1.6k★）按年归档 + "不担保准确性请自行辨别"免责声明。→ 参考其时效性管理与数据可信度声明。

### 模块 3 · 时间线 / 材料管理
- **[CS-BAOYAN/CS-BAOYAN-DDL](https://github.com/CS-BAOYAN/CS-BAOYAN-DDL)**（~450★）DDL 追踪站，档次筛选 + 单时钟驱动全部倒计时 + 列表/日历双视图 + URL 状态可分享。→ **时间线前端交互最佳范例，可直接搬到 TimelinePage**。
- **[Gsync/jobsync](https://github.com/Gsync/jobsync)**（~760★）自托管求职 tracker，Next.js + Prisma + SQLite + AI 评审 + 多 LLM provider。→ 技术栈几乎同构，"申请记录+任务+状态流转+仪表盘"数据模型可直接改造。
- **[lumiis2/opportunity-tracker](https://github.com/lumiis2/opportunity-tracker)**（~100★）可订阅 .ics 日历源。→ 时间线模块低成本高价值功能。

### 模块 4 · AI 文书写作 / SOP
- **[AmirLayegh/agentic-essay-writer](https://github.com/AmirLayegh/agentic-essay-writer)** LangGraph 五阶段 plan→research→write→revise→finalize + SQLite checkpoint。→ **文书 Agent 标准骨架，checkpoint 持久化正好解决你们"换项目覆盖旧稿"的缺陷**。
- **[SagarMaddela/Essay-Writer-Agent](https://github.com/SagarMaddela/Essay-Writer-Agent)** 把 plan/critique 每步实时透出给用户。→ 与可信工作流理念一致，critique 应显式呈现而非黑盒改写。
- **[gen-li/SOP_GEN](https://github.com/gen-li/SOP_GEN)** "一份主文书 + 按校变量替换"模板机制。→ 申请多个港新项目时文书 80% 复用，只对差异段个性化，比每校从零生成更贴近真实工作流（也能缓解 B-1 的机械重复）。

### 模块 5 · Multi-Agent 编排框架
- **[LangGraph](https://github.com/langchain-ai/langgraph)**（~38k★）有状态图 + durable execution + **human-in-the-loop（任意节点暂停供人审核）**。→ **与你们 review_gate 人工审核关卡完美契合，四个 Agent 天然是带条件边的 StateGraph**。
- **[crewAI](https://github.com/crewAIInc/crewAI)**（~56k★）role/goal/backstory 角色化 + Flows 事件驱动。→ 适合把"评估/择校/文书导师"角色化，及"数据刷新完成触发重评估"链路。
- **[MetaGPT](https://github.com/FoundationAgents/MetaGPT)**（~70k★）Code=SOP(Team)，SOP 驱动角色流水线逐级产出结构化文档。→ 恰好对应留学顾问流水线（评估报告→选校清单→时间规划→文书）。
- 教育域实例：[ASUCICREPO/Admissions-AI-Agent](https://github.com/ASUCICREPO/Admissions-AI-Agent)（AWS Bedrock 招生顾问 + 转人工 handoff）。

### 模块 6 · 大学官网数据采集 / 可信度
- **[crawl4ai](https://github.com/unclecode/crawl4ai)**（~75k★）LLM 友好爬虫，schema-based JSON 抽取 + FastAPI 部署。→ **data_acquisition Agent 可直接用它抓港新官网，比手写解析器可维护得多，栈一致**。
- **[Hipo/university-domains-list](https://github.com/Hipo/university-domains-list)**（~1.6k★）全球大学官方域名 JSON + API。→ **与 source_identity 模块高度契合，可作"域名是否官方"判定的基础数据**。
- **[AnshumanAtrey/ucas_scraper](https://github.com/AnshumanAtrey/ucas_scraper)** 按页面版块模块化抽取 + 动态检测版块存在性。→ 适合港新各校官网结构差异大的现实，每校一份 JSON 快照与 source_snapshot 吻合。

---

## 六、优先修复建议（按 ROI 排序）

1. **A-1 / A-2**（安全，立即）：给 `/api/llm-config` 加鉴权 + 对 base_url 做 SSRF 校验。改动小、风险大。
2. **B-1**（文书重复，核心可用性）：重写段落装配，或改组合 SOP_GEN 主模板机制 + agentic-essay-writer 骨架。
3. **B-4 / B-6**（DDL 早一天 + GPA 变 0 + 文书覆盖 + 材料勾选丢失）：直接伤害学生的数据可靠性细节。
4. **UX 收敛术语**：内部治理词收敛为"✅可信 / ⚠️去官网确认"两级，细节折叠。
5. **B-2 / B-3**（采集范围 + SQLite 并发）：worker 数据安全与稳定性。
6. **架构诚实化**：删死代码与虚构 agent_chain 标签，把 pipeline 与真正 agentic 的审核链分开命名。

底层可信度管线是这个产品真正的护城河，值得保留并做深；当前主要缺陷集中在安全边界、文书生成质量、以及"把工程内部世界观直接暴露给学生"这三点。
