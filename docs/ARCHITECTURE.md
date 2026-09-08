# ARCHITECTURE — 长江文化智能知识基础设施（YCKI）

> 版本 v0.2（2026-09-06，T00 六项目审计 + T01 基线实测后修订）· 审计依据：`docs/OPEN_SOURCE_AUDIT.md`
> 原则：**LightRAG 是宿主，YCKI 是产品**。最小修改核心 + 最大程度扩展。

## 1. 分层总览

```text
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3  Intelligence                                          │
│  Hybrid GraphRAG · Query Router · Deep Research · Gap Detection │
│  Knowledge Exploration · Timeline · GIS · Evidence Tracing      │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2  Knowledge                                             │
│  Canonical KG（Claim/Evidence/Provenance/KnowledgeState）        │
│  Entity Resolution · TimeSpan · PlaceVersion · Topic 轴         │
│  （下层继续保留 LightRAG Entity/Relation 作为 Retrieval Graph）  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1  Data                                                  │
│  Source Registry → Discovery → Acquisition → Raw Resource Lake  │
│  → Normalization → LightRAG Ingestion（chunk/抽取/索引）         │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 双图模式（核心决策）

| | Retrieval Graph（LightRAG 原生） | Canonical Knowledge Graph（YCKI 新增） |
| --- | --- | --- |
| 生成方式 | LightRAG OpenIE 自动抽取 | schema 约束 + ER + 证据绑定 + 准入后生成 |
| 特点 | 快、大、宽松 | 精、可解释、带证据链 |
| 职责 | 服务召回（local/global/hybrid/mix 检索） | 服务正式知识、引用、时空问答、研究 |
| 存储 | LightRAG 支持的图后端（默认 NetworkX→Neo4j） | Neo4j + PostgreSQL（claim/evidence 元数据） |

## 3. 知识改造流水线（替换 Document→LLM→Triple→KG）

```text
Resource(原始件, checksum, rights)
→ Document → Chunk（LightRAG 原生）
→ Candidate Entity/Event（领域 schema 约束抽取，prompt 版本化）
→ Candidate Claim（subject/predicate/object/scope/time）
→ Evidence（chunk/page/quote_span, relation: SUPPORTS|CONTRADICTS|MENTIONS|QUALIFIES）
→ Source / Provenance（全链可回溯）
→ Normalization → Entity Resolution（别名/古今地名/译名，非字符串去重）
→ Verification → Admission（状态机，禁止直接覆盖）
→ Knowledge State → Canonical Graph → Hybrid Index → GraphRAG / Research
```

## 4. 存储规划（Complexity on Demand）

**V1 四件套**：LightRAG（含内置存储）+ PostgreSQL/PostGIS（元数据/registry/claims/jobs）+ MinIO（原始对象）+ Neo4j（双图）。向量与全文沿用 LightRAG 内置后端起步；规模扩大再评估 Qdrant/Milvus/OpenSearch。

**Provider Layer（全部经抽象，不硬编码厂商）**：LLMProvider / EmbeddingProvider / RerankProvider / SearchProvider / CrawlerProvider / OCRProvider / VLMProvider。首批实现：LLM=OpenAI 兼容（Qwen3.5-122B-A10B）、Embedding=OpenAI 兼容（bge-m3）、Search=Tavily/SearXNG 之一、Crawler=httpx+Playwright fallback。

## 5. 模块挂载策略（T00 审计后确认为低侵入路线）

```text
ycki/
├── upstream/LightRAG/     # 宿主，pin commit 440d25b0，只读基线（fork 维护见 UPSTREAM_PATCHES.md）
├── yangtze/               # 领域层：ontology YAML、schema 提案、prompt 模板（版本化）
├── extensions/            # 扩展层：claim/evidence/admission/ER/时空/gap/research 工作流
├── adapters/              # Provider 实现：search/crawler/ocr/llm 适配
├── plugins/               # 可选插件挂载
├── config/                # .env 与部署配置（密钥不入 Git）
├── deploy/                # 基线部署（lightrag compose + .env + 测试文档 + API 脚本）
├── docs/                  # 全部治理文档
└── reports/               # 基线与各里程碑验收报告
```

**审计确认的挂载点（按侵入度从低到高，全部优先走前三种）**：

| 层级 | 机制 | 侵入度 |
| --- | --- | --- |
| 配置面 | `ENTITY_TYPE_PROMPT_FILE` YAML（实体类型指南+抽取示例整体替换）、`SUMMARY_LANGUAGE`、`LIGHTRAG_PARSER` 路由、全部 env | 零改动 |
| 回调面 | `LightRAG.chunking_func`、chunker 选择器 C/P、SDK `insert_custom_kg` 模式 | 零改动（SDK 层） |
| 外挂面 | YCKI 自有 FastAPI 服务（`/yangtze/*` 路由）持有 Claim/Evidence/Registry 表，经 LightRAG client/SDK 对接；或 `create_app` 处 include_router（1 行） | 1 行或零 |
| 注册面 | 存储后端切换（Neo4j/PG 等，继承 base.py 基类 + STORAGES 注册） | 各 1 处 |
| 禁区 | operate.py / prompt.py / lightrag.py / pipeline.py / document_routes.py（6-7K 行级，改动需过 UPSTREAM_PATCHES 检查清单） | 高风险 |

**已确认的宿主对接事实**（T01 实测）：`/query/data` 返回 entities/relationships/chunks/references 且各带 `source_id`(chunk)/`reference_id`/`file_path` —— YCKI 的 Evidence↔Chunk 关联直接消费此结构；文档状态机 PENDING→PARSING→ANALYZING→PROCESSING→PROCESSED/FAILED 用于 Resource 联动。

## 6. 服务拓扑（V1）

```text
[Browser]
   │
[LightRAG WebUI + YCKI 扩展页] :9621
   │ REST（原生路由 + /yangtze/* 扩展路由）
[LightRAG Server] ──── LLM/Embedding Provider ──→ 用户网关 :3001/v1
   │                         ↘ SearchProvider → Tavily/SearXNG（M7）
[PostgreSQL+PostGIS]  [Neo4j]  [MinIO]
   元数据/registry/      双图      原始资源
   claims/jobs
```

## 7. 关键设计约束（摘自方案，执行时不可违背）

1. Baseline First：T01 原版跑通前禁止开发新功能。
2. 禁止裸 Chunk 注入回答：必须组织 Evidence Package。
3. 禁止覆盖旧知识：新证据走 confirm/qualify/revise/supersede/contest。
4. 禁止单一来源评分制：authority_level 仅是证据信息之一。
5. 模型输出 ≠ 数据库真相：Raw / Candidate / Admitted 三态分离。
6. 研究过程持久化为数据库对象，单工作流状态机，禁止多智能体形式化。
7. Prompt 与抽取结果必须记录版本（model/prompt_version/pipeline_version）。
8. 版权：can_store/can_display/can_redistribute/can_use_for_ai 四权分离。
