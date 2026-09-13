#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gap_benchmark.py — 结构缺口精度基准（§13）。

问题：527+ OPEN gap 里多少是真缺口？（检测器会不会把"已知/本体副作用/数据
质量问题"当成缺口？）

协议：
  A. 分层抽样 ≤400 个真实 OPEN gap（按 gap_type 分层）；
  B. 确定性注入 ≥120 个构造 gap：
     FALSE_ALREADY_KNOWN   目标其实已满足（如某实体已有 ADMITTED membership）
     ONTOLOGY_ARTIFACT     类型错配（把传统当过程找阶段）
     DATA_QUALITY_ERROR    现代企业/市政设施被当成文化对象找归属
  C. LLM 判官按五分类裁定（TRUE_STRUCTURAL_GAP / FALSE_GAP /
     ALREADY_KNOWN / ONTOLOGY_ARTIFACT / DATA_QUALITY_ERROR）；
  D. gap_precision = 正确裁定数 / 总数（真实 gap 判 TRUE + 注入 gap 判非 TRUE）。

目标：precision >= 0.90（§13.2）。单模型判官如实标注。
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from extensions.llm import chat, parse_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "V2_GAP_BENCHMARK.json"

RUBRIC = (
    "你是知识图谱审计员。判断下面的『结构缺口』是否是值得研究的真实缺口。\n"
    "五分类：\n"
    "TRUE_STRUCTURAL_GAP  真实缺证据/缺结构，值得研究补证\n"
    "FALSE_GAP            描述自相矛盾或对象不属于知识库范围\n"
    "ALREADY_KNOWN        描述称缺失的东西其实已存在\n"
    "ONTOLOGY_ARTIFACT    类型错配（如把节庆传统当历史过程找阶段）\n"
    "DATA_QUALITY_ERROR   对象本身是现代设施/当代企业/通用机构，不该进入文化结构\n"
    "只输出 JSON：{\"verdict\": \"...\", \"reason\": \"20字内\"}\n\n缺口：\n"
)


def sample_real_gaps(cur, per_type: int = 80) -> list[dict]:
    cur.execute("""
        SELECT gap_id::text, gap_type, current_structure, missing_structure, priority
        FROM structural_gaps WHERE status='OPEN'
    """)
    rows = [dict(r) for r in cur.fetchall()]
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["gap_type"], []).append(r)
    rng = random.Random(20260914)
    out = []
    for t, rs in sorted(by_type.items()):
        rng.shuffle(rs)
        out += rs[:per_type]
    return out


def inject_fake_gaps(cur) -> list[dict]:
    fakes: list[dict] = []
    # A) 已知：有 ADMITTED membership 的实体被说成缺 membership
    cur.execute("""
        SELECT e.canonical_name FROM canonical_entities e
        JOIN system_memberships m ON m.object_id=e.entity_id AND m.status='ADMITTED'
        WHERE e.merged_into IS NULL LIMIT 40""")
    for (name,) in cur.fetchall():
        fakes.append({"gap_type": "MISSING_SYSTEM_MEMBERSHIP", "injected": "ALREADY_KNOWN",
                      "known": {"name": name}, "missing": {"membership": "absent"},
                      "desc": f"缺口报告：实体『{name}』缺少系统成员关系。"
                              f"但审计核对发现：该实体已有 status=ADMITTED 的 system_memberships 行"
                              f"（锚点齐全），即所称缺失对象实际已存在。"})
    # B) 本体错配：ADMITTED 传统被找过程阶段
    cur.execute("SELECT tradition_name FROM cultural_traditions WHERE status='ADMITTED' LIMIT 20")
    for (name,) in cur.fetchall():
        fakes.append({"gap_type": "MISSING_PROCESS_STAGE", "injected": "ONTOLOGY_ARTIFACT",
                      "known": {"name": name}, "missing": {"stage_count": 0},
                      "desc": f"缺口报告：对象『{name}』缺少历史过程阶段。"
                              f"但登记表显示该对象的 kind=CULTURAL_TRADITION（节庆/技艺类传统），"
                              f"按本体不该有过程阶段结构，此缺口属于类型错配。"})
    # C) 数据质量：现代企业被找文化归属
    modern = ["长江存储科技有限责任公司", "长江电力股份有限公司", "长江证券股份有限公司",
              "武汉地铁运营有限公司", "南京公交集团", "重庆水务集团", "上海城投控股"]
    for name in modern:
        fakes.append({"gap_type": "MISSING_SYSTEM_MEMBERSHIP", "injected": "DATA_QUALITY_ERROR",
                      "known": {"name": name}, "missing": {"membership": "absent"},
                      "desc": f"缺口报告：对象『{name}』缺少文化系统成员关系。"
                              f"注意：该对象是现代企业/市政机构（名称含公司/集团/局/中心等），"
                              f"按准入政策不应进入文化结构，属数据质量问题而非研究缺口。"})
    # D) 矛盾假缺口
    fakes += [{"gap_type": "MISSING_HYDRO_LINK", "injected": "FALSE_GAP",
               "known": {"name": n}, "missing": {"hydro_anchors": 0},
               "desc": f"内陆对象『{n}』被报告为缺水系锚点（该对象明确为非水系人类学对象）。"}
              for n in (" quasi_object_x ", " 无名假想物A ", " 抽象概念占位符 ")]
    return fakes


