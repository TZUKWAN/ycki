#!/usr/bin/env python3
"""membership_benchmark.py — Membership LLM 判官基准（goal §21-§23）。

从 1959 条 system 成员行分层抽样（全部规则 ADMITTED + 随机 CANDIDATE），
用 LLM 按 §19 标准独立判定（判官不接触规则结论），度量规则与判官的一致率：

  admitted_precision  规则 ADMITTED 中被判官认可 ADMIT 的比例（目标 >=0.97）
  candidate_uphold    规则 CANDIDATE 中判官同样不给 ADMIT 的比例

判官输出 JSON：{"judgment": "ADMIT|CANDIDATE|REJECT", "reason": "..."}
结果写 reports/V2_MEMBERSHIP_BENCHMARK.json，分歧明细供审计。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.llm import chat, parse_json

REPORT = ROOT / "reports" / "V2_MEMBERSHIP_BENCHMARK.json"
N_CANDIDATE_SAMPLE = 108


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def load_sample() -> list[dict[str, Any]]:
    conn = psycopg2.connect(dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT m.membership_id::text AS mid, m.status AS rule_status,
                       m.anchor_count, m.region, m.spatial_anchor, m.temporal_anchor,
                       m.domain_anchor, m.process_anchor,
                       e.canonical_name, e.entity_type,
                       substr(COALESCE(e.description,''),1,300) AS description,
                       s.system_name, r.region_name, r.provinces
                FROM system_memberships m
                JOIN canonical_entities e ON m.object_id = e.entity_id
                JOIN cultural_systems s ON m.system_id = s.system_id
                LEFT JOIN cultural_regions r ON r.entity_id = s.system_id
                WHERE m.system_id IS NOT NULL AND e.merged_into IS NULL
            """)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    admitted = [r for r in rows if r["rule_status"] == "ADMITTED"]
    candidate = [r for r in rows if r["rule_status"] != "ADMITTED"]
    random.seed(20260913)
    sample = admitted + random.sample(candidate, min(N_CANDIDATE_SAMPLE, len(candidate)))
    return sample


def judge(case: dict[str, Any]) -> dict[str, Any] | None:
    def anchor_brief(a: Any) -> str:
        if not a:
            return "无"
        if isinstance(a, dict):
            if "admitted_events" in a:
                return f"{a.get('event_count', '?')}条事件"
            if "timespans" in a:
                return f"{len(a['timespans'])}条时间"
            if "domains" in a:
                return "、".join(a["domains"][:3])
            if "province_text" in a:
                return a.get("province_text", "")
        return "有"
    provinces = "、".join(case["provinces"] or []) if case["provinces"] else "未知"
    prompt = (
        "你是文化知识图谱的成员关系审核员。判断该实体是否应被 ADMITTED（正式接纳）到所列文化系统。\n"
        f"实体：{case['canonical_name']}（类型 {case['entity_type']}）\n"
        f"描述：{case['description'] or '（无）'}\n"
        f"候选系统：{case['system_name']}（文化区域 {case['region_name'] or '未定'}；地理范围 {provinces}）\n"
        f"锚点摘要：空间={anchor_brief(case['spatial_anchor'])}; 时间={anchor_brief(case['temporal_anchor'])}; "
        f"领域={anchor_brief(case['domain_anchor'])}; 过程={anchor_brief(case['process_anchor'])}\n\n"
        "标准：仅有地理关联（如『位于某省』）不得 ADMIT；需要至少两类相互独立的锚点证明其"
        "文化成员身份（创作/事件/制度/信仰/技艺与该系统的实质联系）。证据明显矛盾可 REJECT。\n"
        '只输出 JSON：{"judgment": "ADMIT|CANDIDATE|REJECT", "reason": "不超过40字"}'
    )
    try:
        text = chat([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.0)
        return parse_json(text)
    except Exception as exc:
        return {"judgment": "ERROR", "reason": str(exc)[:100]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sample = load_sample()
    print(f"样本量: {len(sample)}（ADMITTED {sum(1 for s in sample if s['rule_status']=='ADMITTED')}）")
    results = []
    admit_total = admit_upheld = 0
    cand_total = cand_upheld = 0
    errors = 0
    for i, case in enumerate(sample):
        j = judge(case)
        judgment = (j or {}).get("judgment", "ERROR")
        if judgment == "ERROR":
            errors += 1
        if case["rule_status"] == "ADMITTED":
            admit_total += 1
            if judgment == "ADMIT":
                admit_upheld += 1
        else:
            cand_total += 1
            if judgment in ("CANDIDATE", "REJECT"):
                cand_upheld += 1
        results.append({"mid": case["mid"], "name": case["canonical_name"],
                        "system": case["system_name"], "rule": case["rule_status"],
                        "judge": judgment, "reason": (j or {}).get("reason", "")})
        if (i + 1) % 25 == 0:
            print(f"  ... {i+1}/{len(sample)}  admitted_precision={admit_upheld/max(admit_total,1):.3f}")
    report = {
        "sample_size": len(sample),
        "rule_admitted": admit_total,
        "judge_admit_uphold": admit_upheld,
        "admitted_precision": round(admit_upheld / admit_total, 4) if admit_total else None,
        "rule_candidate": cand_total,
        "judge_candidate_uphold": cand_upheld,
        "candidate_uphold_rate": round(cand_upheld / cand_total, 4) if cand_total else None,
        "judge_errors": errors,
        "note": "单模型(Qwen3.6-35B-A3B)判官一致率，非多模型金标；分歧明细见 disputes",
        "disputes": [r for r in results if (r["rule"] == "ADMITTED") != (r["judge"] == "ADMIT")],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "disputes"}, ensure_ascii=False, indent=2))
    print(f"分歧数: {len(report['disputes'])}  报告: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
