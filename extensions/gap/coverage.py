# -*- coding: utf-8 -*-
"""Phase 14：Coverage Matrix 与 Knowledge Gap 检测（真实计算，非模拟）。

Coverage = Region × Period × Topic × EntityType 覆盖计数。
Gap 类型（v1 实现）：
  missing_region   —— 省级区域完全无 CORE 资源
  missing_period   —— 主要历史时期无 ADMITTED claims
  single_source    —— ADMITTED claim 仅有 1 个独立来源
  conflicting      —— CONTESTED claims
  unresolved_entity—— UNRESOLVED 候选
  low_confidence   —— confidence < 0.65 的 ADMITTED
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
import requests

from config.settings import SETTINGS

H = {"X-API-Key": "ycki-baseline-6f2a91c4"}

PROVINCES = ["湖北", "湖南", "四川", "重庆", "江苏", "江西", "安徽", "云南",
             "贵州", "青海", "西藏", "甘肃", "河南", "陕西", "浙江", "上海", "南京", "武汉",
             "宜昌", "荆州", "岳阳", "九江", "安庆", "芜湖", "镇江", "扬州", "万州", "宜宾",
             "泸州", "涪陵", "黄石", "鄂州", "长沙", "南昌", "成都", "昆明", "贵阳"]
PERIODS = ["先秦", "秦汉", "三国", "两晋南北朝", "隋唐", "宋元", "明清", "近代", "现代"]


def _gid(*parts) -> str:
    return "gap-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def compute_and_store():
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    gaps = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # --- 覆盖矩阵：region(省) × 周期(朝代) 计数（基于 claims 的时空属性 + 资源主题）---
            cur.execute("""SELECT count(*) AS n FROM resources
                           WHERE admission_status='CORE'""")
            core_total = cur.fetchone()["n"]

            # missing_region：省名在 CORE 资源 title/text_domain 中完全无覆盖
            cur.execute("SELECT coalesce(string_agg(title,' '), '') || ' ' || "
                        "coalesce(string_agg(COALESCE(source_domain),''),'') AS blob "
                        "FROM resources WHERE admission_status IN ('CORE','CONTEXT')")
            blob = cur.fetchone()["blob"]
            covered_regions = [p for p in PROVINCES if p in blob]
            missing_regions = [p for p in PROVINCES if p not in blob]

            # missing_period：ADMITTED claims 的朝代分布
            cur.execute("""SELECT COALESCE(t.dynasty, t.historical_period, '未分期') AS period,
                                  count(DISTINCT c.claim_id) AS n
                           FROM claims c LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
                           WHERE c.status='ADMITTED' GROUP BY 1""")
            period_counts = {r["period"]: r["n"] for r in cur.fetchall()}
            missing_periods = [p for p in PERIODS if period_counts.get(p, 0) == 0]

            # single_source：仅一条 evidence 的 ADMITTED
            cur.execute("""SELECT c.claim_id, s.canonical_name AS sub, o.canonical_name AS obj,
                                  c.predicate_id, count(e.evidence_id) AS n
                           FROM claims c
                           JOIN canonical_entities s ON s.entity_id=c.subject_id
                           JOIN canonical_entities o ON o.entity_id=c.object_id
                           LEFT JOIN evidence e ON e.claim_id=c.claim_id
                           WHERE c.status='ADMITTED'
                           GROUP BY c.claim_id, s.canonical_name, o.canonical_name,
                                    c.predicate_id
                           HAVING count(e.evidence_id) <= 1
                           ORDER BY random() LIMIT 200""")
            single = cur.fetchall()

            cur.execute("SELECT count(*) AS n FROM claims WHERE status='CONTESTED'")
            contested = cur.fetchone()["n"]
            cur.execute("""SELECT count(*) AS n FROM candidate_entities
                           WHERE resolution_status='UNRESOLVED'""")
            unresolved = cur.fetchone()["n"]
            cur.execute("""SELECT count(*) AS n FROM claims
                           WHERE status='ADMITTED' AND COALESCE(confidence,1) < 0.65""")
            low_conf = cur.fetchone()["n"]

        def add(gtype, region, period, topic, etype, detail):
            gaps.append({"gap_id": _gid(gtype, region, period, topic, etype),
                         "gap_type": gtype, "region": region, "period": period,
                         "topic": topic, "entity_type": etype, "detail": detail})

        for p in missing_regions:
            add("missing_region", p, None, None, None,
                {"core_resources": 0})
        for p in missing_periods:
            add("missing_period", None, p, None, None,
                {"admitted_claims": 0})
        for r in single[:100]:
            add("single_source", None, None, None, None,
                {"claim_id": str(r["claim_id"]), "subject": r["sub"],
                 "predicate": r["predicate_id"], "object": r["obj"],
                 "evidence_count": r["n"]})
        add("conflicting", None, None, None, None, {"count": contested})
        add("unresolved_entity", None, None, None, None, {"count": unresolved})
        add("low_confidence", None, None, None, None, {"count": low_conf})

        # 缺口自动收敛：missing_region 已获得覆盖 → RESOLVED
        with conn.cursor() as cur:
            cur.execute("""UPDATE knowledge_gaps SET status='RESOLVED', resolved_at=now()
                           WHERE gap_type='missing_region' AND status IN ('OPEN','RESEARCHING')
                             AND region = ANY(%s)""", (covered_regions,))
            resolved_n = cur.rowcount
        # 去重后入库
        with conn.cursor() as cur:
            for g in gaps:
                cur.execute(
                    """INSERT INTO knowledge_gaps
                       (gap_id, gap_type, region, period, topic, entity_type, detail)
                       VALUES (%(gap_id)s,%(gap_type)s,%(region)s,%(period)s,%(topic)s,
                               %(entity_type)s,%(detail)s::jsonb)
                       ON CONFLICT (gap_id) DO UPDATE SET detail=EXCLUDED.detail,
                         status='OPEN'""",
                    {**g, "detail": json.dumps(g["detail"], ensure_ascii=False)})
        conn.commit()

        summary = {
            "coverage": {"core_resources": core_total,
                         "covered_regions": covered_regions,
                         "period_admitted": period_counts},
            "gaps_resolved_this_run": resolved_n,
            "gaps": {"total": len(gaps),
                     "missing_region": len(missing_regions),
                     "missing_period": missing_periods,
                     "single_source": len(single),
                     "conflicting": contested,
                     "unresolved_entity": unresolved,
                     "low_confidence": low_conf},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        out = ROOT / "reports" / "COVERAGE_GAPS.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        conn.close()


if __name__ == "__main__":
    compute_and_store()
