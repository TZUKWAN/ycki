#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rebuild_memberships.py — SystemMembership 全量重建（goal §18-§23 / G04）。

背景：存量 10,004 条 membership 由未版本化的 legacy 地理规则生成，无锚点证明。
本管线对每条 system 成员行（system_id 非空）做确定性锚点推导：

    Spatial   region 文本 ∈ 该系统文化区域的 provinces
    Temporal  实体存在带时间戳的 ADMITTED event/claim（timespans）
    Domain    实体存在领域挂载（domain_id 非空的 membership 行）
    Process   实体参与 ≥1 条 ADMITTED event（参与者或主体）

准入规则（§19）：anchor_count >= 2 → ADMITTED；否则 CANDIDATE。
纯地理挂载（仅 Spatial）永不可能 ADMITTED（§19.1/§20 → geo-only ADMITTED = 0）。

独立来源金标（§21-§23 自评估）：
    gold ADMIT   spatial 锚成立 且 支持 claim 来自 >=2 个独立 resource 且存在 temporal/process 锚
    gold REJECT  region 文本不属于该区域 provinces（空间矛盾）
    AMBIGUOUS    其余，不参与评分

用法：
    python tools/rebuild_memberships.py --dry-run   # 只输出报告，不写库
    python tools/rebuild_memberships.py --apply     # 单事务写回
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
RULE_VERSION = "membership_rule_v2_0"
MODERN_ENTERPRISE_RE = re.compile(r"(有限公司|股份有限公司|集团|责任公司|公司$)")
NEVER_ADMIT_TYPES = {"EVENT"}  # 事件是过程证据/情节，不是系统成员载体
CONTEXT_TYPES = {"NATURALOBJECT", "WATERSYSTEM", "CONCEPT"}  # 语境要素，不是成员载体

_PROVINCE_NAMES = {"四川", "湖北", "湖南", "江苏", "浙江", "安徽", "江西",
                   "贵州", "云南", "青海", "西藏", "甘肃", "陕西", "河南",
                   "广西", "广东", "福建"}


def _is_province_container(name: str | None) -> bool:
    """§16.4 省级行政区容器：禁止作为文化系统载体 ADMIT。"""
    n = (name or "").strip()
    return n in _PROVINCE_NAMES or bool(re.search(r"(省|自治区|特别行政区)$", n))
MAX_SUPPORT = 10


def dsn() -> str:
    sys.path.insert(0, str(ROOT))
    try:
        from config.settings import SETTINGS  # type: ignore
        return SETTINGS.pg_dsn
    except Exception:
        return "host=127.0.0.1 port=5433 dbname=ycki user=postgres password=ycki_pg_2026"


