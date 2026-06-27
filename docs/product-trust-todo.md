# HarborPilot 可信化改造 TODO

## 已落地

- `/api/programs` 已返回 `trust_detail`，目录页能直接展示项目字段级证据、状态、来源和人工发布闸门。
- 新增 `GET /api/programs/{program_id}/trust`，后续项目详情页和人工审核后台可以复用同一份可信度结构。
- 项目目录页新增关键字段证据面板，未确认字段明确标记为准备建议，避免把上一申请季或抽取结果包装成正式结论。

- GPA 按 `100 / 4.0 / 5.0` 标尺换算后再进入评估和择校。
- 语言硬门槛按考试类型单独判断，TOEFL 不再被包装成 IELTS。
- ReviewAgent 将未确认官网数据纳入未通过条件，不能把草案当正式申请结论。
- 背景资料页新增排名、语言单项、核心课程、经历表等关键入口。
- GradWindow / QS Master Applications 已作为港新官网线索包接入，用于定位官网项目页、申请入口和上一申请季窗口，不直接覆盖正式字段。

## 参考项目落地方式

- GlobalCS / WaterCS：采用“信息辅助 + 主观限制声明 + 项目初选”的定位，不把社区经验写成官方要求。
- GradWindow / qs-master-applications：复用其 `universities / programs / applications / window-policies` 思路，把申请窗口拆成来源、周期、证据和政策。
- LangGraph / AutoGen：后续将当前顺序式 agent 升级为状态机，支持资料不足时主动追问、回退和复核。
- Haystack / LlamaIndex：用于官网 HTML/PDF 的字段抽取、证据片段绑定和 RAG 检索。
- Phoenix：记录每次 agent 的输入、输出、证据来源和人工复核原因。
- Formbricks：把背景资料、经历表和文书问卷拆成可维护问卷 schema。
- Plane / cal.com：把任务与材料页面升级成看板、日历和提醒。
- Reactive Resume / Docmost：文书工作台增加版本管理、导出、逐句事实绑定和审阅流程。

## 下一阶段 P0

- 建立真实官网抓取队列：Playwright + PDF parser + snapshot hash + diff。
- 为 `deadline / tuition / language / materials / application_url` 建立人工发布闸门。
- 项目详情页展示每个字段的来源原文、抓取时间、申请季和状态。
- 文书工作台增加版本、字数约束、逐句事实绑定编辑和导出。
- 把 localStorage 替换为本地用户档案 API，API Key 不进入浏览器存储。
