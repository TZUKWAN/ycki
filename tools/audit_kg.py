# -*- coding: utf-8 -*-
"""Phase 12 v2：KG Quality Audit Suite（独立复验，不信任库内标记）。

A. Resource Scope 正/负例（真实调用 gate）
B. ER 裁决器准确率（LLM pair 测试）+ **假合并抽检**（对 multi-alias 实体逐对 LLM 复核）
C. 谓词有效性（ADMITTED 中未注册谓词数，应为 0）
D. **溯源闭环（完整版）**：ADMITTED Claim → Evidence → Chunk(重读湖文件+重切片+复定位)
   → Document(lightrag_doc_id 存在) → Resource → Source
E. **证据独立复验**：重新对湖文件切片并调 binder，比对库内 match_status
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
import requests
import yaml

from config.settings import SETTINGS
from extensions.admission import resource_gate
from extensions.evidence.binder import bind

results: dict = {}

SCOPE_CASES = [
    ("CORE", "都江堰", "都江堰位于四川岷江之上，李冰父子主持修建，两千年来灌溉成都平原。"),
    ("CORE", "汉阳铁厂", "张之洞1890年在湖北汉阳创办汉阳铁厂，为中国近代钢铁工业发端。"),
    ("CORE", "洞庭湖", "洞庭湖位于湖南省北部，长江中游重要调蓄湖泊，流域面积广大。"),
    ("CONTEXT", "北京桥梁专家组赴武汉", "来自北京的桥梁专家组抵达武汉，参与武汉长江大桥的钢梁架设技术指导工作。"),
    ("REJECT", "故宫", "故宫又称紫禁城，位于北京市中心，是明清两代皇宫。"),
    ("REJECT", "颐和园", "颐和园是清朝皇家园林，位于北京西郊，以昆明湖和万寿山著称。"),
    ("REJECT", "山西晋商", "晋商指明清时期山西一带的商帮，以票号闻名全国，经营活动以山西为中心。"),
    ("REJECT", "东北抗联一般史", "东北抗日联军在白山黑水间坚持游击战争，是东北抗战的重要力量。"),
]

def _er_gold_cases() -> list:
    import json
    f = ROOT / "yangtze" / "schema" / "er_gold.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    return [(c["a"], c["type"], c["b"], c["expected_same"], c.get("category", ""))
            for c in d["cases"]]


def audit_scope() -> dict:
    ok, rows = 0, []
    for expect, title, text in SCOPE_CASES:
        v = resource_gate.evaluate(title, text, "audit.local", "GeneralWebsite")
        passed = v["scope_role"] == expect
        ok += passed
        rows.append({"expect": expect, "got": v["scope_role"], "title": title,
                     "pass": passed, "reason": v["relevance_reason"][:80]})
    return {"cases": len(SCOPE_CASES), "passed": ok,
            "scope_precision": round(ok / len(SCOPE_CASES), 3), "detail": rows}


def _llm_pair(a, t, b) -> dict:
    from extensions.llm import chat
    from extensions.prompts import PROMPTS
    raw = chat([{"role": "user", "content": PROMPTS["entity_resolution_v1"].format(
        name_a=a, type_a=t, desc_a="", name_b=b, type_b=t, desc_b="")}], max_tokens=250)
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {}


def audit_er_adjudicator() -> dict:
    """在金标集上测量 ER 裁决器（同人异名/沿革/同名不同实/节日异名）。"""
    cases = _er_gold_cases()
    by_cat: dict = {}
    ok, rows = 0, []
    for a, t, b, expect, cat in cases:
        v = _llm_pair(a, t, b)
        same = v.get("verdict") == "same"
        passed = same == expect
        ok += passed
        c = by_cat.setdefault(cat, {"n": 0, "pass": 0})
        c["n"] += 1
        c["pass"] += passed
        rows.append({"a": a, "b": b, "expect_same": expect, "verdict": same,
                     "pass": passed, "category": cat})
    out = {"cases": len(cases), "passed": ok,
           "adjudicator_accuracy": round(ok / len(cases), 3),
           "by_category": {k: f"{v['pass']}/{v['n']}" for k, v in by_cat.items()},
           "detail": rows}
    return out


def audit_false_merges(limit: int = 20) -> dict:
    """假合并抽检：对拥有多个不同 surface_name 的 Canonical 实体，逐对 LLM 复核。"""
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    checked = false_merged = 0
    samples = []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.entity_id, c.canonical_name, c.entity_type,
                       count(DISTINCT ce.surface_name) AS names
                FROM canonical_entities c
                JOIN candidate_entities ce ON ce.resolved_entity_id=c.entity_id
                WHERE c.status='ACTIVE'
                GROUP BY c.entity_id, c.canonical_name, c.entity_type
                HAVING count(DISTINCT ce.surface_name) > 1
                ORDER BY names DESC LIMIT %s""", (limit,))
            multi = cur.fetchall()
            for eid, cname, etype, _n in multi:
                cur.execute("""SELECT DISTINCT surface_name FROM candidate_entities
                               WHERE resolved_entity_id=%s LIMIT 6""", (eid,))
                names = [r[0] for r in cur.fetchall()]
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        v = _llm_pair(names[i], etype, names[j])
                        checked += 1
                        if v.get("verdict") != "same":
                            false_merged += 1
                            if len(samples) < 8:
                                samples.append({"entity": cname, "type": etype,
                                                "a": names[i], "b": names[j],
                                                "verdict": v.get("verdict"),
                                                "reason": str(v.get("reason", ""))[:80]})
                        if checked >= 40:
                            return {"pairs_checked": checked,
                                    "false_merge_count": false_merged,
                                    "false_merge_rate": round(false_merged / checked, 3),
                                    "samples": samples}
    finally:
        conn.close()
    return {"pairs_checked": checked, "false_merge_count": false_merged,
            "false_merge_rate": round(false_merged / checked, 3) if checked else None,
            "samples": samples}


