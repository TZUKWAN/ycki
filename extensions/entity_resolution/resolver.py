# -*- coding: utf-8 -*-
"""Phase 6 v3：Entity Resolution —— 候选实体 → Canonical Entity（§三 收口版）。

原则：
- name 永远不是身份；同名同类型必须上下文裁决，禁止直接 merge。
- 裁决多命中 same → AMBIGUOUS_MATCH → UNRESOLVED（宁可分裂不错误合并）。
- 地名/机构不同名 → 沿革五态判定：
  historical_name_of / successor_of / predecessor_of / NO_RELATION / UNRESOLVED
  仅当 LLM 同时给出证据短语且该短语能在候选原文 chunk 中定位时，
  才写入 place_relations（带 evidence）；否则只入 candidate_evolution_relations。
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from config.settings import SETTINGS
from extensions.evidence.binder import bind
from extensions.llm import chat, embed, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.er")

EVOLUTION_TYPES = {"Place", "Organization", "Institution"}
EVOLUTION_RELS = {"historical_name_of", "successor_of", "predecessor_of"}

# 沿革裁决 prompt v2（五态 + 证据引用要求）
EVOLUTION_PROMPT_V2 = """判断两个{etype}候选的关系，从以下五选一：
- historical_name_of：A 是 B 的历史名称（同一实体不同时代称谓）
- successor_of：A 是 B 的后继/更名后形态（行政/机构沿革）
- predecessor_of：A 是 B 的前身
- NO_RELATION：无沿革关系（两个不同实体）
- UNRESOLVED：可能相关但依据不足

候选A：{name_a} —— {desc_a}
候选B：{name_b} —— {desc_b}

规则：只有当描述中存在明确沿革表述时才允许前三种；否则 NO_RELATION 或 UNRESOLVED。
若给出沿革关系，必须同时引用候选A描述中的证据短语 evidence_quote（逐字摘抄）。

