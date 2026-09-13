# -*- coding: utf-8 -*-
"""gap_synthesis.py — 缺口驱动结构综合（§9：Growth 必须含 Structural Synthesis）。

把结构缺口映射为结构综合尝试（类型匹配，§9.4）：
  MISSING_EVIDENCE        → TRADITION 重综合（同名 upsert 重写证据行）
  SINGLE_SOURCE_STRUCTURE → 按对象 kind 重综合（补独立来源）
  MISSING_PROCESS_STAGE   → PROCESS 重综合（重写阶段结构）
  MISSING_CROSS_REGION_LINK → FLOW 合成尝试（硬门禁保护）
  MISSING_SYSTEM_MEMBERSHIP / MISSING_HYDRO_LINK → 非综合路径（memberships/hydro 重建）

复用 synthesize_candidate（证据束 → LLM → 确定性核验 → 准入）。
证据不足只会得到 SKIP/CANDIDATE/REJECT——绝不硬凑。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2

from extensions.v2.research_planner import GAP_TYPE_FIELDS, _expand_terms
from extensions.v2.synthesis import synthesize_candidate

LOG = logging.getLogger("v2.gap_synthesis")


def _target_parts(target_name: str, gap_type: str) -> tuple[str, str]:
    """'TRADITION:都江堰放水节' → (TRADITION, 都江堰放水节)；否则按缺口类型推断。"""
    if ":" in target_name:
        k, n = target_name.split(":", 1)
        if k in ("TRADITION", "PROCESS", "FLOW"):
            return k, n
    mapping = {
        "MISSING_EVIDENCE": "TRADITION",
        "MISSING_PROCESS_STAGE": "PROCESS",
        "MISSING_CROSS_REGION_LINK": "FLOW",
    }
    return mapping.get(gap_type, ""), target_name


def synthesize_for_gap(cur: psycopg2.extensions.cursor, gap: dict[str, Any]) -> dict[str, Any]:
    """按缺口类型做一次结构综合尝试；返回 {attempted, decision, ...}。"""
    known = gap.get("known") or {}
    raw_target = known.get("name") or known.get("_ref") or gap.get("type", "")
    gap_type = gap["type"]
    kind, name = _target_parts(str(raw_target), gap_type)
    if not kind:
        return {"attempted": False,
                "reason": f"gap_type {gap_type} 不走综合路径（membership/hydro 重建处理）"}

    terms = _expand_terms(name)
    for extra in (known.get("systems") or []):
        if isinstance(extra, str) and extra not in terms:
            terms.append(extra)
    seed = {
        "id": f"gap_{str(gap.get('gap_id'))[:8]}",
        "name": name,
        "kind": kind,
        "system": known.get("system") if isinstance(known, dict) else None,
        "terms": terms[:8],
        "fields": GAP_TYPE_FIELDS.get(gap_type) or None,
    }
    try:
        r = synthesize_candidate(cur, seed)
        r["attempted"] = True
        r["gap_type"] = gap_type
        return r
    except Exception as exc:
        cur.connection and cur.connection.rollback()
        return {"attempted": True, "decision": "ERROR",
                "reason": f"{type(exc).__name__}: {exc}"[:200], "gap_type": gap_type}
