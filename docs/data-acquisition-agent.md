# HarborPilot 数据获取与公开信息聚合 Agent

## 目标

学生打开项目详情时，应看到一份可审计的信息包，而不是一段没有来源的模型总结。信息包需要覆盖：

- 项目要求：截止日期、学费、语言、材料、申请入口、文书题目。
- 项目内容：课程方向、学制、先修课线索、适配背景。
- 投递时间线：官方截止、上一申请季参考、内部准备建议三类状态分开显示。
- 公开社区经验：笔试、面试、文书、录取/拒信时间线、准备建议。
- 每条信息都展示来源 URL、申请季、抓取时间、快照 hash、字段状态和是否需要人工审核。

## 数据边界

官方字段只能来自学校公开页面、官方 PDF/FAQ、公开申请系统入口或学校官方项目索引。社区来源只用于经验参考，不能覆盖官方字段。

官方字段：`deadline`、`tuition_hkd`、`language_requirement`、`materials`、`application_url`、`essay_prompts`。

社区参考：`interview`、`written_test`、`admission_case`、`timeline_experience`、`preparation_advice`、`program_alias`。

禁止推断：录取概率、保录承诺、官方豁免、内部推荐、未发布申请季的最终截止日期。

## Agent 流程

1. `SourceDiscoveryAgent`
   - 读取 `data/source_registry.json` 与 `data/acquisition_sources.json`。
   - 按学校、项目 URL、项目别名、社区查询模板生成采集计划。

2. `RobotsPolicyAgent`
   - live fetch 前先检查 `robots.txt`。
   - robots 未明确允许时，进入人工审核队列，不自动抓取。
   - 对搜索、论坛、社交平台，只使用合规搜索 API、公开页面或人工提供的公开 URL。

3. `OfficialCrawlerAgent`
   - 低频抓取学校官方项目页、索引页、PDF/FAQ 和公开申请入口。
   - 保存 HTML/PDF 快照、`page_hash`、抓取时间和 MIME 类型。
   - 与历史快照比较，标记 `content_changed`。

4. `PdfFaqExtractionAgent`
   - 对官方 PDF/FAQ 提取文本候选。
   - 只输出材料、语言、文书、面试政策等候选字段。
   - 候选字段默认 `review_required=true`。

5. `CommunitySignalAgent`
   - 只采集公开页面、公开 GitHub 仓库、公开论坛/搜索结果短摘录。
   - 不采集登录后内容、付费墙、私域群聊、个人隐私信息。
   - 输出面试、笔试、文书、时间线和准备建议标签。

6. `EvidenceMergeAgent`
   - 按字段合并来源，官方优先级高于社区。
   - 冲突字段标记 `CONFLICTED`。
   - 社区信息始终保留“经验参考，非官方要求”边界。

7. `HumanReviewGateAgent`
   - 人工查看原文后，官方字段才能发布为 `OFFICIAL_VERIFIED_CURRENT`。
   - 未确认字段只能用于准备提醒，不能作为正式推荐或正式时间线。

## 当前接口

```text
GET  /api/programs/{program_id}/data-package
POST /api/workflows/data-acquisition
POST /api/workflows/data-refresh
```

`ProgramDataPackage` 包含：

- `official_requirements`
- `content_sections`
- `essay_prompts`
- `timeline_fields`
- `community_experiences`
- `acquisition_plan`
- `freshness_warning`
- `human_review_required`

`DataRefreshReport.source_checks` 现在包含：

- `robots_txt_url`
- `robots_allowed`
- `robots_status`
- `page_hash`
- `previous_page_hash`
- `content_changed`
- `snapshot_path`
- `snapshot_mime`

## 运行方式

```cmd
cd /d E:\multi_agent
python -m pytest tests\test_api.py::test_program_data_package_exposes_official_and_community_acquisition_plan -q
```

默认实现是 dry-run/review-first，不会自动覆盖主项目库。生产化时继续接入 Playwright、PDF parser、搜索 API、队列、快照 diff 和人工审核后台。