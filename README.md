# YCKI — 长江文化智能知识基础设施

Yangtze Cultural Knowledge Infrastructure — 以 [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) 为宿主的长江文化领域知识库，具备持续自增长采集、证据溯源与中文领域本体。

## 当前能力（实测）

- **持续自增长**：`auto_growth.py` 常驻循环 —— 轮换采集 10+ 主题表 → 正文抽取 → 知识图谱 → 自愈重试 → PostgreSQL 对账
- **双层图谱**：Retrieval Graph（LightRAG 索引层，9.9 万实体/12.3 万关联边，仅供检索）+ **Canonical KG**（正式知识：UUID 实体/受控谓词有向 Claim/证据溯源，2026-09-08 起建设）
- **资源准入**：Resource Scope Gate（CORE/CONTEXT/REJECT，实测正负例 7/8）；Chunk 级相关性分层
- **证据可溯**：任何实体/关系可回溯 chunk → 文档 → 资源 → 来源 URL（权威级 S/A/B/C 分级）
- **可视化控制台**（:9622）：增长曲线、最新入库、队列状态、引擎启停
- **自定义词条**：控制台粘贴搜索词，立即采集或由引擎自动消化
- **质量审计**：ADMITTED Claim 溯源闭环率 100%、证据原文定位率 100%、ER 测试 6/6（reports/KG_QUALITY_AUDIT.json）

## 架构

```
SearXNG(本机:8080, engines=bing,sogou) ─┐
zh.wikipedia.org MediaWiki API ─────────┤→ 采集管线(tools/collect.py)
                                        │   ├─ 轻量HTTP抓取 + trafilatura 正文抽取
                                        │   ├─ 质量守卫 + BLOCKED_DOMAINS
                                        │   └─ 原始件/正文入湖(双sha256去重)
PostgreSQL+PostGIS(:5433) ←─────────────┘   sources / resources / collection_jobs
LightRAG Server(:9621, Docker) ←── 1,444 篇全 processed
   ├─ 领域本体注入: ENTITY_TYPE_PROMPT_FILE (14 类长江文化实体类型, 零代码)
   ├─ 双源模型: LLM=Qwen3.6-35B-A3B / Embedding=bge-m3 (OpenAI 兼容网关)
   └─ 查询: local/global/hybrid/mix + /query/data 全链引用
控制台 dashboard/(:9622, FastAPI) → 增长总览 + 自定义词条 + 引擎控制
```

## 快速开始（Windows）

1. 双击 `启动长江文化知识库.bat`（自动拉起 Docker Desktop、容器、控制台与自增长引擎，并打开浏览器页面）
2. 控制台 http://localhost:9622 —— 看增长、加词条、暂停/恢复
3. 知识库 WebUI http://localhost:9621/webui/ —— 图谱可视化与检索问答
4. 停止：双击 `停止长江文化知识库.bat`（数据落盘不丢）

## 目录

```
auto_growth.py            # 自增长引擎（采集循环/自愈/对账/心跳/暂停）
adapters/                 # SearchProvider：searxng_provider / wikipedia_provider
tools/                    # fetcher / registry(PG) / collect / reconcile
│                          # verify_chain(全链核验) / verify_queries(抽检溯源)
│                          # fix_upload_failures / split_reinsert(顽固失败拆分重灌)
dashboard/                # 可视化控制台 (FastAPI, :9622)
yangtze/                  # topics_batch*.json 主题表（引擎自动轮换）
deploy/lightrag/          # LightRAG compose + .env(不入库) + 本体 YAML
deploy/sql/               # PostgreSQL 建库脚本
docs/                     # 架构/本体/数据模型/决策记录(ADR)/审计报告
reports/                  # 基线报告 / 采集验证报告
upstream/                 # LightRAG 等上游仓库克隆（不入库）
```

## 文档

- [MASTER_TASK_LIST.md](MASTER_TASK_LIST.md) — T00–T31 全任务树与里程碑
- [docs/OPEN_SOURCE_AUDIT.md](docs/OPEN_SOURCE_AUDIT.md) — 六开源项目能力矩阵与技术选择
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构与挂载策略
- [docs/DECISIONS.md](docs/DECISIONS.md) — ADR-001~019
- [reports/COLLECTION_REPORT_BATCH1.md](reports/COLLECTION_REPORT_BATCH1.md) — 采集与全链验证报告

## 状态

- M0 开源审计 ✅ · M1 基线 ✅ · M2 数据库批1–8 ✅（队列 100% 排空）
- 已知问题：自增长引擎的自愈(reprocess_failed)与 LightRAG 排他栅栏(manual_freeze)存在竞态，会造成上传期 409 弹回（已加入栅栏等待逻辑；顽固失败用拆分重灌兜底，见 ADR-019 与 split_reinsert.py）

## canonical_v2 — 长江文化系统知识图谱（2026-09-13）

在 canonical_v1 事实层之上叠加多层异质时空结构层：

- **受控本体**（Git seed 唯一来源）：`yangtze/schema/`（系统/区域/领域/分期/演化模式/水系骨架），`python tools/init_canonical_v2.py --dry-run|--apply|--verify` 幂等构建，clean-room 0 漂移。
- **结构合成**：`python tools/synthesize_structures.py --all` 从跨文档证据束合成 文化传统/文化过程/文化流动，字段级证据核验 + 单来源最多 SUPPORTED + 流动硬门禁。
- **成员关系两阶段准入**：`python tools/rebuild_memberships.py --apply`（确定性锚点预滤 + LLM 判官终审；纯地理/省级行政区永不 ADMIT）。
- **缺口驱动增长**：`python tools/cultural_system_growth.py --cycle`（缺口→研究任务→采集溯源→复测，熔断审计 `--audit`）。
- **API/UI**：`/yangtze/v2/*` 13 端点；`/v2` 分层钻取页（系统/流域/演进/传统/过程/流动/缺口）。
- **验收**：`python tools/validate_canonical_v2.py`（G01-G13 门禁）；最终报告 `python tools/generate_final_report.py` → `reports/V2_FINAL_VALIDATION.md`（数字全部脚本生成）。

状态与指标以 `reports/V2_FINAL_VALIDATION.md` 与 `reports/CANONICAL_V2_EXECUTION_STATE.json` 为准。
