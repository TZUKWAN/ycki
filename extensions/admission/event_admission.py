# -*- coding: utf-8 -*-
"""§47/48：Event Admission —— 事件准入（9 阶段 + 证据落 event_evidence）。

对 CANDIDATE 事件执行：
  event_schema_validation → entity_resolution → time_validation → place_validation
  → participant_validation → evidence_validation → yangtze_scope
  → conflict_detection → admission
全部 PASS → ADMITTED + event_evidence 落地；否则 REJECTED / 保持 CANDIDATE。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.evidence.binder import bind
from extensions.extraction.extract import ENTITY_TYPES

log = logging.getLogger("ycki.event_admission")


class EventStageFailure(Exception):
    def __init__(self, stage: str, detail: dict):
        super().__init__(stage)
        self.stage = stage
        self.detail = detail


def admit_event(event: dict[str, Any], participants: list[dict],
                conn) -> dict[str, Any]:
    """event 字段含：event_id/name/event_type/description/time_text/period/
    place/place_entity_id/quote_span/chunk_text/chunk_id/resource_id/
    lightrag_doc_id/entity_id(已解析 Event 实体)。participants 已含 entity_id。"""
    stages: list[tuple[str, str, dict]] = []

    def record(stage: str, result: str, detail: dict) -> None:
        stages.append((stage, result, detail))
        if result == "FAIL":
            raise EventStageFailure(stage, detail)

    try:
        # 1 schema
        if not event.get("name") or not event.get("event_type"):
            record("event_schema_validation", "FAIL", {"reason": "缺名称或类型"})
        record("event_schema_validation", "PASS", {"name": event["name"][:40]})

        # 2 entity_resolution（Event 实体已解析存在）
        if not event.get("entity_id"):
            record("entity_resolution", "FAIL", {"reason": "Event 实体未解析"})
        record("entity_resolution", "PASS",
               {"entity_id": str(event["entity_id"])})

        # 3 time_validation
        time_ok = bool(event.get("time_text") or event.get("period"))
        record("time_validation", "PASS" if time_ok else "FAIL",
               {"time": event.get("time_text", "")})

        # 4 place_validation
        place_ok = bool(event.get("place_entity_id") or event.get("place"))
        record("place_validation", "PASS" if place_ok else "FAIL",
               {"place": event.get("place", "")})

        # 5 participant_validation（至少 1 个已解析参与者）
        valid_parts = [p for p in participants if p.get("entity_id")]
        if len(valid_parts) == 0:
            record("participant_validation", "FAIL", {"reason": "无已解析参与者"})
        record("participant_validation", "PASS", {"count": len(valid_parts)})

        # 6 evidence_validation（quote 绑定真实 chunk 文本）
        match = bind(event.get("quote_span", ""), event.get("chunk_text", ""))
        if match == "FAILED":
            record("evidence_validation", "FAIL", {"reason": "quote 无法定位"})
        record("evidence_validation", "PASS", {"match_status": match})

        # 7 yangtze_scope
        with conn.cursor() as cur:
            cur.execute("SELECT admission_status FROM resources WHERE resource_id=%s",
                        (event.get("resource_id"),))
            r = cur.fetchone()
        adm = r[0] if r else "REJECTED"
        if adm not in ("CORE", "CONTEXT"):
            record("yangtze_scope", "FAIL", {"reason": f"资源状态 {adm}"})
        record("yangtze_scope", "PASS", {"resource_admission": adm})

        # 8 conflict_detection（同类型同名不同事件 → CONTESTED）
        with conn.cursor() as cur:
            cur.execute("""SELECT e2.event_id FROM events e2
                           WHERE e2.canonical_name=%s AND e2.event_type=%s
                             AND e2.event_id<>%s AND e2.status='ADMITTED' LIMIT 1""",
                        (event["name"], event["event_type"], event["event_id"]))
            dup = cur.fetchone()
        contested = dup is not None
        record("conflict_detection", "PASS",
               {"contested": contested, "dup": str(dup[0]) if dup else None})

        # 9 admission
        status = "CONTESTED" if contested else (
            "ADMITTED" if (time_ok and place_ok and match != "FAILED") else "CANDIDATE")
        record("admission", "PASS", {"status": status})

        # 落库：状态 + event_evidence
        with conn.cursor() as cur:
            cur.execute("""UPDATE events SET status=%s, chunk_id=%s, match_status=%s
                           WHERE event_id=%s""",
                        (status, event.get("chunk_id"), match, event["event_id"]))
            if status == "ADMITTED":
                cur.execute(
                    """INSERT INTO event_evidence
                       (event_id, resource_id, chunk_id, quote_span, match_status)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (event["event_id"], event.get("resource_id"),
                     event.get("chunk_id"), event["quote_span"], match))
            for stage, result, detail in stages:
                cur.execute(
                    """INSERT INTO provenance_events
                       (object_type, object_id, action, actor, detail)
                       VALUES ('event', %s, %s, 'event_admission', %s)""",
                    (str(event["event_id"]), f"stage_{stage}",
                     json.dumps({"result": result, **detail}, ensure_ascii=False)))
        conn.commit()
        return {"event_id": str(event["event_id"]), "status": status, "stages": stages}

    except EventStageFailure as fail:
        with conn.cursor() as cur:
            cur.execute("UPDATE events SET status='REJECTED' WHERE event_id=%s",
                        (event["event_id"],))
            cur.execute(
                """INSERT INTO provenance_events
                   (object_type, object_id, action, actor, detail)
                   VALUES ('event', %s, 'rejected', 'event_admission', %s)""",
                (str(event["event_id"]), json.dumps(
                    {"stage": fail.stage, **fail.detail}, ensure_ascii=False)))
        conn.commit()
        return {"event_id": str(event["event_id"]), "status": "REJECTED",
                "failed_stage": fail.stage}
