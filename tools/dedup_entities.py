#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedup_entities.py — 同名重复实体确定性去重（ENTITY_RESOLUTION 失败族通用修复）。

背景：历史批次中 ER 的 AMBIGUOUS_MATCH→new 路径制造了大量同 名+同类型 重复实体
（如 上海 Place ×70）。重复使消歧永远有 ≥2 候选 → AMBIGUOUS → 主张端点解析失败 →
证据永久无法进入束。这是系统性根因，不是个案。

合并策略（确定性 + 可审计，非名字盲并）：
  1. 分组：lower(canonical_name)+entity_type 完全相同、status='ACTIVE'、merged_into IS NULL。
  2. 组内簇化：embed(name+desc) 余弦 ≥0.86 归簇（union-find）；
     描述全空视为同簇（同名同类型且无任何区分性信息）。
  3. 仅 ≥2 成员的簇合并；簇间保持分裂（同名异实体保护，红队"同名实体"族）。
  4. canonical = 簇内 claim 端点引用最多者（平票取 created_at 最早）。
  5. 改写引用：claims 端点、events 端点、event_participants、system_memberships、
     candidate_entities.resolved_entity_id、place_relations；
     aliases 并入 canonical；merged→status='MERGED', merged_into=canonical。
  6. 每簇写 provenance_events(action='dedup_merge')。

用法：
  python tools/dedup_entities.py            # dry-run 统计
  python tools/dedup_entities.py --apply    # 执行（分簇事务，可断点重跑）
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from extensions.llm import embed

