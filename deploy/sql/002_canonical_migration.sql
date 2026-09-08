-- =====================================================================
-- YCKI 002_canonical_migration.sql
-- Canonical Yangtze Cultural Knowledge Graph 数据层（Phase 3）
-- 原则：只新增，不修改旧表语义；resources 仅"解耦"准入状态（新增列）
-- 身份规则：canonical_entities 以 UUID 为身份，name 不作主键（同名允许并存）
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------
-- A. resources 准入解耦 + 采集上下文持久化（Phase 2/八）
-- ---------------------------------------------------------------
ALTER TABLE resources
  ADD COLUMN IF NOT EXISTS admission_status TEXT NOT NULL DEFAULT 'DISCOVERED'
    CHECK (admission_status IN ('DISCOVERED','FETCHED','CANDIDATE','CORE','CONTEXT','REJECTED','INGESTED')),
  ADD COLUMN IF NOT EXISTS discovery_topic   TEXT,
  ADD COLUMN IF NOT EXISTS search_intent     TEXT,
  ADD COLUMN IF NOT EXISTS collection_reason TEXT,
  ADD COLUMN IF NOT EXISTS target_region     TEXT,
  ADD COLUMN IF NOT EXISTS target_period     TEXT,
  ADD COLUMN IF NOT EXISTS gap_id            TEXT,
  ADD COLUMN IF NOT EXISTS research_task_id  TEXT,
  ADD COLUMN IF NOT EXISTS simhash           BIGINT,
  ADD COLUMN IF NOT EXISTS source_cluster_id TEXT;

-- 存量回填：已入库processed视为已过旧链路（待重评）；其余按字面状态映射
UPDATE resources SET admission_status = 'FETCHED'    WHERE admission_status = 'DISCOVERED' AND ingest_status IN ('processed');
UPDATE resources SET admission_status = 'DISCOVERED' WHERE admission_status = 'DISCOVERED';
CREATE INDEX IF NOT EXISTS idx_res_admission ON resources(admission_status);

