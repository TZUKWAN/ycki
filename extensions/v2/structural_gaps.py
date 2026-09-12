# -*- coding: utf-8 -*-
"""structural_gaps.py — 结构缺口引擎（goal §53-§57 / G12）。

覆盖网格（coverage_cells）降级为诊断信号；正式知识缺口是结构性缺口：
每个 gap 必须指明 target_object / known_structure / missing_structure /
why_it_matters / required_evidence / resolution_criteria / priority。

检测器（确定性 SQL）覆盖 §54 至少要求的类型；输出写入 structural_gaps，
幂等（同类型同目标存在 OPEN gap 则跳过）。
"""
from __future__ import annotations

from typing import Any

import psycopg2

# §54 缺口类型 → 检测 SQL（返回 target 描述 + jsonb 已知/缺失结构 + 优先级基线）
DETECTORS: list[dict[str, Any]] = [
    {
        "type": "MISSING_SYSTEM_MEMBERSHIP",
        "target_kind": "canonical_entity",
        "why": "高置信实体无任何系统成员关系，Formal Graph 无法解释其文化归属",
        "resolution": "为实体推导≥2个结构锚点（空间/时间/领域/过程）后重建 membership",
        "sql": """
            SELECT ce.entity_id::text,
                   jsonb_build_object('name', ce.canonical_name, 'type', ce.entity_type,
                                      'admitted_claims', (SELECT count(*) FROM claims c
                                          WHERE (c.subject_id=ce.entity_id OR c.object_id=ce.entity_id)
                                            AND c.status='ADMITTED')) AS known,
                   jsonb_build_object('membership', 'absent') AS missing,
                   LEAST(0.9, 0.4 + (SELECT count(*) FROM claims c
                       WHERE (c.subject_id=ce.entity_id OR c.object_id=ce.entity_id)
                         AND c.status='ADMITTED')::real * 0.05) AS priority
            FROM canonical_entities ce
            WHERE ce.merged_into IS NULL
              AND NOT EXISTS (SELECT 1 FROM system_memberships m WHERE m.object_id=ce.entity_id)
              AND EXISTS (SELECT 1 FROM claims c
                  WHERE (c.subject_id=ce.entity_id OR c.object_id=ce.entity_id)
                    AND c.status='ADMITTED')
            LIMIT 200
        """,
    },
    {
        "type": "MISSING_PROCESS_STAGE",
        "target_kind": "cultural_process",
        "why": "过程缺阶段结构，无法说明发展脉络（§39 过程性要求）",
        "resolution": "采集分期断代证据，合成至少2个有引文支撑的阶段",
        "sql": """
            SELECT p.process_id::text,
                   jsonb_build_object('name', p.process_name, 'time',
                                      COALESCE(p.start_time,'')||'~'||COALESCE(p.end_time,'')) AS known,
                   jsonb_build_object('stage_count', (SELECT count(*) FROM process_stages s
                                                      WHERE s.process_id=p.process_id)) AS missing,
                   0.7 AS priority
            FROM cultural_processes p
            WHERE p.status IN ('ADMITTED','SUPPORTED')
              AND (SELECT count(*) FROM process_stages s WHERE s.process_id=p.process_id) < 2
        """,
    },
    {
        "type": "MISSING_EVIDENCE",
        "target_kind": "cultural_tradition",
        "why": "传统无字段级证据分解，证据链不可追溯（G07）",
        "resolution": "补充至少2个独立来源的字段级引文",
        "sql": """
            SELECT t.tradition_id::text,
                   jsonb_build_object('name', t.tradition_name, 'status', t.status) AS known,
                   jsonb_build_object('evidence_rows',
                                      (SELECT count(*) FROM tradition_evidence te
                                       WHERE te.tradition_id=t.tradition_id)) AS missing,
                   0.8 AS priority
            FROM cultural_traditions t
            WHERE t.status = 'ADMITTED'
              AND (SELECT count(*) FROM tradition_evidence te WHERE te.tradition_id=t.tradition_id) < 3
        """,
    },
    {
        "type": "SINGLE_SOURCE_STRUCTURE",
        "target_kind": "structure",
        "why": "单一来源结构仅 SUPPORTED，独立性不足（§14）",
        "resolution": "发现至少1个额外独立来源集群",
        "sql": """
            SELECT sa.object_kind || ':' || COALESCE(t.tradition_name, p.process_name, f.flow_id::text),
                   jsonb_build_object('decision', sa.decision,
                                      'clusters', sa.independent_source_clusters) AS known,
                   jsonb_build_object('required', '>=2 independent source clusters') AS missing,
                   0.6 AS priority
            FROM structural_admissions sa
            LEFT JOIN cultural_traditions t ON sa.object_kind='TRADITION' AND sa.object_id=t.tradition_id
            LEFT JOIN cultural_processes p ON sa.object_kind='PROCESS' AND sa.object_id=p.process_id
            LEFT JOIN cultural_flows f ON sa.object_kind='FLOW' AND sa.object_id=f.flow_id
            WHERE sa.decision='SUPPORTED'
        """,
    },
    {
        "type": "MISSING_CROSS_REGION_LINK",
        "target_kind": "system_pair",
        "why": "区域系统对之间无可证据的互动关系（§26 EVIDENCE_BACKED 要求）",
        "resolution": "找到具体跨区过程/流动/事件及其证据",
        "sql": """
            SELECT a.system_name || '<->' || b.system_name,
                   jsonb_build_object('systems', to_jsonb(ARRAY[a.system_name, b.system_name])) AS known,
                   jsonb_build_object('evidence_backed_relations', 0) AS missing,
                   0.65 AS priority
            FROM cultural_systems a
            JOIN cultural_systems b ON a.system_level='REGIONAL' AND b.system_level='REGIONAL'
                 AND a.system_name < b.system_name
            WHERE NOT EXISTS (
                SELECT 1 FROM structural_relations r
                WHERE r.status='ADMITTED' AND r.knowledge_type='EVIDENCE_BACKED'
                  AND ((r.subject_id=a.system_id AND r.object_id=b.system_id)
                    OR (r.subject_id=b.system_id AND r.object_id=a.system_id)))
        """,
    },
    {
        "type": "MISSING_HYDRO_LINK",
        "target_kind": "cultural_process",
        "why": "过程无水系网络锚点，无法解释长江水系的作用（§116-E）",
        "resolution": "为过程绑定 hydro_network / process_routes 并给出证据",
        "sql": """
            SELECT p.process_id::text,
                   jsonb_build_object('name', p.process_name) AS known,
                   jsonb_build_object('hydro_anchors',
                                      COALESCE(array_length(p.hydro_network,1),0),
                                      'routes', (SELECT count(*) FROM process_routes pr
                                                 WHERE pr.process_id=p.process_id)) AS missing,
                   0.55 AS priority
            FROM cultural_processes p
            WHERE p.status IN ('ADMITTED','SUPPORTED')
              AND COALESCE(array_length(p.hydro_network,1),0) = 0
              AND NOT EXISTS (SELECT 1 FROM process_routes pr WHERE pr.process_id=p.process_id)
        """,
    },
    {
        "type": "ORPHAN_ENTITY",
        "target_kind": "fact_entity",
        "why": "实体孤立无任何证据链（v1 事实层卫生）",
        "resolution": "关联 claim/event 证据或标记低价值",
        "sql": """
            SELECT ce.entity_id::text,
                   jsonb_build_object('name', ce.canonical_name, 'type', ce.entity_type) AS known,
                   jsonb_build_object('claims', 0, 'events', 0) AS missing,
                   0.3 AS priority
            FROM canonical_entities ce
            WHERE ce.merged_into IS NULL
              AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.subject_id=ce.entity_id OR c.object_id=ce.entity_id)
              AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.entity_id=ce.entity_id)
              AND NOT EXISTS (SELECT 1 FROM event_participants ep WHERE ep.entity_id=ce.entity_id)
            LIMIT 300
        """,
    },
]


