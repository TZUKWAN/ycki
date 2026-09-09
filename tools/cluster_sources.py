# -*- coding: utf-8 -*-
"""存量资源 SimHash 聚类：转载链归簇，写 source_clusters + resources.source_cluster_id。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2

from config.settings import SETTINGS
from extensions.dup.simhash import hamming, simhash64

MAX_DIST = 6


def main():
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    with conn.cursor() as cur:
        cur.execute("""SELECT resource_id, text_path, content_chars FROM resources
                       WHERE admission_status IN ('CORE','CONTEXT')
                         AND text_path IS NOT NULL ORDER BY retrieved_at ASC""")
        rows = cur.fetchall()
    clusters: list[dict] = []          # {"sim": int, "members": [rid]}
    rid2cluster: dict[str, str] = {}
    for i, (rid, text_path, nchars) in enumerate(rows):
        try:
            text = Path(text_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) < 300:
            continue
        sim = simhash64(text[:8000])
        matched = None
        for c in clusters:
            # 长度差 3 倍以上直接排除（同稿转载长度接近）
            if abs(c["chars"] - nchars) > max(c["chars"], nchars) * 0.5:
                continue
            if hamming(c["sim"], sim) <= MAX_DIST:
                matched = c
                break
        if matched:
            matched["members"].append(rid)
            rid2cluster[rid] = matched["cid"]
        else:
            cid = "sc-" + f"{sim:016x}"[:12]
            clusters.append({"cid": cid, "sim": sim, "chars": nchars,
                             "members": [rid]})
            rid2cluster[rid] = cid
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(rows)}", flush=True)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM source_clusters")
        for c in clusters:
            if len(c["members"]) < 1:
                continue
            cur.execute("""INSERT INTO source_clusters (cluster_id, method)
                           VALUES (%s,'simhash64-k3-h6') ON CONFLICT (cluster_id) DO NOTHING""",
                        (c["cid"],))
            for rid in c["members"]:
                cur.execute("UPDATE resources SET source_cluster_id=%s WHERE resource_id=%s",
                            (c["cid"], rid))
    multi = [c for c in clusters if len(c["members"]) > 1]
    conn.commit()
    conn.close()
    print(f"聚类完成: {len(clusters)} 簇 / {len(rows)} 资源；多成员簇 {len(multi)}")
    for c in sorted(multi, key=lambda x: -len(x["members"]))[:5]:
        print(f"  {c['cid']}: {len(c['members'])} 篇")


if __name__ == "__main__":
    main()