CREATE TABLE IF NOT EXISTS resource_admissions (
  admission_id        BIGSERIAL PRIMARY KEY,
  resource_id         TEXT NOT NULL REFERENCES resources(resource_id),
  scope_role          TEXT NOT NULL CHECK (scope_role IN ('CORE','CONTEXT','REJECT')),
  yangtze_relevance   REAL,
  topic_relevance     REAL,
  spatial_relevance   REAL,
  cultural_relevance  REAL,
  geo_scope           TEXT,
  geo_evidence        TEXT,
  topic_labels        TEXT[] NOT NULL DEFAULT '{}',
  relevance_reason    TEXT,
  model               TEXT NOT NULL,
  prompt_version      TEXT NOT NULL,
  pipeline_version    TEXT NOT NULL,
  evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_res_adm_resource ON resource_admissions(resource_id);

-- ---------------------------------------------------------------
-- B. Chunk 级相关性（Phase 4，支持"一篇文档 30% CORE 50% REJECT"）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunk_admissions (
  chunk_adm_id    BIGSERIAL PRIMARY KEY,
  resource_id     TEXT NOT NULL REFERENCES resources(resource_id),
  chunk_index     INT NOT NULL,
  chunk_hash      TEXT NOT NULL,
  relevance       TEXT NOT NULL CHECK (relevance IN ('CORE','CONTEXT','REJECT')),
  reason          TEXT,
  model           TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (resource_id, chunk_index)
);

-- ---------------------------------------------------------------
-- C. 实体身份体系（Phase 5/6：Candidate → Canonical + Alias + Resolution）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candidate_entities (
  candidate_id      TEXT PRIMARY KEY,              -- ce-<sha116>
  surface_name      TEXT NOT NULL,
  normalized_name   TEXT NOT NULL,
  entity_type       TEXT NOT NULL,
  description       TEXT,
  chunk_id          TEXT,
  document_id       TEXT,
  resource_id       TEXT REFERENCES resources(resource_id),
  time_context      TEXT,
  spatial_context   TEXT,
  topic_context     TEXT,
  extraction_model  TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  pipeline_version  TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_entity_id UUID,                          -- 001 后可 FK（canonical_entities）
  resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED'
    CHECK (resolution_status IN ('UNRESOLVED','RESOLVED_EXISTING','NEW','TYPE_CONFLICT'))
);
CREATE INDEX IF NOT EXISTS idx_cand_norm ON candidate_entities(normalized_name, entity_type);
CREATE INDEX IF NOT EXISTS idx_cand_resource ON candidate_entities(resource_id);

CREATE TABLE IF NOT EXISTS canonical_entities (
  entity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name TEXT NOT NULL,                     -- 禁止作为主键；同名可并存
  entity_type    TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE','MERGED','DEPRECATED')),
  merged_into    UUID REFERENCES canonical_entities(entity_id),
  description    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_canon_name ON canonical_entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_canon_type ON canonical_entities(entity_type);

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_id         BIGSERIAL PRIMARY KEY,
  entity_id        UUID NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
  alias            TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  alias_type       TEXT NOT NULL DEFAULT 'alias'
    CHECK (alias_type IN ('alias','historical_name','modern_name','foreign_name','courtesy_name','abbreviation')),
  source           TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (entity_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON entity_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS entity_resolutions (
  resolution_id      BIGSERIAL PRIMARY KEY,
  candidate_id       TEXT NOT NULL REFERENCES candidate_entities(candidate_id),
  matched_entity_id  UUID REFERENCES canonical_entities(entity_id),
  method             TEXT NOT NULL CHECK (method IN ('exact','alias','embedding','llm','rules')),
  score              REAL,
  reason             TEXT,
  model              TEXT,
  prompt_version     TEXT,
  status             TEXT NOT NULL CHECK (status IN ('MERGED','NEW','UNRESOLVED')),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_resol_candidate ON entity_resolutions(candidate_id);

-- ---------------------------------------------------------------
-- D. TimeSpan / Place（Phase 9/10 一等时间与地名版本）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timespans (
  timespan_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  valid_from       TEXT,
  valid_to         TEXT,
  approximate      BOOLEAN NOT NULL DEFAULT FALSE,
  granularity      TEXT NOT NULL DEFAULT 'year'
    CHECK (granularity IN ('day','month','year','decade','era','dynasty','period','unknown')),
  dynasty          TEXT,
  historical_period TEXT,
  raw_text         TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS place_versions (
  place_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id        UUID NOT NULL REFERENCES canonical_entities(entity_id),
  name             TEXT NOT NULL,
  name_type        TEXT NOT NULL CHECK (name_type IN ('historical','modern')),
  timespan_id      UUID REFERENCES timespans(timespan_id),
  admin_code       TEXT,
  geometry         geometry(Geometry, 4326),
  source           TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_place_geom ON place_versions USING GIST(geometry);

CREATE TABLE IF NOT EXISTS place_relations (
  id            BIGSERIAL PRIMARY KEY,
  from_entity   UUID NOT NULL REFERENCES canonical_entities(entity_id),
  relation      TEXT NOT NULL CHECK (relation IN
    ('historical_name_of','successor_of','predecessor_of','part_of','overlaps_with','located_within')),
  to_entity     UUID NOT NULL REFERENCES canonical_entities(entity_id),
  timespan_id   UUID REFERENCES timespans(timespan_id),
  evidence_id   UUID,                               -- evidence(evidence_id)，后加 FK
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- E. Event 对象（Phase 5 事件中心建模，替代 pairwise 共现边）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
  event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type     TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  description    TEXT,
  timespan_id    UUID REFERENCES timespans(timespan_id),
  place_entity_id UUID REFERENCES canonical_entities(entity_id),
  entity_id      UUID REFERENCES canonical_entities(entity_id),  -- 事件对应的 Canonical Entity
  status         TEXT NOT NULL DEFAULT 'CANDIDATE'
    CHECK (status IN ('CANDIDATE','ADMITTED','CONTESTED','REJECTED')),
  resource_id    TEXT REFERENCES resources(resource_id),
  quote_span     TEXT,                              -- 事件原文证据
  extraction_model TEXT, prompt_version TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(canonical_name);

CREATE TABLE IF NOT EXISTS event_participants (
  id            BIGSERIAL PRIMARY KEY,
  event_id      UUID NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  entity_id     UUID NOT NULL REFERENCES canonical_entities(entity_id),
  role          TEXT NOT NULL DEFAULT 'participant'
    CHECK (role IN ('participant','organization','object','cause','outcome')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, entity_id, role)
);

-- ---------------------------------------------------------------
-- F. Claim / Evidence / Admission（Phase 5/8/9 核心知识单位）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
  claim_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id      UUID NOT NULL REFERENCES canonical_entities(entity_id),
  predicate_id    TEXT NOT NULL,                   -- 必须在 predicates.yaml 注册
  object_id       UUID NOT NULL REFERENCES canonical_entities(entity_id),
  event_id        UUID REFERENCES events(event_id),
  timespan_id     UUID REFERENCES timespans(timespan_id),
  place_entity_id UUID REFERENCES canonical_entities(entity_id),
  status          TEXT NOT NULL DEFAULT 'CANDIDATE'
    CHECK (status IN ('CANDIDATE','SUPPORTED','CORROBORATED','ADMITTED','CONDITIONAL',
                      'CONTESTED','REJECTED','STALE','SUPERSEDED','REVOKED')),
  confidence      REAL,
  generation_model TEXT NOT NULL,
  model_version   TEXT,
  prompt_version  TEXT NOT NULL,
  pipeline_version TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_claims_sub ON claims(subject_id);
CREATE INDEX IF NOT EXISTS idx_claims_obj ON claims(object_id);
CREATE INDEX IF NOT EXISTS idx_claims_pred ON claims(predicate_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
-- 同一三元组+同一时间范围允许并存多条 Claim（不同来源可争议）；不设唯一约束

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id     UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
  resource_id  TEXT REFERENCES resources(resource_id),
  document_id  TEXT,
  chunk_id     TEXT,
  page         INT,
  paragraph    INT,
  quote_span   TEXT NOT NULL,                      -- 必须能在 chunk 原文定位
  match_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (match_status IN ('PENDING','EXACT','NORMALIZED','FAILED')),
  relation     TEXT NOT NULL DEFAULT 'SUPPORTS'
    CHECK (relation IN ('SUPPORTS','CONTRADICTS','MENTIONS','QUALIFIES')),
  source_id    TEXT REFERENCES sources(source_id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_id);

CREATE TABLE IF NOT EXISTS claim_admissions (
  admission_id   BIGSERIAL PRIMARY KEY,
  claim_id       UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
  stage          TEXT NOT NULL CHECK (stage IN
    ('schema_validation','entity_resolution','domain_range','evidence_span',
     'temporal','spatial','yangtze_scope','source_independence','conflict_detection','admission')),
  result         TEXT NOT NULL CHECK (result IN ('PASS','FAIL','SKIP')),
  detail         JSONB NOT NULL DEFAULT '{}',
  model          TEXT,
  prompt_version TEXT,
  evaluated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_claim_adm ON claim_admissions(claim_id);

-- ---------------------------------------------------------------
-- G. Source 聚类（Phase 8 转载/近重复）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_clusters (
  cluster_id   TEXT PRIMARY KEY,                    -- sc-<hash>
  original_url TEXT,
  method       TEXT NOT NULL DEFAULT 'simhash',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE resources
  ADD COLUMN IF NOT EXISTS cluster_key TEXT;

-- ---------------------------------------------------------------
-- H. Knowledge Gap / ResearchTask（Phase 14/15 Gap 驱动自增长）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_gaps (
  gap_id      TEXT PRIMARY KEY,                     -- gap-<hash>
  gap_type    TEXT NOT NULL CHECK (gap_type IN
    ('missing_entity_info','missing_evidence','single_source','missing_period',
     'missing_region','conflicting','low_confidence','unresolved_entity','uncovered_subquestion')),
  region      TEXT,
  period      TEXT,
  topic       TEXT,
  entity_type TEXT,
  detail      JSONB NOT NULL DEFAULT '{}',
  priority    REAL DEFAULT 0.5,
  status      TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESEARCHING','RESOLVED','WONTFIX')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS research_tasks (
  task_id       TEXT PRIMARY KEY,                   -- rt-<hash>
  gap_id        TEXT REFERENCES knowledge_gaps(gap_id),
  status        TEXT NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED','RUNNING','DONE','FAILED','CANCELLED')),
  search_intent TEXT,
  queries       TEXT[] NOT NULL DEFAULT '{}',
  result_summary TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- I. Provenance 事件（全链操作留痕）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provenance_events (
  prov_id    BIGSERIAL PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id  TEXT NOT NULL,
  action     TEXT NOT NULL,
  actor      TEXT NOT NULL DEFAULT 'pipeline',
  detail     JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prov_object ON provenance_events(object_type, object_id);

-- ---------------------------------------------------------------
-- J. Candidate → Canonical 外链（表创建后补 FK）
-- ---------------------------------------------------------------
ALTER TABLE candidate_entities
  DROP CONSTRAINT IF EXISTS fk_cand_canonical,
  ADD CONSTRAINT fk_cand_canonical FOREIGN KEY (resolved_entity_id)
    REFERENCES canonical_entities(entity_id);

-- ---------------------------------------------------------------
-- K. 质量视图
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW v_canonical_stats AS
SELECT
  (SELECT count(*) FROM canonical_entities WHERE status='ACTIVE')            AS canonical_entities,
  (SELECT count(*) FROM events)                                              AS events,
  (SELECT count(*) FROM claims WHERE status='ADMITTED')                      AS admitted_claims,
  (SELECT count(*) FROM claims)                                              AS claims_total,
  (SELECT count(DISTINCT claim_id) FROM evidence)                            AS claims_with_evidence,
  (SELECT count(*) FROM evidence WHERE match_status IN ('EXACT','NORMALIZED')) AS evidence_located,
  (SELECT count(*) FROM resources WHERE admission_status='CORE')             AS resources_core,
  (SELECT count(*) FROM resources WHERE admission_status='CONTEXT')          AS resources_context,
  (SELECT count(*) FROM resources WHERE admission_status='REJECTED')         AS resources_rejected,
  (SELECT count(*) FROM knowledge_gaps WHERE status='OPEN')                  AS gaps_open;
