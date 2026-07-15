# HarborPilot 官网真实数据管线实施计划
## 抓取快照 → 字段抽取 → 冲突检测 → 人工发布

> **目标**：将多 Agent 留学平台从"静态 JSON + 部分正则爬取"升级为**全自动、可溯源、人工审核把关**的官网真实数据管线，彻底消除学生看到假数据的风险。

---

## 一、现状审计 — 核心问题诊断

### 1.1 数据层现状（严重缺陷）

| 问题 | 现象 | 危害 |
|------|------|------|
| **数据几乎全是静态 JSON** | `programs_2027_fall.json` 428KB 静态文件，`captured_at: 2026-06-13`，所有字段 `data_status: EXTRACTED`，`last_verified_at: null` | 学生看到的截止日期可能是错的，会误了申请 |
| **爬虫只是占位符** | `source_snapshot.py` 用的是 `urllib.urlopen` + 简单正则，Playwright 被环境变量 `HARBORPILOT_USE_PLAYWRIGHT=0` 完全禁用 | 大量 JS 渲染页面（HKU/CUHK）根本抓不到 |
| **字段抽取极其脆弱** | `_deadline_candidate()` 等函数只是暴力正则，没有结构感知，confidence 永远是 medium/low | 抽取质量极低，假阳性率高 |
| **无调度机制** | 没有任何 cron job / scheduler，数据只能手动触发刷新 | 申请季关键时间节点无法自动捕捉变更 |
| **冲突检测缺失** | 同一字段新旧值不一致时没有任何 diff 逻辑 | 数据悄悄变了，没人知道 |
| **人工审核 UI 不存在** | 代码里写了 `review_required=True`，但前端没有对应的审核界面 | 审核流程是空话 |
| **official_program_url 指向目录页** | 所有 HKU 项目的 `official_program_url` 都是 `https://admissions.hku.hk/tpg/programme-list` 而非具体项目页 | 字段级别的官方证据完全无效 |
| **PDF 处理能力不足** | 只用了 pypdf，遇到扫描版 PDF/图片型截止日期表完全失效 | 大量学校把关键要求放在 PDF 里 |

### 1.2 现有基础（可复用）

- ✅ `FieldEvidenceRecord` 数据模型设计合理，支持字段级溯源
- ✅ `source_registry.json` 已注册 30+ 个官方来源，有 URL
- ✅ `program_store.py` SQLite schema 设计正确（`program_field_evidence` 表）
- ✅ `snapshot_source()` 函数骨架存在，可升级
- ✅ Agent 链设计（SourceDiscoveryAgent → OfficialCrawlerAgent → ...）方向正确
- ✅ `HARBORPILOT_USE_PLAYWRIGHT` 开关存在，只需打开并完善

---

## 二、目标架构 — 四阶段管线

```
┌─────────────────────────────────────────────────────────────────┐
│                    HarborPilot 数据管线 v2                        │
├──────────┬──────────────┬──────────────┬──────────────────────┤
│  Stage 1  │   Stage 2    │   Stage 3    │       Stage 4         │
│ 抓取快照   │  字段抽取     │  冲突检测    │    人工发布            │
│ Crawl4AI  │  Docling+LLM │  Diff Engine │  Review UI → Publish │
│ + Scrapy  │  + 正则兜底   │  + Alert     │  → programs JSON     │
└──────────┴──────────────┴──────────────┴──────────────────────┘
```

### 技术选型决策

| 场景 | 推荐工具 | 理由 |
|------|---------|------|
| JS 渲染页面（HKU/NUS/HKUST） | **Crawl4AI** `AsyncWebCrawler` | 原生 Playwright 封装，支持 LLM 提取，无需自写 Playwright 控制逻辑 |
| 静态 HTML 大批量 index 页 | **Scrapy** Spider | 成熟的调度/中间件/去重/速率控制，适合批量索引页抓取 |
| PDF 文件（要求手册/FAQ） | **Docling** `DocumentConverter` | IBM 出品，支持 OCR、表格识别、结构化输出 Markdown，远超 pypdf 正则 |
| 字段语义提取 | **Crawl4AI `LLMExtractionStrategy`** + 自定义 schema | 直接把抽取 prompt 绑定在 schema 上，输出结构化 JSON |
| 调度 | **APScheduler** / cron | 每周申请季自动触发，夜间批量运行 |

