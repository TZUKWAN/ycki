# -*- coding: utf-8 -*-
"""/yangtze/* 正式知识 API（目标书 §60）：全部读 Canonical 层，不碰 Retrieval 层。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
from fastapi import FastAPI

from config.settings import SETTINGS


def _conn():
    return psycopg2.connect(SETTINGS.pg_dsn)


def mount(app: FastAPI) -> None:
    @app.get("/yangtze/entities")
    def entities(search: str = "", type: str = "", limit: int = 50):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT entity_id, canonical_name, entity_type, description,
                                  status, created_at
                           FROM canonical_entities
                           WHERE status='ACTIVE'
                             AND (%s='' OR canonical_name ILIKE '%%'||%s||'%%')
                             AND (%s='' OR entity_type=%s)
                           ORDER BY created_at DESC LIMIT %s""",
                        (search, search, type, type, limit))
            return {"entities": cur.fetchall()}

    @app.get("/yangtze/entities/{entity_id}")
    def entity_detail(entity_id: str):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT * FROM canonical_entities WHERE entity_id=%s""",
                        (entity_id,))
            ent = cur.fetchone()
            if not ent:
                return {"error": "not found"}
            cur.execute("""SELECT alias, alias_type FROM entity_aliases
                           WHERE entity_id=%s""", (entity_id,))
            aliases = cur.fetchall()
            cur.execute("""SELECT c.claim_id, c.predicate_id, c.status, c.confidence,
                                  o.entity_id AS object_id, o.canonical_name AS object,
                                  o.entity_type AS object_type, t.raw_text AS time_raw,
                                  e.quote_span, e.match_status, r.source_url, r.title AS res_title
                           FROM claims c
                           JOIN canonical_entities o ON o.entity_id=c.object_id
                           LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
                           LEFT JOIN evidence e ON e.claim_id=c.claim_id
                           LEFT JOIN resources r ON r.resource_id=e.resource_id
                           WHERE c.subject_id=%s AND c.status IN ('ADMITTED','CONDITIONAL','CONTESTED')
                           ORDER BY c.confidence DESC NULLS LAST""", (entity_id,))
            claims_out = cur.fetchall()
            cur.execute("""SELECT e.event_id, e.canonical_name, e.event_type, e.description,
                                  e.status, t.raw_text AS time_raw, p.canonical_name AS place,
                                  ep.role
                           FROM event_participants ep
                           JOIN events e ON e.event_id=ep.event_id
                           LEFT JOIN timespans t ON t.timespan_id=e.timespan_id
                           LEFT JOIN canonical_entities p ON p.entity_id=e.place_entity_id
                           WHERE ep.entity_id=%s""", (entity_id,))
            events = cur.fetchall()
        return {"entity": ent, "aliases": aliases,
                "claims_as_subject": claims_out, "events": events}

    @app.get("/yangtze/claims")
    def claims(status: str = "ADMITTED", predicate: str = "", limit: int = 50):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT c.claim_id, s.canonical_name AS subject, c.predicate_id,
                                  o.canonical_name AS object, c.status, c.confidence,
                                  t.raw_text AS time_raw, p.canonical_name AS place
                           FROM claims c
                           JOIN canonical_entities s ON s.entity_id=c.subject_id
                           JOIN canonical_entities o ON o.entity_id=c.object_id
                           LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
                           LEFT JOIN canonical_entities p ON p.entity_id=c.place_entity_id
                           WHERE (%s='' OR c.status=%s)
                             AND (%s='' OR c.predicate_id=%s)
                           ORDER BY c.created_at DESC LIMIT %s""",
                        (status, status, predicate, predicate, limit))
            return {"claims": cur.fetchall()}

    @app.get("/yangtze/claims/{claim_id}/evidence")
    def claim_evidence(claim_id: str):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT e.*, r.title AS res_title, r.source_url, so.authority_level
                           FROM evidence e
                           JOIN resources r ON r.resource_id=e.resource_id
                           LEFT JOIN sources so ON so.source_id=r.source_id
                           WHERE e.claim_id=%s""", (claim_id,))
            return {"evidence": cur.fetchall()}

    @app.get("/yangtze/events")
    def events(limit: int = 50, status: str = "ADMITTED"):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT e.event_id, e.canonical_name, e.event_type, e.description,
                                  e.status, e.quote_span, t.raw_text AS time_raw,
                                  p.canonical_name AS place,
                                  count(ep.id) AS participants
                           FROM events e
                           LEFT JOIN timespans t ON t.timespan_id=e.timespan_id
                           LEFT JOIN canonical_entities p ON p.entity_id=e.place_entity_id
                           LEFT JOIN event_participants ep ON ep.event_id=e.event_id
                           WHERE (%s='' OR e.status=%s)
                           GROUP BY e.event_id, t.raw_text, p.canonical_name
                           ORDER BY e.created_at DESC LIMIT %s""", (status, status, limit))
            return {"events": cur.fetchall()}

    @app.get("/yangtze/graph")
    def graph(entity_id: str, depth: int = 1):
        """邻域：实体 + 其 ADMITTED claims 指向/来自的实体（带证据计数）。"""
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            nodes, edges = {entity_id: None}, []
            frontier = [entity_id]
            for _ in range(max(1, depth)):
                if not frontier:
                    break
                cur.execute("""
                    SELECT c.claim_id, c.subject_id, c.predicate_id, c.object_id,
                           c.status, c.confidence,
                           (SELECT count(*) FROM evidence e WHERE e.claim_id=c.claim_id) AS ev_count,
                           t.raw_text AS time_raw
                    FROM claims c
                    LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
                    WHERE c.status IN ('ADMITTED','CONDITIONAL','CONTESTED')
                      AND (c.subject_id = ANY(%s) OR c.object_id = ANY(%s))""",
                    (frontier, frontier))
                new_ids = set()
                for row in cur.fetchall():
                    edges.append(dict(row))
                    new_ids.add(row["subject_id"])
                    new_ids.add(row["object_id"])
                frontier = [i for i in new_ids if i not in nodes]
                for i in frontier:
                    nodes[i] = None
                if frontier:
                    cur.execute("""SELECT entity_id, canonical_name, entity_type, description
                                   FROM canonical_entities WHERE entity_id = ANY(%s)""",
                                (frontier,))
                    for r in cur.fetchall():
                        nodes[r["entity_id"]] = dict(r)
            # 实体详情
            if nodes:
                cur.execute("""SELECT entity_id, canonical_name, entity_type, description
                               FROM canonical_entities WHERE entity_id = ANY(%s)""",
                            (list(nodes.keys()),))
                ent_list = cur.fetchall()
            else:
                ent_list = []
        return {"entities": ent_list, "edges": edges}

    @app.get("/yangtze/gaps")
    def gaps(status: str = "OPEN"):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT gap_id, gap_type, region, period, topic, entity_type,
                                  detail, status, created_at
                           FROM knowledge_gaps WHERE status=%s ORDER BY priority DESC""",
                        (status,))
            return {"gaps": cur.fetchall()}

    @app.get("/yangtze/coverage")
    def coverage():
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM v_canonical_stats")
            stats = dict(cur.fetchone())
            cur.execute("""SELECT historical_period AS period, count(*) FROM timespans
                           WHERE historical_period IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""")
            stats["period_distribution"] = cur.fetchall()
            cur.execute("""SELECT admission_status, count(*) FROM resources
                           GROUP BY 1 ORDER BY 2 DESC""")
            stats["resource_admission"] = cur.fetchall()
        return {"coverage": stats}

    @app.get("/yangtze/resources/admission")
    def resources_admission(status: str = "", limit: int = 50):
        with _conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT r.resource_id, r.title, r.admission_status,
                                  a.scope_role, a.yangtze_relevance, a.topic_labels,
                                  a.relevance_reason, s.authority_level, r.source_url
                           FROM resources r
                           LEFT JOIN resource_admissions a ON a.resource_id=r.resource_id
                           LEFT JOIN sources s ON s.source_id=r.source_id
                           WHERE (%s='' OR r.admission_status=%s)
                           ORDER BY r.retrieved_at DESC LIMIT %s""",
                        (status, status, limit))
            return {"resources": cur.fetchall()}
