-- =====================================================================
-- YCKI 004_er_evolution.sql
-- ER 沿革关系收口（§3.1-3.2）：无证据沿革只入候选表，不入正式 place_relations
-- =====================================================================

-- 候选沿革关系（ER 提名，未达证据标准）
CREATE TABLE IF NOT EXISTS candidate_evolution_relations (
  id           BIGSERIAL PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidate_entities(candidate_id),
  from_entity  UUID NOT NULL REFERENCES canonical_entities(entity_id),
  to_entity    UUID NOT NULL REFERENCES canonical_entities(entity_id),
  relation     TEXT NOT NULL CHECK (relation IN
    ('historical_name_of','successor_of','predecessor_of','NO_RELATION','UNRESOLVED')),
  evidence_resource_id TEXT REFERENCES resources(resource_id),
  evidence_chunk_id   TEXT,
  evidence_quote_span TEXT,
  evidence_verified   TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (evidence_verified IN ('PENDING','EXACT','NORMALIZED','FAILED','NONE')),
  model        TEXT,
  prompt_version TEXT,
  confidence   REAL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evo_cand ON candidate_evolution_relations(candidate_id);

-- LLM 裁决命中多个同名实体 → AMBIGUOUS_MATCH 新增状态
ALTER TABLE entity_resolutions DROP CONSTRAINT IF EXISTS entity_resolutions_status_check;
ALTER TABLE entity_resolutions
  ADD CONSTRAINT entity_resolutions_status_check
  CHECK (status IN ('MERGED','NEW','UNRESOLVED','AMBIGUOUS_MATCH'));

ALTER TABLE candidate_entities
  DROP CONSTRAINT IF EXISTS candidate_entities_resolution_status_check;
ALTER TABLE candidate_entities
  ADD CONSTRAINT candidate_entities_resolution_status_check
  CHECK (resolution_status IN ('UNRESOLVED','RESOLVED_EXISTING','NEW','TYPE_CONFLICT',
                               'AMBIGUOUS_MATCH'));

-- ResearchTask 状态机扩展（§12）
ALTER TABLE research_tasks DROP CONSTRAINT IF EXISTS research_tasks_status_check;
ALTER TABLE research_tasks
  ADD CONSTRAINT research_tasks_status_check
  CHECK (status IN ('PLANNED','SEARCHING','COLLECTED','INGESTING','CANONICALIZING',
                    'VALIDATING','RESOLVED','NO_GAIN','FAILED','BLOCKED'));
ALTER TABLE research_tasks
  ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_gain JSONB,
  ADD COLUMN IF NOT EXISTS last_queries TEXT[],
  ADD COLUMN IF NOT EXISTS resolution_evidence JSONB,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

-- Coverage Cube（§25）
CREATE TABLE IF NOT EXISTS coverage_cells (
  cell_id     BIGSERIAL PRIMARY KEY,
  region_id   TEXT NOT NULL,
  period_id   TEXT NOT NULL,
  topic_id    TEXT NOT NULL DEFAULT 'all',
  entity_type TEXT NOT NULL,
  resource_count INT NOT NULL DEFAULT 0,
  entity_count   INT NOT NULL DEFAULT 0,
  event_count    INT NOT NULL DEFAULT 0,
  claim_count    INT NOT NULL DEFAULT 0,
  independent_evidence_count INT NOT NULL DEFAULT 0,
  coverage_score REAL NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (region_id, period_id, topic_id, entity_type)
);

-- 事件证据（§48）：events 已有 chunk_id/match_status，补 evidence 事件表
CREATE TABLE IF NOT EXISTS event_evidence (
  id          BIGSERIAL PRIMARY KEY,
  event_id    UUID NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  resource_id TEXT REFERENCES resources(resource_id),
  chunk_id    TEXT,
  quote_span  TEXT NOT NULL,
  match_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (match_status IN ('PENDING','EXACT','NORMALIZED','FAILED')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_event_evidence ON event_evidence(event_id);