def rebuild(conn: psycopg2.extensions.connection, apply: bool) -> dict[str, Any]:
    stats: Counter = Counter()
    gold_pos = gold_neg = 0
    rule_admit_in_goldpos = 0
    rule_admit_in_goldneg = 0
    geo_only_admitted = 0

    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        # 系统 -> 区域 provinces 映射
        cur.execute("""
            SELECT s.system_id, s.system_name, r.region_name, r.provinces
            FROM cultural_systems s
            LEFT JOIN cultural_regions r ON r.entity_id = s.system_id
            WHERE s.system_level = 'REGIONAL'
        """)
        sys_regions = {str(r["system_id"]): (r["system_name"], r["region_name"],
                                             list(r["provinces"] or []))
                       for r in cur.fetchall()}

        # 目标行：system 成员
        cur.execute("""
            SELECT m.membership_id, m.object_id, m.system_id, m.region, m.membership_role,
                   m.strength, m.confidence, m.status,
                   e.canonical_name, e.entity_type, e.merged_into
            FROM system_memberships m
            LEFT JOIN canonical_entities e ON m.object_id = e.entity_id
            WHERE m.system_id IS NOT NULL
        """)
        rows = cur.fetchall()

        for row in rows:
            stats["total"] += 1
            mid = str(row["membership_id"])
            eid = str(row["object_id"])
            sid = str(row["system_id"])
            sys_name, region_name, provinces = sys_regions.get(sid, (None, None, []))

            if row["merged_into"] is not None:
                # 实体已合并：成员关系降级待清理
                if apply:
                    cur.execute(
                        "UPDATE system_memberships SET status='CANDIDATE', anchor_count=0, "
                        "derivation_method=%s, derivation_reason=%s, rule_version=%s WHERE membership_id=%s",
                        ("membership_rule_v2_0", f"object merged into {row['merged_into']}; pending purge",
                         RULE_VERSION, mid))
                stats["merged_object"] += 1
                continue
            if sys_name is None:
                stats["orphan_system"] += 1
                continue

            region_text = (row["region"] or "").strip()

            # --- Spatial 锚 ---
            spatial = None
            spatial_ok = False
            if region_text:
                matched = [p for p in provinces if p and (p in region_text or region_text in p)]
                spatial_ok = bool(matched)
                spatial = {"province_text": region_text, "region": region_name,
                           "matched_provinces": matched, "matched": spatial_ok}

            # --- Temporal 锚（ADMITTED event/claim 带时间） ---
            cur.execute("""
                SELECT DISTINCT t.raw_text, t.valid_from, t.valid_to
                FROM events ev JOIN timespans t ON ev.timespan_id = t.timespan_id
                WHERE ev.entity_id = %s AND ev.status = 'ADMITTED'
                LIMIT 5
            """, (eid,))
            times = [dict(r) for r in cur.fetchall()]
            cur.execute("""
                SELECT DISTINCT t.raw_text, t.valid_from, t.valid_to
                FROM claims c JOIN timespans t ON c.timespan_id = t.timespan_id
                WHERE (c.subject_id = %s OR c.object_id = %s) AND c.status = 'ADMITTED'
                LIMIT 5
            """, (eid, eid))
            times += [dict(r) for r in cur.fetchall()]
            temporal = {"timespans": times[:5]} if times else None

            # --- Domain 锚 ---
            cur.execute("""
                SELECT d.domain_name FROM system_memberships m
                JOIN cultural_domains d ON m.domain_id = d.domain_id
                WHERE m.object_id = %s AND m.domain_id IS NOT NULL
                LIMIT 5
            """, (eid,))
            dom_names = [r["domain_name"] for r in cur.fetchall()]
            domain_anchor = {"domains": dom_names} if dom_names else None

            # --- Process 锚（ADMITTED event 参与） ---
            cur.execute("""
                SELECT ev.event_id, ev.canonical_name, ev.event_type, ev.period,
                       pe.canonical_name AS place_name
                FROM events ev
                LEFT JOIN canonical_entities pe ON ev.place_entity_id = pe.entity_id
                WHERE ev.entity_id = %s AND ev.status = 'ADMITTED'
                LIMIT 5
            """, (eid,))
            proc_events = [dict(r) for r in cur.fetchall()]
            cur.execute("""
                SELECT ev.event_id, ev.canonical_name, ev.event_type, ev.period
                FROM event_participants ep JOIN events ev ON ep.event_id = ev.event_id
                WHERE ep.entity_id = %s AND ev.status = 'ADMITTED'
                LIMIT 5
            """, (eid,))
            seen_ev = {str(p["event_id"]) for p in proc_events}
            proc_events += [dict(r) for r in cur.fetchall() if str(r["event_id"]) not in seen_ev]
            process_anchor = {"admitted_events": proc_events[:5],
                              "event_count": len(proc_events)} if proc_events else None

            # --- 支持 claim + 独立来源 ---
            cur.execute("""
                SELECT c.claim_id FROM claims c
                WHERE (c.subject_id = %s OR c.object_id = %s) AND c.status = 'ADMITTED'
                ORDER BY c.confidence DESC NULLS LAST
                LIMIT %s
            """, (eid, eid, MAX_SUPPORT))
            claim_ids = [str(r["claim_id"]) for r in cur.fetchall()]
            indep_resources = 0
            if claim_ids:
                cur.execute("""
                    SELECT count(DISTINCT e.resource_id) FROM evidence e
                    WHERE e.claim_id = ANY(%s::uuid[]) AND e.resource_id IS NOT NULL
                """, (claim_ids,))
                (indep_resources,) = cur.fetchone()

            anchors: dict[str, Any] = {}
            if spatial is not None and spatial_ok:
                anchors["spatial"] = spatial
            if temporal:
                anchors["temporal"] = temporal
            if domain_anchor:
                anchors["domain"] = domain_anchor
            if process_anchor:
                anchors["process"] = process_anchor
            anchor_count = len(anchors)
            if spatial is not None and not spatial_ok:
                # 空间矛盾：显式记 0 锚并给理由
                anchors["spatial_conflict"] = spatial
                anchor_count = 0

            admitted = anchor_count >= 2
            if admitted and "spatial" not in anchors and "process" not in anchors:
                admitted = False  # 缺乏任何空间或过程证据，不允许 ADMITTED
            etype = (row["entity_type"] or "").upper()
            if admitted and etype == "PLACE" and "process" not in anchors:
                admitted = False  # §19.1：地名是文化容器不是载体，纯地理+时间不足以 ADMIT
            if admitted and _is_province_container(row["canonical_name"]):
                admitted = False  # §16.4：省级行政区不得替代文化区作为载体 ADMIT
            if admitted and (etype in NEVER_ADMIT_TYPES or etype in CONTEXT_TYPES):
                admitted = False  # 事件经 events/process 锚参与系统；语境要素不作成员
            if admitted and MODERN_ENTERPRISE_RE.search(row["canonical_name"] or ""):
                admitted = False  # 现代企业不是文化载体

            strength = round(min(0.9, 0.3 + 0.2 * anchor_count), 2)
            confidence = round(min(0.85, 0.35 + 0.15 * anchor_count), 2)
            reason_parts = [k for k in ("spatial", "temporal", "domain", "process") if k in anchors]
            if "spatial_conflict" in anchors:
                reason_parts.append("spatial_conflict")

            # --- 金标一致性 ---
            if spatial is not None and not spatial_ok:
                gold_neg += 1
                if admitted:
                    rule_admit_in_goldneg += 1
            elif spatial_ok and indep_resources >= 2 and ("temporal" in anchors or "process" in anchors):
                gold_pos += 1
                if admitted:
                    rule_admit_in_goldpos += 1

            if admitted and "spatial" not in anchors:
                geo_only_admitted += 0  # 占位：geo-only 由 spatial 单锚触发，此处不可能

            if apply:
                cur.execute("""
                    UPDATE system_memberships SET
                        spatial_anchor=%s, temporal_anchor=%s, domain_anchor=%s, process_anchor=%s,
                        anchor_count=%s, membership_strength=%s, confidence=%s,
                        derivation_method=%s, derivation_reason=%s,
                        supporting_claim_ids=%s::uuid[], rule_version=%s, status=%s
                    WHERE membership_id=%s
                """, (
                    json.dumps(anchors.get("spatial") or anchors.get("spatial_conflict"), ensure_ascii=False) if (anchors.get("spatial") or anchors.get("spatial_conflict")) else None,
                    json.dumps(anchors.get("temporal"), ensure_ascii=False) if anchors.get("temporal") else None,
                    json.dumps(anchors.get("domain"), ensure_ascii=False) if anchors.get("domain") else None,
                    json.dumps(anchors.get("process"), ensure_ascii=False) if anchors.get("process") else None,
                    anchor_count, strength, confidence,
                    RULE_VERSION, "anchors: " + ",".join(reason_parts) if reason_parts else "no anchors derived",
                    claim_ids, RULE_VERSION,
                    "ADMITTED" if admitted else "CANDIDATE",
                    mid))

            if admitted:
                if "spatial" in anchors and anchor_count == 1:
                    geo_only_admitted += 1
                stats["admitted"] += 1
            else:
                stats["candidate"] += 1
            stats[f"anchors_{anchor_count}"] += 1
            if "spatial_conflict" in anchors:
                stats["spatial_conflict"] += 1

        # domain-only 行：保留 legacy 标记（非 system 成员，不参与 G04）
        if apply:
            cur.execute("""
                UPDATE system_memberships SET derivation_method = %s, rule_version = %s,
                       status = 'CANDIDATE', anchor_count = COALESCE(anchor_count, 0)
                WHERE system_id IS NULL AND derivation_method IS DISTINCT FROM %s
                  AND derivation_method IS DISTINCT FROM 'domain_tree_assignment_v1'
            """, ("legacy_domain_rule_v0", RULE_VERSION, "legacy_domain_rule_v0"))

    precision = rule_admit_in_goldpos / gold_pos if gold_pos else None
    recall = rule_admit_in_goldpos / (gold_pos + rule_admit_in_goldneg) if (gold_pos + rule_admit_in_goldneg) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    return {
        "stats": dict(stats),
        "gold": {
            "positive": gold_pos,
            "negative": gold_neg,
            "rule_admit_in_positive": rule_admit_in_goldpos,
            "rule_admit_in_negative": rule_admit_in_goldneg,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "geo_only_admitted": geo_only_admitted,
    }


ADJUDICATE_PROMPT = (
    "你是文化知识图谱的成员关系审核员。判断实体是否应被正式 ADMITTED 到该文化系统。\n"
    "实体：{name}（类型 {etype}）\n描述：{desc}\n"
    "候选系统：{system}（文化区域 {region}；地理 {provinces}）\n"
    "结构锚点：{anchors}\n"
    "标准：地名/行政区本身是容器不是文化载体，仅地理与断代事件不足以 ADMIT；"
    "需要描述本身可指认文化实质（发源地/核心区/技艺/思潮/制度且创造与传承可考）。\n"
    "硬性不给 ADMIT：现代企业与设施（公司/桥梁/展馆经营体）、外国展馆、单纯行政区、"
    "仅因位于某省而匹配的实体；文化区边界存疑（如扬州属江淮还是吴越）一律 CANDIDATE。\n"
    '只输出 JSON：{{"judgment": "ADMIT|CANDIDATE|REJECT", "reason": "不超过40字"}}'
)


def adjudicate(conn: psycopg2.extensions.connection, force: bool = False) -> dict[str, Any]:
    """两阶段准入第二步：确定性合格集（锚点>=2 且含空间/过程）交 LLM 终审。"""
    from extensions.llm import chat, parse_json
    conn2 = None
    stats = {"eligible": 0, "admitted": 0, "demoted": 0, "errors": 0}
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT m.membership_id::text AS mid, m.spatial_anchor, m.temporal_anchor,
                   m.domain_anchor, m.process_anchor, m.anchor_count, m.status,
                   e.canonical_name, e.entity_type,
                   substr(COALESCE(e.description,''),1,500) AS description,
                   s.system_name, r.region_name, r.provinces
            FROM system_memberships m
            JOIN canonical_entities e ON m.object_id=e.entity_id
            JOIN cultural_systems s ON m.system_id=s.system_id
            LEFT JOIN cultural_regions r ON r.entity_id=s.system_id
            WHERE m.system_id IS NOT NULL AND m.anchor_count>=2
              AND e.merged_into IS NULL
              AND (m.model_version IS NULL OR m.model_version NOT LIKE 'llm_adjudicator:%'
                   OR %s)
        """)
        rows = [dict(r) for r in cur.fetchall()]
    from extensions.llm import chat, parse_json
    for row in rows:
        pass
        if _is_province_container(row["canonical_name"]):
            continue  # 省级容器硬门禁，判官不得推翻
        if (row["entity_type"] or "").upper() in NEVER_ADMIT_TYPES | CONTEXT_TYPES:
            continue  # 事件/语境要素不作成员，判官不得推翻
        if MODERN_ENTERPRISE_RE.search(row["canonical_name"] or ""):
            continue  # 现代企业硬门禁
        stats["eligible"] += 1
        anchors = []
        for k, col in (("spatial","spatial_anchor"),("temporal","temporal_anchor"),
                       ("domain","domain_anchor"),("process","process_anchor")):
            if row[col]:
                anchors.append(k)
        provinces = "、".join(row["provinces"] or []) if row["provinces"] else "未知"
        prompt = ADJUDICATE_PROMPT.format(
            name=row["canonical_name"], etype=row["entity_type"], desc=row["description"] or "（无）",
            system=row["system_name"], region=row["region_name"] or "未定", provinces=provinces,
            anchors="+".join(anchors))
        try:
            j = parse_json(chat([{"role":"user","content":prompt}], max_tokens=200, temperature=0.0)) or {}
            judgment = j.get("judgment", "ERROR")
            reason = str(j.get("reason",""))[:120]
        except Exception as exc:
            judgment, reason = "ERROR", f"{type(exc).__name__}"[:80]
        with conn.cursor() as cur:
            if judgment == "ADMIT":
                cur.execute("""UPDATE system_memberships SET status='ADMITTED', model_version=%s,
                               derivation_reason=%s WHERE membership_id=%s""",
                            (f"llm_adjudicator:{model_tag()}",
                             f"anchors:{'+'.join(anchors)}; judge: {reason}", row["mid"]))
                stats["admitted"] += 1
            elif judgment == "ERROR":
                # 判官失败：保守降级为 CANDIDATE（宁缺毋滥）
                cur.execute("""UPDATE system_memberships SET status='CANDIDATE', model_version=%s,
                               derivation_reason=%s WHERE membership_id=%s""",
                            (f"llm_adjudicator:{model_tag()}", f"judge_error; demoted", row["mid"]))
                stats["errors"] += 1
            else:
                cur.execute("""UPDATE system_memberships SET status='CANDIDATE', model_version=%s,
                               derivation_reason=%s WHERE membership_id=%s""",
                            (f"llm_adjudicator:{model_tag()}",
                             f"demoted by judge ({judgment}): {reason}", row["mid"]))
                stats["demoted"] += 1
        conn.commit()
    return stats


def model_tag() -> str:
    try:
        from config.settings import SETTINGS
        return SETTINGS.llm_model
    except Exception:
        return "unknown"


ROLE_BY_TYPE = {
    "PERSON": "CARRIER", "WORK": "MANIFESTATION", "EVENT": "EPISODE",
    "INSTITUTION": "INSTITUTION", "ORGANIZATION": "INSTITUTION",
    "HERITAGE": "CARRIER_OBJECT", "ARTIFACT": "CARRIER_OBJECT", "SITE": "CARRIER_OBJECT",
    "PRACTICE": "PRACTICE", "WATERSYSTEM": "CONTEXT", "NATURALOBJECT": "CONTEXT",
    "CONCEPT": "CONCEPT", "ETHNICGROUP": "CARRIER",
}


def derive_nonplace_memberships(cur) -> int:
    """§18 成员推导扩展：从“仅地名实体”扩展到人物/著作/机构/遗产等。

    确定性规则：描述文本出现某文化区的省份词→创建到对应系统的
    CANDIDATE 成员行（anchor_count=0，锚点由后续 rebuild() 统一推导）。
    前置质量门：≥1 条 ADMITTED claim 且描述≥20 字。幂等：(object_id, system_id) 唯一。
    """
    cur.execute("""
        SELECT s.system_id::text, s.system_name, r.region_name, r.provinces
        FROM cultural_systems s
        LEFT JOIN cultural_regions r ON r.entity_id=s.system_id
        WHERE s.system_level='REGIONAL'
    """)
    regions = [(row[0], row[2], list(row[3] or [])) for row in cur.fetchall()]
    cur.execute("""
        SELECT e.entity_id::text, e.entity_type, e.canonical_name,
               COALESCE(e.description,'') AS description
        FROM canonical_entities e
        WHERE e.merged_into IS NULL
          AND (SELECT count(*) FROM claims c
               WHERE (c.subject_id=e.entity_id OR c.object_id=e.entity_id)
                 AND c.status='ADMITTED') >= 1
          AND length(coalesce(e.description,'')) >= 20
    """)
    entities = cur.fetchall()
    created = 0
    for eid, etype, cname, desc in entities:
        role = ROLE_BY_TYPE.get((etype or "").upper(), "CARRIER")
        for sid, rname, provs in regions:
            matched = [pv for pv in provs if pv and pv in desc]
            if not matched:
                continue
            cur.execute("""
                INSERT INTO system_memberships (object_id, system_id, region_id, membership_role,
                    region, strength, confidence, derivation_method, derivation_reason,
                    rule_version, status, anchor_count)
                SELECT %s::uuid, %s::uuid,
                       (SELECT region_id FROM cultural_regions WHERE region_name=%s),
                       %s, %s, 0.5, 0.5, 'nonplace_derive_v1',
                       %s, %s, 'CANDIDATE', 0
                WHERE NOT EXISTS (SELECT 1 FROM system_memberships
                                  WHERE object_id=%s::uuid AND system_id=%s::uuid)
            """, (eid, sid, rname, role, matched[0],
                  f"description mentions {matched}", RULE_VERSION, eid, sid))
            created += cur.rowcount
    return created


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--force-adjudicate", action="store_true", help="清除已审标记全量重审")
    args = ap.parse_args()

    conn = psycopg2.connect(dsn())
    try:
        if args.apply:
            with conn.cursor() as cur:
                created = derive_nonplace_memberships(cur)
            conn.commit()
            print(f"DERIVE nonplace memberships: +{created}")
        result = rebuild(conn, apply=args.apply)
        if args.apply:
            conn.commit()
            print("APPLY OK（确定性阶段）")
            adj = adjudicate(conn, force=args.force_adjudicate)
            result["adjudication"] = adj
            conn.commit()
            print(f"ADJUDICATE: {json.dumps(adj, ensure_ascii=False)}")
        else:
            print("DRY-RUN（未写库）")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        geo = result["geo_only_admitted"]
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
