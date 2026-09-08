# YCKI MASTER TASK LIST

> 长江文化智能知识基础设施 — 完整任务树
> 宿主平台：HKUDS/LightRAG · 立项日期：2026-09-06
> 状态图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成 · `[-]` 阻塞/跳过

## 里程碑总览（Milestone 关键路径，禁止倒序）

```text
M0 开源审计 → M1 基线跑通 → M2 Schema+Resource层 → M3 Claim-Evidence-Provenance
→ M4 ER+时空 → M5 Canonical KG → M6 Hybrid Retrieval → M7 自主采集
→ M8 Deep Research → M9 Gap→Research→Update 闭环 → M10 完整 WebUI
```

---

## T00 项目与开源项目审计 `[x]`（M0）✅ 2026-09-06

- [x] T00.1 建立项目目录骨架（ycki/：upstream、docs、yangtze、extensions、adapters、plugins、config、reports）
- [x] T00.2 Clone LightRAG（完整历史，main@440d25b0）
- [x] T00.3 Clone KAG（OpenSPG/KAG）
- [x] T00.4 Clone Graphiti（getzep/Graphiti）
- [x] T00.5 Clone GPT-Researcher（assafelovic/gpt-researcher）
- [x] T00.6 Clone ScrapeGraphAI（ScrapeGraphAI/Scrapegraph-ai）
- [x] T00.7 Clone Neo4j LLM Graph Builder（neo4j-labs/llm-graph-builder）
- [x] T00.8 LightRAG 代码级审计（server/WebUI/ingestion/extraction/storage/query/citation/config/docker/扩展点）
- [x] T00.9 KAG 审计（schema 约束抽取、KnowledgeUnit、逻辑形式、检索算子）
- [x] T00.10 Graphiti 审计（bi-temporal、edge invalidation、增量 ER、混合检索）
- [x] T00.11 GPT-Researcher 审计（研究流水线、retriever 抽象、source tracking）
- [x] T00.12 ScrapeGraphAI 审计（SmartScraper、schema 抽取、fetch 后端、依赖重量）
- [x] T00.13 Neo4j LLM Graph Builder 审计（摄取 UI、schema 处理、可视化）
- [x] T00.14 六项目能力矩阵与技术选择报告 → `docs/OPEN_SOURCE_AUDIT.md`
- [x] T00.15 确认复用/借鉴/自建清单 → `docs/DECISIONS.md`
- [x] T00.16 更新 `docs/ARCHITECTURE.md` 至审计后版本

## T01 LightRAG 基线部署 `[x]`（M1）✅ 2026-09-06 · 17通过/1降级(Reranker) · 见 reports/BASELINE_REPORT.md

- [ ] T01.1 启动 Docker Desktop 或确定 pip/uv 本地部署路线
- [x] T01.2 配置 `.env`（LLM=Qwen3.5-122B-A10B @用户API，Embedding=bge-m3 @用户API；密钥不入 Git）
- [x] T01.3 启动 LightRAG Server + WebUI
- [x] T01.4 验证 LLM binding 连通（/chat 探活）
- [x] T01.5 验证 Embedding binding 连通
- [x] T01.6 验证 Reranker（网关无 rerank 服务 → RERANK_BINDING=null 降级禁用，方案记录于 BASELINE_REPORT §2/§3）
- [x] T01.7 上传 PDF 并完成解析
- [x] T01.8 上传 DOCX 并完成解析
- [x] T01.9 Entity Extraction + Relation Extraction 成功
- [x] T01.10 Knowledge Graph 生成并可查询（WebUI + API）
- [x] T01.11 RAG 问答（local/global/hybrid/mix 各模式）
- [x] T01.12 验证 Citation/reference 返回
- [x] T01.13 删除文档 + 知识更新（增量导入）
- [x] T01.14 输出 `reports/BASELINE_REPORT.md`（真实运行结果）

## T02 LightRAG 源码架构分析深化 `[ ]`

