# -*- coding: utf-8 -*-
"""Phase 8/9 v2：Claim Admission —— 十阶段准入（全部真实执行并留痕）。

stages:
 1 schema_validation     谓词已注册、cardinality 已知
 2 entity_resolution     subject/object 已解析为 Canonical Entity（禁止补建类型）
 3 domain_range          类型 ∈ domain/range
 4 evidence_span         quote_span 能在「真实所在 chunk」定位（EXACT/NORMALIZED）
 5 temporal              谓词要求时间 → 必须有 TimeSpan
 6 spatial               谓词要求地点 → 必须有 place entity
 7 yangtze_scope         来源资源为 CORE/CONTEXT
 8 source_independence   统计同三元组独立来源数（进 confidence）
 9 conflict_detection    cardinality 感知：single 谓词同主体不同宾语 → CONTESTED
10 admission             综合置信模型 → ADMITTED / SUPPORTED / CONTESTED

confidence 模型（可解释，非拍脑袋）：
  base 0.35
  + 0.15 × min(独立来源数−1, 2)     （独立来源增益，封顶 +0.30）
  + 0.15                             （来源权威级 S/A）
  + 0.10                             （证据 EXACT 定位）
  + 0.10                             （有时间）
  + 0.10                             （非兜底谓词 associated_with）
  上限 0.95；CONTESTED 固定 0.30。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.evidence.binder import bind
from extensions.extraction.extract import _PRED

log = logging.getLogger("ycki.claim_gate")

_FALLBACK_PREDICATES = {"associated_with"}


class StageFailure(Exception):
    def __init__(self, stage: str, detail: dict):
        super().__init__(stage)
        self.stage = stage
        self.detail = detail


def admit(claim_draft: dict[str, Any], conn) -> dict[str, Any]:
    """执行十阶段准入。claim_draft 必须含：
    subject_entity_id / object_entity_id（已解析，禁止缺省补建）、predicate、
    quote_span、chunk_id（真实 chunk）、chunk_text（该 chunk 原文）、
    resource_id / document_id / source_id、time_text、place_name、object_name。
    """
    stages: list[tuple[str, str, dict]] = []

    def record(stage: str, result: str, detail: dict) -> None:
        stages.append((stage, result, detail))
        if result == "FAIL":
            raise StageFailure(stage, detail)

    pred = _PRED[claim_draft["predicate"]]

    def _type_of(entity_id: str) -> str:
        with conn.cursor() as cur:
            cur.execute("SELECT entity_type FROM canonical_entities WHERE entity_id=%s",
                        (entity_id,))
            row = cur.fetchone()
        return row[0] if row else ""

    try:
        # ---- 1 schema_validation ----
        if claim_draft["predicate"] not in _PRED:
            record("schema_validation", "FAIL", {"reason": "谓词未注册"})
        record("schema_validation", "PASS",
               {"predicate": claim_draft["predicate"],
                "cardinality": pred.get("cardinality", "single")})

        # ---- 2 entity_resolution（端点必须已解析，绝不补建） ----
        if not claim_draft.get("subject_entity_id") or not claim_draft.get("object_entity_id"):
            # 端点未解析：不产生 claims 行（claims 表要求端点存在），
            # 只在 provenance 留痕，等待实体解析后重试。
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO provenance_events
                       (object_type, object_id, action, actor, detail)
                       VALUES ('claim_draft', %s, 'rejected_pre_insert',
                               'claim_gate', %s)""",
                    (f"{claim_draft.get('resource_id')}|{claim_draft.get('subject')}|"
                     f"{claim_draft['predicate']}|{claim_draft.get('object')}",
                     json.dumps({"reason": "endpoints unresolved",
                                 "quote": claim_draft["quote_span"][:80]},
                                ensure_ascii=False)))
            conn.commit()
            return {"status": "REJECTED_PRE_INSERT",
                    "failed_stage": "entity_resolution",
                    "reason": "端点实体未解析（等待 ER 后重试）",
                    "stages": stages}
        with conn.cursor() as cur:
            cur.execute("""SELECT resolution_status FROM candidate_entities
                           WHERE resolved_entity_id=%s
                           ORDER BY created_at DESC LIMIT 1""",
                        (claim_draft["subject_entity_id"],))
            r = cur.fetchone()
            s_stat = r[0] if r else "RESOLVED_EXISTING"
            cur.execute("""SELECT resolution_status FROM candidate_entities
                           WHERE resolved_entity_id=%s
                           ORDER BY created_at DESC LIMIT 1""",
                        (claim_draft["object_entity_id"],))
            r = cur.fetchone()
            o_stat = r[0] if r else "RESOLVED_EXISTING"
        if "UNRESOLVED" in (s_stat, o_stat):
            record("entity_resolution", "FAIL",
                   {"reason": "端点候选处于 UNRESOLVED", "subject": s_stat, "object": o_stat})
        record("entity_resolution", "PASS", {"subject": s_stat, "object": o_stat})

        # ---- 3 domain_range ----
        stype, otype = _type_of(claim_draft["subject_entity_id"]), \
            _type_of(claim_draft["object_entity_id"])
        if stype not in pred["domain"] or otype not in pred["range"]:
            record("domain_range", "FAIL",
                   {"reason": f"{stype} --{claim_draft['predicate']}--> {otype} 越界",
                    "domain": pred["domain"], "range": pred["range"]})
        record("domain_range", "PASS", {"subject_type": stype, "object_type": otype})

        # ---- 4 evidence_span（绑定真实 chunk） ----
        chunk_text = claim_draft.get("chunk_text", "")
        match = bind(claim_draft["quote_span"], chunk_text)
        if match == "FAILED":
            record("evidence_span", "FAIL",
                   {"reason": "quote_span 无法在真实 chunk 原文定位",
                    "chunk_id": claim_draft.get("chunk_id")})
        record("evidence_span", "PASS", {"match_status": match,
                                         "chunk_id": claim_draft.get("chunk_id")})

        # ---- 5 temporal ----
        if pred.get("time_required") and not (claim_draft.get("timespan_id")
                                              or claim_draft.get("time_text")):
            record("temporal", "FAIL", {"reason": "谓词要求时间但缺失"})
        record("temporal", "PASS", {"time": claim_draft.get("time_text", "")})

        # ---- 6 spatial ----
        if pred.get("place_required") and not claim_draft.get("place_entity_id"):
            record("spatial", "FAIL", {"reason": "谓词要求地点但缺失"})
        record("spatial", "PASS", {"place": claim_draft.get("place_name", ""),
                                   "place_entity_id": str(claim_draft.get("place_entity_id") or "")})

        # ---- 7 yangtze_scope ----
        with conn.cursor() as cur:
            cur.execute("SELECT admission_status FROM resources WHERE resource_id=%s",
                        (claim_draft["resource_id"],))
            row = cur.fetchone()
        adm = row[0] if row else "REJECTED"
        if adm not in ("CORE", "CONTEXT"):
            record("yangtze_scope", "FAIL", {"reason": f"资源准入状态 {adm}"})
        record("yangtze_scope", "PASS", {"resource_admission": adm})

        # ---- 8 source_independence（§六：独立证据单位=cluster，缺省退化 resource） ----
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(DISTINCT COALESCE(r.source_cluster_id, r.resource_id)) AS indep,
                       count(DISTINCT e.resource_id) AS raw_res,
                       count(DISTINCT e.source_id) AS raw_src,
                       count(*) AS raw_ev
                FROM claims c2
                JOIN evidence e ON e.claim_id=c2.claim_id
                JOIN resources r ON r.resource_id=e.resource_id
                WHERE c2.subject_id=%s AND c2.predicate_id=%s AND c2.object_id=%s
                  AND c2.status='ADMITTED'""",
                (claim_draft["subject_entity_id"], claim_draft["predicate"],
                 claim_draft["object_entity_id"]))
            r = cur.fetchone()
            indep = (r["indep"] if r else 0) + 1
            raw_res = (r["raw_res"] if r else 0) + 1
            raw_src = (r["raw_src"] if r else 0) + 1
            raw_ev = (r["raw_ev"] if r else 0) + 1
            cur.execute("SELECT authority_level FROM sources WHERE source_id=%s",
                        (claim_draft.get("source_id") or "",))
            ar = cur.fetchone()
            authority = ar[0] if ar else "UNKNOWN"
        authority_dist = {authority: 1}
        record("source_independence", "PASS",
               {"independent_evidence_count": indep,
                "raw_evidence_count": raw_ev,
                "distinct_resource_count": raw_res,
                "distinct_domain_count": raw_src,
                "authority_distribution": authority_dist})

        # ---- 9 conflict_detection（cardinality 感知） ----
        cardinality = pred.get("cardinality", "single")
        conflict_id = None
        if cardinality == "single":
            with conn.cursor() as cur:
                cur.execute("""SELECT c.claim_id, o.canonical_name FROM claims c
                               JOIN canonical_entities o ON o.entity_id=c.object_id
                               WHERE c.subject_id=%s AND c.predicate_id=%s
                                 AND c.object_id<>%s AND c.status='ADMITTED'
                               LIMIT 5""",
                            (claim_draft["subject_entity_id"], claim_draft["predicate"],
                             claim_draft["object_entity_id"]))
                conflicts = cur.fetchall()
            if conflicts:
                conflict_id = str(conflicts[0][0])
                record("conflict_detection", "PASS",
                       {"CONTESTED": True, "with_claim": conflict_id,
                        "other_object": conflicts[0][1]})
        else:
            record("conflict_detection", "PASS",
                   {"note": "multi-cardinality 谓词允许多宾语，不判冲突"})

        # ---- 10 admission（置信模型） ----
        status = "CONTESTED" if conflict_id else (
            "ADMITTED" if match in ("EXACT", "NORMALIZED") else "SUPPORTED")
        confidence, explanation = _confidence(
            indep, authority, match, claim_draft.get("time_text"),
            claim_draft["predicate"], status)
        record("admission", "PASS",
               {"status": status, "confidence": confidence,
                "explanation": explanation})

        claim_id = _insert(claim_draft, status, match, confidence, indep,
                           conflict_id, conn, stages, explanation=explanation)
        return {"claim_id": str(claim_id), "status": status,
                "confidence": round(confidence, 2), "stages": stages}

    except StageFailure as fail:
        claim_id = _insert(claim_draft, "REJECTED", "FAILED", 0.0, 0, None, conn,
                           stages, fail_stage=fail.stage, fail_detail=fail.detail)
        return {"claim_id": str(claim_id), "status": "REJECTED",
                "failed_stage": fail.stage, "detail": fail.detail, "stages": stages}


def _confidence(indep: int, authority: str, match: str, time_text: Any,
                predicate: str, status: str) -> tuple[float, dict]:
    """可解释置信模型（§十）。返回 (confidence, explanation)。"""
    if status == "CONTESTED":
        return 0.30, {"final_confidence": 0.30, "conflict_penalty": 0.55,
                      "evidence_grounding": 1.0, "independent_sources": indep,
                      "authority_score": 0.15 if authority in ("S", "A") else 0.0}
    grounding = 1.0 if match == "EXACT" else 0.85
    c = 0.35
    c += 0.15 * min(max(indep - 1, 0), 2)
    auth_score = 0.15 if authority in ("S", "A") else 0.0
    c += auth_score
    if match == "EXACT":
        c += 0.10
    if time_text:
        c += 0.10
    if predicate not in _FALLBACK_PREDICATES:
        c += 0.10
    c = min(0.95, round(c, 2))
    explanation = {
        "final_confidence": c,
        "evidence_grounding": grounding,
        "independent_sources": indep,
        "authority_score": auth_score,
        "match_bonus": 0.10 if match == "EXACT" else 0.0,
        "time_bonus": 0.10 if time_text else 0.0,
        "predicate_specificity": 0.0 if predicate in _FALLBACK_PREDICATES else 0.10,
        "conflict_penalty": 0.0,
    }
    return c, explanation


def _insert(claim_draft: dict[str, Any], status: str, match_status: str,
            confidence: float, indep: int, conflict_id: str | None, conn,
            stages: list, fail_stage: str | None = None,
            fail_detail: dict | None = None,
            explanation: dict | None = None) -> str:
    keep = status in ("ADMITTED", "SUPPORTED", "CONTESTED")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO claims
               (subject_id, predicate_id, object_id, timespan_id, place_entity_id,
                status, confidence, generation_model, model_version, prompt_version,
                pipeline_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING claim_id""",
            (claim_draft["subject_entity_id"], claim_draft["predicate"],
             claim_draft["object_entity_id"], claim_draft.get("timespan_id"),
             claim_draft.get("place_entity_id"), status, confidence,
             SETTINGS.llm_model, "", SETTINGS.prompt_admission,
             SETTINGS.pipeline_version))
        claim_id = cur.fetchone()[0]

        if keep:
            cur.execute(
                """INSERT INTO evidence
                   (claim_id, resource_id, document_id, chunk_id, page, quote_span,
                    match_status, relation, source_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'SUPPORTS',%s)""",
                (claim_id, claim_draft.get("resource_id"), claim_draft.get("document_id"),
                 claim_draft.get("chunk_id"), claim_draft.get("chunk_part_index"),
                 claim_draft["quote_span"], match_status, claim_draft.get("source_id")))

        for stage, result, detail in stages:
            if stage == "admission" and explanation:
                detail = {**detail, "confidence_explanation": explanation,
                          "independent_evidence_count": indep}
            cur.execute(
                """INSERT INTO claim_admissions
                   (claim_id, stage, result, detail, model, prompt_version)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (claim_id, stage, result, json.dumps(detail, ensure_ascii=False),
                 SETTINGS.llm_model, SETTINGS.prompt_admission))
        if fail_stage:
            cur.execute(
                """INSERT INTO claim_admissions
                   (claim_id, stage, result, detail, model, prompt_version)
                   VALUES (%s,%s,'FAIL',%s,%s,%s)""",
                (claim_id, fail_stage, json.dumps(fail_detail or {}, ensure_ascii=False),
                 SETTINGS.llm_model, SETTINGS.prompt_admission))
    conn.commit()
    return claim_id
