#!/usr/bin/env python3
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
            one = lambda sql: cur.execute(sql) or cur.fetchone()[0]
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
                "interpretation_evidence": one("SELECT count(*) FROM interpretation_evidence"),
                "interpretations_without_evidence": one(
                    "SELECT count(*) FROM interpretations i WHERE NOT EXISTS "
                    "(SELECT 1 FROM interpretation_evidence x WHERE x.interpretation_id=i.interpretation_id)"),
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
                            ("sample_size", "rule_admitted", "admitted_precision",
                             "candidate_uphold_rate", "judge_errors")}
        membership_bench["interpretation"] = (
            "单模型受限：同模型证据丰富判官=准入终审（自洽不可作金标）；"
            "本 precision 为信息饥饿盲判官一致率（诊断指标，系统性低于准入判官）；"
            "多模型金标 P/R/F1 因网关仅 1 稳定模型而 NOT_MEASURED")

    def _json_report(name: str) -> dict:
        p = ROOT / "reports" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    red_team = _json_report("V2_RED_TEAM_REPORT.json")
    soak = _json_report("V2_SOAK_REPORT.json")
    burn_in = _json_report("V2_BURN_IN_REPORT.json")
    dh = _json_report("V2_DH_BENCHMARK_ANSWERS.json")
    try:
        daemon = json.loads((ROOT / "reports" / "V2_GROWTH_DAEMON_HEARTBEAT.json")
                            .read_text(encoding="utf-8"))
    except Exception:
        daemon = {}
    dh_ok = dh.get("answered") == 100 and (dh.get("mean_score") or 0) >= 0.85

    # 门禁状态直读（含 FAIL_CAPABILITY_ABSENT / NOT_MEASURED 语义，§3.2）
    g09 = gate.get("G09", {}).get("status", "NOT_MEASURED")
    g04 = gate.get("G04", {}).get("status", "NOT_MEASURED")
    g1213 = gate.get("G12/G13", {}).get("status", "NOT_MEASURED")
    g05 = gate.get("G05", {}).get("status", "NOT_MEASURED")
    g06 = gate.get("G06", {}).get("status", "NOT_MEASURED")

    # Golden Ten：从真实综合报告计算（10/10 结构 ADMITTED 且流动能力存在）
    synth = _json_report("V2_GOLDEN_CASE_SYNTHESIS.json")
    results = synth.get("results", []) if isinstance(synth, dict) else []
    golden_admitted = sum(1 for r in results if r.get("decision") == "ADMITTED")
    flows_now = counts.get("flows", 0)
    golden_status = ("PASS" if len(results) >= 10 and golden_admitted >= 10 and flows_now > 0
                     else f"PARTIAL(admitted={golden_admitted}/{len(results)},flows={flows_now})")

    # Clean Room：读取真实报告，禁止硬编码 PASS
    cr_path = ROOT / "reports" / "V2_CLEAN_ROOM_REPORT.md"
    if cr_path.exists() and "PASS" in cr_path.read_text(encoding="utf-8"):
        cr_mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(cr_path.stat().st_mtime))
        clean_room = f"PASS(report {cr_mtime})"
    else:
        clean_room = "NOT_MEASURED(no fresh clean-room report)"

    burn_cycles = len(burn_in.get("cycles", [])) if isinstance(burn_in, dict) else 0
    struct_rel = ("PASS" if g05 == "PASS" and g06 == "PASS"
                  else (g05 if g05 != "PASS" else g06))

    phase_status = {
        "REPRODUCIBILITY": gate["G01"]["status"],
        "ONTOLOGY": gate["G02/G03"]["status"],
        "HYDRO_SPATIAL": gate["G02/G03"]["status"],
        "SYSTEM_MEMBERSHIP": g04,
        "STRUCTURAL_RELATION": struct_rel,
        "TRADITION": gate["G07"]["status"],
        "PROCESS": gate["G08"]["status"],
        "FLOW": g09,
        "INTERPRETATION": ("PASS" if counts.get("interpretations", 0) > 0
                           and counts.get("interpretations_without_evidence", 1) == 0
                           else ("FAIL" if counts.get("interpretations", 0) > 0 else "NOT_MEASURED")),
        "STRUCTURAL_GAP_ENGINE": g1213,
        "RESEARCH_ENGINE": g1213,
        "DIGITAL_HUMANITIES_BENCHMARK": (f"FAIL_PROXY_ONLY(mean={dh.get('mean_score')},needs_real_benchmark)"
                                         if dh_ok else "NOT_MEASURED(questions_ready,answers_not_measured)"),
        "GOLDEN_TEN": golden_status,
        "RED_TEAM": ("PASS" if red_team.get("total_cases", 0) >= 500 and red_team.get("breaches") == 0
                     else ("FAIL" if red_team else "NOT_MEASURED")),
        "CLEAN_ROOM": clean_room,
        "BURN_IN": (f"PARTIAL_GAIN(cycles={burn_cycles})" if burn_cycles >= 3
                    else f"NOT_MEASURED(cycles={burn_cycles})"),
        "SOAK_TEST": ("PASS" if soak.get("cycles_completed", 0) >= 10
                      and soak.get("zero_violation_across_run") else
                      (f"PARTIAL({soak.get('cycles_completed', 0)}/10)" if soak else "NOT_MEASURED")),
        "CULTURAL_SYSTEM_AUTONOMOUS_GROWTH": ("RUNNING(daemon cycle %s)" % daemon["cycle"]
                                              if daemon.get("state") in ("RUNNING_CYCLE", "IDLE")
                                              else "CYCLE_MODE(NOT_DAEMON)"),
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
            "未达 PASS 项（§120）：" + "; ".join(f"{k}={v}" for k, v in phase_status.items() if v != "PASS") or "无",
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
