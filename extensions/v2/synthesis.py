# -*- coding: utf-8 -*-
"""synthesis.py — 高阶结构合成与准入（goal §32-§50 / G07-G09）。

从证据束（跨文档、已验证引文）合成 CulturalTradition / CulturalProcess /
CulturalFlow 候选，经确定性证据核验与准入规则后写库。

铁律：
  §30 禁止一条证据支撑一个高阶对象；ADMITTED 至少 2 个独立来源（§14/§35）。
  §40 过程证据必须按字段分解；时间/身份字段 100% 有证据（§41）。
  §43 流动硬门禁：origin/destination/content/evidence 缺一即 FAIL；
      路线未知允许 UNKNOWN，禁止脑补水路（§43）。
  §46 LLM 只能引用束内编号引文，禁止编造证据文本。
  §44-45 解释与事实分层：综合出的概括属于 STRUCTURAL_INFERENCE，
      学术观点必须来自来源文本并标注。

状态：ADMITTED / SUPPORTED（单来源）/ CANDIDATE（证据不足）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import psycopg2
import psycopg2.extras

from extensions.llm import chat, parse_json
from extensions.v2.evidence_bundle import Bundle, build_bundle, bundle_prompt_blocks

LOG = logging.getLogger("v2.synthesis")

RULE_VERSION = "synthesis_rule_v2_0"
SYNTH_PROMPT_VERSION = "v2_synthesis_v1"

REQUIRED_FIELDS: dict[str, list[str]] = {
    "PROCESS": ["time", "origin", "destination", "actors", "mechanism", "outcomes"],
    "TRADITION": ["origin_time_place", "core_practices", "carriers", "development"],
    "FLOW": ["origin", "destination", "content"],
}
KEY_FIELDS: dict[str, list[str]] = {
    "PROCESS": ["time"],
    "TRADITION": ["core_practices"],
    "FLOW": ["origin", "destination", "content"],
}
ADMIT_MIN_COVERAGE = 0.85
ADMIT_MIN_RESOURCES = 2
MIN_BUNDLE_RESOURCES = 2

_QID = re.compile(r"^Q\d+$")


class SynthesisError(RuntimeError):
    pass


# ----------------------------------------------------------------------
# prompt
# ----------------------------------------------------------------------

_PROMPT_HEAD = (
    "你是长江文化知识基础设施的结构合成引擎。下面给出围绕一个候选对象的编号证据束"
    "（每条含编号、引文、来源标题、时间）。你只能引用这些编号引文（quote_ids 用 Q 编号），"
    "严禁编造束中不存在的证据。对证据不支持的字段，留空并写进 uncertainty。"
    "所有 value 用简体中文、不超过60字。只输出 JSON。\n\n"
    "候选类型：{kind}\n候选名称：{name}\n所属文化系统：{system}\n\n"
    "证据束：\n{blocks}\n\n"
    "输出 JSON schema（字段值均为 {{value, quotes: [Q编号]}}，stages/regional_variants 为数组）：\n"
)

_SCHEMA: dict[str, str] = {
    "PROCESS": (
        '{"name": str, "summary": str,'
        ' "time": {"start": str, "end": str, "value": str, "quotes": []},'
        ' "origin": {..}, "destination": {..}, "actors": {value, quotes},'
        ' "mechanism": {..}, "causes": {..}, "outcomes": {..}, "long_term_impacts": {..},'
        ' "stages": [{"name": str, "time": str, "quotes": []} 至少2个],'
        ' "why_yangtze": str, "uncertainty": [str]}'
    ),
    "TRADITION": (
        '{"name": str, "summary": str,'
        ' "origin_time_place": {..}, "core_practices": {..}, "carriers": {..},'
        ' "development": {..},'
        ' "regional_variants": [{"region": str, "feature": str, "quotes": []}],'
        ' "modern_forms": {..},'
        ' "why_yangtze": str, "uncertainty": [str]}'
    ),
    "FLOW": (
        '{"name": str, "summary": str,'
        ' "origin": {..}, "destination": {..}, "content": {..},'
        ' "carrier": {..}, "time": {..},'
        ' "route": {value: 具体路线或"UNKNOWN", quotes},'
        ' "mechanism": {..}, "impact": {..},'
        ' "why_yangtze": str, "uncertainty": [str]}'
    ),
}


def _render_prompt(kind: str, seed: dict[str, Any], b: Bundle) -> str:
    blocks = bundle_prompt_blocks(b)
    lines = []
    for blk in blocks:
        lines.append(f"[{blk['id']}] (来源: {blk['resource']}; 时间: {blk['time'] or '未知'}) {blk['quote']}")
    return (
        _PROMPT_HEAD.format(kind=kind, name=seed["name"], system=b.system_name or "未指定",
                            blocks="\n".join(lines) or "(无)")
        + _SCHEMA[kind]
    )


# ----------------------------------------------------------------------
# 核验
# ----------------------------------------------------------------------

def _check_field(obj: dict[str, Any], key: str, valid_ids: set[str]) -> tuple[bool, list[str]]:
    """返回 (是否有实质内容+证据, 引用过的Q id 列表)。"""
    fld = obj.get(key)
    if not isinstance(fld, dict):
        return False, []
    value = (fld.get("value") or fld.get("start") or "").strip()
    quotes = [q for q in (fld.get("quotes") or []) if isinstance(q, str) and _QID.match(q)]
    used = [q for q in quotes if q in valid_ids]
    if key == "time" and "start" in fld:
        ok = bool((fld.get("start") or "").strip()) and len(used) > 0
        return ok, used
    ok = bool(value) and len(used) > 0
    return ok, used


def verify_and_admit(kind: str, b: Bundle, obj: dict[str, Any]) -> dict[str, Any]:
    """确定性核验 LLM 输出 → 覆盖率 + 准入决定 + 引用明细。"""
    valid_ids = {f"Q{i}" for i in range(len(b.quotes))}
    required = REQUIRED_FIELDS[kind]
    key_fields = KEY_FIELDS[kind]

    used_quotes: dict[str, list[str]] = {}
    supported: list[str] = []
    for f in required:
        ok, used = _check_field(obj, f, valid_ids)
        if ok:
            supported.append(f)
        if used:
            used_quotes[f] = used
    # 附加字段（causes/impacts/modern_forms 等）的证据也收集
    for f, fld in obj.items():
        if isinstance(fld, dict) and f not in used_quotes:
            _, used = _check_field(obj, f, valid_ids)
            if used:
                used_quotes[f] = used
    stages = obj.get("stages") or []
    if kind == "PROCESS":
        valid_stages = [s for s in stages if isinstance(s, dict) and (s.get("name") or "").strip()
                        and any(_QID.match(str(q)) and str(q) in valid_ids for q in (s.get("quotes") or []))]
        if len(valid_stages) >= 2:
            supported.append("stages")
            used_quotes["stages"] = [q for s in valid_stages for q in s.get("quotes", [])]
    variants = obj.get("regional_variants") or []
    if kind == "TRADITION":
        valid_variants = [v for v in variants if isinstance(v, dict) and (v.get("region") or "").strip()
                          and any(_QID.match(str(q)) and str(q) in valid_ids for q in (v.get("quotes") or []))]
        if valid_variants:
            supported.append("regional_variants")
            used_quotes["regional_variants"] = [q for v in valid_variants for q in v.get("quotes", [])]

    coverage = len(supported) / len(required)
    key_ok = all(f in supported for f in key_fields)

    # 被引引文涉及的独立资源数
    idx2res = {f"Q{i}": str(q["resource_id"]) for i, q in enumerate(b.quotes)}
    cited_resources = {idx2res[q] for qs in used_quotes.values() for q in qs if q in idx2res}

    if kind == "FLOW":
        hard_missing = [f for f in ("origin", "destination", "content") if f not in supported]
        if hard_missing:
            return {"decision": "REJECT", "reason": f"flow hard gate missing: {hard_missing}",
                    "coverage": coverage, "cited_resources": sorted(cited_resources),
                    "supported_fields": supported}
    if key_fields and not key_ok:
        return {"decision": "CANDIDATE", "reason": f"key fields without evidence: {key_fields}",
                "coverage": coverage, "cited_resources": sorted(cited_resources),
                "supported_fields": supported}

    if len(cited_resources) >= ADMIT_MIN_RESOURCES and coverage >= ADMIT_MIN_COVERAGE:
        decision = "ADMITTED"
    elif len(cited_resources) >= 1:
        decision = "SUPPORTED"
    else:
        decision = "CANDIDATE"
    reason = (f"coverage={coverage:.2f} cited_resources={len(cited_resources)} "
              f"supported={supported}")
    return {"decision": decision, "reason": reason, "coverage": round(coverage, 3),
            "cited_resources": sorted(cited_resources), "supported_fields": supported,
            "used_quotes": used_quotes}


# ----------------------------------------------------------------------
# 持久化
# ----------------------------------------------------------------------

def _quote_lookup(b: Bundle) -> dict[str, dict[str, Any]]:
    return {f"Q{i}": q for i, q in enumerate(b.quotes)}


def _persist(cur: psycopg2.extensions.cursor, seed: dict[str, Any], b: Bundle,
             obj: dict[str, Any], verdict: dict[str, Any]) -> str:
    kind = seed["kind"]
    ql = _quote_lookup(b)
    primary_q = None
    for qs in verdict.get("used_quotes", {}).values():
        if qs:
            primary_q = qs[0]
            break
    primary = ql.get(primary_q or "", {})
    status = verdict["decision"]
    confidence = {"ADMITTED": 0.8, "SUPPORTED": 0.6, "CANDIDATE": 0.4, "REJECT": 0.2}.get(status, 0.4)

    if kind == "TRADITION":
        variants = obj.get("regional_variants") or []
        cur.execute("""
            INSERT INTO cultural_traditions (tradition_name, origin, historical_development,
                regional_variants, description, status, confidence, resource_id, quote_span)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
            ON CONFLICT (tradition_name) DO UPDATE SET
                origin=EXCLUDED.origin, historical_development=EXCLUDED.historical_development,
                regional_variants=EXCLUDED.regional_variants, description=EXCLUDED.description,
                status=EXCLUDED.status, confidence=EXCLUDED.confidence
            RETURNING tradition_id
        """, (_s(seed["name"]),
              _fval(obj, "origin_time_place"), _fval(obj, "development"),
              json.dumps([{"region": _s(v.get("region")), "feature": _s(v.get("feature"))}
                          for v in variants if isinstance(v, dict)], ensure_ascii=False),
              _s(obj.get("summary"))[:2000],
              status, confidence, str(primary.get("resource_id") or ""),
              (primary.get("quote_span") or "")[:500]))
        tid = str(cur.fetchone()[0])
        cur.execute("DELETE FROM tradition_evidence WHERE tradition_id=%s", (tid,))
        for field_name, qs in verdict.get("used_quotes", {}).items():
            for qid in qs:
                q = ql.get(qid)
                if not q:
                    continue
                cur.execute("""INSERT INTO tradition_evidence
                    (tradition_id, claim_id, evidence_id, resource_id, evidence_role, quote_span)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    (tid, q.get("claim_id"), q.get("evidence_id"), str(q.get("resource_id") or ""),
                     field_name, (q.get("quote_span") or "")[:500]))
        object_id = tid

    elif kind == "PROCESS":
        tm = obj.get("time") or {}
        if isinstance(tm.get("start"), dict):
            tm = {"start": _s(tm.get("start")), "end": _s(tm.get("end")) or None}
        cur.execute("""
            INSERT INTO cultural_processes (process_name, process_type, description,
                start_time, end_time, origin_region, destination_region,
                actors, carriers, mechanisms, causes, outcomes, long_term_impacts,
                status, confidence, resource_id, quote_span, evidence_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (process_name) DO UPDATE SET
                process_type=EXCLUDED.process_type, description=EXCLUDED.description,
                start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                origin_region=EXCLUDED.origin_region, destination_region=EXCLUDED.destination_region,
                actors=EXCLUDED.actors, carriers=EXCLUDED.carriers,
                mechanisms=EXCLUDED.mechanisms, causes=EXCLUDED.causes,
                outcomes=EXCLUDED.outcomes, long_term_impacts=EXCLUDED.long_term_impacts,
                status=EXCLUDED.status, confidence=EXCLUDED.confidence, evidence_count=EXCLUDED.evidence_count
            RETURNING process_id
        """, (_s(seed["name"]), _s(seed.get("type")) or "CULTURAL_PROCESS",
              _s(obj.get("summary"))[:2000],
              _s(tm.get("start"))[:80] or None, _s(tm.get("end"))[:80] or None,
              _fval(obj, "origin"), _fval(obj, "destination"),
              _splt(_fval(obj, "actors")) or None, _splt(_fval(obj, "carriers")) or None,
              _fval(obj, "mechanism"), _fval(obj, "causes"),
              _fval(obj, "outcomes"), _fval(obj, "long_term_impacts"),
              status, confidence, str(primary.get("resource_id") or ""),
              (primary.get("quote_span") or "")[:500],
              len(verdict.get("cited_resources", []))))
        pid = str(cur.fetchone()[0])
        cur.execute("DELETE FROM process_stages WHERE process_id=%s", (pid,))
        for i, st in enumerate(obj.get("stages") or []):
            if not isinstance(st, dict) or not _s(st.get("name")):
                continue
            cur.execute("""INSERT INTO process_stages (process_id, stage_name, stage_order, time_range)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (pid, _s(st.get("name"))[:200], i + 1, _s(st.get("time"))[:120] or None))
        cur.execute("DELETE FROM process_evidence WHERE process_id=%s", (pid,))
        for field_name, qs in verdict.get("used_quotes", {}).items():
            for qid in qs:
                q = ql.get(qid)
                if not q:
                    continue
                cur.execute("""INSERT INTO process_evidence
                    (process_id, field_name, claim_id, evidence_id, resource_id, quote_span)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    (pid, field_name, q.get("claim_id"), q.get("evidence_id"),
                     str(q.get("resource_id") or ""), (q.get("quote_span") or "")[:500]))
        object_id = pid

    elif kind == "FLOW":
        cur.execute("SELECT flow_id FROM cultural_flows WHERE flow_type=%s AND COALESCE(origin,'')=%s "
                    "AND COALESCE(destination,'')=%s LIMIT 1",
                    (seed.get("type") or "CULTURAL_FLOW", _fval(obj, "origin"), _fval(obj, "destination")))
        row = cur.fetchone()
        route = obj.get("route") or {}
        route_val = _s(route.get("value")) or "UNKNOWN"
        if row:
            fid = str(row[0])
            cur.execute("""UPDATE cultural_flows SET content=%s, carrier=%s, time_range=%s, via=%s,
                mechanism=%s, impact=%s, quote_span=%s, resource_id=%s WHERE flow_id=%s""",
                (_fval(obj, "content"), _fval(obj, "carrier"),
                 _fval(obj, "time"), route_val[:400],
                 _fval(obj, "mechanism"), _fval(obj, "impact"),
                 (primary.get("quote_span") or "")[:500],
                 str(primary.get("resource_id") or ""), fid))
        else:
            cur.execute("""INSERT INTO cultural_flows (flow_type, origin, destination, via, time_range,
                carrier, content, mechanism, impact, quote_span, resource_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING flow_id""",
                (seed.get("type") or "CULTURAL_FLOW", _fval(obj, "origin"), _fval(obj, "destination"),
                 route_val[:400], _fval(obj, "time"), _fval(obj, "carrier"), _fval(obj, "content"),
                 _fval(obj, "mechanism"), _fval(obj, "impact"),
                 (primary.get("quote_span") or "")[:500], str(primary.get("resource_id") or "")))
            fid = str(cur.fetchone()[0])
        object_id = fid
    else:
        raise SynthesisError(f"unknown kind {kind}")

    # 准入审计记录（幂等：同对象同决定同规则版本）
    cur.execute("""
        INSERT INTO structural_admissions (object_kind, object_id, decision, checks,
            evidence_coverage, independent_source_clusters, rule_version, reason)
        SELECT %s,%s,%s,%s::jsonb,%s,%s,%s,%s
        WHERE NOT EXISTS (SELECT 1 FROM structural_admissions
            WHERE object_kind=%s AND object_id=%s AND decision=%s AND rule_version=%s)
    """, (kind, object_id, status,
          json.dumps({"coverage": verdict.get("coverage"),
                      "supported_fields": verdict.get("supported_fields"),
                      "prompt_version": SYNTH_PROMPT_VERSION}, ensure_ascii=False),
          verdict.get("coverage"), len(verdict.get("cited_resources", [])),
          RULE_VERSION, verdict.get("reason"),
          kind, object_id, status, RULE_VERSION))
    return object_id


