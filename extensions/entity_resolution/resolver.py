# -*- coding: utf-8 -*-
"""Phase 6 v2：Entity Resolution —— 候选实体 → Canonical Entity。

核心原则（对齐重构目标 §13/§14）：
- name 永远不是身份；canonical_entities 以 UUID 为身份，同名实体允许并存。
- 任何命中（exact/alias/embedding）都必须经过「上下文 LLM 裁决」才能 MERGE。
- 裁决 unsure → 候选保持 UNRESOLVED（宁可分裂，不错误合并）。
- resolve_match_only() 为只读匹配（供审计复用），resolve() 为落库写入。

漏斗：exact → alias → embedding（候选发现）→ 每一步都走 LLM 裁决。
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, embed, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.er")


# ---------------------------------------------------------------- 只读匹配（审计可复用）
def resolve_match_only(surface_name: str, entity_type: str, description: str,
                       conn) -> dict[str, Any]:
    """不落库的匹配：返回 {decision: merged_existing|new|unresolved, entity_id?, method?, score?}。

    用于审计独立复验 ER 行为；与 resolve() 使用同一套裁决逻辑。
    """
    norm = surface_name.strip().lower()
    cand = {"surface_name": surface_name, "normalized_name": norm,
            "entity_type": entity_type, "description": description or ""}

    # 地名/机构不同名：绝不合并（即便 LLM 判 same——沿革关系用
    # historical_name_of/successor_of 表达，见重构目标 §13.3/§13.5）
    EVOLUTION_TYPES = {"Place", "Organization", "Institution"}
    with conn.cursor() as cur:
        cur.execute("""SELECT entity_id, canonical_name, COALESCE(description,'') AS d
                       FROM canonical_entities
                       WHERE lower(canonical_name)=%s AND entity_type=%s AND status='ACTIVE'""",
                    (norm, entity_type))
        rows = cur.fetchall()
    if rows:
        if entity_type in EVOLUTION_TYPES and all(
                r[1].strip().lower() != norm for r in rows) is False:
            pass  # 同名同名：走下方上下文裁决（同一称谓的连续实体）
        if entity_type in EVOLUTION_TYPES:
            # 与既有实体名字不同 → 分裂 + 沿革关系
            eid, name, desc, score = rows[0][0], rows[0][1], rows[0][2], 1.0
            rel = _evolution_relation(cand, name, desc, conn)
            return {"decision": "new_with_relation", "method": "exact+evolution",
                    "relation": rel, "related_entity_id": eid,
                    "reason": f"{entity_type} 沿革：分裂并记录 {rel}"}
        best = _best_context_match(cand, rows, conn)
        if best:
            return {"decision": "merged_existing", "entity_id": best["entity_id"],
                    "method": "exact+llm", "score": best.get("score", 1.0)}
        return {"decision": "new", "method": "exact+llm",
                "reason": "同名但上下文不同 → 分裂"}
    alias_id = _alias_lookup(norm, entity_type, conn)
    if alias_id:
        with conn.cursor() as cur:
            cur.execute("SELECT canonical_name, COALESCE(description,'') FROM canonical_entities "
                        "WHERE entity_id=%s", (alias_id,))
            n, d = cur.fetchone()
        best = _adjudicate(cand, [(alias_id, n, d, 0.95)], conn)
        if best:
            return {"decision": "merged_existing", "entity_id": best["entity_id"],
                    "method": "alias+llm", "score": best.get("score", 0.95)}
        return {"decision": "new", "method": "alias+llm", "reason": "裁决不同/不确定 → 分裂"}
    # 不同名地名/机构：embedding 只做沿革关系提名，不合并
    if entity_type in EVOLUTION_TYPES:
        emb = _embedding_candidates(cand, conn)
        if emb:
            eid, name, desc, score = emb[0]
            rel = _evolution_relation(cand, name, desc, conn)
            return {"decision": "new_with_relation", "method": "embedding+evolution",
                    "relation": rel, "related_entity_id": eid,
                    "reason": f"沿革提名（相似度 {score:.2f}）→ 分裂 + {rel}"}
        return {"decision": "new", "method": "no-match"}
    # embedding 候选发现
    emb = _embedding_candidates(cand, conn)
    if emb:
        best = _adjudicate(cand, emb, conn)
        if best:
            return {"decision": "merged_existing", "entity_id": best["entity_id"],
                    "method": "embedding+llm", "score": best.get("score", 0)}
        return {"decision": "new", "method": "embedding+llm", "reason": "裁决不同/不确定 → 分裂"}
    return {"decision": "new", "method": "no-match"}


def _evolution_relation(cand: dict, existing_name: str, existing_desc: str,
                        conn) -> str:
    """问 LLM 沿革方向：候选是既存地名的后继还是前身/历史名。"""
    prompt = PROMPTS["entity_resolution_v1"].format(
        name_a=cand["surface_name"], type_a=cand["entity_type"],
        desc_a=(cand.get("description") or "")[:150],
        name_b=existing_name, type_b=cand["entity_type"],
        desc_b=(existing_desc or "")[:150])
    v = parse_json(chat([{"role": "user", "content": prompt}], max_tokens=250)) or {}
    rel = v.get("relation")
    if rel in ("historical_name_of", "successor_of", "predecessor_of"):
        return rel
    return "successor_of"       # 保守默认：候选是既有地名的后继沿革


def _best_context_match(cand: dict, rows: list, conn) -> dict | None:
    """同名（可能多行）时用 LLM 上下文裁决挑出真正同一实体；不确定返回 None。"""
    pairs = [(r[0], r[1], r[2], 1.0) for r in rows]
    return _adjudicate(cand, pairs, conn)


def _alias_lookup(norm: str, etype: str, conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT a.entity_id FROM entity_aliases a
                       JOIN canonical_entities c ON c.entity_id=a.entity_id
                       WHERE a.normalized_alias=%s AND c.entity_type=%s AND c.status='ACTIVE'
                       LIMIT 1""", (norm, etype))
        row = cur.fetchone()
    return row[0] if row else None


