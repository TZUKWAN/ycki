# -*- coding: utf-8 -*-
"""Phase 2：Resource Scope Gate —— 资源级长江文化准入评审。

CORE    = 内容本身构成长江文化研究对象
CONTEXT = 域外但有明确长江关系（须原文证据）
REJECT  = 无直接结构性关系

结果写 resource_admissions + resources.admission_status，附完整评估元数据。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.resource_gate")

_STATUS_MAP = {"CORE": "CORE", "CONTEXT": "CONTEXT", "REJECT": "REJECTED"}


def evaluate(title: str, text: str, domain: str, source_type: str,
             discovery_topic: str = "", search_query: str = "") -> dict[str, Any]:
    """评审单个资源，返回结构化判定（含版本信息）。不可解析时保守判 REJECT。"""
    prompt = PROMPTS["resource_scope_v1"].format(
        title=title, domain=domain, source_type=source_type,
        discovery_topic=discovery_topic or "（无）", search_query=search_query or "（无）",
        text=text[:6000])
    raw = chat([{"role": "user", "content": prompt}], max_tokens=800)
    data = parse_json(raw) or {}

    role = str(data.get("scope_role", "")).upper()
    if role not in _STATUS_MAP:
        role = "REJECT"

    def _f(key: str) -> float:
        try:
            return max(0.0, min(1.0, float(data.get(key, 0))))
        except (TypeError, ValueError):
            return 0.0

    labels = data.get("topic_labels") or []
    return {
        "scope_role": role,
        "yangtze_relevance": _f("yangtze_relevance"),
        "topic_relevance": _f("topic_relevance"),
        "spatial_relevance": _f("spatial_relevance"),
        "cultural_relevance": _f("cultural_relevance"),
        "geo_scope": str(data.get("geo_scope") or "")[:80],
        "geo_evidence": str(data.get("geo_evidence") or "")[:200],
        "topic_labels": [str(x)[:30] for x in labels][:4],
        "relevance_reason": str(data.get("relevance_reason") or "")[:300],
        "model": SETTINGS.llm_model,
        "prompt_version": SETTINGS.prompt_scope_resource,
        "pipeline_version": SETTINGS.pipeline_version,
    }


def persist(resource_id: str, verdict: dict[str, Any], conn) -> None:
    """写 resource_admissions 评审记录并更新 resources.admission_status。"""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO resource_admissions
               (resource_id, scope_role, yangtze_relevance, topic_relevance,
                spatial_relevance, cultural_relevance, geo_scope, geo_evidence,
                topic_labels, relevance_reason, model, prompt_version, pipeline_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (resource_id, verdict["scope_role"], verdict["yangtze_relevance"],
             verdict["topic_relevance"], verdict["spatial_relevance"],
             verdict["cultural_relevance"], verdict["geo_scope"], verdict["geo_evidence"],
             verdict["topic_labels"], verdict["relevance_reason"], verdict["model"],
             verdict["prompt_version"], verdict["pipeline_version"]))
        cur.execute("UPDATE resources SET admission_status=%s WHERE resource_id=%s",
                    (_STATUS_MAP[verdict["scope_role"]], resource_id))
        cur.execute(
            """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
               VALUES ('resource', %s, 'scope_evaluated', 'resource_gate', %s)""",
            (resource_id, json.dumps({"scope_role": verdict["scope_role"],
                                      "reason": verdict["relevance_reason"]},
                                     ensure_ascii=False)))
    conn.commit()
    log.info("resource %s -> %s", resource_id, verdict["scope_role"])