def _s(v: Any) -> str:
    """LLM 字段值安全字符串化（dict 取 value、list 连接）。"""
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, list):
        v = "、".join(str(x) for x in v)
    return (str(v) if v is not None else "").strip()


def _fval(obj: dict[str, Any], key: str) -> str:
    fld = obj.get(key)
    if not isinstance(fld, dict):
        return ""
    v = fld.get("value")
    if isinstance(v, list):
        v = "、".join(str(x) for x in v)
    return (v or "").strip()


def _splt(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[、,，;；]", v or "") if x.strip()][:20]


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def synthesize_candidate(cur: psycopg2.extensions.cursor, seed: dict[str, Any]) -> dict[str, Any]:
    """单个候选：证据束 → LLM 合成 → 核验准入 → 写库。可事务调用、可重放。"""
    b = build_bundle(cur, seed)
    result: dict[str, Any] = {"seed": seed["id"], "name": seed["name"], "kind": seed["kind"],
                              "bundle": b.summary()}
    if b.distinct_resources < MIN_BUNDLE_RESOURCES:
        result["decision"] = "SKIP_INSUFFICIENT_EVIDENCE"
        result["reason"] = f"distinct_resources={b.distinct_resources} < {MIN_BUNDLE_RESOURCES}"
        return result

    prompt = _render_prompt(seed["kind"], seed, b)
    text = chat([{"role": "user", "content": prompt}], max_tokens=2600, temperature=0.2)
    obj = parse_json(text)
    if not obj:
        result["decision"] = "FAIL_LLM_JSON"
        return result
    result["why_yangtze"] = obj.get("why_yangtze") or ""
    result["uncertainty"] = obj.get("uncertainty") or []

    verdict = verify_and_admit(seed["kind"], b, obj)
    result.update(verdict)
    if verdict["decision"] == "REJECT":
        return result
    object_id = _persist(cur, seed, b, obj, verdict)
    result["object_id"] = object_id
    return result
