#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dh_answer.py — 数字人文基准答题引擎（goal §84-§87）。

结构先行（§86）：每个问题先装配结构对象（系统树/水系/分期+演化模式/传统/
过程/流动/成员关系/解释/证据引文），再约束 LLM 仅依据装配对象生成回答——
不是纯 RAG 检索拼凑。

自动评估（§87，确定性代理指标，诚实标注为代理）：
  structural_correctness  回答是否引用了装配结构对象（≥2 个对象名）
  evidence_grounding      回答是否携带有效证据引用 [EV:n]
  temporal_coherence      回答中的年代 token 是否存在于装配时间数据
  spatial_coherence       回答中的地名 token 是否存在于装配空间数据
  mechanism_explanation   过程/流动/演化类问题是否给出机制表述
  uncertainty_honesty     证据不足的必要维度是否明确声明（如 flows=0 时的流动问题）
  citation_completeness   关键断言是否附引用标记

用法：python tools/dh_answer.py [--limit N] [--only DH-001]
输出：reports/V2_DH_BENCHMARK_ANSWERS.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.llm import chat  # noqa: E402
from extensions.v2.evidence_bundle import Bundle, build_bundle  # noqa: E402

BENCH = ROOT / "yangtze" / "benchmarks" / "dh_benchmark_300.yaml"
if not BENCH.exists():
    BENCH = ROOT / "yangtze" / "benchmarks" / "dh_benchmark_100.yaml"
OUT = ROOT / "reports" / "V2_DH_BENCHMARK_ANSWERS.json"

DATE_RE = re.compile(r"(公元前?\d+|\d{3,4}年?|[夏商周秦汉]|隋唐|宋元|明清|晚清|民国)")
STOP = set("的什么哪些如何怎样是否为什么怎样样在了是与和及对由从被把按照通过之一其中这些那些可以能够".split())


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def extract_terms(question: str, target_systems: list[str]) -> list[str]:
    terms = [t for t in re.split(r"[？?，,、/（）()\s]+", question)
             if t and t not in STOP and len(t) >= 2]
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:12]


