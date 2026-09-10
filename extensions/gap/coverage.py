# -*- coding: utf-8 -*-
"""Phase 14 v2：Coverage Cube（§19-27）——真正基于 Canonical 数据的覆盖计算。

Region 归属：Claim.place_entity_id / object(Place) / Event.place → Place 实体名 → 省
Period：claims.timespan → historical_period / dynasty
Topic：resource_admissions.topic_labels（scope gate 输出）
EntityType：canonical_entities.entity_type

输出：coverage_cells 表 + 缺口分级（EMPTY/VERY_LOW/LOW_EVIDENCE/SINGLE_SOURCE/
LOW_CONFIDENCE/CONFLICTED/UNRESOLVED/STALE）+ gap_priority_score + 自动收敛
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from config.settings import SETTINGS

PROVINCES = ["湖北", "湖南", "四川", "重庆", "江苏", "江西", "安徽", "云南",
             "贵州", "青海", "西藏", "甘肃", "河南", "陕西", "浙江", "上海"]
PERIOD_AXIS = ["先秦", "秦汉", "两晋南北朝", "隋唐", "宋元", "明清", "近代", "现代"]
TOPIC_AXIS = ["水利工程", "历史文化", "红色文化", "考古与早期文明", "文学文化",
              "工业文化", "交通航运", "城市文化", "非遗", "民俗", "宗教", "民族",
              "生态文化", "饮食文化", "教育文化", "科技文化", "移民与人口流动",
              "中外文化交流", "商业文化", "艺术文化", "建筑文化"]
ETYPE_AXIS = ["Person", "Event", "Place", "WaterSystem", "Organization", "Site",
              "Work", "Institution", "Artifact", "Heritage", "Practice"]


def region_of(name: str | None) -> str | None:
    for p in PROVINCES:
        if p in (name or ""):
            return p
    return None


def build_cube(conn) -> dict:
    """从 ADMITTED claims 构建 coverage_cells（真实归属）。"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT COALESCE(rp.canonical_name, op.canonical_name,
                            evp.canonical_name, '全流域') AS place_name,
                   COALESCE(NULLIF(t.historical_period,''),
                            NULLIF(t.dynasty,''), '未分期') AS period,
                   COALESCE((SELECT tl FROM resource_admissions a,
                             unnest(a.topic_labels) AS tl
                             WHERE a.resource_id=(SELECT e.resource_id FROM evidence e
                                                  WHERE e.claim_id=c.claim_id LIMIT 1)
                               AND tl IN ('水利工程','历史文化','红色文化','考古与早期文明',
                                  '文学文化','工业文化','交通航运','城市文化','非遗',
                                  '民俗','宗教','民族','生态文化','饮食文化','教育文化',
                                  '科技文化','移民与人口流动','中外文化交流','商业文化',
                                  '艺术文化','建筑文化')
                             LIMIT 1), '未标注') AS topic,
                   s.entity_type AS entity_type,
                   count(DISTINCT c.claim_id) AS claims,
                   count(DISTINCT ev.resource_id) AS resources,
                   count(DISTINCT COALESCE(r.source_cluster_id, ev.resource_id)) AS indep
            FROM claims c
            JOIN canonical_entities s ON s.entity_id=c.subject_id
            LEFT JOIN evidence ev ON ev.claim_id=c.claim_id
            LEFT JOIN resources r ON r.resource_id=ev.resource_id
            LEFT JOIN resource_admissions a ON a.resource_id=ev.resource_id
            LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
            LEFT JOIN canonical_entities rp ON rp.entity_id=c.place_entity_id
            LEFT JOIN canonical_entities op ON op.entity_id=c.object_id
                 AND op.entity_type='Place'
            LEFT JOIN canonical_entities evp ON evp.entity_id=c.place_entity_id
            WHERE c.status='ADMITTED'
            GROUP BY 1,2,3,4""")
        facts = cur.fetchall()

    cell_map: dict = {}
    for f in facts:
        region = region_of(f["place_name"]) or "全流域"
        period = f["period"] if f["period"] in PERIOD_AXIS else "未分期"
        topic = f["topic"] if f["topic"] in TOPIC_AXIS else "其他"
        key = (region, period, topic, f["entity_type"])
        cell = cell_map.setdefault(key, {"claims": 0, "resources": 0, "indep": 0})
        cell["claims"] += f["claims"]
        cell["resources"] += f["resources"]
        cell["indep"] += f["indep"]

    cur2 = conn.cursor()
    cur2.execute("DELETE FROM coverage_cells")
    for (region, period, topic, etype), v in cell_map.items():
        score = min(1.0, (v["claims"] / 10) * 0.5 + (v["indep"] / 8) * 0.5)
        cur2.execute(
            """INSERT INTO coverage_cells
               (region_id, period_id, topic_id, entity_type, resource_count,
                claim_count, independent_evidence_count, coverage_score)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (region_id, period_id, topic_id, entity_type)
               DO UPDATE SET claim_count=EXCLUDED.claim_count,
                 resource_count=EXCLUDED.resource_count,
                 independent_evidence_count=EXCLUDED.independent_evidence_count,
                 coverage_score=EXCLUDED.coverage_score, updated_at=now()""",
            (region, period, topic, etype, v["resources"], v["claims"],
             v["indep"], score))
    conn.commit()
    return {"cells": len(cell_map)}


def grade_gaps(conn) -> dict:
    """全组合网格分级 + 缺口生成 + 自动收敛（§26/§27）。"""
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT region_id, period_id, topic_id, entity_type, claim_count,
                          independent_evidence_count, coverage_score
                   FROM coverage_cells""")
    cells = {(r["region_id"], r["period_id"], r["topic_id"], r["entity_type"]): r
             for r in cur.fetchall()}

    generated = resolved = 0
    for region in PROVINCES:
        for period in PERIOD_AXIS:
            for topic in TOPIC_AXIS[:8]:
                for etype in ETYPE_AXIS[:5]:
                    cell = cells.get((region, period, topic, etype))
                    claims = cell["claim_count"] if cell else 0
                    indep = cell["independent_evidence_count"] if cell else 0
                    score = cell["coverage_score"] if cell else 0.0
                    if claims == 0:
                        gtype = "EMPTY"
                    elif indep == 0:
                        gtype = "VERY_LOW"
                    elif indep <= 1 and claims < 3:
                        gtype = "SINGLE_SOURCE"
                    elif score < 0.25:
                        gtype = "LOW_EVIDENCE"
                    else:
                        continue
                    gid = "gap-" + hashlib.sha1(
                        f"{gtype}|{region}|{period}|{topic}|{etype}".encode()
                    ).hexdigest()[:12]
                    priority = min(1.0, 0.4 + (0.2 if gtype == "EMPTY" else 0.1)
                                   + (0.2 if indep == 0 else 0.1))
                    cur.execute(
                        """INSERT INTO knowledge_gaps
                           (gap_id, gap_type, region, period, topic, entity_type,
                            detail, priority, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'OPEN')
                           ON CONFLICT (gap_id) DO UPDATE
                           SET detail=EXCLUDED.detail, priority=EXCLUDED.priority""",
                        (gid, gtype, region, period, topic, etype,
                         json.dumps({"claims": claims, "indep": indep},
                                    ensure_ascii=False), priority))
                    generated += 1
    # 自动收敛：组合已有足够覆盖 → RESOLVED
    cur.execute("""
        UPDATE knowledge_gaps g SET status='RESOLVED', resolved_at=now()
        WHERE g.status IN ('OPEN','RESEARCHING')
          AND g.gap_type IN ('EMPTY','VERY_LOW','SINGLE_SOURCE','LOW_EVIDENCE',
                             'missing_period','missing_region','uncovered_subquestion')
          AND EXISTS (SELECT 1 FROM coverage_cells cc
                      WHERE (cc.region_id=g.region OR g.region IS NULL)
                        AND (cc.period_id=g.period OR g.period IS NULL)
                        AND (cc.topic_id=g.topic OR g.topic IS NULL)
                        AND cc.claim_count >= 5
                        AND cc.independent_evidence_count >= 2)""")
    resolved = cur.rowcount
    cur.execute("SELECT count(*) AS open_gaps FROM knowledge_gaps WHERE status='OPEN'")
    open_n = (cur.fetchone() or {}).get("open_gaps", 0)
    cur.close()
    return {"gap_cells_generated": generated, "auto_resolved": resolved,
            "open_gaps": open_n}


if __name__ == "__main__":
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    r1 = build_cube(conn)
    r2 = grade_gaps(conn)
    conn.close()
    print("cube cells:", r1["cells"])
    print("gaps:", json.dumps(r2, ensure_ascii=False))
