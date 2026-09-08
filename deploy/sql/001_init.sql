-- =====================================================================
-- YCKI PostgreSQL Schema v1 (真实建库脚本)
-- 库: ycki @ ycki-postgres (postgis/postgis:16-3.4)
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------
-- Source Registry（信息源注册表，方案 §13）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
  source_id       TEXT PRIMARY KEY,              -- src-<domain 的 sha1 前 10 位>
  name            TEXT NOT NULL,
  domain          TEXT NOT NULL UNIQUE,
  organization    TEXT,
  source_type     TEXT NOT NULL DEFAULT 'GeneralWebsite'
                    CHECK (source_type IN ('Government','Archive','Library','Museum',
                         'University','AcademicJournal','LocalChronicle','ResearchInstitute',
                         'Newspaper','CulturalInstitution','GeneralWebsite','UserUpload','AIGenerated')),
  region          TEXT,
  authority_level TEXT NOT NULL DEFAULT 'UNKNOWN'
                    CHECK (authority_level IN ('S','A','B','C','UNKNOWN')),
  crawl_policy    JSONB NOT NULL DEFAULT '{}',
  rights_policy   JSONB NOT NULL DEFAULT '{}',
  topic           TEXT[] NOT NULL DEFAULT '{}',
  priority        INT NOT NULL DEFAULT 5,
  first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked    TIMESTAMPTZ
);

-- ---------------------------------------------------------------
-- Raw Resource Lake 登记表（方案 §12；对象实体存本地湖目录，MinIO 后移）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resources (
  resource_id    TEXT PRIMARY KEY,               -- res-<canonical_url sha1 前 16>
  title          TEXT,
  source_url     TEXT NOT NULL,
  canonical_url  TEXT NOT NULL UNIQUE,
  source_domain  TEXT NOT NULL,
  source_id      TEXT REFERENCES sources(source_id),
  source_type    TEXT,
  publisher      TEXT,
  author         TEXT,
  publication_time TEXT,                         -- 原文模糊时间
  published_at   TIMESTAMPTZ,
  retrieved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  mime_type      TEXT,
  http_status    INT,
  language       TEXT NOT NULL DEFAULT 'zh',
  checksum       TEXT NOT NULL,                  -- 原始字节 sha256
  text_checksum  TEXT NOT NULL,                  -- 抽取正文 sha256（内容去重键）
  raw_path       TEXT,                           -- 湖对象：raw/<domain>/<res_id>.html
  text_path      TEXT,                           -- 湖对象：text/<domain>/<res_id>.txt
  content_chars  INT,
  lightrag_doc_id TEXT,                          -- 与宿主文档状态联动
  ingest_status  TEXT NOT NULL DEFAULT 'pending'
                   CHECK (ingest_status IN ('pending','uploaded','processed',
                          'failed','duplicate','lowquality','rejected')),
  fail_reason    TEXT,
  rights         JSONB NOT NULL DEFAULT '{}',
  search_query   TEXT,
  collection_batch TEXT,
  UNIQUE (text_checksum)
);
CREATE INDEX IF NOT EXISTS idx_res_domain  ON resources(source_domain);
CREATE INDEX IF NOT EXISTS idx_res_status  ON resources(ingest_status);
CREATE INDEX IF NOT EXISTS idx_res_batch   ON resources(collection_batch);

-- ---------------------------------------------------------------
-- 采集作业日志（方案 §69）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collection_jobs (
  job_id     BIGSERIAL PRIMARY KEY,
  batch      TEXT NOT NULL,
  phase      TEXT NOT NULL CHECK (phase IN ('search','fetch','ingest')),
  query      TEXT,
  target     TEXT,
  engine     TEXT,
  status     TEXT NOT NULL CHECK (status IN ('ok','error','skipped')),
  detail     JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jobs_batch ON collection_jobs(batch, phase);

-- ---------------------------------------------------------------
-- 运行统计视图
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW v_collection_stats AS
SELECT
  (SELECT count(*) FROM sources)                                AS sources_total,
  (SELECT count(*) FROM resources)                              AS resources_total,
  count(*) FILTER (WHERE ingest_status='pending')               AS res_pending,
  count(*) FILTER (WHERE ingest_status='uploaded')              AS res_uploaded,
  count(*) FILTER (WHERE ingest_status='processed')             AS res_processed,
  count(*) FILTER (WHERE ingest_status='failed')                AS res_failed,
  count(*) FILTER (WHERE ingest_status='duplicate')             AS res_duplicate,
  count(*) FILTER (WHERE ingest_status='lowquality')            AS res_lowquality,
  sum(content_chars)                                            AS total_chars,
  count(DISTINCT source_domain)                                 AS domains_covered
FROM resources;