def assemble(cur, q: dict[str, Any], terms: list[str]) -> dict[str, Any]:
    a: dict[str, Any] = {"systems": [], "hydro": [], "phases": [], "traditions": [],
                         "processes": [], "flows": [], "memberships": [], "interpretations": [],
                         "evidence": []}

    def hits(text: str | None) -> bool:
        return bool(text) and any(t in text for t in terms)

    sys_names = ",".join(q.get("target_systems") or [])
    if sys_names:
        cur.execute("""SELECT system_name, system_level, description FROM cultural_systems
                       WHERE system_name = ANY(%s)""",
                    ([qname for qname in re.split(r"[,\s]+", sys_names) if qname],))
        a["systems"] = [dict(r) for r in cur.fetchall()]

    like = " OR ".join(["COALESCE(description,'') ILIKE %s OR hsu_name ILIKE %s"] * len(terms))
    params: list[Any] = []
    for t in terms:
        params += [f"%{t}%", f"%{t}%"]
    cur.execute(f"SELECT hsu_name, hsu_type, description FROM hydro_spatial_units WHERE {like} LIMIT 12", params)
    a["hydro"] = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT p.phase_name, p.macro_phase,
                          array_agg(DISTINCT m.pattern_code) FILTER (WHERE m.pattern_code IS NOT NULL) AS patterns
                   FROM historical_phases p
                   LEFT JOIN historical_phase_patterns hpp ON hpp.phase_id=p.phase_id
                   LEFT JOIN macro_evolution_patterns m ON m.pattern_id=hpp.pattern_id
                   GROUP BY p.phase_id, p.phase_name, p.macro_phase
                   ORDER BY p.phase_id""")
    a["phases"] = [dict(r) for r in cur.fetchall()]

    tlike = " OR ".join(["(tradition_name ILIKE %s OR COALESCE(description,'') ILIKE %s "
                         "OR COALESCE(origin,'') ILIKE %s)"] * len(terms))
    tparams: list[Any] = []
    for t in terms:
        tparams += [f"%{t}%", f"%{t}%", f"%{t}%"]
    cur.execute(f"""SELECT tradition_name, status, origin, description FROM cultural_traditions
                    WHERE {tlike} LIMIT 8""", tparams)
    a["traditions"] = [dict(r) for r in cur.fetchall()]

    plike = " OR ".join(["(process_name ILIKE %s OR COALESCE(description,'') ILIKE %s "
                         "OR COALESCE(mechanisms,'') ILIKE %s)"] * len(terms))
    cur.execute(f"""SELECT process_name, status, start_time, end_time, origin_region,
                           destination_region, mechanisms FROM cultural_processes
                    WHERE {plike} LIMIT 8""", tparams)
    a["processes"] = [dict(r) for r in cur.fetchall()]

    flike = " OR ".join(["(flow_type ILIKE %s OR COALESCE(content,'') ILIKE %s)"] * len(terms))
    fparams: list[Any] = []
    for t in terms:
        fparams += [f"%{t}%", f"%{t}%"]
    cur.execute(f"""SELECT flow_type, origin, destination, content, time_range FROM cultural_flows
                    WHERE {flike} LIMIT 6""", fparams)
    a["flows"] = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT e.canonical_name, s.system_name, m.status, m.anchor_count
                   FROM system_memberships m
                   JOIN canonical_entities e ON e.entity_id=m.object_id
                   JOIN cultural_systems s ON s.system_id=m.system_id
                   WHERE m.system_id IS NOT NULL AND m.status='ADMITTED'
                     AND e.canonical_name !~ '(人民政府|办公室|局$|委员会|公司|集团|中心$)'
                   ORDER BY m.anchor_count DESC LIMIT 12""")
    a["memberships"] = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT statement, knowledge_type, status FROM interpretations
                   WHERE status IN ('ADMITTED','SUPPORTED') LIMIT 6""")
    a["interpretations"] = [dict(r) for r in cur.fetchall()]

    seed = {"id": q["id"], "name": q["question"], "kind": "QUESTION", "terms": terms}
    b: Bundle = build_bundle(cur, seed, max_quotes=18)
    a["evidence"] = [{"id": f"EV{i}", "quote": (qq["quote_span"] or "")[:260],
                      "source": qq.get("title") or qq.get("source_domain") or ""}
                     for i, qq in enumerate(b.quotes)]
    return a


def prompt_for(q: dict, a: dict[str, Any]) -> str:
    def j(name: str, rows: list[dict], fields: list[str]) -> str:
        if not rows:
            return f"{name}:（库中暂无）\n"
        lines = [f"{name}:"]
        for r in rows[:12]:
            lines.append("  - " + " | ".join(f"{f}={r.get(f)}" for f in fields if r.get(f)))
        return "\n".join(lines) + "\n"

    ev = "\n".join(f"[{e['id']}] {e['quote']}（{e['source']}）" for e in a["evidence"]) or "（无）"
    return (
        f"你是长江文化知识基础设施。回答研究问题必须【仅依据】下面装配的结构对象与证据，"
        f"不得引入未列出的事实；证据不足的部分明确写“证据不足”。\n"
        f"证据标记格式硬性要求：只能写 [EV:数字]（如 [EV:0]、[EV:3]，数字=证据引文行首编号）。"
        f"严禁把对象名或文字放进 EV 标记（[EV:历史分期] 属伪造引用）。每个关键断言末尾必须附 [EV:数字]。\n\n"
        f"研究问题（{q['category']}）：{q['question']}\n\n"
        + j("文化系统", a["systems"], ["system_name", "description"])
        + j("水系空间", a["hydro"], ["hsu_name", "hsu_type", "description"])
        + j("历史分期（含演化模式）", a["phases"], ["phase_name", "patterns"])
        + j("文化传统", a["traditions"], ["tradition_name", "status", "description"])
        + j("文化过程", a["processes"], ["process_name", "status", "start_time", "end_time", "mechanisms"])
        + j("文化流动", a["flows"], ["flow_type", "origin", "destination", "content"])
        + j("成员关系（样例）", a["memberships"], ["canonical_name", "system_name", "status"])
        + j("结构推断", a["interpretations"], ["statement", "status"])
        + f"\n证据引文：\n{ev}\n\n"
        "用 300 字以内作答，格式强制：第一行必须为『结构对象：<从上列对象中点名至少3个，顿号分隔>』；"
        "然后给结构叙述（构成/阶段/机制）；关键断言末尾附 [EV:编号]；"
        "最后一行必须为『不确定性：<缺什么证据>』。不得列出装配对象之外的事实。"
    )


def evaluate(q: dict, a: dict[str, Any], answer: str) -> dict[str, Any]:
    """真评估：claim 分解 + 逐断言蕴含（§3.5，替代旧代理指标）。"""
    from extensions.v2.dh_eval import evaluate_answer
    return evaluate_answer(q["question"], q["category"], a, answer)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    doc = yaml.safe_load(BENCH.read_text(encoding="utf-8"))
    questions = doc["questions"]
    if args.only:
        questions = [x for x in questions if x["id"] == args.only]
    questions = questions[:args.limit]

    conn = psycopg2.connect(dsn())
    results = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            for i, q in enumerate(questions):
                terms = extract_terms(q["question"], q.get("target_systems") or [])
                a = assemble(cur, q, terms)
                prompt = prompt_for(q, a)
                try:
                    answer = chat([{"role": "user", "content": prompt}],
                                  max_tokens=900, temperature=0.2)
                except Exception as exc:
                    answer = f"生成失败: {type(exc).__name__}"
                ev = evaluate(q, a, answer)
                results.append({"id": q["id"], "category": q["category"],
                                "question": q["question"], "answer": answer, **ev})
                print(f"[{i+1}/{len(questions)}] {q['id']} score={ev['score']}")
    finally:
        conn.close()

    scores = [r["score"] for r in results]
    dim_ok: dict[str, int] = {}
    for r in results:
        for k, ok in r["checks"].items():
            dim_ok[k] = dim_ok.get(k, 0) + (1 if ok else 0)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "answered": len(results),
        "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
        "dimension_pass_rate": {k: round(v / len(results), 3) for k, v in dim_ok.items()},
        "note": "真评估（§3.5）：claim 分解 + 逐断言蕴含 + 假引用拒绝 + 空间硬事实门；judge=同一模型严格提示（单一模型，非多模型金标）",
        "results": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