def detect_gaps(conn: psycopg2.extensions.connection, apply: bool = True,
                per_type_limit: int = 50) -> list[dict[str, Any]]:
    """运行全部检测器；幂等写入 structural_gaps（OPEN 状态去重）。"""
    created: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for det in DETECTORS:
            cur.execute(det["sql"] + (" LIMIT %s" if "LIMIT" not in det["sql"].upper() else ""),
                        (per_type_limit,))
            rows = cur.fetchall()
            for target_ref, known, missing, priority in rows:
                if apply:
                    cur.execute("""
                        SELECT gap_id FROM structural_gaps
                        WHERE gap_type=%s AND status='OPEN'
                          AND current_structure->>'_ref'=%s LIMIT 1
                    """, (det["type"], str(target_ref)))
                    hit = cur.fetchone()
                    if hit:
                        continue
                if apply:
                    cur.execute("""
                        INSERT INTO structural_gaps (gap_type, target_system, current_structure,
                            missing_structure, candidate_hypotheses, priority, status)
                        VALUES (%s,
                            (SELECT system_id FROM cultural_systems WHERE system_level='ROOT' LIMIT 1),
                            %s::jsonb, %s::jsonb, %s, %s, 'OPEN')
                        RETURNING gap_id
                    """, (det["type"],
                          json.dumps({"_ref": str(target_ref), **known}, ensure_ascii=False),
                          json.dumps(missing, ensure_ascii=False),
                          [det["resolution"]], priority))
                    gid = str(cur.fetchone()[0])
                    created.append({"gap_id": gid, "type": det["type"], "target": str(target_ref),
                                    "priority": float(priority)})
                else:
                    created.append({"type": det["type"], "target": str(target_ref),
                                    "priority": float(priority)})
        if apply:
            conn.commit()
    return created


import json  # noqa: E402  (检测器 JSON 参数需要)