- [ ] T02.1 输出调用链图谱：ingest 与 query 两条主线（含函数级 trace）
- [ ] T02.2 存储抽象接口逐个确认（KV/Vector/Graph/DocStatus）及我们的选型
- [ ] T02.3 确定最小侵入扩展点清单（路由挂载、pipeline 钩子、prompt 注入）
- [ ] T02.4 记录到 `docs/ARCHITECTURE.md` 与 `docs/UPSTREAM_PATCHES.md`

## T03 长江文化数据架构 `[x]`（M2）✅ 2026-09-06 · PostgreSQL+PostGIS 已建库（deploy/sql/001_init.sql）；MinIO 后移（ADR-015）；compose 现有容器直用

- [x] T03.1 Resource / Source 数据模型定稿 → `docs/DATA_MODEL.md` + `deploy/sql/001_init.sql`
- [x] T03.2 PostgreSQL(+PostGIS) schema 设计与迁移脚本（已应用，ycki-postgres :5433）
- [x] T03.3 湖存储以本地目录承载（raw/text 对象+双校验和去重）；MinIO 后移（ADR-015）
- [~] T03.4 服务组合：LightRAG+PostGIS+SearXNG 已同机运行；Neo4j/MinIO 按里程碑后移

## T04 长江文化 Ontology 与 Schema `[x]`（M2）✅ 2026-09-06 · 实测生效（李冰=person/都江堰=watersystem；14类全在用）

- [x] T04.1 14 领域抽取类型定稿（deploy/lightrag/data/prompts/entity_type_prompt.yml，yangtze_entity_types_v1）
- [x] T04.2 十主题轴用于批1采集（yangtze/topics_batch1.json）；20 主题全量表待 batch2
- [~] T04.3 关系为自由 keywords+受控谓词规划中（M3 Claim 谓词表）
- [x] T04.4 治理流程入 `docs/ONTOLOGY.md`；提案目录 `yangtze/schema/proposals/`
- [x] T04.5 已注入并验证（ENTITY_TYPE_PROMPT_FILE，零代码，ADR-008/017）

## T05 原始资源湖 Raw Resource Lake `[ ]`

- [ ] T05.1 resource 对象表 + checksum 去重 + 原始文件落 MinIO
- [ ] T05.2 解析器版本记录（parser_version、ingestion_job）
- [ ] T05.3 权限字段（copyright/license/can_store/can_display/can_use_for_ai）

## T06 Source Registry `[ ]`

- [ ] T06.1 source 注册表表结构（source_type 13 类、authority_level S/A/B/C/UNKNOWN）
- [ ] T06.2 初始长江文化信息源名录（政府/档案/图书馆/博物馆/高校/期刊/方志…≥50 条）
- [ ] T06.3 crawl_policy 与 rights_policy 字段及 API

## T07 自主资源发现 Discovery Engine `[ ]`（M7）

- [ ] T07.1 调查任务 → research scope / 检索概念 / 同义词 / 历史地名 / 时间范围 展开器
- [ ] T07.2 SearchProvider 抽象（search(query, filters, top_k)）
- [ ] T07.3 首个 Provider 实现（Tavily 或 SearXNG，视可用性）
- [ ] T07.4 学术 Adapter：Crossref / OpenAlex / Semantic Scholar / arXiv（CNKI 仅合法元数据）

## T08 网页抓取 Acquisition Engine `[ ]`（M7）

- [ ] T08.1 robots/policy check + 轻量 fetch 优先
- [ ] T08.2 Playwright browser fallback（仅 JS/动态页）
- [ ] T08.3 正文/元数据抽取、canonicalization、checksum、去重入湖

## T09 文档解析 `[ ]`

- [ ] T09.1 复用 LightRAG 解析管道（textract/docling 路线确认）
- [ ] T09.2 古籍/竖排/繁简特殊处理评估
- [ ] T09.3 解析质量日志（成功率、失败原因分类）

## T10 资源标准化 `[ ]`

- [ ] T10.1 Resource → LightRAG Document 的映射与状态同步
- [ ] T10.2 元数据补全（publication_time、publisher、region 推断）

## T11 实体事件抽取 `[ ]`（M2）