---

## 三、详细实施计划（按模块）

---

### Module 1：依赖升级与环境配置

**目标**：安装真实爬虫工具链，不破坏现有代码

#### 文件变更

**[MODIFY] requirements-crawler.txt**
```
-r requirements.txt
pypdf>=4.0.0
playwright>=1.45.0
# NEW: 真实爬虫工具链
crawl4ai>=0.6.0
scrapy>=2.11.0
docling>=2.0.0
apscheduler>=3.10.0
httpx>=0.27.0
parsel>=1.9.0
```

**[NEW] scripts/install_crawlers.ps1** — Windows 环境一键安装脚本
```powershell
pip install -r requirements-crawler.txt
playwright install chromium
python -m crawl4ai.sync_installer
```

**[MODIFY] .env.example** — 新增关键环境变量
```
HARBORPILOT_USE_PLAYWRIGHT=1        # 打开 Playwright 渲染
HARBORPILOT_USE_CRAWL4AI=1          # 启用 Crawl4AI
HARBORPILOT_CRAWL_CONCURRENCY=3     # 并发数（礼貌爬取）
HARBORPILOT_CRAWL_DELAY_SEC=2.0     # 请求间隔
HARBORPILOT_CRAWL_SCHEDULE_CRON=0 2 * * 1  # 每周一凌晨2点
HARBORPILOT_LLM_EXTRACTOR=openai   # 字段抽取 LLM
HARBORPILOT_REVIEW_NOTIFY_EMAIL=    # 审核通知邮件
```

---

### Module 2：Stage 1 — 抓取快照（CrawlerEngine 升级）

**目标**：用 Crawl4AI 替代现有 urllib，支持 JS 渲染、PDF、速率控制

#### 新文件结构

```
src/harbor_agent/crawler/
├── __init__.py
├── engine.py          # 核心爬取引擎（Crawl4AI + Scrapy 统一接口）
├── spider_hk.py       # 港校 Scrapy Spider
├── spider_sg.py       # 新加坡高校 Spider
├── pdf_downloader.py  # PDF 专项下载器
├── robots_policy.py   # 统一 robots.txt 策略（升级现有逻辑）
└── rate_limiter.py    # 速率控制（per-domain leaky bucket）
```

#### engine.py 核心实现思路

```python
# src/harbor_agent/crawler/engine.py
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy
import asyncio

class HarborCrawlerEngine:
    """
    统一爬取入口。
    - JS 渲染页面 → Crawl4AI (Playwright)
    - 静态页面    → httpx + parsel（快速）
    - PDF        → requests 下载 → Docling 解析
    """

    async def crawl_program_page(
        self, url: str, program_id: str
    ) -> CrawlSnapshot:
        """
        抓取单个项目页，返回含原始 HTML、截图、page_hash 的快照。
        自动判断是否需要 JS 渲染。
        """
        config = CrawlerRunConfig(
            wait_until="networkidle",
            screenshot=True,           # 保存截图作为人工审核附件
            pdf=False,
            word_count_threshold=50,
            cache_mode=CacheMode.BYPASS,  # 每次强制刷新
        )
        async with AsyncWebCrawler(headless=True) as crawler:
            result = await crawler.arun(url=url, config=config)
        return CrawlSnapshot(
            url=url,
            program_id=program_id,
            html=result.html,
            markdown=result.markdown.raw_markdown,
            screenshot_path=self._save_screenshot(result.screenshot, program_id),
            page_hash=sha256(result.html.encode()).hexdigest(),
            crawled_at=datetime.now(UTC),
            http_status=result.status_code,
        )
```

#### 关键设计原则

