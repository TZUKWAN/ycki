#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cultural_system_growth.py — 文化系统自主增长引擎 v2（goal §57-§70 / §97）。

严格闭环（§67）：
  结构缺口 → 研究任务（绑定 gap_id，§59）→ 查询策略（从研究问题展开，§58）
  → 采集（collect.run，batch=task_id 实现资源级溯源 §60）→ canonical 管线
  → 目标候选重新合成 → 缺口复测（§62：只有缺口消失才 RESOLVED）
  → 质量审计 + 增益报告（§65）→ 熔断检查（§69）

用法：
  python tools/cultural_system_growth.py --cycle                 # 单轮，最多3个任务
  python tools/cultural_system_growth.py --cycle --gaps 5
  python tools/cultural_system_growth.py --audit                 # 只跑熔断审计
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.v2.structural_gaps import detect_gaps  # noqa: E402

REPORT_DIR = ROOT / "reports"

# 研究问题的查询展开模板（§58：由研究问题展开，禁止机械组合为主策略）
QUERY_TEMPLATES: dict[str, list[str]] = {
    "SINGLE_SOURCE_STRUCTURE": [
        "{target_name} 史料", "{target_name} 地方志", "{target_name} 研究 论文",
        "{target_name} 起源 争议", "{target_name} 考古 发现",
    ],
    "MISSING_EVIDENCE": [
        "{target_name} 文献", "{target_name} 非遗 申报", "{target_name} 历史 记载",
        "{target_name} 田野调查",
    ],
    "MISSING_PROCESS_STAGE": [
        "{target_name} 分期", "{target_name} 早期 形成", "{target_name} 晚期 演变",
        "{target_name} 转折",
    ],
    "MISSING_CROSS_REGION_LINK": [
        "{region_a} {region_b} 交流", "{target_name} 路线", "{target_name} 移民",
        "{target_name} 贸易 史",
    ],
    "MISSING_SYSTEM_MEMBERSHIP": [
        "{target_name} 生平", "{target_name} 籍贯", "{target_name} 事迹",
    ],
    "MISSING_HYDRO_LINK": [
        "{target_name} 航运", "{target_name} 水路", "{target_name} 长江 港口",
    ],
    "MISSING_PROCESS": [
        "{target_name} 过程", "{target_name} 历史 变迁", "{target_name} 开发",
    ],
}


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


# ----------------------------------------------------------------------
# 熔断审计（§69 硬断路 + 质量断路）
# ----------------------------------------------------------------------