- [ ] T11.1 领域 prompt 模板（版本化 entity_extraction_v1）
- [ ] T11.2 事件抽取（含 event_time、place 属性）
- [ ] T11.3 抽取日志（model/prompt_version/tokens/latency）

## T12 Entity Resolution `[ ]`（M4）

- [ ] T12.1 别名/异名/繁简/字号/译名规则库 + 归一化函数
- [ ] T12.2 人物消歧（毛泽东=毛润之=润之=Mao Zedong → canonical + alias）
- [ ] T12.3 历史地名关系（same_as / historical_name_of / successor_of / part_of / overlaps_with…带时间条件）
- [ ] T12.4 LLM 辅助消歧与人工审核队列

## T13 时空知识建模 `[ ]`（M4）

- [ ] T13.1 TimeSpan 模型（模糊时间/朝代/区间）
- [ ] T13.2 PlaceVersion 模型（古今行政区沿革）
- [ ] T13.3 流域体系（上中下游/支流/湖泊）PostGIS 落库
- [ ] T13.4 朝代/历史时期对照表数据

## T14 Claim-Evidence-Provenance `[ ]`（M3，本项目最关键定制）

- [ ] T14.1 Claim 对象（subject/predicate/object/scope/time/status/confidence）
- [ ] T14.2 Evidence 对象（source/document/chunk/page/quote_span/evidence_type/relation: SUPPORTS|CONTRADICTS|MENTIONS|QUALIFIES）
- [ ] T14.3 ProvenanceEvent 与全链回溯 Knowledge→Claim→Evidence→Chunk→Document→Resource→Source
- [ ] T14.4 从 LightRAG entity/relation + chunk 派生 Candidate Claim 的 pipeline

## T15 知识准入 Knowledge Admission `[ ]`（M3）

- [ ] T15.1 状态机（CANDIDATE/SUPPORTED/CORROBORATED/ADMITTED/CONDITIONAL/CONTESTED/REJECTED/STALE/SUPERSEDED/REVOKED）
- [ ] T15.2 规则+LLM+evidence count 初版准入策略（admission_v1）
- [ ] T15.3 人工审核接口

## T16 Knowledge State `[ ]`

- [ ] T16.1 知识状态聚合视图（实体级/关系级/主题级）
- [ ] T16.2 知识更新流程：confirm/qualify/revise/supersede/contest（禁止覆盖）

## T17 图谱增量更新 `[ ]`

- [ ] T17.1 Retrieval Graph 增量与 Canonical Graph 同步策略
- [ ] T17.2 冲突检测（新旧 claim 对比）与 Graphiti 式 invalidation 借鉴

## T18 Hybrid Index `[ ]`（M6）

- [ ] T18.1 通道确认：Full-text / Vector / Retrieval Graph / Canonical Graph / Temporal / Spatial / Evidence / Source
- [ ] T18.2 各通道索引构建与一致性

## T19 Query Router `[ ]`（M6）

- [ ] T19.1 Query Understanding 分类（FACT/ENTITY/RELATION/TEMPORAL/SPATIAL/TOPIC/COMPARATIVE/EVIDENCE/GLOBAL_SYNTHESIS/RESEARCH）
- [ ] T19.2 路由策略与通道组合（含三类示例问题调通过）

## T20 GraphRAG `[ ]`（M6）

- [ ] T20.1 Evidence Package 组织（Claims/Evidence/Sources/GraphPaths/时空上下文/Conflicts）
- [ ] T20.2 答案生成禁止裸 Chunk 注入；引用必须落到 Evidence

## T21 Deep Research `[ ]`（M8）

- [ ] T21.1 ResearchTask/ResearchPlan/SearchQuery/SearchResult/VisitedSource/ResearchFinding/KnowledgeGap/TaskStatus 持久化对象
- [ ] T21.2 工作流状态机（PLAN→SEARCH→SELECT→FETCH→READ→EXTRACT→VERIFY→STORE→ASSESS_GAP→RESEARCH_MORE→FINISH）
- [ ] T21.3 单工作流实现（明确禁止多智能体形式化拆分）