1. **快照必须持久化**：每次抓取都写磁盘 `data/source_snapshots/YYYYMMDD/`，不仅存 HTML，还存截图 PNG，供人工审核对比
2. **page_hash 变更检测**：新快照 hash ≠ 旧快照 hash → 触发 Stage 3 冲突检测
3. **robots.txt 尊重**：升级现有 `_robots_allowed()`，加 per-domain 缓存，避免重复请求
4. **速率限制**：每个域名最多 1 req/3s，避免被封

---

### Module 3：Stage 2 — 字段抽取（Docling + LLM Schema）

**目标**：从 HTML/PDF 中精确提取 7 个关键字段，置信度显著高于正则

#### 抽取 Schema 定义

```python
# src/harbor_agent/crawler/field_schema.py
from pydantic import BaseModel
from typing import Optional

class ProgramFieldsSchema(BaseModel):
    """Crawl4AI LLMExtractionStrategy 使用的字段 schema"""
    deadline: Optional[str] = None          # "2027-01-31" 或 "Round 1: Nov 30"
    deadline_rounds: Optional[list[str]] = None  # 多轮截止日期
    tuition_hkd: Optional[str] = None       # "HKD 365,000" 或 "SGD 58,800"
    language_ielts: Optional[str] = None    # "6.5 overall"
    language_toefl: Optional[str] = None    # "90"
    materials: Optional[list[str]] = None   # ["transcript", "CV", ...]
    application_url: Optional[str] = None   # 申请系统直链
    essay_prompts: Optional[str] = None     # Personal Statement 要求
    open_date: Optional[str] = None         # 开放申请时间
    duration_months: Optional[int] = None   # 学制（月）
```

#### 三层抽取策略（降级兜底）

```
Layer 1（最优）: Crawl4AI LLMExtractionStrategy
  → instruction: "从以下官方项目页提取申请截止日期、学费、语言要求..."
  → schema: ProgramFieldsSchema
  → 置信度: high

Layer 2（降级）: Docling DocumentConverter（PDF 专用）
  → 将 PDF 转为结构化 Markdown
  → 再用 LLM 提取或增强正则

Layer 3（兜底）: 现有 regex candidates（保留）
  → _deadline_candidate(), _tuition_candidate() 等
  → 置信度: medium/low，标记为 review_required=True
```

#### PDF 处理升级

```python
# src/harbor_agent/crawler/pdf_processor.py
from docling.document_converter import DocumentConverter

class PdfFieldExtractor:
    def __init__(self):
        self.converter = DocumentConverter()

    def extract_from_url(self, pdf_url: str) -> str:
        """下载 PDF 并用 Docling 转换为结构化 Markdown"""
        # 1. 下载 PDF
        # 2. DocumentConverter().convert(pdf_path)
        # 3. 返回 result.document.export_to_markdown()
        # 4. 这个 Markdown 再交给 LLM 抽取字段
        ...
```

**Docling 优势**（对比现有 pypdf）：
- 支持 OCR（扫描版 PDF）
- 支持表格识别（学费表、申请时间表）
- 输出结构化 Markdown，LLM 可更精准理解
- 支持 NUS/NTU 那种多栏 PDF 申请手册

---

### Module 4：Stage 3 — 冲突检测（DiffEngine）

**目标**：自动发现字段值变更，生成可审核的 diff 报告

#### 新文件

**[NEW] src/harbor_agent/services/diff_engine.py**

```python
class FieldDiffEngine:
    """
    比较新抽取值 vs 数据库当前值，生成冲突报告。
    """

    def compute_diff(
        self,
        program_id: str,
        field_name: str,
        new_value: str,
        new_snapshot_hash: str,
    ) -> FieldDiffResult:
        current = self._load_current(program_id, field_name)
        if current is None:
            return FieldDiffResult(status="NEW_FIELD", ...)
        if current.page_hash == new_snapshot_hash:
            return FieldDiffResult(status="UNCHANGED", ...)
        if self._values_equivalent(current.value, new_value):
            return FieldDiffResult(status="HASH_CHANGED_VALUE_SAME", ...)
        # 关键字段变更：deadline, tuition → 触发紧急告警
        severity = "CRITICAL" if field_name in {"deadline", "tuition_hkd"} else "NORMAL"
        return FieldDiffResult(
            status="CONFLICT",
            severity=severity,
            old_value=current.value,
            new_value=new_value,
            old_snapshot=current.snapshot_url,
            new_snapshot=new_snapshot_hash,
            detected_at=datetime.now(UTC),
            requires_human_review=True,
        )
```

