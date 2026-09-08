-- =====================================================================
-- YCKI 003_pipeline_resume.sql
-- 抽取载荷跨阶段持久化（断点续跑安全）+ 事件证据字段
-- =====================================================================

-- events：抽取载荷与证据定位
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS time_text   TEXT,
  ADD COLUMN IF NOT EXISTS period      TEXT,
  ADD COLUMN IF NOT EXISTS participants_json JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS organizations_json JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS chunk_id    TEXT,
  ADD COLUMN IF NOT EXISTS match_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (match_status IN ('PENDING','EXACT','NORMALIZED','FAILED'));

-- 待准入 claims 暂存（抽取阶段写入，准入阶段消费）
CREATE TABLE IF NOT EXISTS pending_claims (
  id          BIGSERIAL PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resources(resource_id),
  subject     TEXT NOT NULL,
  predicate   TEXT NOT NULL,
  object      TEXT NOT NULL,
  time_text   TEXT,
  place       TEXT,
  quote_span  TEXT NOT NULL,
  consumed    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (resource_id, subject, predicate, object, quote_span)
);
CREATE INDEX IF NOT EXISTS idx_pending_claims_res ON pending_claims(resource_id, consumed);

-- 事件同名防重（同资源内）
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_res_name
  ON events(resource_id, canonical_name);

-- 断点续跑阶段列（PENDING→GATED→CHUNK_GATED→EXTRACTED→DONE）
ALTER TABLE resources
  ADD COLUMN IF NOT EXISTS rebuild_stage TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (rebuild_stage IN ('PENDING','GATED','CHUNK_GATED','EXTRACTED','DONE'));
CREATE INDEX IF NOT EXISTS idx_res_stage ON resources(rebuild_stage);
