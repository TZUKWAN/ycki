# -*- coding: utf-8 -*-
"""evidence_bundle.py — 证据束引擎（goal §29-§31）。

围绕一个候选对象（CulturalTradition / CulturalProcess / CulturalFlow 种子或研究问题）
从既有 canonical_v1 事实层聚合知识：实体、ADMITTED 事件、ADMITTED claim 及其
已验证的 evidence 引文、来源与来源簇。

硬约束（§30）：束必须跨文档。单文档证据不允许支撑任何高阶结构 ADMITTED。
排序（§31）：relevance（词命中密度）> authority（source authority_level）>
independence（来源去重）> temporal/spatial diversity > directness（引文长度）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg2
import psycopg2.extras


@dataclass
class Bundle:
    seed_id: str
    seed_name: str
    kind: str
    system_name: str | None
    entities: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)   # 已验证 evidence 引文
    resource_ids: set[str] = field(default_factory=set)
    source_domains: set[str] = field(default_factory=set)

    @property
    def distinct_resources(self) -> int:
        return len(self.resource_ids)

    @property
    def distinct_source_domains(self) -> int:
        return len(self.source_domains)

    def summary(self) -> dict[str, Any]:
        return {
            "seed": self.seed_id,
            "kind": self.kind,
            "entities": len(self.entities),
            "events": len(self.events),
            "quotes": len(self.quotes),
            "distinct_resources": self.distinct_resources,
            "distinct_source_domains": self.distinct_source_domains,
        }


def build_bundle(cur: psycopg2.extensions.cursor, seed: dict[str, Any],
                 max_quotes: int = 40) -> Bundle:
    """按 terms 聚合证据束。terms 命中 evidence 引文 / 事件名 / 实体名/描述。"""
    b = Bundle(seed_id=seed["id"], seed_name=seed["name"], kind=seed["kind"],
               system_name=seed.get("system"))
    terms: list[str] = list(seed.get("terms") or [seed["name"]])

    like_ors = " OR ".join(["e.quote_span ILIKE %s"] * len(terms))
    params = [f"%{t}%" for t in terms]

    # 1) 已验证引文（claim ADMITTED + evidence 引文），按来源独立性排序
    cur.execute(f"""
        SELECT e.evidence_id, e.claim_id, e.quote_span, e.resource_id,
               r.title, r.source_domain, r.published_at, s.authority_level,
               c.subject_id, c.object_id, t.raw_text AS time_text
        FROM evidence e
        JOIN claims c ON c.claim_id = e.claim_id AND c.status = 'ADMITTED'
        LEFT JOIN resources r ON r.resource_id = e.resource_id
        LEFT JOIN sources s ON s.source_id = r.source_id
        LEFT JOIN timespans t ON t.timespan_id = c.timespan_id
        WHERE {like_ors}
        ORDER BY CASE WHEN e.match_status = 'EXACT' THEN 0 ELSE 1 END,
                 COALESCE(s.authority_level, '3'), e.evidence_id        LIMIT %s
    """, (*params, max_quotes))
    for row in cur.fetchall():
        q = dict(row)
        if q["quote_span"] and q["resource_id"]:
            b.quotes.append(q)
            b.resource_ids.add(str(q["resource_id"]))
            if q["source_domain"]:
                b.source_domains.add(q["source_domain"])

    quote_resource_params: list[str] = list(b.resource_ids) or [""]

    # 2) 相关实体：名称或描述命中 terms
    ent_like = " OR ".join(["(ce.canonical_name ILIKE %s OR ce.description ILIKE %s)"] * len(terms))
    ent_params: list[Any] = []
    for t in terms:
        ent_params += [f"%{t}%", f"%{t}%"]
    cur.execute(f"""
        SELECT ce.entity_id, ce.canonical_name, ce.entity_type, ce.description
        FROM canonical_entities ce
        WHERE ce.merged_into IS NULL AND {ent_like}
        ORDER BY char_length(ce.canonical_name)
        LIMIT 25
    """, ent_params)
    b.entities = [dict(r) for r in cur.fetchall()]

    # 3) ADMITTED 事件：主体命中或引文来源资源命中
    ev_like = " OR ".join(["(ev.canonical_name ILIKE %s OR ev.description ILIKE %s)"] * len(terms))
    ev_params: list[Any] = []
    for t in terms:
        ev_params += [f"%{t}%", f"%{t}%"]
    cur.execute(f"""
        SELECT ev.event_id, ev.canonical_name, ev.event_type, ev.period, ev.time_text,
               ev.description, ce.canonical_name AS place_name
        FROM events ev
        LEFT JOIN canonical_entities ce ON ev.place_entity_id = ce.entity_id
        WHERE ev.status = 'ADMITTED' AND ({ev_like}
              OR ev.resource_id = ANY(%s::text[]))
        ORDER BY ev.event_id
        LIMIT 30
    """, (*ev_params, quote_resource_params))
    b.events = [dict(r) for r in cur.fetchall()]

    return b


def bundle_prompt_blocks(b: Bundle, max_chars_per_quote: int = 420) -> list[dict[str, str]]:
    """把束渲染成 LLM 可引用的编号证据块。"""
    blocks = []
    for i, q in enumerate(b.quotes):
        text = (q["quote_span"] or "").strip()
        if len(text) > max_chars_per_quote:
            text = text[:max_chars_per_quote] + "…"
        blocks.append({
            "id": f"Q{i}",
            "quote": text,
            "resource": q.get("title") or q.get("source_domain") or str(q.get("resource_id")),
            "time": q.get("time_text") or "",
        })
    return blocks
