#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_quality_audit.py — 来源质量审计（§30）。

产出 reports/V2_SOURCE_QUALITY_AUDIT.md：
  1) 来源类 × 权威级分布（resources × sources.classify）
  2) 各来源类的 Scope 通过率（CORE/CONTEXT vs REJECTED）
  3) 各来源类证据产出率（resource → ADMITTED evidence）
  4) 采集批次 yield（注册→范围通过→上传→processed→admitted 证据）
  5) 独立来源簇统计（source_cluster_id 覆盖）
确定性 SQL，无模型参与。
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "V2_SOURCE_QUALITY_AUDIT.md"


def main() -> int:
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    lines = [f"# V2 Source Quality Audit", f"- 生成：{time.strftime('%Y-%m-%dT%H:%M:%S%z')}", ""]
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(s.source_type,'UNKNOWN'), COALESCE(s.authority_level,'UNKNOWN'),
                              count(*)
                       FROM resources r LEFT JOIN sources s ON s.source_id=r.source_id
                       GROUP BY 1,2 ORDER BY 3 DESC""")
        lines += ["## 来源类 × 权威级", "", "| 类 | 级 | 资源数 |", "|---|---|---|"]
        for st, au, n in cur.fetchall():
            lines.append(f"| {st} | {au} | {n} |")

        cur.execute("""SELECT COALESCE(s.source_type,'UNKNOWN'),
                              count(*) FILTER (WHERE r.admission_status IN ('CORE','CONTEXT')),
                              count(*) FILTER (WHERE r.admission_status='REJECTED'),
                              count(*)
                       FROM resources r LEFT JOIN sources s ON s.source_id=r.source_id
                       GROUP BY 1 ORDER BY 4 DESC""")
        lines += ["", "## 范围门通过率（按来源类）", "", "| 类 | CORE/CONTEXT | REJECTED | 通过率 |", "|---|---|---|---|"]
        for st, ok, rej, tot in cur.fetchall():
            rate = ok / max(1, ok + rej)
            lines.append(f"| {st} | {ok} | {rej} | {rate:.1%} |")

        cur.execute("""SELECT COALESCE(s.source_type,'UNKNOWN'),
                              count(DISTINCT r.resource_id)
                       FROM evidence e
                       JOIN resources r ON r.resource_id=e.resource_id
                       JOIN claims c ON c.claim_id=e.claim_id AND c.status='ADMITTED'
                       LEFT JOIN sources s ON s.source_id=r.source_id
                       GROUP BY 1 ORDER BY 2 DESC""")
        lines += ["", "## 证据产出（有 ADMITTED 证据的资源，按来源类）", "", "| 类 | 资源数 |", "|---|---|"]
        for st, n in cur.fetchall():
            lines.append(f"| {st} | {n} |")

        cur.execute("""SELECT collection_batch, count(*),
                              count(*) FILTER (WHERE admission_status IN ('CORE','CONTEXT')),
                              count(*) FILTER (WHERE ingest_status='processed'),
                              count(*) FILTER (WHERE ingest_status='failed')
                       FROM resources WHERE collection_batch IS NOT NULL
                       GROUP BY 1 ORDER BY 1""")
        lines += ["", "## 批次 yield", "", "| 批次 | 注册 | 范围通过 | processed | failed |", "|---|---|---|---|---|"]
        for b, n, ok, pr, fa in cur.fetchall():
            lines.append(f"| {b} | {n} | {ok} | {pr} | {fa} |")

        cur.execute("SELECT count(*) FROM resources WHERE COALESCE(source_cluster_id,'')<>''")
        clustered = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT source_cluster_id) FROM resources WHERE COALESCE(source_cluster_id,'')<>''")
        clusters = cur.fetchone()[0]
    conn.close()
    lines += ["", "## 独立来源簇（§7.3）", "",
              f"- 带簇标记资源：{clustered}",
              f"- 独立簇数：{clusters}",
              "", "> 审计结论：以数据库实时统计为准；低通过率来源类不证明采集失败，",
              "> 需结合 scope_gold 与 claim 准入拒绝原因复核。"]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {OUT} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
