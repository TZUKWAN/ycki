# -*- coding: utf-8 -*-
"""evidence_bundle.py — 证据束引擎 v2（§7 多通道检索重写）。

通道（§7.1）：
  lexical   pg_trgm 三元组相似 + ILIKE 兜底（词汇召回通道）
  entity    断言端点实体名命中（canonical entity overlap）
  event     ADMITTED 事件名/描述命中（事件引文已通过分段定位验证）
  graph     命中实体的一跳邻域断言证据（graph neighborhood）
  semantic  bge-m3 嵌入余弦（semantic relevance）

排序（§7.2）：score = 0.30*semantic + 0.20*field + 0.15*authority
              + 0.15*independence + 0.10*directness + 0.05*temporal + 0.05*novelty
MMR 多样性重排（§7.4）：λ 抑制近重复 + 来源簇配额。

独立来源单位（§7.3）：COALESCE(source_cluster_id, resource_id)，不再只数域名。

充分度输出（§7.5）：field_coverage / independent_clusters /
authority_distribution / temporal_coverage / spatial_coverage /
contradiction_coverage。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg2

from extensions.llm import embed  # noqa: E402

_DISPUTE_RE = re.compile(r"争议|另一说|一说|质疑|存疑|考证|或云|异说|分歧")
_YEAR_RE = re.compile(r"(公元前?\s*\d+|\d{3,4})")
_FIELD_HINTS = {
    "time": ("年", "元年", "历", "世纪", "时期", "朝代"),
    "origin": ("起源", "来源", "发源", "始于", "自", "迁出"),
    "destination": ("迁入", "到达", "抵达", "流入", "传入", "至"),
    "content": ("盐", "茶", "米", "粮", "瓷", "铜", "移民", "商", "货", "佛教", "技术"),
    "core_practices": ("习俗", "祭祀", "仪式", "技艺", "表演", "实践"),
    "carriers": ("人群", "移民", "商帮", "僧", "工匠", "士人", "群体"),
    "mechanism": ("通过", "借助", "由于", "因为", "机制", "制度", "政策"),
}


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _trigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s or "")
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))} if len(s) >= 3 else {s}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


@dataclass
class Bundle:
    seed_id: str
    seed_name: str
    kind: str
    system_name: str | None
    entities: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    resource_ids: set[str] = field(default_factory=set)
    source_domains: set[str] = field(default_factory=set)
    sufficiency: dict[str, Any] = field(default_factory=dict)

    @property
    def distinct_resources(self) -> int:
        return len(self.resource_ids)

    @property
    def distinct_source_domains(self) -> int:
        return len(self.source_domains)

    def summary(self) -> dict[str, Any]:
        return {
            "seed": self.seed_id, "kind": self.kind,
            "entities": len(self.entities), "events": len(self.events),
            "quotes": len(self.quotes),
            "distinct_resources": self.distinct_resources,
            "distinct_source_domains": self.distinct_source_domains,
            **({} if not self.sufficiency else {"sufficiency": self.sufficiency}),
        }


def _base_select(cur, where: str, params: tuple, limit: int) -> list[dict[str, Any]]:
    cur.execute(f"""
        SELECT e.evidence_id, e.claim_id, e.quote_span, e.resource_id,
               r.title, r.source_domain, r.published_at, s.authority_level,
               r.source_cluster_id, c.subject_id, c.object_id,
               t.raw_text AS time_text
        FROM evidence e
        JOIN claims c ON c.claim_id = e.claim_id AND c.status = 'ADMITTED'
        LEFT JOIN resources r ON r.resource_id = e.resource_id
        LEFT JOIN sources s ON s.source_id = r.source_id
        LEFT JOIN timespans t ON t.timespan_id = c.timespan_id
        WHERE e.quote_span IS NOT NULL AND {where}
        LIMIT %s
    """, (*params, limit))
    return [dict(r) for r in cur.fetchall()]


def build_bundle(cur: psycopg2.extensions.cursor, seed: dict[str, Any],
                 max_quotes: int = 40) -> Bundle:
    """多通道聚合 + 统一评分 + MMR 多样性选束。"""
    b = Bundle(seed_id=seed["id"], seed_name=seed["name"], kind=seed["kind"],
               system_name=seed.get("system"))
    terms: list[str] = [t for t in (seed.get("terms") or [seed["name"]]) if t]
    pool: dict[str, dict[str, Any]] = {}   # quote 归一键 → row（跨通道去重）

    def add(rows: list[dict[str, Any]], channel: str) -> None:
        for r in rows:
            key = _norm_key(r.get("quote_span") or "")
            if not key:
                continue
            if key in pool:
                if channel not in pool[key]["channels"]:
                    pool[key]["channels"].append(channel)
                continue
            r["channels"] = [channel]
            pool[key] = r

    # ---- 1 lexical：ILIKE + trigram ----
    like_ors = " OR ".join(["e.quote_span ILIKE %s"] * len(terms))
    add(_base_select(cur, f"({like_ors})", tuple(f"%{t}%" for t in terms), 120), "lexical")
    sim_ors = " OR ".join(["SIMILARITY(e.quote_span, %s) > 0.28"] * len(terms))
    add(_base_select(cur, f"({sim_ors})", tuple(terms), 120), "lexical")

    # ---- 2 entity：断言端点实体命中 ----
    ent_like = " OR ".join(["ce.canonical_name ILIKE %s"] * len(terms))
    cur.execute(f"""SELECT DISTINCT c.claim_id FROM claims c
                    JOIN canonical_entities ce ON ce.entity_id IN (c.subject_id, c.object_id)
                    WHERE c.status='ADMITTED' AND ({ent_like}) LIMIT 200""",
                tuple(f"%{t}%" for t in terms))
    claim_ids = [r[0] for r in cur.fetchall()]
    if claim_ids:
        cur.execute("""
            SELECT e.evidence_id, e.claim_id, e.quote_span, e.resource_id,
                   r.title, r.source_domain, r.published_at, s.authority_level,
                   r.source_cluster_id, c.subject_id, c.object_id,
                   t.raw_text AS time_text
            FROM evidence e JOIN claims c ON c.claim_id=e.claim_id AND c.status='ADMITTED'
            LEFT JOIN resources r ON r.resource_id=e.resource_id
            LEFT JOIN sources s ON s.source_id=r.source_id
            LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
            WHERE e.claim_id = ANY(%s::uuid[]) LIMIT 120""", (claim_ids,))
        add([dict(r) for r in cur.fetchall()], "entity")

    # ---- 3 event：ADMITTED 事件命中（引文已分段验证） ----
    ev_like = " OR ".join(["(ev.canonical_name ILIKE %s OR COALESCE(ev.description,'') ILIKE %s)"] * len(terms))
    params: list[Any] = []
    for t in terms:
        params += [f"%{t}%", f"%{t}%"]
    cur.execute(f"""SELECT ev.event_id, ev.canonical_name, ev.event_type, ev.period, ev.time_text,
                          ev.description, ev.quote_span, ev.resource_id, ev.chunk_id, ev.match_status,
                          ce.canonical_name AS place_name
                   FROM events ev LEFT JOIN canonical_entities ce ON ev.place_entity_id=ce.entity_id
                   WHERE ev.status='ADMITTED' AND ev.quote_span IS NOT NULL AND ({ev_like})
                   LIMIT 40""", tuple(params))
    for r in cur.fetchall():
        d = dict(r)
        key = _norm_key(d.get("quote_span") or "")
        if not key or key in pool:
            continue
        pool[key] = {
            "evidence_id": None, "claim_id": None, "quote_span": d["quote_span"],
            "resource_id": d["resource_id"], "title": d["canonical_name"],
            "source_domain": None, "published_at": None, "authority_level": None,
            "source_cluster_id": None, "subject_id": None, "object_id": None,
            "time_text": d.get("time_text") or d.get("period"), "channels": ["event"],
            "event_id": str(d["event_id"]),
        }

    # ---- 4 graph：命中实体的一跳邻域 ----
    if claim_ids:
        cur.execute("""SELECT DISTINCT c2.claim_id FROM claims c2
                       WHERE c2.status='ADMITTED' AND (
                           c2.subject_id IN (SELECT object_id FROM claims WHERE claim_id = ANY(%s::uuid[]))
                        OR c2.object_id   IN (SELECT subject_id FROM claims WHERE claim_id = ANY(%s::uuid[])))
                       LIMIT 120""", (claim_ids, claim_ids))
        hop_ids = [r[0] for r in cur.fetchall()]
        if hop_ids:
            cur.execute("""
                SELECT e.evidence_id, e.claim_id, e.quote_span, e.resource_id,
                       r.title, r.source_domain, r.published_at, s.authority_level,
                       r.source_cluster_id, c.subject_id, c.object_id,
                       t.raw_text AS time_text
                FROM evidence e JOIN claims c ON c.claim_id=e.claim_id AND c.status='ADMITTED'
                LEFT JOIN resources r ON r.resource_id=e.resource_id
                LEFT JOIN sources s ON s.source_id=r.source_id
                LEFT JOIN timespans t ON t.timespan_id=c.timespan_id
                WHERE e.claim_id = ANY(%s::uuid[]) LIMIT 80""", (hop_ids,))
            add([dict(r) for r in cur.fetchall()], "graph")

    # ---- 5 fulltext：湖内 CORE/CONTEXT 全文命中片段（§7.1 第6通道）----
    # 动机：大量 CORE 资源的 claim 在实体解析阶段未通过，但其原文含关键证据；
    # 只允许 ADMITTED claim 证据进束会让检索死于上游失败。此处直接从湖文本
    # 抽取词命中片段（±110 字符窗），每资源最多 2 片段，可被原文定位验证。
    ft_like = " OR ".join(["r.title ILIKE %s", "r.search_query ILIKE %s"] * 1)
    ft_params: list[Any] = []
    ft_ors = []
    for t in terms:
        ft_ors.append("r.title ILIKE %s")
        ft_params.append(f"%{t}%")
    for t in terms:
        ft_ors.append("r.search_query ILIKE %s")
        ft_params.append(f"%{t}%")
    cur.execute(f"""SELECT r.resource_id, r.title, r.source_domain, r.published_at,
                           s.authority_level, r.source_cluster_id, r.text_path
                    FROM resources r LEFT JOIN sources s ON s.source_id=r.source_id
                    WHERE r.admission_status IN ('CORE','CONTEXT')
                      AND r.text_path IS NOT NULL AND ({' OR '.join(ft_ors)})
                    ORDER BY char_length(COALESCE(r.title, '')) DESC LIMIT 14""",
                tuple(ft_params))
    for row in cur.fetchall():
        d = dict(row)
        try:
            tp = d.get("text_path")
            full = Path(tp).read_text(encoding="utf-8", errors="replace") if tp and Path(tp).exists() else ""
        except Exception:
            continue
        if not full:
            continue
        snippet_count = 0
        seen_spans: set[int] = set()
        for t in terms:
            start = 0
            while snippet_count < 2:
                idx = full.find(t, start)
                if idx < 0:
                    break
                bucket = idx // 400
                if bucket in seen_spans:
                    start = idx + len(t)
                    continue
                seen_spans.add(bucket)
                s0, s1 = max(0, idx - 110), min(len(full), idx + len(t) + 110)
                snippet = full[s0:s1].strip()
                if len(_norm_key(snippet)) >= 30:
                    key = _norm_key(snippet)
                    if key and key not in pool:
                        pool[key] = {
                            "evidence_id": None, "claim_id": None, "quote_span": snippet,
                            "resource_id": d["resource_id"], "title": d["title"],
                            "source_domain": d["source_domain"], "published_at": d["published_at"],
                            "authority_level": d["authority_level"],
                            "source_cluster_id": d["source_cluster_id"],
                            "subject_id": None, "object_id": None, "time_text": None,
                            "channels": ["fulltext"],
                        }
                    snippet_count += 1
                start = idx + len(t)

    # 相关实体（供 prompt 与充分度）
    ent_like2 = " OR ".join(["(ce.canonical_name ILIKE %s OR ce.description ILIKE %s)"] * len(terms))
    eparams: list[Any] = []
    for t in terms:
        eparams += [f"%{t}%", f"%{t}%"]
    cur.execute(f"""SELECT ce.entity_id, ce.canonical_name, ce.entity_type, ce.description
                    FROM canonical_entities ce
                    WHERE ce.merged_into IS NULL AND {ent_like2}
                    ORDER BY char_length(ce.canonical_name) LIMIT 25""", eparams)
    b.entities = [dict(r) for r in cur.fetchall()]

    rows = [r for r in pool.values() if len(_norm_key(r.get("quote_span") or "")) >= 12]
    rows = _score_and_select(rows, terms, seed, max_quotes)
    for q in rows:
        b.quotes.append(q)
        if q.get("resource_id"):
            b.resource_ids.add(str(q["resource_id"]))
        if q.get("source_domain"):
            b.source_domains.add(q["source_domain"])

    b.sufficiency = _sufficiency(b, seed)
    return b


def _norm_key(s: str) -> str:
    return re.sub(r"[\s，。、；：？！\"'（）()\[\]【】《》<>—\-…·,.:;?!]+", "", s or "")[:120]


def _score_and_select(rows: list[dict[str, Any]], terms: list[str],
                      seed: dict[str, Any], max_quotes: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    rows = rows[:64]
    # ---- semantic：嵌入（批量；失败退化为 0.5 中性分） ----
    try:
        vecs = embed([f"{seed['name']}。{(r.get('quote_span') or '')[:200]}" for r in rows])
        qv = vecs[0]
        sems = [_cos(qv, v) for v in vecs[1:]]
        sems = [1.0] + sems
    except Exception:
        sems = [0.5] * len(rows)

    fields = seed.get("fields") or []
    for i, r in enumerate(rows):
        qs = r.get("quote_span") or ""
        f_hits = sum(1 for f in fields if any(h in qs for h in _FIELD_HINTS.get(f, ())))
        term_hits = sum(1 for t in terms if t in qs)
        auth = (r.get("authority_level") or "").upper()
        cluster = str(r.get("source_cluster_id") or f"res:{r.get('resource_id')}")
        ln = len(_norm_key(qs))
        yrs = []
        for _y in _YEAR_RE.findall(qs):
            _digits = re.sub(r"[^0-9]", "", _y)
            if _digits:
                yrs.append(int(_digits))
        r["_cluster"] = cluster
        r["_year"] = yrs[0] if yrs else None
        r["score"] = round(
            0.30 * max(0.0, min(1.0, sems[i]))
            + 0.20 * min(1.0, 0.25 * f_hits + 0.15 * term_hits)
            + 0.15 * {"S": 1.0, "A": 0.85}.get(auth, 0.4 if auth == "C" else 0.6)
            + 0.15 * (1.0 if cluster.startswith("cl:") else 0.55)
            + 0.10 * (1.0 if 30 <= ln <= 220 else (0.6 if ln > 220 else 0.3))
            + 0.05 * (1.0 if yrs else 0.4)
            + 0.05 * (1.0 if _DISPUTE_RE.search(qs) else 0.6), 4)

    rows.sort(key=lambda r: -r["score"])

    # ---- MMR 多样性：λ 抑制近重复 + 簇配额 ----
    tris = [_trigrams(r.get("quote_span") or "") for r in rows]
    selected: list[int] = []
    sel_tris: list[set[str]] = []
    clusters: dict[str, int] = {}
    LAMBDA = 0.72
    quota = max(3, max_quotes // 4)
    for i, r in enumerate(rows):
        if len(selected) >= max_quotes:
            break
        c = r["_cluster"]
        if clusters.get(c, 0) >= quota:
            continue
        if selected and len(selected) < max_quotes - 2:
            if max(_jaccard(tris[i], t) for t in sel_tris) > LAMBDA:
                continue
        selected.append(i)
        sel_tris.append(tris[i])
        clusters[c] = clusters.get(c, 0) + 1
    if len(selected) < min(max_quotes, 6):
        selected = sorted(set(selected + list(range(min(max_quotes, len(rows))))))[:max_quotes]
    out = [rows[i] for i in sorted(selected)]
    for r in out:
        r.pop("_cluster", None)
        r.pop("_year", None)
    return out


def _sufficiency(b: Bundle, seed: dict[str, Any]) -> dict[str, Any]:
    fields = seed.get("fields") or []
    cov = {}
    for f in fields:
        hints = _FIELD_HINTS.get(f, ())
        cov[f] = any(any(h in (q.get("quote_span") or "") for h in hints) for q in b.quotes)
    clusters = {str(q.get("source_cluster_id") or f"res:{q.get('resource_id')}") for q in b.quotes}
    auth: dict[str, int] = {}
    years = []
    for q in b.quotes:
        a = (q.get("authority_level") or "UNKNOWN").upper()
        auth[a] = auth.get(a, 0) + 1
        m = [int(re.sub(r"[^0-9]", "", y)) for y in _YEAR_RE.findall(q.get("quote_span") or "")
             if re.sub(r"[^0-9]", "", y)]
        if m:
            years.append(m[0])
    places = set()
    for q in b.quotes:
        for t in (seed.get("terms") or [seed["name"]]):
            if len(t) >= 2 and t in (q.get("quote_span") or ""):
                places.add(t)
    return {
        "field_coverage": cov,
        "field_coverage_ratio": (round(sum(cov.values()) / len(cov), 3) if cov else None),
        "independent_clusters": len(clusters),
        "authority_distribution": auth,
        "temporal_coverage": [min(years), max(years)] if years else None,
        "spatial_coverage": sorted(places)[:12],
        "contradiction_coverage": sum(1 for q in b.quotes if _DISPUTE_RE.search(q.get("quote_span") or "")),
    }


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