## T22 Knowledge Gap Detection `[ ]`（M9）

- [ ] T22.1 缺口类型定义（9 类：missing entity info/missing evidence/single-source/missing period/missing region/conflicting/low-confidence/unresolved/uncovered subquestion）
- [ ] T22.2 缺口 → 调查任务生成

## T23 自增长闭环 `[ ]`（M9）

- [ ] T23.1 Gap → Research → 入湖 → 建知识 → 图谱更新 → 重答 全链贯通
- [ ] T23.2 闭环端到端演示脚本与报告

## T24 GIS 与 Timeline `[ ]`

- [ ] T24.1 地图服务（点/线/区域/流域 + 时间/主题/朝代过滤）
- [ ] T24.2 Timeline 服务（朝代/年代/模糊时间/区间）与 Graph 联动

## T25 Knowledge Explorer `[ ]`

- [ ] T25.1 实体详情页（Person 页：基本信息/别名/时间线/空间轨迹/关系/事件/作品/主题/来源/Claim/Evidence/争议/文献）

## T26 WebUI 改造 `[ ]`（M10，直接改 LightRAG WebUI）

- [ ] T26.1 导航改造（总览/资源库/知识图谱/地图/时间轴/主题/问答/深度研究/知识审核/数据源/采集任务/系统管理）
- [ ] T26.2 首页 Dashboard（13 项指标）
- [ ] T26.3 Research 实时过程页
- [ ] T26.4 主题页自动生成

## T27 管理后台 `[ ]`

- [ ] T27.1 Source Registry 管理 / 采集任务管理 / 审核队列 / 日志查询

## T28 质量评价 `[ ]`

- [ ] T28.1 五层评价体系（Data/Extraction/Knowledge/Retrieval/Generation）指标与脚本

## T29 数据规模测试 `[ ]`

- [ ] T29.1 V1 切片（长江流域红色文化/党史文献）1k–10k Resource 灌入与压测

## T30 V1 验收 `[ ]`

- [ ] T30.1 Task1 导入 1000+ 文档
- [ ] T30.2 Task2 自动实体关系图
- [ ] T30.3 Task3 Claim→Evidence 回溯
- [ ] T30.4 Task4 人物别名融合
- [ ] T30.5 Task5 历史地点时间状态区分
- [ ] T30.6 Task6 时间查询
- [ ] T30.7 Task7 空间查询
- [ ] T30.8 Task8 GraphRAG
- [ ] T30.9 Task9 可靠来源返回
- [ ] T30.10 Task10 复杂研究问题闭环（最关键验收项）
- [ ] T30.11 `reports/V1_ACCEPTANCE_REPORT.md`

## T31 V2 扩展 `[ ]`

- [ ] T31.1 主题扩展：文学/工业/非遗/考古/航运（红色文化之后）
- [ ] T31.2 V3 流域级规模与持续自主增长（周期 Discovery/Crawl/Change Detection/Re-verification）
- [ ] T31.3 多模态预留字段启用（Image/Audio/Video/Map/3D/Manuscript）

---

## 交付物索引

| 文件 | 位置 | 状态 |
| --- | --- | --- |
| MASTER_TASK_LIST.md | ycki/ | 本文件 |
| PROJECT_STATE.md | ycki/ | 已建 |
| ARCHITECTURE.md | ycki/docs/ | 已建（待审计后更新） |
| DATA_MODEL.md | ycki/docs/ | 已建（骨架） |
| ONTOLOGY.md | ycki/docs/ | 已建（骨架） |
| OPEN_SOURCE_AUDIT.md | ycki/docs/ | 审计代理运行中 |
| DECISIONS.md | ycki/docs/ | 已建 |
| CHANGELOG_YCKI.md | ycki/docs/ | 已建 |
| UPSTREAM_PATCHES.md | ycki/docs/ | 已建 |
| BASELINE_REPORT.md | ycki/reports/ | T01 完成后 |
| M*_ACCEPTANCE_REPORT.md | ycki/reports/ | 各里程碑后 |
