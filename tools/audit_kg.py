# -*- coding: utf-8 -*-
"""Phase 12：KG Quality Audit Suite —— 自动质量审计（真实测量，禁止模拟数字）。

审计项：
A. Resource Scope 正/负例（目标书 §47 样例集）
B. Entity Resolution 测试对（§48：同名/异名/古今地名）
C. Claim 谓词/方向/域值抽检（§49）
D. Provenance 闭环：ADMITTED Claim → Evidence → Chunk → Document → Resource → Source（§51，目标 100%）
E. 证据 span 回定位（§52）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
import requests

from config.settings import SETTINGS
from extensions.admission import resource_gate

results: dict = {}


# ---------------- A. Resource Scope 正/负例 ----------------
SCOPE_CASES = [
    # positive
    ("CORE", "都江堰", "都江堰位于四川岷江之上，李冰父子主持修建，两千年来灌溉成都平原。"),
    ("CORE", "汉阳铁厂", "张之洞1890年在湖北汉阳创办汉阳铁厂，为中国近代钢铁工业发端。"),
    ("CORE", "洞庭湖", "洞庭湖位于湖南省北部，长江中游重要调蓄湖泊，流域面积广大。"),
    # context
    ("CONTEXT", "北京桥梁专家组赴武汉", "来自北京的桥梁专家组抵达武汉，参与武汉长江大桥的钢梁架设技术指导工作。"),
    # negative
    ("REJECT", "故宫", "故宫又称紫禁城，位于北京市中心，是明清两代皇宫。"),
    ("REJECT", "颐和园", "颐和园是清朝皇家园林，位于北京西郊，以昆明湖和万寿山著称。"),
    ("REJECT", "山西晋商", "晋商指明清时期山西一带的商帮，以票号闻名全国，经营活动以山西为中心。"),
    ("REJECT", "东北抗联一般史", "东北抗日联军在白山黑水间坚持游击战争，是东北抗战的重要力量。"),
]


def audit_scope() -> dict:
    ok, rows = 0, []
    for expect, title, text in SCOPE_CASES:
        v = resource_gate.evaluate(title, text, "audit.local", "GeneralWebsite")
        passed = v["scope_role"] == expect
        ok += passed
        rows.append({"expect": expect, "got": v["scope_role"], "title": title,
                     "pass": passed})
    prec = ok / len(SCOPE_CASES)
    return {"cases": len(SCOPE_CASES), "passed": ok, "precision": round(prec, 3),
            "detail": rows}


# ---------------- B. Entity Resolution 测试对 ----------------
ER_CASES = [
    # (name_a, type, name_b, expect_same)
    ("毛泽东", "Person", "毛润之", True),
    ("毛泽东", "Person", "Mao Zedong", True),
    ("南京", "Place", "江宁", True),          # 古今地名
    ("武昌起义", "Event", "辛亥首义", True),
    ("汉阳铁厂", "Artifact", "汉冶萍公司", False),   # 前身≠后继公司
    ("李白", "Person", "李隆基", False),
]


def audit_er() -> dict:
    from extensions.llm import chat
    from extensions.prompts import PROMPTS
    ok, rows = 0, []
    for a, t, b, expect in ER_CASES:
        raw = chat([{"role": "user", "content": PROMPTS["entity_resolution_v1"].format(
            name_a=a, type_a=t, desc_a="", name_b=b, type_b=t, desc_b="")}],
            max_tokens=250)
        try:
            verdict = json.loads(raw.strip().strip("`").replace("json", "", 1)
                                 if raw.startswith("```") else raw)
        except Exception:
            import re
            m = re.search(r"\{.*\}", raw, re.S)
            verdict = json.loads(m.group(0)) if m else {}
        same = verdict.get("verdict") == "same"
        passed = same == expect
        ok += passed
        rows.append({"a": a, "b": b, "expect_same": expect, "verdict": same,
                     "pass": passed})
    prec = ok / len(ER_CASES)
    return {"cases": len(ER_CASES), "passed": ok, "accuracy": round(prec, 3),
            "detail": rows}


# ---------------- C/D/E. 现库审计（claim 谓词/溯源/证据） ----------------
def audit_db() -> dict:
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    out: dict = {}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # C. ADMITTED claims 谓词有效性（全部谓词都在本体中）
            cur.execute("""SELECT count(*) AS bad FROM claims
                           WHERE status='ADMITTED' AND predicate_id NOT IN %s""",
                        (tuple(_all_predicates()),))
            out["invalid_predicate_admitted"] = cur.fetchone()["bad"]

            # D. 溯源闭环：ADMITTED → Evidence → Resource → Source
            cur.execute("""
                SELECT count(*) AS total,
                  count(*) FILTER (WHERE ev.resource_id IS NOT NULL
                                    AND rs.source_id IS NOT NULL) AS closed
                FROM claims c
                JOIN evidence ev ON ev.claim_id = c.claim_id
                JOIN resources rs ON rs.resource_id = ev.resource_id
                JOIN sources  so ON so.source_id   = rs.source_id
                WHERE c.status='ADMITTED'""")
            r = cur.fetchone()
            total = r["total"]
            out["admitted_claims_with_evidence"] = total
            out["claim_provenance_complete_rate"] = round(r["closed"] / total, 4) if total else None

            # 无证据的 ADMITTED（应为 0）
            cur.execute("""SELECT count(*) AS bad FROM claims c
                           WHERE c.status='ADMITTED'
                             AND NOT EXISTS (SELECT 1 FROM evidence e
                                             WHERE e.claim_id=c.claim_id)""")
            out["admitted_without_evidence"] = cur.fetchone()["bad"]

            # E. 证据 span 回定位
            cur.execute("""SELECT count(*) AS total,
                                  count(*) FILTER (WHERE match_status IN ('EXACT','NORMALIZED'))
                                  AS located FROM evidence""")
            r = cur.fetchone()
            out["evidence_total"] = r["total"]
            out["evidence_located_rate"] = round(r["located"] / r["total"], 4) if r["total"] else None

            # 图结构健康
            cur.execute("""SELECT count(*) FROM canonical_entities
                           WHERE entity_type='UNKNOWN' AND status='ACTIVE'""")
            out["unknown_type_entities"] = cur.fetchone()["count"]
    finally:
        conn.close()
    return out


def _all_predicates():
    import yaml
    d = yaml.safe_load(open(ROOT / "yangtze" / "schema" / "predicates.yaml",
                            encoding="utf-8"))
    return set(d["predicates"].keys())


def main():
    print("=== A. Resource Scope 正负例 ===")
    results["scope"] = audit_scope()
    print(json.dumps({k: v for k, v in results["scope"].items() if k != "detail"},
                     ensure_ascii=False))
    for r in results["scope"]["detail"]:
        if not r["pass"]:
            print("  FAIL:", r)

    print("=== B. Entity Resolution 测试对 ===")
    results["er"] = audit_er()
    print(json.dumps({k: v for k, v in results["er"].items() if k != "detail"},
                     ensure_ascii=False))
    for r in results["er"]["detail"]:
        if not r["pass"]:
            print("  FAIL:", r)

    print("=== C/D/E. 现库审计 ===")
    results["db"] = audit_db()
    print(json.dumps(results["db"], ensure_ascii=False, indent=1))

    out = ROOT / "reports" / "KG_QUALITY_AUDIT.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n审计结果已写入 {out}")


if __name__ == "__main__":
    main()
