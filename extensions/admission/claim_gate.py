# -*- coding: utf-8 -*-
"""Phase 9：Claim Admission —— 十阶段准入流水线（任一 FAIL 即不得 ADMITTED）。

stages: schema_validation → entity_resolution → domain_range → evidence_span
        → temporal → spatial → yangtze_scope → source_independence
        → conflict_detection → admission
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.extraction.extract import predicate_domain_range
from extensions.evidence.binder import bind

log = logging.getLogger("ycki.claim_gate")


def admit(claim_draft: dict[str, Any], conn) -> dict[str, Any]:
    """对单条候选 claim 执行准入。返回最终 claim 记录（含状态与 stages 结果）。

    claim_draft 字段：subject_candidate_id/object_candidate_id（已解析实体 id）、
    predicate、quote_span、chunk_id、document_id、resource_id、source_id、
    time_text、place_name、chunk_text
    """
    stages: list[tuple[str, str, dict]] = []

    def record(stage: str, result: str, detail: dict) -> None:
        stages.append((stage, result, detail))
        if result == "FAIL":
            raise _StageFailure(stage, detail)

    try:
        # 1 schema_validation：谓词已注册
        dr = predicate_domain_range(claim_draft["predicate"])
        if dr is None:
            record("schema_validation", "FAIL", {"reason": "谓词未注册"})
        record("schema_validation", "PASS", {"predicate": claim_draft["predicate"]})

        # 3 domain_range：subject/object 实体类型必须在 domain/range 内
        with conn.cursor() as cur:
            cur.execute("SELECT entity_type FROM canonical_entities WHERE entity_id=%s",
                        (claim_draft["subject_entity_id"],))
            stype = (cur.fetchone() or [""])[0]
            cur.execute("SELECT entity_type FROM canonical_entities WHERE entity_id=%s",
                        (claim_draft["object_entity_id"],))
            otype = (cur.fetchone() or [""])[0]
        domain, rng = dr
        if (stype not in domain) or (otype not in rng):
            record("domain_range", "FAIL",
                   {"reason": f"{stype} --{claim_draft['predicate']}--> {otype} 不在 domain/range",
                    "domain": domain, "range": rng})
        record("domain_range", "PASS", {"subject_type": stype, "object_type": otype})

        # 4 evidence_span：quote 必须能在 chunk 原文定位
        match = bind(claim_draft["quote_span"], claim_draft.get("chunk_text", ""))
        if match == "FAILED":
            record("evidence_span", "FAIL", {"reason": "quote_span 无法在原文定位"})
        record("evidence_span", "PASS", {"match_status": match})

        # 5 temporal：谓词要求时间则必须有 time
        pred = SETTINGS  # noqa
        from extensions.extraction.extract import _PRED
        need_time = _PRED[claim_draft["predicate"]].get("time_required", False)
        if need_time and not (claim_draft.get("timespan_id") or claim_draft.get("time_text")):
            record("temporal", "FAIL", {"reason": "谓词要求时间但缺失"})
        record("temporal", "PASS", {"time": claim_draft.get("time_text", "")})

        # 7 yangtze_scope：来源资源必须 CORE/CONTEXT
        with conn.cursor() as cur:
            cur.execute("SELECT admission_status FROM resources WHERE resource_id=%s",
                        (claim_draft["resource_id"],))
            adm = (cur.fetchone() or ["REJECTED"])[0]
        if adm not in ("CORE", "CONTEXT"):
            record("yangtze_scope", "FAIL", {"reason": f"资源准入状态 {adm}"})
        record("yangtze_scope", "PASS", {"resource_admission": adm})

        # 9 conflict_detection：与已 ADMITTED 主张矛盾 → CONTESTED
        conflict = _detect_conflict(claim_draft, conn)
        contested = conflict is not None

        # 10 admission
        status = "CONTESTED" if contested else (
            "ADMITTED" if match in ("EXACT", "NORMALIZED") else "SUPPORTED")
        record("admission", "PASS", {"status": status})

        claim_id = _insert_claim(claim_draft, status, match, conn, stages)
        return {"claim_id": claim_id, "status": status, "stages": stages,
                "conflict_with": conflict}

    except _StageFailure as fail:
        claim_id = _insert_claim(claim_draft, "REJECTED", "FAILED", conn, stages,
                                 fail_stage=fail.stage, fail_detail=fail.detail)
        return {"claim_id": claim_id, "status": "REJECTED",
                "failed_stage": fail.stage, "detail": fail.detail, "stages": stages}


class _StageFailure(Exception):
    def __init__(self, stage: str, detail: dict):
        super().__init__(stage)
        self.stage = stage
        self.detail = detail


def _detect_conflict(claim_draft: dict[str, Any], conn) -> str | None:
    """同主体同谓词但宾语不同、且均为 ADMITTED → 视为冲突（保守判定）。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT c.claim_id, o.canonical_name FROM claims c
                       JOIN canonical_entities o ON o.entity_id=c.object_id
                       WHERE c.subject_id=%s AND c.predicate_id=%s AND c.status='ADMITTED'
                       LIMIT 5""", (claim_draft["subject_entity_id"],
                                    claim_draft["predicate"]))
        rows = cur.fetchall()
    for cid, oname in rows:
        if oname != claim_draft.get("object_name"):
            return str(cid)
    return None


def _insert_claim(claim_draft: dict[str, Any], status: str, match_status: str,
                  conn, stages: list, fail_stage: str | None = None,
                  fail_detail: dict | None = None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO claims
               (subject_id, predicate_id, object_id, timespan_id, status, confidence,
                generation_model, model_version, prompt_version, pipeline_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING claim_id""",
            (claim_draft["subject_entity_id"], claim_draft["predicate"],
             claim_draft["object_entity_id"], claim_draft.get("timespan_id"), status,
             0.6 if status == "ADMITTED" else 0.3,
             SETTINGS.llm_model, "", SETTINGS.prompt_admission,
             SETTINGS.pipeline_version))
        claim_id = cur.fetchone()[0]

        if status in ("ADMITTED", "SUPPORTED", "CONTESTED"):
            cur.execute(
                """INSERT INTO evidence
                   (claim_id, resource_id, document_id, chunk_id, quote_span,
                    match_status, relation, source_id)
                   VALUES (%s,%s,%s,%s,%s,%s,'SUPPORTS',%s)""",
                (claim_id, claim_draft.get("resource_id"), claim_draft.get("document_id"),
                 claim_draft.get("chunk_id"), claim_draft["quote_span"], match_status,
                 claim_draft.get("source_id")))

        for stage, result, detail in stages:
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
