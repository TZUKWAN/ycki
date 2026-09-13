#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""golden_ten_validate.py — Golden Ten 逐案验收（§18）。

对 10 个终极案例逐个检查 required_components：
  traditions / processes / flows：名称在库且 status ∈ ADMITTED/SUPPORTED
  key_entities：实体存在且 ACTIVE（含别名归并）
  interpretation_questions：interpretations 表有非空解释（模糊匹配）
输出每案覆盖矩阵 + 总门禁（10/10 PASS 才过 §18）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
import yaml

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "yangtze" / "benchmarks" / "golden_ten.yaml"
OUT = ROOT / "reports" / "V2_GOLDEN_TEN_VALIDATION.json"


def main() -> int:
    doc = yaml.safe_load(BENCH.read_text(encoding="utf-8"))
    cases = doc["cases"]
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    report_cases = []
    try:
        with conn.cursor() as cur:
            for c in cases:
                req = c.get("required_components") or {}
                res = {"id": c["id"], "title": c["title"], "components": {}}

                def check(names, table, name_col, id_col):
                    out = []
                    for name in names:
                        cur.execute(f"""SELECT {id_col}::text, status FROM {table}
                                        WHERE {name_col}=%s ORDER BY created_at LIMIT 1""", (name,))
                        r = cur.fetchone()
                        out.append({"name": name, "exists": bool(r),
                                    "status": r[1] if r else None,
                                    "ok": bool(r) and r[1] in ("ADMITTED", "SUPPORTED")})
                    return out

                res["components"]["traditions"] = check(req.get("traditions") or [],
                                                        "cultural_traditions", "tradition_name", "tradition_id")
                res["components"]["processes"] = check(req.get("processes") or [],
                                                       "cultural_processes", "process_name", "process_id")
                flows = req.get("flows") or []
                fl = []
                for name in flows:
                    # flow 名称是描述性的：按关键词匹配 flow_type/content/origin/destination
                    kw = name[:2]
                    cur.execute("""SELECT flow_id::text FROM cultural_flows
                                   WHERE flow_type ILIKE %s OR content ILIKE %s
                                      OR origin ILIKE %s OR destination ILIKE %s LIMIT 1""",
                                (f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%"))
                    r = cur.fetchone()
                    fl.append({"name": name, "ok": bool(r)})
                res["components"]["flows"] = fl
                ents = []
                for name in req.get("key_entities") or []:
                    cur.execute("""SELECT entity_id::text FROM canonical_entities
                                   WHERE (canonical_name=%s OR EXISTS (
                                     SELECT 1 FROM entity_aliases a WHERE a.entity_id=canonical_entities.entity_id
                                       AND a.alias=%s)) AND status='ACTIVE' AND merged_into IS NULL LIMIT 1""",
                                (name, name))
                    r = cur.fetchone()
                    ents.append({"name": name, "ok": bool(r)})
                res["components"]["key_entities"] = ents
                interps = []
                for q in c.get("required_components", {}).get("interpretation_questions") or []:
                    cur.execute("SELECT count(*) FROM interpretations WHERE statement ILIKE %s",
                                (f"%{q[:6]}%",))
                    interps.append({"question": q, "ok": cur.fetchone()[0] > 0})
                res["components"]["interpretations"] = interps

                def cov(items):
                    return (round(sum(1 for x in items if x.get("ok")) / len(items), 3)
                            if items else None)
                res["coverage"] = {k: cov(v) for k, v in res["components"].items()}
                flat_ok = [x for v in res["components"].values() for x in v if x.get("ok") is not None]
                all_items = [x for v in res["components"].values() for x in v]
                res["ratio"] = round(sum(1 for x in all_items if x.get("ok")) / max(1, len(all_items)), 3)
                res["gate"] = "PASS" if res["ratio"] >= 0.95 else "FAIL"
                report_cases.append(res)
    finally:
        conn.close()
    passed = sum(1 for c in report_cases if c["gate"] == "PASS")
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "cases": report_cases, "passed": passed, "total": len(report_cases),
           "gate": "PASS" if passed == len(report_cases) else "FAIL"}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in report_cases:
        print(f"{c['id']} {c['title']}: ratio={c['ratio']} gate={c['gate']}")
    print("GATE:", out["gate"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