COS_THRESHOLD = 0.80   # 同名同类型强先验内；0.86 会漏并 LLM 已判 same 的簇


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def fetch_groups(conn) -> list[list[dict]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT entity_id::text, canonical_name, entity_type,
                   COALESCE(description,'') AS description, created_at,
                   (SELECT count(*) FROM claims c
                     WHERE c.subject_id=ce.entity_id OR c.object_id=ce.entity_id) AS refs
            FROM canonical_entities ce
            WHERE merged_into IS NULL AND status='ACTIVE'
              AND (lower(canonical_name), entity_type) IN (
                    SELECT lower(canonical_name), entity_type FROM canonical_entities
                    WHERE merged_into IS NULL AND status='ACTIVE'
                    GROUP BY lower(canonical_name), entity_type HAVING count(*) > 1)
            ORDER BY lower(canonical_name), entity_type, created_at
        """)
        rows = [dict(r) for r in cur.fetchall()]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["canonical_name"].lower(), r["entity_type"]), []).append(r)
    return list(groups.values())


def cluster_group(group: list[dict]) -> list[list[dict]]:
    n = len(group)
    texts = [f"{g['canonical_name']} {g['description'][:120]}" for g in group]
    try:
        vecs = embed(texts)
        sim = [[_cos(vecs[i], vecs[j]) if i != j else 1.0 for j in range(n)] for i in range(n)]
    except Exception:
        sim = [[1.0 if i == j else (1.0 if not group[i]["description"] and not group[j]["description"] else 0.0)
                for j in range(n)] for i in range(n)]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            both_empty = not group[i]["description"] and not group[j]["description"]
            if sim[i][j] >= COS_THRESHOLD or both_empty:
                pi, pj = find(i), find(j)
                if pi != pj:
                    parent[pi] = pj
    clusters: dict[int, list[dict]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(group[i])
    out = [c for c in clusters.values() if len(c) >= 2]
    # ---- 第二层：嵌入未归簇 → LLM 群裁"是否同一指称"（同名同类型强先验下）----
    if len(out) <= 1 and n >= 2:
        merged_so_far = out[0] if out else []
        rest = [g for g in group if g not in merged_so_far]
        if len(rest) >= 2 and _llm_same_referent(rest):
            out = out + [rest]
    return out


def _llm_same_referent(group: list[dict]) -> bool | None:
    """同名同类型组的 LLM 群裁。True=同一指称可合并；False/None=保守不并。"""
    try:
        from extensions.llm import chat, parse_json
        descs = [f"{i+1}. {g['description'][:80]}" for i, g in enumerate(group[:8])]
        v = parse_json(chat([{"role": "user", "content":
            f"以下 {len(group[:8])} 个候选的规范化名称完全相同、类型相同"
            f"（名称：{group[0]['canonical_name']}，类型：{group[0]['entity_type']}）。"
            "判断它们是否指称同一个现实实体（描述差异可以只是视角不同）。\n"
            + "\n".join(descs)
            + '\n只输出 JSON：{"same_referent": true|false}'}],
            max_tokens=40, temperature=0.0)) or {}
        return bool(v.get("same_referent"))
    except Exception:
        return None


def choose_canonical(cluster: list[dict]) -> dict:
    return sorted(cluster, key=lambda g: (-g["refs"], g["created_at"], g["entity_id"]))[0]


def apply_merge(conn, cluster: list[dict], dry: bool) -> dict:
    canonical = choose_canonical(cluster)
    merged = [g for g in cluster if g["entity_id"] != canonical["entity_id"]]
    rec = {"canonical": canonical["entity_id"], "merged": [g["entity_id"] for g in merged],
           "name": canonical["canonical_name"], "type": canonical["entity_type"]}
    if dry or not merged:
        return rec
    with conn.cursor() as cur:
        for g in merged:
            gid = g["entity_id"]
            # memberships：与 canonical 同系统冲突时按状态优先级保留较强一行
            cur.execute("""
                SELECT m.system_id::text, m.status FROM system_memberships m
                WHERE m.object_id=%s""", (gid,))
            for sys_id, m_status in cur.fetchall():
                cur.execute("""
                    SELECT status::text FROM system_memberships
                    WHERE object_id=%s AND system_id=%s::uuid""", (canonical["entity_id"], sys_id))
                row = cur.fetchone()
                prec = {"ADMITTED": 3, "SUPPORTED": 2, "CANDIDATE": 1}
                if row:
                    if prec.get(m_status, 0) > prec.get(row[0], 0):
                        cur.execute("""UPDATE system_memberships SET status=%s
                                       WHERE object_id=%s AND system_id=%s::uuid""",
                                    (m_status, canonical["entity_id"], sys_id))
                    cur.execute("DELETE FROM system_memberships WHERE object_id=%s AND system_id=%s::uuid",
                                (gid, sys_id))
            cur.execute("UPDATE claims SET subject_id=%s WHERE subject_id=%s", (canonical["entity_id"], gid))
            cur.execute("UPDATE claims SET object_id=%s WHERE object_id=%s", (canonical["entity_id"], gid))
            cur.execute("UPDATE events SET entity_id=%s WHERE entity_id=%s", (canonical["entity_id"], gid))
            cur.execute("UPDATE events SET place_entity_id=%s WHERE place_entity_id=%s", (canonical["entity_id"], gid))
            cur.execute("UPDATE event_participants SET entity_id=%s WHERE entity_id=%s", (canonical["entity_id"], gid))
            cur.execute("""UPDATE system_memberships SET object_id=%s WHERE object_id=%s""",
                        (canonical["entity_id"], gid))
            cur.execute("""UPDATE candidate_entities SET resolved_entity_id=%s
                           WHERE resolved_entity_id=%s""", (canonical["entity_id"], gid))
            cur.execute("UPDATE place_relations SET from_entity=%s WHERE from_entity=%s", (canonical["entity_id"], gid))
            cur.execute("UPDATE place_relations SET to_entity=%s WHERE to_entity=%s", (canonical["entity_id"], gid))
            cur.execute("""INSERT INTO entity_aliases (entity_id, normalized_alias, alias)
                           SELECT %s, a.normalized_alias, a.alias FROM entity_aliases a
                           WHERE a.entity_id=%s
                           ON CONFLICT DO NOTHING""", (canonical["entity_id"], gid))
            cur.execute("""UPDATE canonical_entities SET merged_into=%s, status='MERGED'
                           WHERE entity_id=%s""", (canonical["entity_id"], gid))
        cur.execute("""
            INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
            VALUES ('canonical_entity', %s, 'dedup_merge', 'dedup_entities', %s)
        """, (canonical["entity_id"],
              json.dumps(rec, ensure_ascii=False)))
    conn.commit()
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 组（0=全部）")
    args = ap.parse_args()

    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    t0 = time.time()
    groups = fetch_groups(conn)
    if args.limit:
        groups = groups[:args.limit]
    print(f"dup groups: {len(groups)}")
    stats = {"clusters": 0, "merge_moves": 0, "refs_rewritten": 0}
    for gi, g in enumerate(groups):
        try:
            clusters = cluster_group(g)
            for c in clusters:
                rec = apply_merge(conn, c, not args.apply)
                stats["clusters"] += 1
                stats["merge_moves"] += len(rec["merged"])
            if gi % 100 == 0:
                print(f"  ..{gi}/{len(groups)} clusters={stats['clusters']} moves={stats['merge_moves']}")
        except Exception as exc:
            conn.rollback()
            print(f"ERR group {gi} {g[0]['canonical_name']}: {exc}")
    # 统计引用改写量（近似：合并簇的平均 refs）
    print(json.dumps({**stats, "elapsed_s": round(time.time() - t0, 1),
                      "mode": "APPLY" if args.apply else "DRY-RUN"}, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
