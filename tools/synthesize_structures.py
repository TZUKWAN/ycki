#!/usr/bin/env python3
"""synthesize_structures.py — Golden Case 结构合成驱动器（goal §32-§50）。

读取 yangtze/schema/golden_case_seeds.yaml 的真实候选，对每个候选：
  证据束（跨文档聚合）→ LLM 合成 → 确定性证据核验 → 准入 → 写库。
每个候选独立事务：单个失败只回滚该候选，不污染其他结果（可安全重放，幂等 upsert）。

用法：
  python tools/synthesize_structures.py --only seed_huguang_tian_sichuan   # 冒烟
  python tools/synthesize_structures.py --all                              # 全量
  python tools/synthesize_structures.py --all --dry-run                    # 只建束不调用 LLM
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.v2.evidence_bundle import build_bundle
from extensions.v2.synthesis import synthesize_candidate

SEEDS_PATH = ROOT / "yangtze" / "schema" / "golden_case_seeds.yaml"
MIGRATION = ROOT / "deploy" / "sql" / "008_synthesis_constraints.sql"
REPORT = ROOT / "reports" / "V2_GOLDEN_CASE_SYNTHESIS.json"


def dsn() -> str:
    from config.settings import SETTINGS
    return SETTINGS.pg_dsn


def ensure_constraints(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text(encoding="utf-8"))
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--only", metavar="SEED_ID")
    ap.add_argument("--dry-run", action="store_true", help="只聚合证据束并输出统计，不调用 LLM 不写库")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    seeds_doc = yaml.safe_load(SEEDS_PATH.read_text(encoding="utf-8"))
    seeds = seeds_doc.get("candidates") or []
    if args.only:
        seeds = [s for s in seeds if s["id"] == args.only]
        if not seeds:
            print(f"seed 不存在: {args.only}")
            return 2

    conn = psycopg2.connect(dsn())
    results: list[dict[str, Any]] = []
    try:
        ensure_constraints(conn)
        for seed in seeds:
            t0 = time.time()
            try:
                if args.dry_run:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                        b = build_bundle(cur, seed)
                        results.append({"seed": seed["id"], "name": seed["name"],
                                        "kind": seed["kind"], "bundle": b.summary()})
                    conn.rollback()
                else:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                        r = synthesize_candidate(cur, seed)
                        r["elapsed_s"] = round(time.time() - t0, 1)
                        results.append(r)
                    conn.commit()
                last = results[-1]
                print(f"[OK] {seed['id']:32s} {last.get('decision', last.get('bundle', {}).get('distinct_resources', '?'))}"
                      f"  resources={last.get('bundle', {}).get('distinct_resources', last.get('bundle', {}).get('distinct_resources'))}"
                      f"  {round(time.time() - t0, 1)}s")
            except Exception as exc:
                conn.rollback()
                results.append({"seed": seed["id"], "name": seed["name"], "kind": seed["kind"],
                                "decision": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:300]})
                print(f"[ERR] {seed['id']}: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        conn.close()

    REPORT.write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                  "results": results}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    decisions: dict[str, int] = {}
    for r in results:
        d = r.get("decision", "?")
        decisions[d] = decisions.get(d, 0) + 1
    print("\n== 决定分布 ==", json.dumps(decisions, ensure_ascii=False))
    print(f"报告: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
