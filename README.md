# YCKI — 长江文化智能知识基础设施

Yangtze Cultural Knowledge Infrastructure — 以 [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) 为宿主的长江文化领域知识库，具备持续自增长采集、证据溯源与中文领域本体。

## 当前能力（实测）

- **持续自增长**：`auto_growth.py` 常驻循环 —— 轮换采集 10+ 主题表 → 正文抽取 → 知识图谱 → 自愈重试 → PostgreSQL 对账
- **真实数据规模**：1,400+ 资源 / 340+ 信息源 / 560 万字 / **9.9 万实体 / 12.3 万关系**，全链溯源闭合率 99.9%+
- **证据可溯**：任何实体/关系可回溯 chunk → 文档 → 资源 → 来源 URL（权威级 S/A/B/C 分级）
- **可视化控制台**（:9622）：增长曲线、最新入库、队列状态、引擎启停
- **自定义词条**：控制台粘贴搜索词，立即采集或由引擎自动消化

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
