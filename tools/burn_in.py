#!/usr/bin/env python3
"""burn_in.py — Burn-in 三轮（goal §97-§99）：3/5/10 缺口，每轮前后快照对比（§98）。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports" / "V2_BURN_IN_REPORT.json"


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


SNAPSHOT = """
SELECT
 (SELECT count(*) FROM resources),
 (SELECT count(*) FROM claims WHERE status='ADMITTED'),
 (SELECT count(*) FROM canonical_entities WHERE merged_into IS NULL),
 (SELECT count(*) FROM cultural_traditions WHERE status='ADMITTED'),
 (SELECT count(*) FROM cultural_processes WHERE status='ADMITTED'),
 (SELECT count(*) FROM cultural_flows),
 (SELECT count(*) FROM structural_gaps WHERE status='OPEN'),
 (SELECT count(*) FROM structural_gaps WHERE status='RESOLVED'),
 (SELECT count(*) FROM system_memberships WHERE system_id IS NOT NULL AND status='ADMITTED')
"""


def snap(cur) -> dict:
    cur.execute(SNAPSHOT)
    r = cur.fetchone()
    keys = ["resources", "admitted_claims", "entities", "traditions_adm", "processes_adm",
            "flows", "gaps_open", "gaps_resolved", "memberships_admitted"]
    return dict(zip(keys, [int(x) for x in r]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    conn = psycopg2.connect(dsn())
    cycles = []
    try:
        with conn.cursor() as cur:
            before = snap(cur)
        for i, n_gaps in [(1, 3), (2, 5), (3, 10)]:
            t0 = time.time()
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "cultural_system_growth.py"),
                 "--cycle", "--gaps", str(n_gaps)],
                capture_output=True, text=True, timeout=3000, cwd=str(ROOT))
            with conn.cursor() as cur:
                after = snap(cur)
            delta = {k: after[k] - before.get(k, 0) for k in after}
            cycles.append({
                "cycle": i, "gaps_targeted": n_gaps, "exit": proc.returncode,
                "elapsed_s": round(time.time() - t0, 1),
                "before": before, "after": after, "delta": delta,
            })
            print(f"cycle {i}: exit={proc.returncode} delta={json.dumps(delta, ensure_ascii=False)}")
            before = after
    finally:
        conn.close()

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cycles": cycles,
              "success_criteria": "真实结构增益 + 目标缺口改善 + 熔断健康（§99）",
              "note": "增量评估：资源/结构对象增长、缺口消长、任务状态见 V2_GROWTH_CYCLE_*.json"}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
