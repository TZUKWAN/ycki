#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""growth_report.py — 50 增长周期统计报告（§19）。

从 reports/V2_GROWTH_CYCLE_*.json 汇总：
  周期数、任务数、结构对象增量（按报告时间序列差分）、缺口闭合数、
  采集资源 yield、熔断健康率。输出 reports/V2_GROWTH_50_CYCLE.md/json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "V2_GROWTH_50_CYCLE.json"
OUT_MD = ROOT / "reports" / "V2_GROWTH_50_CYCLE.md"


def main() -> int:
    reports = sorted((ROOT / "reports").glob("V2_GROWTH_CYCLE_*.json"))
    rows = []
    for p in reports:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        gain = d.get("gain", {})
        rows.append({
            "file": p.name,
            "tasks": len(d.get("tasks", [])),
            "resolved": sum(1 for t in d.get("tasks", []) if t.get("gap_resolved")),
            "circuit": (d.get("circuit_audit") or {}).get("circuit"),
            "structures": (gain.get("traditions_total", 0) + gain.get("processes_total", 0)
                           + gain.get("flows_total", 0)),
            "gaps_open": gain.get("gaps_open"),
            "gaps_resolved": gain.get("gaps_resolved"),
        })
    # 结构增量差分（结构总数上升的周期 = 有真实增益）
    gains = 0
    prev = None
    for r in rows:
        if prev is not None and r["structures"] > prev:
            gains += 1
        prev = r["structures"]
    total = len(rows)
    tasks = sum(r["tasks"] for r in rows)
    resolved = sum(r["resolved"] for r in rows)
    healthy = sum(1 for r in rows if r["circuit"] == "HEALTHY")
    gate = "PASS" if (total >= 50 and gains >= 0.6 * total) else (
        "FAIL" if total >= 50 else "NOT_MEASURED")
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cycles_available": total,
        "cycles_with_structural_gain": gains,
        "gain_rate": round(gains / max(1, total), 3),
        "tasks_total": tasks, "tasks_resolved_in_cycle": resolved,
        "circuit_healthy_rate": round(healthy / max(1, total), 3),
        "targets": {"cycles": 50, "gain_rate": 0.60, "resolution": "20-task burn-in RESOLVED>=12 (G10)"},
        "gate": gate,
        "rows_tail": rows[-15:],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# V2 Growth 50-Cycle Report", "",
          f"- 生成：{doc['generated_at']}",
          f"- 周期报告数：{total}",
          f"- 结构增益周期：{gains}（rate={doc['gain_rate']}，目标≥60%）",
          f"- 任务：{tasks}，其中周期内 gap_resolved={resolved}",
          f"- 熔断健康率：{doc['circuit_healthy_rate']}",
          f"- GATE：**{gate}**"]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
