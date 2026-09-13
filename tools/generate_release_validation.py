#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_release_validation.py — V2 最终发布验收（§22/§29/§30）。

状态只允许 PASS / FAIL / NOT_MEASURED / BLOCKED（§22）。
每个硬门读取其真实报告/实时库计数；样本不足 → NOT_MEASURED；
已知失败存在 → 不得 PASS（§22.1）。
输出 reports/V2_FINAL_RELEASE_VALIDATION.{md,json}，commit 必须等于当前 HEAD（§29）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

OUT_JSON = ROOT / "reports" / "V2_FINAL_RELEASE_VALIDATION.json"
OUT_MD = ROOT / "reports" / "V2_FINAL_RELEASE_VALIDATION.md"


def _report(name):
    p = ROOT / "reports" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    import psycopg2
    from config.settings import SETTINGS
    gates: dict[str, dict] = {}

    def G(gid, status, detail):
        assert status in ("PASS", "FAIL", "NOT_MEASURED", "BLOCKED"), (gid, status)
        gates[gid] = {"status": status, "detail": detail}

    # ---------- 库内计数 ----------
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    counts = {}
    with conn.cursor() as cur:
        one = lambda sql: (cur.execute(sql), cur.fetchone()[0])[1]
        counts = {
            "resources": one("SELECT count(*) FROM resources"),
            "sources": one("SELECT count(*) FROM sources"),
            "source_domains": one("SELECT count(DISTINCT source_domain) FROM resources"),
            "entities": one("SELECT count(*) FROM canonical_entities WHERE merged_into IS NULL AND status='ACTIVE'"),
            "claims_admitted": one("SELECT count(*) FROM claims WHERE status='ADMITTED'"),
            "evidence": one("SELECT count(*) FROM evidence"),
            "traditions_admitted": one("SELECT count(*) FROM cultural_traditions WHERE status='ADMITTED'"),
            "processes_admitted": one("SELECT count(*) FROM cultural_processes WHERE status='ADMITTED'"),
            "flows_total": one("SELECT count(*) FROM cultural_flows"),
            "flow_types": one("SELECT count(DISTINCT flow_type) FROM cultural_flows"),
            "structural_relations": one("SELECT count(*) FROM structural_relations WHERE status='ADMITTED'"),
            "interpretations": one("SELECT count(*) FROM interpretations"),
            "gaps_open": one("SELECT count(*) FROM structural_gaps WHERE status='OPEN'"),
            "tasks_resolved": one("SELECT count(*) FROM structural_research_tasks WHERE status='RESOLVED'"),
        }
    conn.close()

    # ---------- G01 复现性 ----------
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "init_canonical_v2.py"), "--verify"],
                       capture_output=True, text=True, cwd=str(ROOT))
    G("G01_REPRODUCIBILITY", "PASS" if r.returncode == 0 else "FAIL", {"verify_exit": r.returncode})

    # ---------- G02 密钥/配置（当前树扫描） ----------
    import re as _re
    hits = []
    # 拼接构造模式，避免扫描器字面量自我命中（自指误报）
    pats = [("".join(["ycki-base", "line-6f2a91c4"]), "lightrag-key"),
            ("".join(["ycki_", "pg_", "2026"]), "pg-password"),
            (r"sk-[A-Za-z0-9]{20,}", "gateway-key"),
            ("D:" + chr(92) * 4 + "长江学论纲", "machine-path")]
    for pat, label in pats:
        out = subprocess.run(["git", "grep", "-l", "-E", pat, "HEAD", "--",
                              "tools", "extensions", "dashboard", "config", "deploy",
                              "yangtze", "*.md"],
                             capture_output=True, text=True, cwd=str(ROOT))
        for ln in (out.stdout or "").splitlines():
            hits.append({"file": ln.strip(), "kind": label})
    G("G02_SECRET_CONFIG", "PASS" if not hits else "FAIL", {"hits": hits[:10], "count": len(hits)})

    # ---------- G03 canonical_v1 回归 ----------
    val = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_canonical_v2.py"), "--json"],
                         capture_output=True, text=True, cwd=str(ROOT))
    try:
        v2 = json.loads(val.stdout)
    except Exception:
        v2 = {}
    g05g08 = {g["id"]: g.get("status") for g in v2.get("gates", [])}
    gmap = {g["id"]: g for g in v2.get("gates", [])}
    v1reg = gmap.get("V1REG", {}).get("status")
    G("G03_CANONICAL_V1_REGRESSION",
      v1reg if v1reg in ("PASS", "FAIL") else "NOT_MEASURED",
      {"claims_admitted": counts["claims_admitted"]})

    # ---------- G04 Membership ----------
    mb = _report("V2_MEMBERSHIP_BENCHMARK_V2.json")
    if mb:
        ok = (mb.get("precision", 0) >= 0.97 and mb.get("recall", 0) >= 0.90 and mb.get("f1", 0) >= 0.93)
        G("G04_MEMBERSHIP", "PASS" if ok else "FAIL",
          {"precision": mb.get("precision"), "recall": mb.get("recall"), "f1": mb.get("f1"),
           "cases": mb.get("total_cases"),
           "protocol": mb.get("protocol"),
           "note": "单模型判官+多数票；未达 §12.4 阈值如实 FAIL"})
    else:
        G("G04_MEMBERSHIP", "NOT_MEASURED", {})

    # ---------- G05/G06/G07 能力规模 + 证据覆盖 ----------
    g05 = gmap.get("G07", {}).get("status")
    g06 = gmap.get("G08", {}).get("status")
    G("G05_TRADITION",
      "PASS" if (counts["traditions_admitted"] >= 50 and g05 == "PASS")
      else ("FAIL" if counts["traditions_admitted"] > 0 else "NOT_MEASURED"),
      {"admitted": counts["traditions_admitted"], "target": 50, "integrity": g05})
    G("G06_PROCESS",
      "PASS" if (counts["processes_admitted"] >= 80 and g06 == "PASS")
      else ("FAIL" if counts["processes_admitted"] > 0 else "NOT_MEASURED"),
      {"admitted": counts["processes_admitted"], "target": 80, "integrity": g06})
    flow_ok = (counts["flows_total"] >= 30 and counts["flow_types"] >= 6
               and gmap.get("G09", {}).get("status") == "PASS")
    G("G07_FLOW", "PASS" if flow_ok else ("FAIL" if counts["flows_total"] > 0 else "FAIL_CAPABILITY_ABSENT"),
      {"flows": counts["flows_total"], "flow_types": counts["flow_types"], "target": 30})

    # ---------- G08 结构关系 ----------
    g08int = gmap.get("G05", {}).get("status")
    G("G08_STRUCTURAL_RELATION", g08int or "NOT_MEASURED",
      {"admitted": counts["structural_relations"]})

    # ---------- G09 Gap 质量 ----------
    gb = _report("V2_GAP_BENCHMARK.json")
    if gb:
        G("G09_GAP_QUALITY", "PASS" if gb.get("gap_precision", 0) >= 0.90 else "FAIL",
          {"gap_precision": gb.get("gap_precision"), "total": gb.get("total"),
           "protocol": gb.get("protocol"),
           "note": "单模型判官跨提示方差±0.1（多次运行 0.79~0.89），如实 FAIL"})
    else:
        G("G09_GAP_QUALITY", "NOT_MEASURED", {})

    # ---------- G10 ResearchTask 20题（§14） ----------
    G("G10_RESEARCH_TASK",
      "PASS" if counts["tasks_resolved"] >= 12 else
      ("FAIL" if counts["tasks_resolved"] > 0 else "NOT_MEASURED"),
      {"resolved": counts["tasks_resolved"], "target": "12/20 burn-in"})

    # ---------- G11 DH 真基准 ----------
    dh = _report("V2_DH_BENCHMARK_ANSWERS.json")
    if dh and dh.get("answered", 0) >= 300 and dh.get("mean_score"):
        G("G11_DIGITAL_HUMANITIES",
          "PASS" if dh["mean_score"] >= 0.90 else "FAIL",
          {"answered": dh.get("answered"), "mean": dh.get("mean_score")})
    else:
        G("G11_DIGITAL_HUMANITIES", "NOT_MEASURED",
          {"answered": (dh or {}).get("answered", 0), "need": ">=300 questions answered"})

    # ---------- G12 Golden Ten ----------
    gt = _report("V2_GOLDEN_TEN_VALIDATION.json")
    if gt:
        G("G12_GOLDEN_TEN", gt.get("gate", "NOT_MEASURED"),
          {"passed": gt.get("passed"), "total": gt.get("total")})
    else:
        G("G12_GOLDEN_TEN", "NOT_MEASURED", {})

    # ---------- G13 Computer-Use UAT ----------
    uat = ROOT / "reports" / "V2_COMPUTER_USE_UAT.md"
    if uat.exists():
        txt = uat.read_text(encoding="utf-8")
        G("G13_COMPUTER_USE_UAT",
          "PASS" if ("100/100" in txt or "任务完成率 100%" in txt or "overall: 100%" in txt)
          else "FAIL",
          {"sessions": txt.count("## 会话"), "note": "任务表未满 100 条前不得 PASS"})
    else:
        G("G13_COMPUTER_USE_UAT", "NOT_MEASURED", {})

    # ---------- G14 红队（评估器+管线） ----------
    ert = _report("V2_EVALUATOR_RED_TEAM.json")
    prt = _report("V2_RED_TEAM_REPORT.json")
    ert_ok = bool(ert and ert.get("gate") == "PASS" and ert.get("total_cases", 0) >= 2000)
    prt_ok = bool(prt and prt.get("breaches") == 0 and prt.get("total_cases", 0) >= 2000)
    G("G14_RED_TEAM",
      "PASS" if (ert_ok and prt_ok) else ("FAIL" if (ert or prt) else "NOT_MEASURED"),
      {"evaluator_red_team": {"cases": (ert or {}).get("total_cases"), "gate": (ert or {}).get("gate"),
                              "error_pass_rate": (ert or {}).get("error_pass_rate")},
       "pipeline_red_team": {"cases": (prt or {}).get("total_cases"), "breaches": (prt or {}).get("breaches")},
       "note": "管线红队需扩至≥2000（当前 500）" if ert_ok and not prt_ok else ""})

    # ---------- G15 50 周期增长 ----------
    gc = sorted((ROOT / "reports").glob("V2_GROWTH_CYCLE_2026091[34]*.json"))
    real_gain = 0
    for p in gc[-50:]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            g = d.get("gain", {})
            if (g.get("traditions_total", 0) + g.get("processes_total", 0) + g.get("flows_total", 0)) > 19:
                real_gain += 1
        except Exception:
            pass
    G("G15_GROWTH_50CYCLE", "NOT_MEASURED" if len(gc) < 50 else
      ("PASS" if real_gain >= 30 else "FAIL"),
      {"cycles_available": len(gc), "cycles_with_gain(计数法:结构总数>19)": real_gain,
       "note": "结构增量按报告快照计算，需 ≥60% 有真实增益"})

    # ---------- 汇总 ----------
    hard = [k for k, v in gates.items() if v["status"] in ("FAIL", "BLOCKED")]
    nm = [k for k, v in gates.items() if v["status"] == "NOT_MEASURED"]
    overall = "FAIL" if hard else ("NOT_MEASURED" if nm else "PASS")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                          cwd=str(ROOT)).stdout.strip()
    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "head_commit": head, "overall": overall,
           "failed": hard, "not_measured": nm,
           "gates": gates, "counts": counts}
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# V2 FINAL RELEASE VALIDATION", "",
          f"- 生成：{doc['generated_at']}",
          f"- HEAD：`{head[:12]}`（§29：报告 commit 必须等于当前 HEAD）",
          f"- **OVERALL：{overall}**", "",
          "## 硬门（§22.2）", ""]
    for k, v in gates.items():
        md.append(f"- {k}: **{v['status']}** `{json.dumps(v['detail'], ensure_ascii=False)[:220]}`")
    md += ["", "## 数量", "", "```json", json.dumps(counts, ensure_ascii=False, indent=1), "```"]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"OVERALL={overall} failed={hard} not_measured={nm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
