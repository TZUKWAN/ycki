# -*- coding: utf-8 -*-
"""CONTESTED claims 审核工具：导出审核报告 + LLM 仲裁建议 + 应用裁决。

用法：
  python tools/review_contested.py export            # 生成 reports/CONTESTED_REVIEW.md
  python tools/review_contested.py suggest --limit 20  # LLM 给出仲裁建议（写回 detail）
  python tools/review_contested.py apply --claim <id> --winner <claim_id|--both|--later>
      # 裁决：胜者保持 ADMITTED，败者 SUPERSEDED/CONTESTED 保持
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from config.settings import SETTINGS
from extensions.llm import chat, parse_json


def conn():
    return psycopg2.connect(SETTINGS.pg_dsn)


def fetch_conflict_pairs(limit=200):
    """CONTESTED 的冲突对：同 subject+predicate 的 ADMITTED 对手 claim。"""
    with conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.claim_id, c.subject_id, c.predicate_id,
                   s.canonical_name AS subject, o.canonical_name AS object,
                   c.confidence, e.quote_span, r.title AS res_title,
                   src.authority_level
            FROM claims c
            JOIN canonical_entities s ON s.entity_id=c.subject_id
            JOIN canonical_entities o ON o.entity_id=c.object_id
            LEFT JOIN evidence e ON e.claim_id=c.claim_id
            LEFT JOIN resources r ON r.resource_id=e.resource_id
            LEFT JOIN sources src ON src.source_id=e.source_id
            WHERE c.status='CONTESTED'
            ORDER BY c.confidence NULLS LAST, c.created_at DESC LIMIT %s""", (limit,))
        contested = [dict(r) for r in cur.fetchall()]
        pairs = []
        for cc in contested:
            cur.execute("""
                SELECT c2.claim_id, o2.canonical_name AS object, e2.quote_span,
                       r2.title AS res_title, src2.authority_level
                FROM claims c2
                JOIN canonical_entities o2 ON o2.entity_id=c2.object_id
                LEFT JOIN evidence e2 ON e2.claim_id=c2.claim_id
                LEFT JOIN resources r2 ON r2.resource_id=e2.resource_id
                LEFT JOIN sources src2 ON src2.source_id=e2.source_id
                WHERE c2.subject_id=%s AND c2.predicate_id=%s
                  AND c2.status='ADMITTED' AND c2.claim_id<>%s
                LIMIT 3""",
                (cc["subject_id"], cc["predicate_id"], cc["claim_id"]))
            others = [dict(x) for x in cur.fetchall()]
            pairs.append({**cc, "others": others})
    return pairs


def export_report(pairs):
    out = ROOT / "reports" / "CONTESTED_REVIEW.md"
    lines = ["# CONTESTED Claims 审核报告", "",
             f"> 生成时间 {datetime.now():%Y-%m-%d %H:%M} · 共 {len(pairs)} 条", ""]
    for i, p in enumerate(pairs, 1):
        lines.append(f"## {i}. {p['subject']} --{p['predicate_id']}--> {p['object']}")
        lines.append(f"- claim_id: `{p['claim_id']}`  置信: {p.get('confidence')}")
        lines.append(f"- 本文证据: 「{(p.get('quote_span') or '')[:100]}」")
        lines.append(f"- 来源: {p.get('res_title') or '—'} [{p.get('authority_level')}]")
        for o in p.get("others", [])[:3]:
            lines.append(f"- 冲突对手 `{o['claim_id'][:8]}`: {o['object']} "
                         f"「{(o.get('quote_span') or '')[:80]}」 "
                         f"[{o.get('authority_level')}]")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告: {out}（{len(pairs)} 条）")


def suggest(limit=20):
    pairs = fetch_conflict_pairs(limit)
    c = conn()
    with c.cursor() as cur:
        for p in pairs[:limit]:
            if not p.get("others"):
                continue
            other = p["others"][0]
            prompt = (
                "两条关于长江文化的历史主张相互冲突，请基于史料常识仲裁。\n"
                f"主张A：{p['subject']} --{p['predicate_id']}--> {p['object']}\n"
                f"A的原文证据：「{(p.get('quote_span') or '')[:150]}」（来源权威 {p.get('authority_level')}）\n"
                f"主张B：{p['subject']} --{p['predicate_id']}--> {other['object']}\n"
                f"B的原文证据：「{(other.get('quote_span') or '')[:150]}」（来源权威 {other.get('authority_level')}）\n"
                "输出 JSON：{\"verdict\":\"A|B|both|unsure\",\"reason\":\"40字内\"}\n"
                "说明：A/B 都可能成立（不同时期/口径），both 表示并存为 CONDITIONAL。")
            raw = chat([{"role": "user", "content": prompt}], max_tokens=300)
            v = parse_json(raw) or {"verdict": "unsure"}
            cur.execute("""UPDATE claim_admissions
                           SET detail = detail || %s::jsonb
                           WHERE claim_id=%s AND stage='conflict_detection'""",
                        (json.dumps({"review_suggestion": v}, ensure_ascii=False),
                         p["claim_id"]))
            print(f"  {p['subject'][:14]}--{p['predicate_id']}--> {p['object'][:14]}"
                  f" => {v.get('verdict')} | {v.get('reason', '')[:40]}")
    c.commit()
    c.close()


def apply(claim_id: str, winner: str):
    c = conn()
    with c.cursor() as cur:
        if winner == "--both":
            cur.execute("UPDATE claims SET status='CONDITIONAL' WHERE claim_id=%s OR "
                        "status='CONTESTED' AND subject_id=(SELECT subject_id FROM claims "
                        "WHERE claim_id=%s) AND predicate_id=(SELECT predicate_id FROM "
                        "claims WHERE claim_id=%s)", (claim_id, claim_id, claim_id))
            print("双方并存为 CONDITIONAL")
        else:
            cur.execute("UPDATE claims SET status='SUPERSEDED' WHERE claim_id=%s",
                        (winner,))
            cur.execute("UPDATE claims SET status='ADMITTED' WHERE claim_id=%s",
                        (claim_id,))
            print(f"胜者 {claim_id} ADMITTED；败者 SUPERSEDED")
    c.commit()
    c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    sg = sub.add_parser("suggest")
    sg.add_argument("--limit", type=int, default=20)
    ap2 = sub.add_parser("apply")
    ap2.add_argument("--claim", required=True)
    ap2.add_argument("--winner", required=True)
    a = ap.parse_args()
    if a.cmd == "export":
        export_report(fetch_conflict_pairs())
    elif a.cmd == "suggest":
        suggest(a.limit)
    elif a.cmd == "apply":
        apply(a.claim, a.winner)
