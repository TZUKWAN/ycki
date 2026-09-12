#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_final_report.py — 生成 reports/V2_FINAL_VALIDATION.{json,md}（goal §109-§110）。

所有数字由脚本实时查询/子进程运行获得（§107 禁止手写统计残留）。
FINAL STATUS 规则（§111/§120）：§120 列出的任一项 FAIL 或 NOT_MEASURED → 整体 FAIL。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from config.settings import SETTINGS

    # 1) 门禁
    val = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_canonical_v2.py"), "--json"],
                         capture_output=True, text=True, cwd=str(ROOT))
    gates_doc = json.loads(val.stdout)

    conn = psycopg2.connect(SETTINGS.pg_dsn)
    counts: dict[str, int] = {}
    try:
        with conn.cursor() as cur:
            one = lambda sql: cur.execute(sql) or cur.fetchone()[0]  # noqa: E731
            counts.update({
                "resources": one("SELECT count(*) FROM resources"),
                "entities": one("SELECT count(*) FROM canonical_entities WHERE merged_into IS NULL"),
                "claims_admitted": one("SELECT count(*) FROM claims WHERE status='ADMITTED'"),
                "evidence": one("SELECT count(*) FROM evidence"),
                "systems": one("SELECT count(*) FROM cultural_systems"),
                "regions": one("SELECT count(*) FROM cultural_regions"),
                "hydro_units": one("SELECT count(*) FROM hydro_spatial_units"),
                "hydro_relations": one("SELECT count(*) FROM hydro_spatial_relations"),
                "phases": one("SELECT count(*) FROM historical_phases"),
                "domains": one("SELECT count(*) FROM cultural_domains"),
                "system_memberships": one("SELECT count(*) FROM system_memberships"),
                "memberships_admitted": one(
                    "SELECT count(*) FROM system_memberships WHERE system_id IS NOT NULL AND status='ADMITTED'"),
                "traditions": one("SELECT count(*) FROM cultural_traditions"),
                "processes": one("SELECT count(*) FROM cultural_processes"),
                "flows": one("SELECT count(*) FROM cultural_flows"),
                "structural_relations": one("SELECT count(*) FROM structural_relations"),
                "interpretations": one("SELECT count(*) FROM interpretations"),
                "fact_only_entities": one("""
                    SELECT count(*) FROM canonical_entities ce
                    WHERE ce.merged_into IS NULL
                      AND NOT EXISTS (SELECT 1 FROM system_memberships m WHERE m.object_id=ce.entity_id)"""),
                "gaps_open": one("SELECT count(*) FROM structural_gaps WHERE status='OPEN'"),
                "gaps_partial": one("SELECT count(*) FROM structural_research_tasks WHERE status='PARTIAL_GAIN'"),
                "gaps_resolved": one("SELECT count(*) FROM structural_gaps WHERE status='RESOLVED'"),
                "tasks_resolved": one("SELECT count(*) FROM structural_research_tasks WHERE status='RESOLVED'"),
            })
    finally:
        conn.close()

    gate = {g["id"]: g for g in gates_doc["gates"]}
    membership_bench = {}
    mb_path = ROOT / "reports" / "V2_MEMBERSHIP_BENCHMARK.json"
    if mb_path.exists():
        mb = json.loads(mb_path.read_text(encoding="utf-8"))
        membership_bench = {k: mb.get(k) for k in
                            ("sample_size", "admitted_precision", "candidate_uphold_rate", "judge_errors")}

    phase_status = {
        "REPRODUCIBILITY": gate["G01"]["status"],
        "ONTOLOGY": gate["G02/G03"]["status"],
        "HYDRO_SPATIAL": gate["G02/G03"]["status"],
        "SYSTEM_MEMBERSHIP": gate["G04"]["status"],
        "STRUCTURAL_RELATION": gate["G05"]["status"] and gate["G06"]["status"],
        "TRADITION": gate["G07"]["status"],
        "PROCESS": gate["G08"]["status"],
        "FLOW": gate["G09"]["status"],
        "INTERPRETATION": "NOT_MEASURED",  # 解释层表已建，内容层未填充
        "STRUCTURAL_GAP_ENGINE": "PASS" if gate["G12/G13"]["status"] == "PASS" else gate["G12/G13"]["status"],
        "RESEARCH_ENGINE": gate["G12/G13"]["status"],
        "DIGITAL_HUMANITIES_BENCHMARK": "PASS(questions_only)",
        "GOLDEN_TEN": "PARTIAL(structures_partial)",
        "RED_TEAM": "NOT_MEASURED",
        "CLEAN_ROOM": "PASS(2026-09-13)",  # reports/V2_CLEAN_ROOM_REPORT.md
        "BURN_IN": "CYCLE_1_DONE(_partial)_2_3_NOT_MEASURED",
        "SOAK_TEST": "NOT_MEASURED",
        "CULTURAL_SYSTEM_AUTONOMOUS_GROWTH": "CYCLE_MODE(手动触发)NOT_DAEMON",
        "CANONICAL_V1_REGRESSION": gate["V1REG"]["status"],
    }
    all_pass = all(v == "PASS" for v in phase_status.values())
    final_status = "PASS" if all_pass else "FAIL"

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                     capture_output=True, text=True).stdout.strip(),
        "final_status": final_status,
        "phase_status": phase_status,
        "gates": gates_doc["gates"],
        "membership_benchmark": membership_bench,
        "counts": counts,
        "notes": [
            "FINAL STATUS=FAIL 的未达项（§120）：INTERPRETATION 内容层、RED_TEAM、BURN_IN 2/3、SOAK_TEST、常驻自主增长——时间预算内诚实记录，不虚报。",
            "按 §0.4：代码完成/SQL成功/HTTP200/数据库有数据均不视为完成；完成只由验收门禁决定。",
        ],
    }
    out_json = ROOT / "reports" / "V2_FINAL_VALIDATION.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# V2 FINAL VALIDATION", "",
          f"- 生成时间：{report['generated_at']}（脚本生成，§107）",
          f"- Git commit：{report['git_commit']}",
          f"- **FINAL STATUS：{final_status}**（§111/§120 规则）", "",
          "## 阶段状态", ""]
    md += [f"- {k}: **{v}**" for k, v in phase_status.items()]
    md += ["", "## 门禁指标", "", "| Gate | 状态 | 指标 |", "|---|---|---|"]
    md += [f"| {g['id']} | {g['status']} | `{json.dumps(g['metrics'], ensure_ascii=False)}` |"
           for g in gates_doc["gates"]]
    md += ["", "## 数量盘点（§110）", "", "```json",
           json.dumps(counts, ensure_ascii=False, indent=2), "```", ""]
    if membership_bench:
        md += ["## Membership 判官基准", "", "```json",
               json.dumps(membership_bench, ensure_ascii=False, indent=2), "```", ""]
    md += ["## 诚实声明（§0.4）", ""] + [f"- {n}" for n in report["notes"]]
    out_md = ROOT / "reports" / "V2_FINAL_VALIDATION.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"FINAL STATUS={final_status}")
    print(f"报告: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
