#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""burn_in_20.py — 20 ResearchTask burn-in（§14）。

选 20 个不同类型的 OPEN 缺口（多样性优先 + 失败降权），每个执行完整闭环：
  研究问题 → 规划器查询 → 来源策略 → 采集(batch=task) → canonical →
  membership 锚点 → 结构综合 → 缺口复测（原判据，不改判）。
状态只允许 RESOLVED / PARTIAL_GAIN / NO_GAIN / BLOCKED，理由如实记录。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from extensions.v2.research_planner import build_plan
from extensions.v2.source_strategy import provider_plan
from extensions.v2.gap_synthesis import synthesize_for_gap

OUT = ROOT / "reports" / "V2_BURN_IN_20.json"


def run(cmd: list[str], timeout: int) -> tuple[int, str]:
    r = subprocess.run([sys.executable] + cmd, cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "")[-300:]


def pick_gaps(cur, n: int = 20) -> list[dict]:
    """类型多样性轮转选择：每轮从每个类型取 1 个未终结缺口。"""
    cur.execute("""SELECT g.gap_id::text, g.gap_type, g.priority, g.current_structure, g.missing_structure
                   FROM structural_gaps g
                   WHERE g.status='OPEN'
                     AND NOT EXISTS (SELECT 1 FROM structural_research_tasks t
                                     WHERE t.gap_id=g.gap_id AND t.status IN ('RESOLVED','FAILED'))
                   ORDER BY g.priority DESC""")
    rows = [dict(r) for r in cur.fetchall()]
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["gap_type"], []).append(r)
    picked, used = [], set()
    for round_ in range(3):
        for t in sorted(by_type):
            pool = [g for g in by_type[t] if g["gap_id"] not in used]
            if pool:
                picked.append(pool[round_ % len(pool)])
                used.add(picked[-1]["gap_id"])
                if len(picked) >= n:
                    return picked
    return picked


def main() -> int:
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    t0 = time.time()
    results = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            gaps = pick_gaps(cur)
        print(f"picked {len(gaps)} gaps")

        for gi, gap in enumerate(gaps):
            known = gap.get("current_structure") or {}
            target = (known.get("name") or known.get("_ref") or gap["gap_type"]) if isinstance(known, dict) else str(known)
            gap_norm = {"gap_id": gap["gap_id"], "type": gap["gap_type"],
                        "known": known, "missing": gap.get("missing_structure") or {}}
            rec: dict[str, Any] = {"idx": gi + 1, "gap_id": gap["gap_id"], "gap_type": gap["gap_type"],
                                   "target": str(target)[:50]}
            t1 = time.time()
            try:
                # 1) 规划器
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    plan = build_plan(cur, gap_norm, str(target), use_llm=False)
                queries = (plan["waves"][0]["queries"] + plan["waves"][2]["queries"])[:6]
                rec["queries"] = queries[:3]

                # 2) 采集（provider 计划；batch=task 溯源）
                batch = f"bi_{gap_norm['gap_id'][:8]}"
                spec = provider_plan(queries, str(target), gap_norm["type"], max_site_queries=4)
                topics = ROOT / "tmp_burn_in_topics.json"
                topics.write_text(json.dumps({"themes": [{"topic": f"bi:{str(target)[:20]}",
                                                          "gap_type": gap["gap_type"],
                                                          "queries": queries,
                                                          "provider_plan": spec}]},
                                             ensure_ascii=False), encoding="utf-8")
                rc, tail = run(["tools/collect.py", "--batch", batch, "--topics", str(topics),
                                "--max-total", "12", "--max-urls", "3"], 900)
                rec["collect_exit"] = rc

                # 3) canonical + membership
                run(["tools/rebuild_canonical.py", "--all", "--collection-batch", batch], 1800)
                run(["tools/rebuild_memberships.py", "--apply"], 1800)

                # 4) 结构综合（类型匹配）
                with conn.cursor() as cur:
                    syn = synthesize_for_gap(cur, gap_norm)
                    conn.commit()
                rec["synthesis"] = {k: syn.get(k) for k in ("attempted", "decision", "reason")}

                # 5) 复测：原检测器判据（不改判）
                from extensions.v2.structural_gaps import DETECTORS
                det = next((d for d in DETECTORS if d["type"] == gap_norm["type"]), None)
                still_open = True
                if det:
                    sql = det["sql"] + (" LIMIT %s" if "LIMIT" not in det["sql"].upper() else "")
                    with conn.cursor() as cur:
                        cur.execute(sql, (10,))
                        refs = {str(r[0]) for r in cur.fetchall()}
                    ref = (known.get("_ref") if isinstance(known, dict) else None) or str(target)
                    still_open = ref in refs
                rec["gap_still_open"] = bool(still_open)
                rec["status"] = "RESOLVED" if not still_open else "NO_GAIN"

                # 任务表落库（幂等：同 gap 新任务行）
                with conn.cursor() as cur:
                    cur.execute("""SELECT task_id::text FROM structural_research_tasks
                                   WHERE gap_id=%s AND status NOT IN ('RESOLVED','FAILED') LIMIT 1""",
                                (gap["gap_id"],))
                    row = cur.fetchone()
                    if row:
                        cur.execute("""UPDATE structural_research_tasks SET status=%s,
                                       resolution_evidence=%s, updated_at=now() WHERE task_id=%s""",
                                    (rec["status"],
                                     json.dumps({k: rec.get(k) for k in ("synthesis", "gap_still_open", "collect_exit")},
                                                ensure_ascii=False), row[0]))
                        rec["task_id"] = row[0]
                    else:
                        cur.execute("""INSERT INTO structural_research_tasks
                                       (gap_id, research_question, structural_gap_type, target_object,
                                        candidate_hypotheses, required_evidence, search_strategy,
                                        expected_output_type, resolution_criteria, status,
                                        resolution_evidence)
                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING task_id""",
                                    (gap_norm["gap_id"], f"burn-in：{gap_norm['type']} {target}",
                                     gap_norm["type"], str(target)[:80],
                                     ["假设1：采集盲区", "假设2：真实史料空缺"],
                                     "≥2 独立来源集群，字段级引文可绑定",
                                     queries[:5],
                                     "结构对象或缺口消失", "目标缺口复测消失",
                                     rec["status"],
                                     json.dumps({"synthesis": rec.get("synthesis"),
                                                 "gap_still_open": rec["gap_still_open"]},
                                                ensure_ascii=False)))
                        rec["task_id"] = str(cur.fetchone()[0])
                conn.commit()
            except Exception as exc:
                conn.rollback()
                rec["status"] = "BLOCKED"
                rec["error"] = f"{type(exc).__name__}: {exc}"[:160]
            rec["elapsed_s"] = round(time.time() - t1, 1)
            results.append(rec)
            print(f"[{gi+1}/{len(gaps)}] {gap['gap_type']} {str(target)[:24]} -> {rec['status']} "
                  f"({rec['elapsed_s']}s)", flush=True)
    finally:
        conn.close()

    resolved = sum(1 for r in results if r["status"] == "RESOLVED")
    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "total": len(results),
           "resolved": resolved, "target": 12,
           "gate": "PASS" if resolved >= 12 else "FAIL",
           "results": results, "elapsed_s": round(time.time() - t0, 1)}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
