# -*- coding: utf-8 -*-
"""Phase 5：Candidate Entity / Event / Claim 抽取（来自通过准入的 chunk）。

硬规则：
- 每条 claim/event 必须携带 quote_span（原文逐字摘抄）
- 推断性"可能有关联"不输出
- predicate 只能取自受控本体
产出：candidate_entities / events / claims(CANDIDATE)——不直接写 ADMITTED。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from config.settings import SETTINGS
from extensions.llm import chat, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.extract")

with open(SETTINGS.data_dir.parent / "yangtze" / "schema" / "predicates.yaml",
          encoding="utf-8") as _f:
    _PRED = yaml.safe_load(_f)["predicates"]

ENTITY_TYPES = {"Person", "Place", "Organization", "Institution", "Event", "Work",
                "Artifact", "Heritage", "Site", "Practice", "Concept", "WaterSystem",
                "Route", "NaturalObject", "EthnicGroup"}


def predicate_names() -> set[str]:
    return set(_PRED.keys())


def predicate_domain_range(pid: str) -> tuple[list[str], list[str]] | None:
    p = _PRED.get(pid)
    if not p:
        return None
    return p.get("domain", []), p.get("range", [])


def extract(title: str, chunks: list[tuple[int, str]]) -> dict[str, Any]:
    """从通过 chunk 准入的文本抽取实体/事件/claims。chunks: [(index, text)]。"""
    joined = "\n\n".join(text for _, text in chunks)[:9000]
    prompt = PROMPTS["entity_event_claim_extraction_v1"].format(title=title, chunks=joined)
    raw = chat([{"role": "user", "content": prompt}], max_tokens=3500, temperature=0.1)
    data = parse_json(raw) or {}

    entities = []
    for e in data.get("entities") or []:
        name = str(e.get("name", "")).strip()
        etype = str(e.get("type", "")).strip()
        if not name or etype not in ENTITY_TYPES:
            continue
        entities.append({"name": name[:80], "type": etype,
                         "description": str(e.get("description", ""))[:300]})

    events = []
    for ev in data.get("events") or []:
        qs = str(ev.get("quote_span", "")).strip()
        name = str(ev.get("name", "")).strip()
        if not name or not qs:
            continue
        events.append({
            "name": name[:100],
            "event_type": str(ev.get("event_type", "其他"))[:20],
            "time": str(ev.get("time", "") or "")[:60],
            "period": str(ev.get("period", "") or "")[:40],
            "place": str(ev.get("place", "") or "")[:60],
            "participants": [str(p)[:60] for p in (ev.get("participants") or [])][:10],
            "organizations": [str(o)[:60] for o in (ev.get("organizations") or [])][:10],
            "description": str(ev.get("description", ""))[:400],
            "quote_span": qs[:300],
        })

    claims = []
    for c in data.get("claims") or []:
        pid = str(c.get("predicate", "")).strip()
        qs = str(c.get("quote_span", "")).strip()
        subj = str(c.get("subject", "")).strip()
        obj = str(c.get("object", "")).strip()
        if pid not in predicate_names() or not subj or not obj or not qs:
            continue          # 未注册谓词/缺主体/缺引文：直接丢弃（准入硬规则）
        claims.append({
            "subject": subj[:80], "predicate": pid, "object": obj[:80],
            "time": str(c.get("time", "") or "")[:60],
            "place": str(c.get("place", "") or "")[:60],
            "quote_span": qs[:300],
        })

    return {"entities": entities, "events": events, "claims": claims,
            "model": SETTINGS.llm_model,
            "prompt_version": SETTINGS.prompt_extraction,
            "pipeline_version": SETTINGS.pipeline_version}


def persist_candidates(resource_id: str, doc_id: str, result: dict[str, Any], conn) -> int:
    """候选实体 + 事件载荷 + 待准入 claims 入库（供后续阶段断点续跑消费）。"""
    import hashlib
    n = 0
    with conn.cursor() as cur:
        # 事件载荷持久化（含 time/place/participants，供断点续跑）
        for ev in result["events"]:
            cur.execute(
                """INSERT INTO events
                   (event_type, canonical_name, description, time_text, period,
                    participants_json, organizations_json, status, resource_id,
                    quote_span, extraction_model, prompt_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'CANDIDATE',%s,%s,%s,%s)
                   ON CONFLICT (resource_id, canonical_name) DO NOTHING""",
                (ev["event_type"], ev["name"], ev["description"], ev.get("time"),
                 ev.get("period"), json.dumps(ev["participants"], ensure_ascii=False),
                 json.dumps(ev["organizations"], ensure_ascii=False),
                 resource_id, ev["quote_span"], result["model"],
                 result["prompt_version"]))
        # 待准入 claims 暂存
        for c in result["claims"]:
            cur.execute(
                """INSERT INTO pending_claims
                   (resource_id, subject, predicate, object, time_text, place, quote_span)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (resource_id, c["subject"], c["predicate"], c["object"],
                 c.get("time"), c.get("place"), c["quote_span"]))
        # 事件名也登记为候选实体（类型 Event），供 ER 统一消歧
        for ev in result["events"]:
            cid = "ce-" + hashlib.sha1(
                f"{resource_id}|{ev['name']}|Event".encode()).hexdigest()[:16]
            cur.execute(
                """INSERT INTO candidate_entities
                   (candidate_id, surface_name, normalized_name, entity_type, description,
                    resource_id, document_id, extraction_model, prompt_version,
                    pipeline_version)
                   VALUES (%s,%s,%s,'Event',%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (candidate_id) DO NOTHING""",
                (cid, ev["name"], ev["name"].strip().lower(), ev["description"][:300],
                 resource_id, doc_id, result["model"], result["prompt_version"],
                 result["pipeline_version"]))
        for e in result["entities"]:
            cid = "ce-" + hashlib.sha1(
                f"{resource_id}|{e['name']}|{e['type']}".encode()).hexdigest()[:16]
            cur.execute(
                """INSERT INTO candidate_entities
                   (candidate_id, surface_name, normalized_name, entity_type, description,
                    resource_id, document_id, extraction_model, prompt_version, pipeline_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (candidate_id) DO NOTHING""",
                (cid, e["name"], e["name"].strip().lower(), e["type"], e["description"],
                 resource_id, doc_id, result["model"], result["prompt_version"],
                 result["pipeline_version"]))
            n += 1
        cur.execute(
            """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
               VALUES ('resource', %s, 'extraction_done', 'extraction', %s)""",
            (resource_id, json.dumps({"candidates": n, "events": len(result["events"]),
                                      "claims": len(result["claims"])},
                                     ensure_ascii=False)))
    conn.commit()
    return n
