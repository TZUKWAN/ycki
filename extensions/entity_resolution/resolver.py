# -*- coding: utf-8 -*-
"""Phase 6：Entity Resolution —— 候选实体 → Canonical Entity（宁可分裂不错误合并）。

四级漏斗（规范名表优先的设计原则，Graphiti/KAG 借鉴）：
1. exact：normalized_name+type 完全一致 → 合并
2. alias：alias 表命中 → 合并
3. embedding：同类型候选名嵌入相似度 ≥0.92 自动合并
4. llm：0.80–0.92 交 LLM 裁决；verdict != same → UNRESOLVED（保持分裂）
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, embed, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.er")

AUTO_MERGE = 0.92
LLM_BAND = (0.80, 0.92)


def resolve(candidate: dict[str, Any], conn) -> dict[str, Any]:
    """解析单个候选实体，落 entity_resolutions 并更新 candidate。"""
    with conn.cursor() as cur:
        cur.execute("SELECT entity_id FROM canonical_entities WHERE canonical_name=%s "
                    "AND entity_type=%s AND status='ACTIVE'",
                    (candidate["normalized_name"], candidate["entity_type"]))
        row = cur.fetchone()
    if row:
        return _finish(candidate, row[0], "exact", 1.0, "标准名+类型完全一致", conn)

    alias_id = _alias_lookup(candidate, conn)
    if alias_id:
        return _finish(candidate, alias_id, "alias", 0.95, "别名表命中", conn)

    emb = _embedding_lookup(candidate, conn)
    if emb:
        return emb              # 已含 LLM 裁决后的结果

    return _create_new(candidate, conn)


def _alias_lookup(candidate: dict[str, Any], conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT a.entity_id FROM entity_aliases a
                       JOIN canonical_entities c ON c.entity_id=a.entity_id
                       WHERE a.normalized_alias=%s AND c.entity_type=%s AND c.status='ACTIVE'
                       LIMIT 1""", (candidate["normalized_name"], candidate["entity_type"]))
        row = cur.fetchone()
    return row[0] if row else None


def _embedding_lookup(candidate: dict[str, Any], conn) -> dict[str, Any] | None:
    """同类型 Canonical 实体嵌入相似度匹配；高置信自动合并，中置信 LLM 裁决。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT entity_id, canonical_name, COALESCE(description,'')
                       FROM canonical_entities
                       WHERE entity_type=%s AND status='ACTIVE' LIMIT 500""",
                    (candidate["entity_type"],))
        pool = cur.fetchall()
    if not pool:
        return None
    try:
        vecs = embed([candidate["surface_name"]] + [f"{n} {d}" for _, n, d in pool])
    except Exception as exc:
        log.warning("embedding failed: %s", exc)
        return None
    import math
    q = vecs[0]
    best_id, best_name, best_desc, best_score = None, "", "", 0.0
    for (eid, name, desc), v in zip(pool, vecs[1:]):
        dot = sum(a * b for a, b in zip(q, v))
        score = dot / (math.sqrt(sum(a * a for a in q)) * math.sqrt(sum(b * b for b in v)) or 1)
        if score > best_score:
            best_id, best_name, best_desc, best_score = eid, name, desc, score
    if best_id is None:
        return None

    if best_score >= AUTO_MERGE:
        return _finish(candidate, best_id, "embedding", best_score,
                       f"嵌入相似度 {best_score:.2f} 高置信", conn)
    if best_score >= LLM_BAND[0]:
        verdict = _llm_adjudicate(candidate["surface_name"], candidate.get("description", ""),
                                  candidate["entity_type"], best_name, best_desc)
        if verdict.get("verdict") == "same":
            return _finish(candidate, best_id, "llm", best_score,
                           f"LLM裁决same: {verdict.get('reason', '')[:80]}", conn)
        reason = verdict.get("verdict", "unsure")
        return _finish_unresolved(candidate, best_score, f"LLM裁决{reason}", conn)
    return None      # 低于阈值 → 新实体


def _llm_adjudicate(name_a: str, desc_a: str, etype: str, name_b: str, desc_b: str) -> dict:
    prompt = PROMPTS["entity_resolution_v1"].format(
        name_a=name_a, type_a=etype, desc_a=desc_a[:150],
        name_b=name_b, type_b=etype, desc_b=desc_b[:150])
    raw = chat([{"role": "user", "content": prompt}], max_tokens=300)
    return parse_json(raw) or {"verdict": "unsure", "reason": "解析失败"}


def _finish(candidate: dict[str, Any], entity_id: str, method: str,
            score: float, reason: str, conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("""UPDATE candidate_entities
                       SET resolved_entity_id=%s, resolution_status='RESOLVED_EXISTING'
                       WHERE candidate_id=%s""", (entity_id, candidate["candidate_id"]))
        cur.execute(
            """INSERT INTO entity_resolutions
               (candidate_id, matched_entity_id, method, score, reason,
                model, prompt_version, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'MERGED')""",
            (candidate["candidate_id"], entity_id, method, score, reason,
             SETTINGS.llm_model, SETTINGS.prompt_resolution))
        cur.execute(
            """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
               VALUES ('candidate_entity', %s, 'resolved', 'entity_resolution', %s)""",
            (candidate["candidate_id"],
             json.dumps({"entity_id": str(entity_id), "method": method, "score": score},
                        ensure_ascii=False)))
    conn.commit()
    return {"status": "MERGED", "entity_id": entity_id, "method": method}


def _finish_unresolved(candidate: dict[str, Any], score: float, reason: str, conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO entity_resolutions
               (candidate_id, method, score, reason, model, prompt_version, status)
               VALUES (%s,'llm',%s,%s,%s,%s,'UNRESOLVED')""",
            (candidate["candidate_id"], score, reason,
             SETTINGS.llm_model, SETTINGS.prompt_resolution))
    conn.commit()
    log.info("unresolved candidate %s (%.2f): %s",
             candidate["surface_name"], score, reason)
    return {"status": "UNRESOLVED"}


def _create_new(candidate: dict[str, Any], conn) -> dict[str, Any]:
    import hashlib
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO canonical_entities (canonical_name, entity_type, description)
               VALUES (%s,%s,%s) RETURNING entity_id""",
            (candidate["surface_name"], candidate["entity_type"], candidate.get("description")))
        eid = cur.fetchone()[0]
        cur.execute("""UPDATE candidate_entities
                       SET resolved_entity_id=%s, resolution_status='NEW'
                       WHERE candidate_id=%s""", (eid, candidate["candidate_id"]))
        cur.execute(
            """INSERT INTO entity_resolutions
               (candidate_id, matched_entity_id, method, score, reason, status)
               VALUES (%s,%s,'exact',1.0,'无匹配，新建 Canonical 实体','NEW')""",
            (candidate["candidate_id"], eid))
    conn.commit()
    return {"status": "NEW", "entity_id": eid}