#### 冲突严重级别

| 级别 | 字段 | 处理方式 |
|------|------|---------|
| 🔴 CRITICAL | `deadline`, `tuition_hkd` | 立即邮件通知审核员，冻结发布 |
| 🟡 WARNING | `language_requirement`, `materials`, `application_url` | 加入审核队列，24h 内处理 |
| 🟢 INFO | `essay_prompts`, `open_date` | 记录 diff，下次审核批处理 |

---

### Module 5：Stage 4 — 人工审核发布（Review UI）

**目标**：给管理员提供完整的审核界面，确保"人工点击发布"才能更新学生可见数据

#### 新 API 端点（app.py 新增）

```python
# 审核队列 API
GET  /api/admin/review-queue          # 获取待审核字段列表
GET  /api/admin/review-queue/{id}     # 获取单条审核详情（含快照截图对比）
POST /api/admin/review-queue/{id}/approve   # 审核通过 → 发布
POST /api/admin/review-queue/{id}/reject    # 驳回 → 保留旧值
POST /api/admin/review-queue/{id}/flag      # 标记为可疑，再次抓取确认
GET  /api/admin/snapshot/{hash}       # 查看原始快照 HTML
GET  /api/admin/snapshot/{hash}/screenshot  # 查看截图
GET  /api/admin/crawl-jobs            # 查看爬虫任务状态
POST /api/admin/crawl-jobs/trigger    # 手动触发爬取（指定 program_id）
```

#### 审核 UI（新页面 web/src/pages/admin/ReviewQueue.tsx）

```
┌────────────────────────────────────────────────────────────┐
│ 待审核字段队列 (23 条)    [触发全量刷新] [导出报告]            │
├──────┬──────┬────────────┬────────────┬────────┬──────────┤
│ 严重 │ 项目  │ 字段       │ 旧值       │ 新值   │ 操作     │
├──────┼──────┼────────────┼────────────┼────────┼──────────┤
│ 🔴  │ HKU  │ deadline   │ 2027-01-31 │ 2027-  │ [查看快照]│
│ CS   │      │            │            │ 02-15  │ [通过][驳]│
├──────┼──────┼────────────┼────────────┼────────┼──────────┤
│ 🟡  │ NUS  │ tuition_hkd│ SGD 58,800 │ SGD   │ [查看快照]│
│ DSML │      │            │            │ 62,100 │ [通过][驳]│
└──────┴──────┴────────────┴────────────┴────────┴──────────┘

[快照对比面板]
左：旧快照 (2026-06-13)    右：新快照 (2026-07-10)
┌─────────────────┐  ┌─────────────────┐
│ Application     │  │ Application     │
│ Deadline:       │  │ Deadline:       │
│ 31 January 2027 │  │ 15 February     │  ← 高亮变更
└─────────────────┘  └─────────────────┘
```

#### 发布逻辑（三级保护）

```python
def publish_field(review_id: str, reviewer_id: str) -> None:
    """
    1. 检查 reviewer 权限
    2. 更新 program_field_evidence.status = 'OFFICIAL_VERIFIED_CURRENT'
    3. 更新 programs_2027_fall.json（或 program_catalog 表）对应字段
    4. 写审计日志（reviewer_id, approved_at, old_value, new_value）
    5. 清除相关 cache
    """
```

---

### Module 6：调度系统（Scheduler）

**目标**：自动化定时爬取，无需人工触发

#### 新文件

