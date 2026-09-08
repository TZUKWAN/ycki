# ONTOLOGY — 长江文化本体与 Schema

> ⚠️ **2026-09-08 canonical_v1 重构进行中**：本文档部分内容描述的是重构前架构。
> 以 [docs/REFACTOR_PHASE0_AUDIT.md](REFACTOR_PHASE0_AUDIT.md) 与 [docs/DECISIONS.md](DECISIONS.md) ADR-018~019 之后的最新决策为准。
> 核心变化：Retrieval Graph 与 Canonical KG 双层拆分；资源准入/实体消歧/Claim-Evidence 流水线上线。

> v0.1 骨架（2026-09-06）· T04 定稿
> 治理：稳定核心 Core → 领域扩展 Domain Extension → 候选 Candidate；Agent 只能提议新类型，不得直接改核心。

## 1. 核心实体类型（16）

Person, Place, Organization, Institution, Event, Work, Artifact, Heritage, Site, Practice, Concept, WaterSystem, Route, Document, Source, Topic

## 2. 知识层对象（与普通 KG 的关键差异）

Claim, Evidence, TimeSpan, PlaceVersion, KnowledgeState, ProvenanceEvent

## 3. 文化主题轴（多标签，独立于实体类型，禁止当 EntityType）

考古与早期文明 / 历史文化 / 水文化 / 文学文化 / 红色文化 / 工业文化 / 交通航运 / 商业文化 / 城市文化 / 建筑文化 / 艺术文化 / 非遗 / 民俗 / 宗教 / 民族 / 生态文化 / 饮食文化 / 教育文化 / 科技文化 / 移民与人口流动 / 中外文化交流

## 4. 核心关系（初稿，T04 定稿）

- 参与/创建类：创建、参与、发生于、隶属于、写作、修建、兼任
- 时空类：located_within, part_of, happened_at, valid_during
- 沿革类：same_as / historical_name_of / successor_of / predecessor_of / overlaps_with（时间条件必填）
- 证据类：SUPPORTS / CONTRADICTS / MENTIONS / QUALIFIES
- 主题类：has_topic

## 5. 新类型提案治理

提案必须记录：reason / examples / existing overlap / expected frequency / schema impact / decision。存放于 `yangtze/schema/proposals/`。

## 6. LightRAG 集成方式（待 T02 确认挂载点）

- entity_types 列表经配置注入 LightRAG 抽取 prompt（保持 upstream 可合并）。
- 抽取结果映射：LightRAG entity_type → YCKI Core Type 的映射表；未映射类型进 Candidate 层。
