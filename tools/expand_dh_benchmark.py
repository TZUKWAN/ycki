#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expand_dh_benchmark.py — DH 基准扩至 300 题（§17.1-17.2）。

从库内真实结构对象确定性生成：
  FACTUAL (100)          单对象事实-结构（系统归属/时间/领域/构成）
  SYNTHESIS (60)         跨区/跨期/综合推理（比较、机制、连续性）
  CRITIQUE (40)          对抗批判（假前提、无证据归因、要求诚实拒答）

每题带 required_object_types / evaluation_dimensions / answer_key_hint。
真实对象名来自 cultural_traditions / cultural_processes / cultural_flows /
hydro_spatial_units / system_memberships，不虚构。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "yangtze" / "benchmarks" / "dh_benchmark_100.yaml"
OUT = ROOT / "yangtze" / "benchmarks" / "dh_benchmark_300.yaml"

DIMS_FULL = ["structural_correctness", "evidence_grounding", "citation_entailment",
             "temporal_coherence", "spatial_coherence", "mechanism_explanation",
             "uncertainty_honesty"]


def load_objects():
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    objs = {"traditions": [], "processes": [], "flows": [], "hydro": [],
            "members": [], "systems": []}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT tradition_name, status FROM cultural_traditions LIMIT 120")
            objs["traditions"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT process_name, status, start_time FROM cultural_processes LIMIT 120")
            objs["processes"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT flow_type, origin, destination, time_range FROM cultural_flows LIMIT 60")
            objs["flows"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT hsu_name, hsu_type FROM hydro_spatial_units LIMIT 60")
            objs["hydro"] = [dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT e.canonical_name AS name, s.system_name AS sys
                           FROM system_memberships m
                           JOIN canonical_entities e ON e.entity_id=m.object_id
                           JOIN cultural_systems s ON s.system_id=m.system_id
                           WHERE m.status='ADMITTED' AND e.merged_into IS NULL LIMIT 120""")
            objs["members"] = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return objs


def main() -> int:
    objs = load_objects()
    questions = []
    n = 100
    sys_of = {m["name"]: m["sys"] for m in objs["members"]}

    # ---- FACTUAL 100 ----
    pool = objs["traditions"] + objs["processes"]
    for i, o in enumerate(pool):
        if len(questions) >= 100:
            break
        name = o.get("tradition_name") or o.get("process_name")
        kind = "CulturalTradition" if "tradition_name" in o else "HistoricalProcess"
        templates = [
            (f"{name}在知识库中归属哪个区域文化系统？其证据链是什么？",
             [kind, "CulturalSystem"], "必须点名系统成员关系并附证据编号"),
            (f"关于{name}，知识库有哪些字段级证据？哪些字段证据不足？",
             [kind], "必须逐字段说明证据覆盖与缺口"),
            (f"{name}的形成与长江水系有何关系？库中有无水系锚点证据？",
             [kind, "HydroSpatialUnit"], "必须区分有证据的水系关联与无证据推断"),
        ]
        q, types, hint = templates[i % 3]
        n += 1
        questions.append({
            "id": f"DH-{n:03d}", "category": "FACTUAL", "question": q,
            "target_systems": [], "required_object_types": types,
            "evidence_requirements": hint,
            "evaluation_dimensions": DIMS_FULL, "difficulty": "MEDIUM",
            "answer_key_hint": {"object": name},
        })

    # ---- SYNTHESIS 60 ----
    flows = objs["flows"]
    for i in range(min(30, max(1, len(flows)))):
        f = flows[i % max(1, len(flows))]
        n += 1
        questions.append({
            "id": f"DH-{n:03d}", "category": "SYNTHESIS",
            "question": f"知识库中『{f.get('origin')}→{f.get('destination')}』的流动反映了怎样的区域互动机制？其路线与载体证据是否充分？",
            "target_systems": [], "required_object_types": ["CulturalFlow", "CulturalProcess"],
            "evidence_requirements": "必须给出起讫、路线、载体及证据编号；路线 UNKNOWN 时必须如实说明",
            "evaluation_dimensions": DIMS_FULL, "difficulty": "HARD",
            "answer_key_hint": {"flow": f"{f.get('origin')}→{f.get('destination')}"},
        })
    pairs = [(t["tradition_name"], p["process_name"]) for t in objs["traditions"][:20]
             for p in objs["processes"][:10]]
    for i, (a, b) in enumerate(pairs[:30]):
        n += 1
        questions.append({
            "id": f"DH-{n:03d}", "category": "SYNTHESIS",
            "question": f"{a}与{b}在知识库中是否存在结构关联（共享实体/过程/水系）？给出关联路径或如实说明无关联证据。",
            "target_systems": [], "required_object_types": ["CulturalTradition", "HistoricalProcess"],
            "evidence_requirements": "必须基于结构对象路径论证，禁止无证据的类比",
            "evaluation_dimensions": DIMS_FULL, "difficulty": "HARD",
        })

    # ---- CRITIQUE 40（对抗批判：假前提/诱导归因） ----
    critiques = []
    for i, o in enumerate(objs["processes"][:10]):
        name = o.get("process_name")
        st = o.get("start_time") or "早期"
        critiques.append(f"有观点认为{name}始于当代而非{st}，请依据库内证据评判该观点。")
    for i, m in enumerate(objs["members"][:15]):
        critiques.append(f"有人断言{m['name']}不属于{m['sys']}，这一断言能否成立？给出结构证据。")
    critiques += [
        "目前知识库的文化流动总量仍然很小。请评估：仅凭现有流动证据，能否支撑『长江文化已形成完整流动网络』的结论？",
        "如果只允许引用 ADMITTED 状态的结构对象，哪些广为流传的长江文化说法在库中其实证据不足？",
        "请指出知识库中证据最薄弱的三个结构性判断，并说明薄弱原因。",
    ]
    for i, q in enumerate(critiques[:40]):
        n += 1
        questions.append({
            "id": f"DH-{n:03d}", "category": "CRITIQUE", "question": q,
            "target_systems": [], "required_object_types": [],
            "evidence_requirements": "必须区分【库内可证】与【库外常识】，禁止用常识冒充库内证据",
            "evaluation_dimensions": DIMS_FULL, "difficulty": "HARD",
        })

    base = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    allq = base["questions"] + questions
    doc = {"version": "dh_benchmark_v2",
           "description": f"长江文化数字人文基准（{len(allq)}题=100原+100事实+60综合+40批判）",
           "total": len(allq), "questions": allq}
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    from collections import Counter
    print("total", len(allq), Counter(q["category"] for q in allq))
    return 0


if __name__ == "__main__":
    sys.exit(main())