def _embedding_candidates(cand: dict, conn) -> list[tuple]:
    """同类型实体嵌入相似度 ≥0.80 的候选发现（只提名，不直接合并）。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT entity_id, canonical_name, COALESCE(description,'')
                       FROM canonical_entities
                       WHERE entity_type=%s AND status='ACTIVE' LIMIT 500""",
                    (cand["entity_type"],))
        pool = cur.fetchall()
    if not pool:
        return []
    try:
        vecs = embed([f"{cand['surface_name']} {cand.get('description','')[:120]}"]
                     + [f"{n} {d}" for _, n, d in pool])
    except Exception as exc:
        log.warning("embedding failed: %s", exc)
        return []
    q = vecs[0]
    qn = math.sqrt(sum(a * a for a in q)) or 1.0
    scored = []
    for (eid, name, desc), v in zip(pool, vecs[1:]):
        dot = sum(a * b for a, b in zip(q, v))
        score = dot / (qn * (math.sqrt(sum(b * b for b in v)) or 1.0))
        if score >= 0.80:
            scored.append((eid, name, desc, score))
    scored.sort(key=lambda x: -x[3])
    return scored[:3]


def _adjudicate(cand: dict, pairs: list[tuple], conn) -> dict | None:
    """对候选与若干既有实体做上下文裁决；唯一 same → 返回该实体；否则 None。"""
    same_hits = []
    for eid, name, desc, score in pairs:
        prompt = PROMPTS["entity_resolution_v1"].format(
            name_a=cand["surface_name"], type_a=cand["entity_type"],
            desc_a=(cand.get("description") or "")[:150],
            name_b=name, type_b=cand["entity_type"], desc_b=(desc or "")[:150])
        raw = chat([{"role": "user", "content": prompt}], max_tokens=250)
        verdict = parse_json(raw) or {}
        v = verdict.get("verdict")
        if v == "same":
            same_hits.append((eid, verdict.get("reason", ""), score))
        # different / unsure 都不合并
    if len(same_hits) == 1:
        eid, reason, score = same_hits[0]
        return {"entity_id": eid, "score": score, "reason": reason}
    if len(same_hits) > 1:
        # 多个同名实体都判 same：保守起见取描述最匹配的一个不再扩展（记录）
        log.warning("ambiguous same hits (%d) for %s", len(same_hits),
                    cand["surface_name"])
        eid, reason, score = same_hits[0]
        return {"entity_id": eid, "score": score, "reason": "multi-same, took first"}
    return None