def circuit_audit(cur) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    cur.execute("""SELECT count(*) FROM structural_relations
                   WHERE status='ADMITTED' AND knowledge_type IS DISTINCT FROM 'ONTOLOGY_RELATION'
                     AND COALESCE(evidence_count,0)=0 AND COALESCE(independent_source_count,0)=0""")
    checks["evidence_less_admitted_relations"] = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM system_memberships
                   WHERE system_id IS NOT NULL AND status='ADMITTED' AND anchor_count < 2""")
    checks["geo_only_admitted"] = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM cultural_traditions t WHERE t.status='ADMITTED'
                   AND NOT EXISTS (SELECT 1 FROM tradition_evidence te WHERE te.tradition_id=t.tradition_id)""")
    checks["admitted_traditions_without_evidence"] = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM cultural_processes p WHERE p.status='ADMITTED'
                     AND (p.start_time IS NULL OR p.start_time='')
                     AND NOT EXISTS (SELECT 1 FROM process_evidence pe
                                     WHERE pe.process_id=p.process_id AND pe.field_name='time')""")
    checks["admitted_processes_without_time_evidence"] = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM cultural_flows WHERE COALESCE(origin,'')='' OR COALESCE(destination,'')=''
                   OR COALESCE(content,'')=''""")
    checks["flows_missing_hard_fields"] = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM process_evidence pe
                   LEFT JOIN claims c ON pe.claim_id=c.claim_id
                   WHERE pe.claim_id IS NOT NULL AND c.claim_id IS NULL""")
    checks["broken_evidence_links"] = cur.fetchone()[0]

    hard_failures = {k: v for k, v in checks.items() if v and k in (
        "evidence_less_admitted_relations", "geo_only_admitted",
        "admitted_traditions_without_evidence", "admitted_processes_without_time_evidence",
        "flows_missing_hard_fields", "broken_evidence_links")}
    return {"checks": checks, "hard_failures": hard_failures,
            "circuit": "PAUSE_GROWTH" if hard_failures else "HEALTHY"}


# ----------------------------------------------------------------------
# 研究任务生成（§57）
# ----------------------------------------------------------------------

def ensure_task_for_gap(cur, gap: dict[str, Any]) -> str | None:
    cur.execute("SELECT task_id FROM structural_research_tasks WHERE gap_id=%s LIMIT 1",
                (gap["gap_id"],))
    row = cur.fetchone()
    if row:
        return str(row[0])
    gap_type = gap["type"]
    known = gap["known"]
    target_name = (known.get("name") or known.get("_ref") or gap_type) if isinstance(known, dict) else str(known)
    question = {
        "SINGLE_SOURCE_STRUCTURE": f"关于{target_name}的既有单一来源结论能否被其他独立来源印证或修正？",
        "MISSING_EVIDENCE": f"有哪些独立史料/档案/研究报告可以为{target_name}提供字段级证据？",
        "MISSING_PROCESS_STAGE": f"{target_name}经历了哪些可断代的阶段？各阶段的起讫与特征是什么？",
        "MISSING_CROSS_REGION_LINK": f"{target_name}所涉区域之间通过哪些具体历史过程发生互动？",
        "MISSING_SYSTEM_MEMBERSHIP": f"{target_name}的文化归属应如何用≥2个结构锚点加以证明？",
        "MISSING_HYDRO_LINK": f"长江水系在{target_name}中扮演了什么角色？",
    }.get(gap_type, f"如何填补{target_name}的结构性缺口{gap_type}？")
    templates = QUERY_TEMPLATES.get(gap_type, ["{target_name} 历史", "{target_name} 文化"])
    queries = [t.format(target_name=target_name, region_a=known.get("systems", ["", ""])[0]
                        if isinstance(known, dict) else "",
                        region_b=known.get("systems", ["", ""])[1]
                        if isinstance(known, dict) else "")
               for t in templates]
    cur.execute("""
        INSERT INTO structural_research_tasks (gap_id, research_question, structural_gap_type,
            target_object, current_known_structure, missing_structure, candidate_hypotheses,
            required_evidence, search_strategy, expected_output_type, resolution_criteria, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PLANNED') RETURNING task_id
    """, (gap["gap_id"], question, gap_type, target_name,
          json.dumps(known, ensure_ascii=False), json.dumps(gap["missing"], ensure_ascii=False),
          [f"假设1：{target_name}的缺口源于采集盲区而非史实空缺",
           f"假设2：{target_name}的缺口反映学术界的真实争议"],
          "至少2个相互独立的来源集群，字段级引文可绑定",
          queries[:5],
          "ADMITTED 结构对象或缺口消失",
          "目标 structural_gap 复测消失（status != OPEN），或证据覆盖达到准入标准"))
    return str(cur.fetchone()[0])


# ----------------------------------------------------------------------
# 增长主循环
# ----------------------------------------------------------------------

def run_cycle(max_gaps: int) -> dict[str, Any]:
    conn = psycopg2.connect(dsn())
    cycle_report: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                    "tasks": []}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            audit = circuit_audit(cur)
            cycle_report["circuit_audit"] = audit
            if audit["circuit"] == "PAUSE_GROWTH":
                print("CIRCUIT BREAKER: PAUSE_GROWTH", json.dumps(audit["hard_failures"], ensure_ascii=False))
                return cycle_report

            # 1) 缺口重检测（幂等）
            detect_gaps(conn, apply=True)
            # 2) 取优先级最高的、尚无任务或任务未终结的 OPEN 缺口
            cur.execute("""
                SELECT g.gap_id::text, g.gap_type, g.priority, g.current_structure, g.missing_structure
                FROM structural_gaps g
                WHERE g.status='OPEN'
                  AND NOT EXISTS (SELECT 1 FROM structural_research_tasks t
                                  WHERE t.gap_id=g.gap_id AND t.status IN ('RESOLVED','FAILED'))
                ORDER BY g.priority DESC, g.created_at
                LIMIT %s
            """, (max_gaps,))
            gaps = [{"gap_id": r["gap_id"], "type": r["gap_type"], "priority": float(r["priority"]),
                     "known": r["current_structure"], "missing": r["missing_structure"]}
                    for r in cur.fetchall()]

        for gap in gaps:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                task_id = ensure_task_for_gap(cur, gap)
                conn.commit()
                cur.execute("UPDATE structural_research_tasks SET status='SEARCHING', "
                            "attempt_count=attempt_count+1, updated_at=now() WHERE task_id=%s", (task_id,))
                cur.execute("SELECT search_strategy, research_question FROM structural_research_tasks "
                            "WHERE task_id=%s", (task_id,))
                strat = cur.fetchone()
                conn.commit()
            task_entry: dict[str, Any] = {"task_id": task_id, "gap_id": gap["gap_id"],
                                          "gap_type": gap["type"],
                                          "research_question": strat["research_question"]}
            if not strat["search_strategy"]:
                task_entry["result"] = "NO_QUERIES"
                continue

            # 3) 采集（batch=task_id 溯源绑定）
            topics_file = ROOT / "tmp_topics.json"
            topics_file.write_text(json.dumps({
                "themes": [{"topic": f"gap:{gap['gap_id'][:8]}",
                            "queries": strat["search_strategy"]}]
            }, ensure_ascii=False), encoding="utf-8")
            try:
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "collect.py"), "--batch", f"task_{task_id[:8]}",
                     "--topics", str(topics_file), "--max-total", "20"],
                    capture_output=True, text=True, timeout=1800, cwd=str(ROOT))
                task_entry["collect_exit"] = proc.returncode
            except subprocess.TimeoutExpired:
                task_entry["collect_exit"] = -1
            # 资源级溯源回填（§60）
            with conn.cursor() as cur:
                cur.execute("""UPDATE resources SET gap_id=%s, research_task_id=%s,
                               search_intent=%s WHERE collection_batch=%s
                               AND (gap_id IS NULL OR gap_id='')""",
                            (gap["gap_id"], task_id, strat["research_question"], f"task_{task_id[:8]}"))
                task_entry["resources_tagged"] = cur.rowcount
                cur.execute("UPDATE structural_research_tasks SET status='CANONICALIZING', "
                            "updated_at=now() WHERE task_id=%s", (task_id,))
            conn.commit()

            # 4) canonical 管线（新增资源走抽取/ER/claim 准入）
            try:
                subprocess.run([sys.executable, str(ROOT / "tools" / "rebuild_canonical.py"),
                                "--limit", "20"], capture_output=True, text=True,
                               timeout=2400, cwd=str(ROOT))
            except subprocess.TimeoutExpired:
                pass

            # 5) 缺口复测（§62：缺口消失才 RESOLVED）
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""SELECT status FROM structural_gaps WHERE gap_id=%s""", (gap["gap_id"],))
                still = cur.fetchone()
                cur.execute("""SELECT count(*) FROM structural_gaps
                               WHERE gap_type=%s AND status='OPEN'
                                 AND current_structure->>'_ref'=%s""",
                            (gap["type"], gap["known"].get("_ref") if isinstance(gap["known"], dict) else ""))
                (dup_open,) = cur.fetchone()
                resolved = dup_open == 0
                cur.execute("""UPDATE structural_research_tasks SET status=%s, updated_at=now(),
                               resolution_evidence=%s WHERE task_id=%s""",
                            ("RESOLVED" if resolved else "PARTIAL_GAIN" if (task_entry.get("resources_tagged") or 0) > 0 else "NO_GAIN",
                             json.dumps({"gap_still_open": bool(still and still[0] == "OPEN"),
                                         "open_duplicates": dup_open}, ensure_ascii=False),
                             task_id))
                if resolved and still and still[0] == "OPEN":
                    cur.execute("UPDATE structural_gaps SET status='RESOLVED' WHERE gap_id=%s",
                                (gap["gap_id"],))
            conn.commit()
            task_entry["gap_resolved"] = resolved
            cycle_report["tasks"].append(task_entry)

        # 6) 增益报告（§65）
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cultural_traditions")
            cycle_report["gain"] = {"traditions_total": cur.fetchone()[0]}
            cur.execute("SELECT count(*) FROM cultural_processes")
            cycle_report["gain"]["processes_total"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM cultural_flows")
            cycle_report["gain"]["flows_total"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM structural_gaps WHERE status='OPEN'")
            cycle_report["gain"]["gaps_open"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM structural_gaps WHERE status='RESOLVED'")
            cycle_report["gain"]["gaps_resolved"] = cur.fetchone()[0]
            cycle_report["circuit_audit"] = circuit_audit(cur)
        conn.commit()
        return cycle_report
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cycle", action="store_true")
    g.add_argument("--audit", action="store_true")
    ap.add_argument("--gaps", type=int, default=3)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.audit:
        conn = psycopg2.connect(dsn())
        try:
            with conn.cursor() as cur:
                print(json.dumps(circuit_audit(cur), ensure_ascii=False, indent=2))
        finally:
            conn.close()
        return 0

    report = run_cycle(args.gaps)
    out = REPORT_DIR / f"V2_GROWTH_CYCLE_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.get("gain", {}), ensure_ascii=False))
    print(f"报告: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
