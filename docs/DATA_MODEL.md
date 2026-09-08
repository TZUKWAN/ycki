# DATA MODEL — YCKI 数据模型

> ⚠️ **2026-09-08 canonical_v1 重构进行中**：本文档部分内容描述的是重构前架构。
> 以 [docs/REFACTOR_PHASE0_AUDIT.md](REFACTOR_PHASE0_AUDIT.md) 与 [docs/DECISIONS.md](DECISIONS.md) ADR-018~019 之后的最新决策为准。
> 核心变化：Retrieval Graph 与 Canonical KG 双层拆分；资源准入/实体消歧/Claim-Evidence 流水线上线。

> v0.1 骨架（2026-09-06）· T03 落库前定稿
> 三态分离：Raw Information → Candidate Knowledge → Admitted Knowledge

## 1. Resource（原始资源，入湖即存，LLM 输出不得替代原文）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| resource_id | UUID PK | |
| title | text | |
| source_url | text | 规范化后 URL |
| source_domain | text | |
| source_id | FK→Source | 来源注册 |
| source_type | enum | Government/Archive/Library/Museum/University/AcademicJournal/LocalChronicle/ResearchInstitute/Newspaper/CulturalInstitution/GeneralWebsite/UserUpload/AIGenerated |
| publisher / author | text | |
| publication_time | timespan | 模糊时间支持 |
| retrieved_time | timestamptz | |
| mime_type / language | text | |
| rights / license | text | |
| copyright / rights_holder | text | |
| can_store / can_display / can_redistribute / can_use_for_ai | bool | 四权分离 |
| checksum | sha256 | 去重键 |
| raw_file_path | text | MinIO 对象键 |
| parser_version | text | |
| ingestion_job | FK→Job | |
| doc_status | FK→LightRAG doc id | 与宿主文档状态联动 |

## 2. Source（信息源注册表）

source_id, name, domain, organization, source_type, region, topic[], crawl_policy(jsonb), priority, authority_level(S/A/B/C/UNKNOWN), rights_policy(jsonb), last_checked

> authority_level 仅作证据权重信息之一，S 级来源不自动判真。

## 3. Claim（知识主张，核心定制对象）

| 字段 | 说明 |
| --- | --- |
| claim_id | UUID |
| subject / predicate / object | 实体引用 + 受控谓词 |
| scope | 适用范围（时间/地域/人群/定义条件） |
| time | TimeSpan 引用 |
| status | CANDIDATE/SUPPORTED/CORROBORATED/ADMITTED/CONDITIONAL/CONTESTED/REJECTED/STALE/SUPERSEDED/REVOKED |
| confidence | 数值 |
| generation | model / model_version / prompt_version / pipeline_version / generated_at |

## 4. Evidence（证据）

claim_id, source_id, document_id, chunk_id, page, paragraph, quote_span, evidence_type, relation ∈ {SUPPORTS, CONTRADICTS, MENTIONS, QUALIFIES}, created_at

## 5. ProvenanceEvent（追溯链）

Knowledge → Claim → Evidence → Chunk → Document → Resource → Source 全链可倒查；每个环节记录 ProvenanceEvent（actor, action, at, inputs, outputs）。

## 6. 时空对象

- **TimeSpan**：valid_from, valid_to, approximate, granularity(era/dynasty/year/month/day), dynasty, historical_period
- **PlaceVersion**：place_id, name, name_type(historical/modern), valid TimeSpan, geometry(PostGIS), relations: same_as / historical_name_of / successor_of / predecessor_of / part_of / overlaps_with / located_within（均带时间条件）
- **流域体系**：river_section(上/中/下游), tributary, lake, basin_region

## 7. Research 域对象（研究即数据）

ResearchTask(status), ResearchPlan, SearchQuery, SearchResult, VisitedSource, ResearchFinding, KnowledgeGap(type ∈ 9 类), Job(job_id, model, tokens, latency, cost, error, retry)

## 8. 与 LightRAG 原生对象的关系

- LightRAG Entity/Relation 原样保留（检索索引层）；YCKI 通过 chunk_id/evidence 关联，派生 Canonical 层，不删除不破坏原生结构。
- document 状态沿用 LightRAG DocStatus，YCKI resource 表保存外键映射。
