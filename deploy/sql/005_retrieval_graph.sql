# -*- coding: utf-8 -*-
"""005_retrieval_graph.sql —— Retrieval Graph 持久化到 PostgreSQL（逐条写入，永不全量序列化）

设计原则：
- 每次 upsert/delete 只触及单行，绝不读取或重写整个图
- 与 GraphML 文件完全解耦——GraphML 只做冷备份，不再参与运行时
- 利用 PostgreSQL 事务保证原子性——异常中断时已提交的写入永久保留
"""
CREATE TABLE IF NOT EXISTS retrieval_nodes (
  node_id      TEXT PRIMARY KEY,
  entity_type  TEXT NOT NULL,
  description  TEXT,
  source_id    TEXT,
  file_path    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_edges (
  edge_id     TEXT PRIMARY KEY,       -- deterministic: src|tgt|keywords_hash
  src_id      TEXT NOT NULL REFERENCES retrieval_nodes(node_id),
  tgt_id      TEXT NOT NULL REFERENCES retrieval_nodes(node_id),
  keywords    TEXT NOT NULL,
  description TEXT,
  weight      REAL NOT NULL DEFAULT 1.0,
  source_id   TEXT,
  file_path   TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_retrieval_edges_src ON retrieval_edges(src_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_edges_tgt ON retrieval_edges(tgt_id);

-- 增量写入统计视图
CREATE OR REPLACE VIEW v_retrieval_graph_stats AS
SELECT
  (SELECT count(*) FROM retrieval_nodes) AS nodes,
  (SELECT count(*) FROM retrieval_edges) AS edges,
  (SELECT count(*) FROM retrieval_nodes WHERE updated_at > now() - interval '1 hour') AS nodes_last_hour,
  (SELECT count(*) FROM retrieval_edges WHERE updated_at > now() - interval '1 hour') AS edges_last_hour;