**[NEW] src/harbor_agent/scheduler/crawl_scheduler.py**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class CrawlScheduler:
    """
    申请季期间（9月-次年3月）：每周一凌晨2点全量爬取
    非申请季：每月爬取一次
    手动触发：支持 API POST /admin/crawl-jobs/trigger
    """

    def setup(self, app):
        scheduler = AsyncIOScheduler()
        # 申请季全量爬取
        scheduler.add_job(
            self.run_full_crawl,
            'cron',
            hour=2, minute=0,
            day_of_week='mon',
            id='weekly_full_crawl'
        )
        # 关键字段（deadline）高频监控
        scheduler.add_job(
            self.run_deadline_monitor,
            'cron',
            hour='*/12',  # 每12小时检查一次截止日期
            id='deadline_monitor'
        )
        scheduler.start()
```

#### 爬取优先级队列

```python
CRAWL_PRIORITY = {
    "deadline_within_30_days": 1,   # 30天内截止：最高优先
    "never_crawled": 2,             # 从未爬过
    "hash_changed": 3,              # 页面 hash 已变
    "crawled_over_7_days": 4,       # 超过7天未爬
    "routine": 5,                   # 常规
}
```

---

### Module 7：具体学校爬取实现

#### HKU（JavaScript 渲染，最复杂）

```python
# src/harbor_agent/crawler/spiders/hku_spider.py
class HKUSpider:
    """
    HKU 使用 React 渲染，必须用 Playwright 等待 networkidle。
    策略：
    1. 抓目录页 https://admissions.hku.hk/tpg/programme-list
    2. 解析每个项目链接
    3. 逐页抓取详情页（含截止日期、学费 tab）
    4. 特别处理：HKU 学费在 "Fees & Funding" tab，需要点击
    """

    PROGRAMME_LIST_URL = "https://admissions.hku.hk/tpg/programme-list"

    async def crawl(self) -> list[ProgramPageResult]:
        config = CrawlerRunConfig(
            js_code="""
                // 等待项目列表加载
                await page.waitForSelector('.programme-item', {timeout: 10000});
                // 收集所有项目链接
                window.__links = Array.from(
                    document.querySelectorAll('a[href*="/programme/"]')
                ).map(a => a.href);
            """,
            wait_for="css:.programme-item",
        )
        async with AsyncWebCrawler() as crawler:
            index_result = await crawler.arun(
                url=self.PROGRAMME_LIST_URL, config=config
            )
        programme_links = self._extract_links(index_result)
        return await self._crawl_detail_pages(programme_links)
```

#### NUS/NTU（多学院分散，需递归发现）

```python
class NUSSpider:
    """
    NUS 各项目在不同学院子域名，需要：
    1. 抓总索引页 → 发现各学院链接
    2. 递归进入学院页 → 找到具体项目页
    3. 每个学院的页面结构不同，需要个性化 selector
    """
    FACULTY_SELECTORS = {
        "nus.edu.sg/soc": "div.programme-details",  # 计算机学院
        "nus.edu.sg/fass": "table.admissions-table", # 文学院
        # ... 按学院配置 selector
    }
```

---

### Module 8：数据库 Schema 升级

#### 新增表和字段

```sql
-- 快照存储表（新增）
CREATE TABLE crawl_snapshots (
    id TEXT PRIMARY KEY,
    program_id TEXT,
    source_url TEXT NOT NULL,
    page_hash TEXT NOT NULL,
    snapshot_path TEXT,           -- HTML 文件路径
    screenshot_path TEXT,         -- 截图路径（人工审核用）
    crawled_at TEXT NOT NULL,
    http_status INTEGER,
    content_bytes INTEGER,
    is_js_rendered INTEGER DEFAULT 0,
    crawler_tool TEXT,            -- 'crawl4ai' | 'scrapy' | 'urllib'
    FOREIGN KEY(program_id) REFERENCES program_catalog(id)
);

-- 字段 diff 审核表（新增）
CREATE TABLE field_review_queue (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    old_snapshot_id TEXT,
    new_snapshot_id TEXT,
    diff_severity TEXT NOT NULL,  -- 'CRITICAL' | 'WARNING' | 'INFO'
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING/APPROVED/REJECTED/FLAGGED
    reviewer_id TEXT,
    reviewed_at TEXT,
    detected_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES program_catalog(id)
);