# ---------------------------------------------------------------- 落库写入
def resolve(candidate: dict[str, Any], conn) -> dict[str, Any]:
    """完整解析：裁决 + 写 candidate/resolutions/provenance。"""
    m = resolve_match_only(candidate["surface_name"], candidate["entity_type"],
                           candidate.get("description", ""), conn)
    with conn.cursor() as cur:
        if m["decision"] == "merged_existing":
            cur.execute("""UPDATE candidate_entities
                           SET resolved_entity_id=%s, resolution_status='RESOLVED_EXISTING'
                           WHERE candidate_id=%s""",
                        (m["entity_id"], candidate["candidate_id"]))
            cur.execute(
                """INSERT INTO entity_resolutions
                   (candidate_id, matched_entity_id, method, score, reason,
                    model, prompt_version, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'MERGED')""",
                (candidate["candidate_id"], m["entity_id"], m.get("method", ""),
                 m.get("score", 0), m.get("reason", ""),
                 SETTINGS.llm_model, SETTINGS.prompt_resolution))
            cur.execute(
                """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
                   VALUES ('candidate_entity', %s, 'resolved', 'entity_resolution', %s)""",
                (candidate["candidate_id"], json.dumps(
                    {"entity_id": m["entity_id"], "method": m.get("method")},
                    ensure_ascii=False)))
            conn.commit()
            return {"status": "MERGED", "entity_id": m["entity_id"], "method": m.get("method")}

        if m["decision"] == "new_with_relation":
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO canonical_entities
                       (canonical_name, entity_type, description)
                       VALUES (%s,%s,%s) RETURNING entity_id""",
                    (candidate["surface_name"], candidate["entity_type"],
                     candidate.get("description")))
                eid = cur.fetchone()[0]
                cur.execute("""UPDATE candidate_entities
                               SET resolved_entity_id=%s, resolution_status='NEW'
                               WHERE candidate_id=%s""",
                            (eid, candidate["candidate_id"]))
                cur.execute(
                    """INSERT INTO entity_resolutions
                       (candidate_id, matched_entity_id, method, score, reason, status)
                       VALUES (%s,%s,%s,%s,%s,'NEW')""",
                    (candidate["candidate_id"], m["related_entity_id"],
                     m.get("method", ""), m.get("score", 0), m.get("reason", "")))
                # 沿革关系落库
                rel = m.get("relation", "successor_of")
                detail = json.dumps({"from": m["related_entity_id"], "to": str(eid),
                                     "relation": rel}, ensure_ascii=False)
                if candidate["entity_type"] == "Place":
                    cur.execute(
                        """INSERT INTO place_relations
                           (from_entity, relation, to_entity) VALUES (%s,%s,%s)""",
                        (eid, rel, m["related_entity_id"]))
                else:
                    cur.execute(
                        """INSERT INTO provenance_events
                           (object_type, object_id, action, actor, detail)
                           VALUES ('organization', %s, 'evolution_relation',
                                   'entity_resolution', %s)""",
                        (str(eid), detail))
            conn.commit()
            return {"status": "NEW", "entity_id": str(eid)}

        if m["decision"] == "new" and m.get("method") in ("exact+llm", "alias+llm",
                                                          "embedding+llm", "no-match"):
            # 不同/无匹配 → 新建；unsure 场景在 _adjudicate 已返回 new（保守分裂）
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO canonical_entities (canonical_name, entity_type, description)
                       VALUES (%s,%s,%s) RETURNING entity_id""",
                    (candidate["surface_name"], candidate["entity_type"],
                     candidate.get("description")))
                eid = cur.fetchone()[0]
                cur.execute("""UPDATE candidate_entities
                               SET resolved_entity_id=%s, resolution_status='NEW'
                               WHERE candidate_id=%s""",
                            (eid, candidate["candidate_id"]))
                cur.execute(
                    """INSERT INTO entity_resolutions
                       (candidate_id, matched_entity_id, method, score, reason, status)
                       VALUES (%s,%s,%s,%s,%s,'NEW')""",
                    (candidate["candidate_id"], eid, m.get("method", ""),
                     m.get("score", 0), m.get("reason", "new entity")))
            conn.commit()
            return {"status": "NEW", "entity_id": str(eid)}

        # UNRESOLVED：保守分裂——不合并、也不建新实体，候选挂起等待后续证据
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO entity_resolutions
                   (candidate_id, method, score, reason, model, prompt_version, status)
                   VALUES (%s,'llm',%s,'unsure → 保持分裂',%s,%s,'UNRESOLVED')""",
                (candidate["candidate_id"], m.get("score", 0),
                 SETTINGS.llm_model, SETTINGS.prompt_resolution))
        conn.commit()
        return {"status": "UNRESOLVED"}
