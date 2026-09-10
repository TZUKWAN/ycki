# -*- coding: utf-8 -*-
"""增量转载聚类（§七/§八）：新资源准入后自动归簇。

cluster_resource(resource_id)：
- 计算 simhash64（正文前 8000 字）+ 标题指纹 + 长度
- 与既有簇代表比较（simhash 汉明 ≤6 且长度差 <50% 且标题相似 ≥0.6）
- 命中 → 加入簇（cluster_confidence/cluster_method/cluster_reason 记录）
- 未命中 → 新簇

输出 cluster_confidence：simhash 距离越近 + 标题越相似，置信越高。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from config.settings import SETTINGS
from extensions.dup.simhash import hamming, simhash64, to_unsigned, to_int64

log = logging.getLogger("ycki.cluster")

MAX_DIST = 6


def _features(text: str, k: int = 3) -> set[str]:
    t = "".join(text.split())
    return {t[i:i + k] for i in range(len(t) - k + 1)} if len(t) >= k else {t} if t else set()


def _title_fingerprint(title: str) -> set[str]:
    return {title[i:i + 2] for i in range(len(title) - 1)} if len(title) > 1 else {title}


def _title_sim(a: str, b: str) -> float:
    fa, fb = _title_fingerprint(a or ""), _title_fingerprint(b or "")
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / len(fa | fb)


def cluster_resource(resource_id: str, conn) -> dict | None:
    """对新资源做增量转载聚类，写 source_cluster_id。返回分配信息。"""
    with conn.cursor() as cur:
        cur.execute("""SELECT title, text_path, content_chars, retrieved_at
                       FROM resources WHERE resource_id=%s""", (resource_id,))
        row = cur.fetchone()
    if not row:
        return None
    title, text_path, nchars, retrieved_at = row
    text = ""
    if text_path and Path(text_path).exists():
        text = Path(text_path).read_text(encoding="utf-8", errors="replace")
    if len(text) < 300:
        return None
    sim = simhash64(text[:8000])
    sim_signed = to_int64(sim)

    # 既有簇代表（首成员资源 + 簇 simhash）
    with conn.cursor() as cur:
        cur.execute("""SELECT sc.cluster_id, sc.original_url,
                              COALESCE(r.title,'') AS rep_title,
                              COALESCE(r.content_chars,0) AS rep_chars
                       FROM source_clusters sc
                       LEFT JOIN resources r ON r.source_cluster_id=sc.cluster_id
                            AND r.retrieved_at = (SELECT MIN(retrieved_at) FROM resources
                                                  WHERE source_cluster_id=sc.cluster_id)
                       ORDER BY sc.created_at""")
        reps = cur.fetchall()

    best, best_conf, best_reason = None, 0.0, ""
    for cid, ourl, rep_title, rep_chars in reps:
        if rep_chars and nchars and abs(rep_chars - nchars) > max(rep_chars, nchars) * 0.5:
            continue                      # 长度差过大，主题相同也不同稿
        with conn.cursor() as cur:
            cur.execute("""SELECT r.simhash FROM resources r
                           WHERE r.source_cluster_id=%s
                             AND r.simhash IS NOT NULL LIMIT 1""", (cid,))
            r2 = cur.fetchone()
        if not r2 or r2[0] is None:
            continue
        dist = hamming(to_unsigned(r2[0]), sim)
        if dist > MAX_DIST:
            continue
        tsim = _title_sim(rep_title, title)
        conf = max(0.0, 1.0 - dist / (MAX_DIST + 1)) * 0.6 + tsim * 0.4
        if conf > best_conf:
            best, best_conf = cid, conf
            best_reason = (f"simhash_dist={dist}, title_sim={tsim:.2f}, "
                           f"len_ratio={min(nchars,rep_chars)/max(max(rep_chars,1),1):.2f}")

    with conn.cursor() as cur:
        if best and best_conf >= 0.55:
            cur.execute("UPDATE resources SET source_cluster_id=%s WHERE resource_id=%s",
                        (best, resource_id))
            result = {"cluster_id": best, "confidence": round(best_conf, 2),
                      "method": "simhash64+title", "reason": best_reason}
        else:
            cid = "sc-" + f"{to_unsigned(sim):016x}"[:12]
            cur.execute("""INSERT INTO source_clusters (cluster_id, method)
                           VALUES (%s,'simhash64-k3-h6-new')
                           ON CONFLICT (cluster_id) DO NOTHING""", (cid,))
            cur.execute("UPDATE resources SET source_cluster_id=%s WHERE resource_id=%s",
                        (cid, resource_id))
            result = {"cluster_id": cid, "confidence": 1.0, "method": "new-cluster"}
        cur.execute(
            """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
               VALUES ('resource', %s, 'clustered', 'cluster_resource', %s)""",
            (resource_id, json.dumps(result, ensure_ascii=False)))
    conn.commit()
    return result