-- 爬虫任务日志表（新增）
CREATE TABLE crawl_jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,       -- 'full' | 'targeted' | 'deadline_monitor'
    triggered_by TEXT NOT NULL,   -- 'scheduler' | 'admin' | 'api'
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,         -- 'RUNNING' | 'SUCCESS' | 'FAILED'
    programs_crawled INTEGER DEFAULT 0,
    fields_extracted INTEGER DEFAULT 0,
    conflicts_detected INTEGER DEFAULT 0,
    error_log TEXT
);

-- program_field_evidence 新增列
ALTER TABLE program_field_evidence ADD COLUMN snapshot_id TEXT;
ALTER TABLE program_field_evidence ADD COLUMN extractor_tool TEXT;
ALTER TABLE program_field_evidence ADD COLUMN raw_extract_json TEXT;
```

---

## 四、实施阶段与时间线

### Phase 0（1天）：环境准备
- [ ] 安装 crawl4ai, scrapy, docling, apscheduler
- [ ] 打开 `HARBORPILOT_USE_PLAYWRIGHT=1`
- [ ] 验证 Playwright chromium 可抓 HKU 目录页
- [ ] 升级 requirements-crawler.txt

### Phase 1（3天）：Stage 1 抓取快照升级
- [ ] 实现 `src/harbor_agent/crawler/engine.py`（Crawl4AI 封装）
- [ ] 实现 `spider_hk.py`（HKU/CUHK/HKUST/CityU/PolyU）
- [ ] 实现 `spider_sg.py`（NUS/NTU/SMU）
- [ ] 升级 `source_snapshot.py` 调用新 engine
- [ ] 实现截图保存逻辑
- [ ] 升级 SQLite：新增 `crawl_snapshots` 表
- [ ] 测试：成功抓取并存储 HKU、NUS 各 3 个项目页

### Phase 2（3天）：Stage 2 字段抽取升级
- [ ] 定义 `ProgramFieldsSchema`（Pydantic）
- [ ] 实现 `Crawl4AI LLMExtractionStrategy` 调用
- [ ] 实现 `PdfFieldExtractor`（Docling）
- [ ] 三层降级逻辑（LLM → Docling → regex）
- [ ] 升级 `extract_field_candidates()` 使用新策略
- [ ] 测试：对 5 个项目页的 7 个字段抽取准确率 > 80%

### Phase 3（2天）：Stage 3 冲突检测
- [ ] 实现 `src/harbor_agent/services/diff_engine.py`
- [ ] `field_review_queue` 表创建
- [ ] 集成到 `_run_live_snapshot_pipeline()`
- [ ] 关键字段变更邮件/日志告警
- [ ] 测试：人为修改旧 hash，验证 CONFLICT 被正确检测

### Phase 4（3天）：Stage 4 人工审核 UI
- [ ] 后端：新增 `/api/admin/review-queue` 等端点
- [ ] 前端：`ReviewQueue` 页面（双快照对比视图）
- [ ] 发布逻辑：`publish_field()` 三级保护
- [ ] 审计日志记录
- [ ] 测试：完整走通一条 pending → approve → 学生可见流程

### Phase 5（1天）：调度器
- [ ] 实现 `CrawlScheduler`（APScheduler）
- [ ] 优先级队列
- [ ] 爬取任务 API
- [ ] 集成到 `app.py` 启动

### Phase 6（2天）：批量回填 + 数据质量验证
- [ ] 对现有 `programs_2027_fall.json` 中所有 `EXTRACTED` 状态项目触发爬取
- [ ] 验证真实 deadline 数据准确率
- [ ] 修正 `official_program_url` — 从目录页换成项目详情页

---

## 五、关键实施风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 高校封 IP | 中 | 高 | 设置每域名 3s 间隔 + User-Agent 标明研究目的 + 遵守 robots.txt |
| JS 渲染超时 | 中 | 中 | 设置 20s 超时，失败自动降级 urllib + 记录告警 |
| LLM API 费用 | 中 | 低 | 只对 CRITICAL 字段用 LLM，其余 regex 兜底 |
| Docling 安装失败 | 低 | 中 | 降级到 pypdf，标记 PDF 字段 confidence=low |
| 学校改版页面结构 | 高 | 中 | 截图存档，page_hash 变更时自动触发人工复核 |
| 审核员延迟 | 高 | 低 | 超过 7 天未审核 → 自动发送提醒 |

---

## 六、验证计划

### 自动化测试
```bash
# 单元测试
pytest tests/test_crawler/ -v
pytest tests/test_field_extractor/ -v
pytest tests/test_diff_engine/ -v

