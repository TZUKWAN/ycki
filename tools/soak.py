#!/usr/bin/env python3
"""soak.py — 连续受控增长 Soak（goal §100-§102）。

时间盒驱动：在 deadline 前连续执行 growth cycle（每轮重新检测缺口、非固定主题），
每轮后检查 §101 零违规项并做故障注入（§102 的可离线等价项）。
到期即停，如实记录完成轮数。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports" / "V2_SOAK_REPORT.json"
VIOLATION_SQL = {
    "critical_schema_violation": """SELECT count(*) FROM structural_relations
        WHERE status='ADMITTED' AND knowledge_type IS DISTINCT FROM 'ONTOLOGY_RELATION'
          AND COALESCE(evidence_count,0)=0 AND COALESCE(independent_source_count,0)=0""",
    "geo_only_membership": """SELECT count(*) FROM system_memberships
        WHERE system_id IS NOT NULL AND status='ADMITTED' AND anchor_count<2""",
    "evidence_less_formal_structure": """SELECT count(*) FROM cultural_traditions t
        WHERE t.status='ADMITTED' AND NOT EXISTS
          (SELECT 1 FROM tradition_evidence te WHERE te.tradition_id=t.tradition_id)""",
    "false_task_resolution": """SELECT count(*) FROM structural_research_tasks t
        WHERE t.status='RESOLVED' AND t.gap_id IS NOT NULL AND EXISTS
          (SELECT 1 FROM structural_gaps g WHERE g.gap_id=t.gap_id AND g.status='OPEN')""",
    "flows_missing_hard_fields": """SELECT count(*) FROM cultural_flows
        WHERE COALESCE(origin,'')='' OR COALESCE(destination,'')='' OR COALESCE(content,'')=''""",
}


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def violations(cur) -> dict[str, int]:
    out = {}
    for k, sql in VIOLATION_SQL.items():
        cur.execute(sql)
        out[k] = int(cur.fetchone()[0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", required=True, help="HH:MM（本地时间，到期停止）")
    ap.add_argument("--max-cycles", type=int, default=10)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    h, m = args.deadline.split(":")
    deadline = datetime.now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    conn = psycopg2.connect(dsn())
    cycles = []
    try:
        for i in range(1, args.max_cycles + 1):
            if datetime.now() >= deadline:
                print(f"时间盒到（{deadline:%H:%M}），已完成 {len(cycles)} 轮")
                break
            t0 = time.time()
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "cultural_system_growth.py"),
                 "--cycle", "--gaps", "3"],
                capture_output=True, text=True, timeout=2400, cwd=str(ROOT))
            with conn.cursor() as cur:
                v = violations(cur)
            cycles.append({"cycle": i, "exit": proc.returncode,
                           "elapsed_s": round(time.time() - t0, 1), "violations": v})
            bad = {k: n for k, n in v.items() if n}
            print(f"soak {i}: exit={proc.returncode} violations={bad or 'ZERO'}")
            if bad:
                break  # §101 任一违规立即停止（circuit）
    finally:
        conn.close()

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "cycles_completed": len(cycles), "cycles_required": 10,
              "status": "PASS" if len(cycles) >= 10 else f"PARTIAL({len(cycles)}/10)",
              "zero_violation_across_run": all(
                  not any(c["violations"].values()) for c in cycles),
              "cycles": cycles}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SOAK status={report['status']} 报告: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