def audit_db() -> dict:
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    out: dict = {}
    try:
        # 谓词注册表
        preds = set(yaml.safe_load(open(
            ROOT / "yangtze" / "schema" / "predicates.yaml",
            encoding="utf-8"))["predicates"].keys())

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT count(*) AS bad FROM claims
                           WHERE status='ADMITTED' AND predicate_id NOT IN %s""",
                        (tuple(preds),))
            out["invalid_predicate_admitted"] = cur.fetchone()["bad"]

            # D. 完整溯源：ADMITTED → Evidence → (chunk 重读复验) → doc → resource → source
            cur.execute("""
                SELECT c.claim_id, e.quote_span, e.match_status, e.chunk_id,
                       e.resource_id, r.text_path, r.lightrag_doc_id, r.source_id,
                       so.source_id AS src_ok
                FROM claims c
                JOIN evidence e ON e.claim_id=c.claim_id
                JOIN resources r ON r.resource_id=e.resource_id
                LEFT JOIN sources so ON so.source_id=r.source_id
                WHERE c.status='ADMITTED' AND e.relation='SUPPORTS'
                ORDER BY c.created_at DESC LIMIT 300""")
            rows = cur.fetchall()
            total = len(rows)
            chunk_ok = doc_ok = src_ok = reloc_ok = 0
            fails = []
            for r in rows:
                # chunk 存在性：重读湖文件，同规格切片后复定位
                part = None
                if r["chunk_id"] and "#" in r["chunk_id"] and r["text_path"]:
                    try:
                        part = int(r["chunk_id"].rsplit("#", 1)[1])
                    except ValueError:
                        part = None
                chunk_exists = False
                if r["text_path"] and Path(r["text_path"]).exists() and part is not None:
                    txt = Path(r["text_path"]).read_text(encoding="utf-8",
                                                         errors="replace")
                    parts = [txt[i:i + 1200]
                             for i in range(0, len(txt), 1200)]
                    chunk_exists = part < len(parts)
                    # E. 独立复验：quote 能否在该 chunk 重新定位
                    if chunk_exists:
                        if bind(r["quote_span"], parts[part]) in ("EXACT", "NORMALIZED"):
                            reloc_ok += 1
                        else:
                            fails.append({"claim": str(r["claim_id"])[:8],
                                          "why": "re-locate failed"})
                if chunk_exists:
                    chunk_ok += 1
                if r["lightrag_doc_id"]:
                    doc_ok += 1
                if r["src_ok"]:
                    src_ok += 1
            out["provenance_checked"] = total
            out["chunk_exists_rate"] = round(chunk_ok / total, 4) if total else None
            out["document_exists_rate"] = round(doc_ok / total, 4) if total else None
            out["source_exists_rate"] = round(src_ok / total, 4) if total else None
            out["evidence_relocated_rate"] = round(reloc_ok / total, 4) if total else None
            out["relocate_fail_samples"] = fails[:5]

            cur.execute("""SELECT count(*) AS bad FROM claims c
                           WHERE c.status='ADMITTED'
                             AND NOT EXISTS (SELECT 1 FROM evidence e
                                             WHERE e.claim_id=c.claim_id)""")
            out["admitted_without_evidence"] = cur.fetchone()["bad"]

            cur.execute("""SELECT count(*) FROM canonical_entities
                           WHERE entity_type='UNKNOWN' AND status='ACTIVE'""")
            out["unknown_type_entities"] = cur.fetchone()["count"]
    finally:
        conn.close()
    return out


def main():
    print("=== A. Resource Scope 正负例 ===")
    results["scope"] = audit_scope()
    print(json.dumps({k: v for k, v in results["scope"].items() if k != "detail"},
                     ensure_ascii=False))
    for r in results["scope"]["detail"]:
        if not r["pass"]:
            print("  FAIL:", r["title"], "→", r["got"])

    print("=== B1. ER 裁决器准确率 ===")
    results["er_adjudicator"] = audit_er_adjudicator()
    print(json.dumps({k: v for k, v in results["er_adjudicator"].items()
                      if k != "detail"}, ensure_ascii=False))

    print("=== B2. 假合并抽检（真实 ER 结果复核）===")
    results["false_merge"] = audit_false_merges()
    print(json.dumps(results["false_merge"], ensure_ascii=False)[:600])

    print("=== C/D/E. 现库独立复验 ===")
    results["db"] = audit_db()
    print(json.dumps(results["db"], ensure_ascii=False, indent=1))

    out = ROOT / "reports" / "KG_QUALITY_AUDIT.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n审计结果已写入 {out}")


if __name__ == "__main__":
    main()
