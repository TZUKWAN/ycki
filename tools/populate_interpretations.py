#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""populate_interpretations.py — 解释层内容导入（goal §44-§45）。

合成阶段产出的 why_yangtze 陈述属于 STRUCTURAL_INFERENCE（结构推断），
不是事实，也不是学术解释；按 §44 分层导入 interpretations 表，
与 object 绑定、可追溯（引用合成轮次的 structural_admissions 记录）。
幂等：同 statement 同 subject 不重复。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SYNTH_REPORT = ROOT / "reports" / "V2_GOLDEN_CASE_SYNTHESIS.json"


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not SYNTH_REPORT.exists():
        print("合成报告不存在，先运行 tools/synthesize_structures.py")
        return 2
    results = json.loads(SYNTH_REPORT.read_text(encoding="utf-8"))["results"]
    conn = psycopg2.connect(dsn())
    imported = 0
    try:
        with conn.cursor() as cur:
            for r in results:
                why = r.get("why_yangtze")
                if isinstance(why, dict):
                    why = why.get("value") or why.get("text") or ""
                elif isinstance(why, list):
                    why = "；".join(str(x) for x in why)
                stmt = str(why or "").strip()
                oid = r.get("object_id")
                if not stmt or not oid:
                    continue
                kind = r.get("kind", "")
                cur.execute("""
                    SELECT interpretation_id FROM interpretations
                    WHERE statement=%s AND subject_id=%s LIMIT 1
                """, (stmt, oid))
                if cur.fetchone():
                    continue
                cur.execute("""
                    INSERT INTO interpretations (statement, knowledge_type, author, source_ref,
                        scope, subject_kind, subject_id, status, confidence)
                    VALUES (%s,'STRUCTURAL_INFERENCE',%s,%s,%s,%s,%s,'SUPPORTED',%s)
                """, (stmt, "synthesis_engine", f"synthesis_rule_v2_0@{r.get('seed','')}",
                      r.get("name", ""), kind, oid, r.get("coverage")))
                imported += 1
        conn.commit()
        cur_count = None
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM interpretations")
            cur_count = cur.fetchone()[0]
        print(f"导入 {imported} 条结构推断，解释层总计 {cur_count}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