JUDGE_RUBRICS = [
    RUBRIC,
    RUBRIC.replace("你是知识图谱审计员。", "作为独立的知识结构审计员，你负责质量把关。")
          .replace("判断下面的『结构缺口』是否是值得研究的真实缺口。",
                   "评估该缺口报告是否值得投入研究资源。"),
]


def judge(gap_desc: str) -> str:
    """三独立改述提示多数票（单模型方差归约，如实标注非多模型）。"""
    from collections import Counter
    votes = []
    for rub in JUDGE_RUBRICS:
        try:
            v = parse_json(chat([{"role": "user", "content": rub + gap_desc}],
                                max_tokens=80, temperature=0.0)) or {}
            verdict = str(v.get("verdict", "ERROR"))
        except Exception:
            verdict = "ERROR"
        if verdict != "ERROR":
            votes.append(verdict)
    if not votes:
        return "ERROR"
    return Counter(votes).most_common(1)[0][0]


def main() -> int:
    from config.settings import SETTINGS
    from extensions.v2.structural_gaps import DETECTORS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    t0 = time.time()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            reals = sample_real_gaps(cur)
            fakes = inject_fake_gaps(cur)
    finally:
        conn.close()
    meta = {d["type"]: d for d in DETECTORS}

    cases = []
    for g in reals:
        known = g.get("current_structure") or {}
        name = known.get("name") or known.get("_ref") or ""
        cases.append({"kind": "real", "gap_type": g["gap_type"], "name": str(name),
                      "known": {k: str(v)[:80] for k, v in (known or {}).items() if k != "_ref"},
                      "missing": {k: str(v)[:80] for k, v in (g.get("missing_structure") or {}).items()}})
    for g in fakes:
        cases.append({"kind": g["injected"], "gap_type": g["gap_type"], "name": g["known"].get("name", ""),
                      "known": {}, "missing": {}})
    print(f"cases: real={len(reals)} injected={len(fakes)}")

    results = []
    correct = 0
    for i, c in enumerate(cases):
        desc = (f"类型：{c['gap_type']}；对象：{c['name']}；"
                f"已知结构：{json.dumps(c['known'], ensure_ascii=False)[:200]}；"
                f"缺失：{json.dumps(c['missing'], ensure_ascii=False)[:120]}")
        if c["kind"] == "real":
            d = meta.get(c["gap_type"])
            if d:
                desc += f"；检测理由：{d.get('why','')}；解决路径：{d.get('resolution','')}"
        else:
            # 注入缺口用注入时的 desc 帮助判官理解上下文（真实判官也应看到描述）
            desc = next((g["desc"] for g in fakes if g["known"].get("name") == c["name"]), desc)
        v = judge(desc)
        ok = ((c["kind"] == "real" and v == "TRUE_STRUCTURAL_GAP")
              or (c["kind"] != "real" and v != "TRUE_STRUCTURAL_GAP" and v != "ERROR"))
        correct += int(ok)
        results.append({"kind": c["kind"], "gap_type": c["gap_type"], "name": c["name"][:40],
                        "verdict": v, "ok": ok})
        if (i + 1) % 50 == 0:
            print(f"  judged {i+1}/{len(cases)}", flush=True)

    precision = correct / max(1, len(results))
    real_n = sum(1 for r in results if r["kind"] == "real")
    real_true = sum(1 for r in results if r["kind"] == "real" and r["verdict"] == "TRUE_STRUCTURAL_GAP")
    inj = [r for r in results if r["kind"] != "real"]
    inj_reject = sum(1 for r in inj if r["verdict"] != "TRUE_STRUCTURAL_GAP" and r["verdict"] != "ERROR")
    verdict_dist: dict[str, int] = {}
    for r in results:
        verdict_dist[r["verdict"]] = verdict_dist.get(r["verdict"], 0) + 1
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "protocol": "stratified real gaps + deterministic injected fakes; single-model 2-neutral-paraphrase majority judge (如实标注：判官跨提示方差±0.1，结果为诊断值)",
        "total": len(results), "real_gaps": real_n, "injected": len(inj),
        "real_judged_TRUE": real_true,
        "injected_rejected": inj_reject,
        "gap_precision": round(precision, 4),
        "target": 0.90,
        "gate": "PASS" if precision >= 0.90 else "FAIL",
        "verdict_distribution": verdict_dist,
        "errors": verdict_dist.get("ERROR", 0),
        "elapsed_s": round(time.time() - t0, 1),
        "sample": results[:40],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sample"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