输出严格 JSON：
{{"relation":"historical_name_of|successor_of|predecessor_of|NO_RELATION|UNRESOLVED",
"evidence_quote":"A描述中的证据短语，无则空串",
"reason":"30字内"}}"""


def resolve_match_only(surface_name: str, entity_type: str, description: str,
                       conn) -> dict[str, Any]:
    """只读匹配（供审计复用）。decision ∈ merged_existing|new|new_with_relation|unresolved。"""
    norm = surface_name.strip().lower()
    cand = {"surface_name": surface_name, "normalized_name": norm,
            "entity_type": entity_type, "description": description or ""}

    with conn.cursor() as cur:
        cur.execute("""SELECT entity_id, canonical_name, COALESCE(description,'') AS d
                       FROM canonical_entities
                       WHERE lower(canonical_name)=%s AND entity_type=%s AND status='ACTIVE'""",
                    (norm, entity_type))
        rows = cur.fetchall()

    if rows:
        # 同名同名：上下文裁决；multi-same → AMBIGUOUS（§3.4）
        best = _best_context_match(cand, rows, conn)
        if best["decision"] == "merged_existing":
            return best
        if best["decision"] == "ambiguous":
            return {"decision": "unresolved", "method": "exact+llm",
                    "reason": "AMBIGUOUS_MATCH：多候选 same，等待更多上下文"}
        # different → 同名不同实体：新建（地名/机构另查沿革提名）
        return _evolution_or_new(cand, conn, "exact")

    alias_id = _alias_lookup(norm, entity_type, conn)
    if alias_id:
        with conn.cursor() as cur:
            cur.execute("SELECT canonical_name, COALESCE(description,'') FROM canonical_entities "
                        "WHERE entity_id=%s", (alias_id,))
            n, d = cur.fetchone()
        best = _adjudicate(cand, [(alias_id, n, d, 0.95)], conn)
        if best["decision"] == "merged_existing":
            return best
        if best["decision"] == "ambiguous":
            return {"decision": "unresolved", "method": "alias+llm",
                    "reason": "AMBIGUOUS_MATCH"}
        return _evolution_or_new(cand, conn, "alias")

    emb = _embedding_candidates(cand, conn)
    if emb:
        best = _adjudicate(cand, emb, conn)
        if best["decision"] == "merged_existing":
            return best
        if best["decision"] == "ambiguous":
            return {"decision": "unresolved", "method": "embedding+llm",
                    "reason": "AMBIGUOUS_MATCH"}
        return _evolution_or_new(cand, conn, "embedding")

    return {"decision": "new", "method": "no-match"}


def _evolution_or_new(cand: dict, conn, funnel: str) -> dict[str, Any]:
    """不同名地名/机构：沿革五态判定；无证据沿革只入候选表。"""
    if cand["entity_type"] not in EVOLUTION_TYPES:
        return {"decision": "new", "method": funnel}
    with conn.cursor() as cur:
        cur.execute("""SELECT entity_id, canonical_name, COALESCE(description,'')
                       FROM canonical_entities
                       WHERE entity_type=%s AND status='ACTIVE' LIMIT 500""",
                    (cand["entity_type"],))
        pool = cur.fetchall()
    if not pool:
        return {"decision": "new", "method": funnel}
    try:
        vecs = embed([f"{cand['surface_name']} {cand.get('description','')[:120]}"]
                     + [f"{n} {d}" for _, n, d in pool])
    except Exception as exc:
        log.warning("embedding failed: %s", exc)
        return {"decision": "new", "method": funnel}
    q = vecs[0]
    qn = math.sqrt(sum(a * a for a in q)) or 1.0
    scored = []
    for (eid, name, desc), v in zip(pool, vecs[1:]):
        dot = sum(a * b for a, b in zip(q, v))
        score = dot / (qn * (math.sqrt(sum(b * b for b in v)) or 1.0))
        if score >= 0.80:
            scored.append((eid, name, desc, score))
    if not scored:
        return {"decision": "new", "method": funnel}
    scored.sort(key=lambda x: -x[3])
    eid, name, desc, score = scored[0]
    evo = _evolution_adjudicate(cand, name, desc)
    return {"decision": "new_with_relation", "method": funnel + "+evolution",
            "relation": evo["relation"], "related_entity_id": eid,
            "evidence_quote": evo.get("evidence_quote", ""),
            "reason": f"{evo['relation']}（{evo.get('reason', '')[:40]}）"}


def _evolution_adjudicate(cand: dict, existing_name: str, existing_desc: str) -> dict:
    """沿革五态裁决（§3.1）：五选一 + 证据短语。"""
    prompt = EVOLUTION_PROMPT_V2.format(
        etype=cand["entity_type"], name_a=cand["surface_name"],
        desc_a=(cand.get("description") or "")[:180],
        name_b=existing_name, desc_b=(existing_desc or "")[:180])
    v = parse_json(chat([{"role": "user", "content": prompt}], max_tokens=300)) or {}
    rel = v.get("relation")
    if rel not in EVOLUTION_RELS:
        rel = "NO_RELATION" if rel == "NO_RELATION" else "UNRESOLVED"
    return {"relation": rel, "evidence_quote": str(v.get("evidence_quote", ""))[:200],
            "reason": str(v.get("reason", ""))[:100]}


def _best_context_match(cand: dict, rows: list, conn) -> dict | None:
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


def _adjudicate(cand: dict, pairs: list[tuple], conn) -> dict[str, Any]:
    """上下文裁决。decision ∈ merged_existing|ambiguous|different。

    multi-same → ambiguous（§3.4 禁止 take first）。
    """
    same_hits = []
    for eid, name, desc, score in pairs:
        prompt = PROMPTS["entity_resolution_v1"].format(
            name_a=cand["surface_name"], type_a=cand["entity_type"],
            desc_a=(cand.get("description") or "")[:150],
            name_b=name, type_b=cand["entity_type"],
            desc_b=(desc or "")[:150])
        v = parse_json(chat([{"role": "user", "content": prompt}], max_tokens=250)) or {}
        if v.get("verdict") == "same":
            same_hits.append((eid, v.get("reason", ""), score))
    if len(same_hits) == 1:
        eid, reason, score = same_hits[0]
        return {"decision": "merged_existing", "entity_id": eid,
                "score": score, "reason": reason}
    if len(same_hits) > 1:
        log.warning("AMBIGUOUS_MATCH for %s (%d same candidates)",
                    cand["surface_name"], len(same_hits))
        return {"decision": "ambiguous",
                "reason": f"{len(same_hits)} 个候选均判 same"}
    return {"decision": "different"}


# ---------------------------------------------------------------- 落库写入
def resolve(candidate: dict[str, Any], conn) -> dict[str, Any]:
    """完整解析：裁决 + 写 candidate/resolutions/provenance/沿革候选。"""
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
            # 沿革判定：新建候选实体本体 + 关系按证据门控分流
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
                rel = m.get("relation", "NO_RELATION")
                evidence_quote = m.get("evidence_quote", "")
                # 证据门控（§3.2）：quote 必须能在【资源原文全文】中定位，
                # 沿革关系才进正式 place_relations；否则只入候选表
                placed = False
                src_res = candidate.get("resource_id")
                if rel in EVOLUTION_RELS and evidence_quote and src_res:
                    cur.execute("SELECT text_path FROM resources WHERE resource_id=%s",
                                (src_res,))
                    tp = (cur.fetchone() or [None])[0]
                    full_text = ""
                    if tp and Path(tp).exists():
                        full_text = Path(tp).read_text(encoding="utf-8",
                                                       errors="replace")
                    match = bind(evidence_quote, full_text or
                                 candidate.get("description", ""))
                    if match in ("EXACT", "NORMALIZED"):
                        cur.execute(
                            """INSERT INTO place_relations
                               (from_entity, relation, to_entity) VALUES (%s,%s,%s)""",
                            (eid, rel, m["related_entity_id"]))
                        placed = True
                    cur.execute(
                        """INSERT INTO candidate_evolution_relations
                           (candidate_id, from_entity, to_entity, relation,
                            evidence_resource_id, evidence_chunk_id,
                            evidence_quote_span, evidence_verified,
                            model, prompt_version, confidence)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (candidate["candidate_id"], eid, m["related_entity_id"], rel,
                         src_res if placed else None,
                         None, evidence_quote,
                         match if placed else "NONE",
                         SETTINGS.llm_model, SETTINGS.prompt_resolution,
                         0.6 if placed else 0.35))
                if rel in ("NO_RELATION", "UNRESOLVED"):
                    cur.execute(
                        """INSERT INTO candidate_evolution_relations
                           (candidate_id, from_entity, to_entity, relation,
                            evidence_quote_span, evidence_verified,
                            model, prompt_version, confidence)
                           VALUES (%s,%s,%s,%s,'','NONE',%s,%s,0.2)""",
                        (candidate["candidate_id"], eid, m["related_entity_id"],
                         rel, SETTINGS.llm_model, SETTINGS.prompt_resolution))
            conn.commit()
            return {"status": "NEW", "entity_id": str(eid)}

        # UNRESOLVED / ambiguous：保守分裂——不合并、不建新实体、不改关系
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO entity_resolutions
                   (candidate_id, method, score, reason, model, prompt_version, status)
                   VALUES (%s,%s,%s,%s,%s,%s,'UNRESOLVED')""",
                (candidate["candidate_id"], m.get("method", ""),
                 m.get("score", 0), m.get("reason", "unresolved"),
                 SETTINGS.llm_model, SETTINGS.prompt_resolution))
        conn.commit()
        return {"status": "UNRESOLVED"}