# 集成测试（实际网络请求，需 VPN）
pytest tests/integration/test_hku_crawl.py -v --live
```

### 人工验收标准

| 验收项 | 标准 |
|--------|------|
| HKU 目录页爬取 | 成功发现 ≥ 30 个项目 URL |
| 字段抽取准确率 | deadline 准确率 ≥ 85%，置信度 high |
| 冲突检测响应 | deadline 变更 2h 内出现在审核队列 |
| 审核发布链路 | 点击 approve 后，学生端 API 返回新值 |
| 截图可查看 | 每个快照附有截图，可在 Review UI 中打开 |
| 数据溯源 | 每个字段有 source_url + snapshot_path + captured_at |

---

## 七、开放问题（需你确认）

> [!IMPORTANT]
> **Q1：LLM 字段抽取 API Key**
> Crawl4AI LLMExtractionStrategy 需要 OpenAI / Gemini API Key。你是否已有 API Key 可以配置？还是希望用本地 LLM（如 Ollama）？

> [!IMPORTANT]
> **Q2：审核 UI 实现位置**
> Review Queue UI 是加到现有 `web/` 前端中（React？），还是单独做一个简单的管理后台页面？

> [!WARNING]
> **Q3：爬取合规声明**
> 部分高校（如 NUS）的 robots.txt 可能限制自动抓取。你是否接受：遵守 robots.txt，对于禁止自动抓取的页面，改为手动抓取 + 人工粘贴？

> [!NOTE]
> **Q4：Docling 依赖**
> Docling 需要约 2GB 存储（含 OCR 模型）。是否在开发机上安装，还是只在生产服务器上用？

---

## 八、文件变更总览

### 新增文件
| 文件 | 用途 |
|------|------|
| `src/harbor_agent/crawler/__init__.py` | 模块入口 |
| `src/harbor_agent/crawler/engine.py` | Crawl4AI 统一爬取引擎 |
| `src/harbor_agent/crawler/field_schema.py` | 字段抽取 Pydantic schema |
| `src/harbor_agent/crawler/pdf_processor.py` | Docling PDF 处理 |
| `src/harbor_agent/crawler/spider_hk.py` | 港校 Spider |
| `src/harbor_agent/crawler/spider_sg.py` | 新加坡高校 Spider |
| `src/harbor_agent/crawler/rate_limiter.py` | 速率控制 |
| `src/harbor_agent/crawler/robots_policy.py` | robots.txt 策略（升级） |
| `src/harbor_agent/services/diff_engine.py` | 字段冲突检测 |
| `src/harbor_agent/scheduler/crawl_scheduler.py` | APScheduler 定时任务 |
| `src/harbor_agent/api/review_routes.py` | 审核队列 API |
| `scripts/install_crawlers.ps1` | Windows 安装脚本 |
| `web/src/pages/admin/ReviewQueue.tsx` | 审核 UI |

### 修改文件
| 文件 | 改动 |
|------|------|
| `src/harbor_agent/services/source_snapshot.py` | 集成新 engine，升级 PDF 处理 |
| `src/harbor_agent/agents/data_acquisition.py` | 调用 diff_engine，写入 review_queue |
| `src/harbor_agent/services/program_store.py` | 新增 snapshot/review_queue/job 表 |
| `src/harbor_agent/app.py` | 注册新 API 路由，启动 scheduler |
| `requirements-crawler.txt` | 新增 crawl4ai/scrapy/docling/apscheduler |
| `.env.example` | 新增爬虫配置项 |
| `data/programs_2027_fall.json` | 逐步用真实抓取数据替换 EXTRACTED 状态字段 |
