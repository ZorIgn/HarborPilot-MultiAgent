# HarborPilot 数据获取与公开信息聚合 Agent 设计

## 目标

学生在项目详情页应能看到：

- 项目概览、方向、学制、课程/先修课线索。
- 官方要求：截止日期、学费、语言、材料、申请入口、文书题目。
- 投递时间线：官方截止、上一申请季参考、内部准备建议三种状态分开显示。
- 公开社区经验：笔试、面试、文书、录取/拒信时间线、准备建议。
- 每条信息都要展示来源 URL、申请季、抓取时间、状态和是否需要人工审核。

## 数据边界

官方字段只能来自学校公开页面、官方 PDF/FAQ、申请系统公开入口或学校官方项目索引。社区来源只用于经验参考，不能覆盖官方字段。

官方字段包括：`deadline`、`tuition_hkd`、`language_requirement`、`materials`、`application_url`、`essay_prompts`。

社区参考包括：`interview`、`written_test`、`admission_case`、`timeline_experience`、`preparation_advice`。

禁止推断：录取概率、保录承诺、官方豁免、内部推荐、未发布申请季的最终截止日期。

## Agent 流程

1. `SourceDiscoveryAgent`
   - 从 `data/source_registry.json` 和 `data/acquisition_sources.json` 读取官方与社区源。
   - 按项目学校、官方 URL、项目别名生成源计划。

2. `OfficialCrawlerAgent`
   - 检查 robots/站点条款。
   - 低频抓取官方项目页、索引页、申请系统公开页。
   - 保存 HTML/PDF 快照、`page_hash`、抓取时间。

3. `PdfFaqExtractionAgent`
   - 对官方 PDF/FAQ 提取文本。
   - 抽取材料、语言、文书、面试政策等候选字段。

4. `CommunitySignalAgent`
   - 只采集公开页面、公开 GitHub 仓库、公开论坛/搜索结果短摘录。
   - 不采集登录后、付费墙、私域群聊、个人隐私信息。
   - 输出面试、笔试、文书和时间线经验标签。

5. `EvidenceMergeAgent`
   - 按字段合并来源，官方优先级高于社区。
   - 对冲突字段标记 `CONFLICTED`。

6. `HumanReviewGateAgent`
   - 人工查看原文后才能把官方字段发布为 `OFFICIAL_VERIFIED_CURRENT`。
   - 社区经验始终保留“经验参考，非官方要求”的边界提示。

## 当前接口

```text
GET  /api/programs/{program_id}/data-package
POST /api/workflows/data-acquisition
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

## 运行方式

```cmd
cd /d E:\multi_agent
python -m pytest tests\test_api.py::test_program_data_package_exposes_official_and_community_acquisition_plan -q
```

当前实现默认是 dry-run/review-first，不会自动覆盖主项目库。生产化时再接入队列、Playwright、PDF parser、搜索 API、快照 diff 和人工审核后台。