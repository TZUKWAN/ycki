# -*- coding: utf-8 -*-
"""回填 resources.lightrag_doc_id / lightrag_file_source（治 document_exists 88.3%）。

原理：collect 上传时 file_source 含 resource_id 后 8 位（{title}_{rid8}.txt），
与 LightRAG docs.file_path 可匹配；维基源经 wikipedia_provider 亦同规则。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from config.settings import SETTINGS

H = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def all_lr_docs():
    docs, page = [], 1
    while True:
        r = requests.post(f"{SETTINGS.lightrag_url}/documents/paginated", headers=H,
                          json={"page": page, "page_size": 100}, timeout=90).json()
        batch = r.get("documents", [])
        if not batch:
            break
        docs.extend(batch)
        total = (r.get("pagination") or {}).get("total_count") or len(docs)
        if len(docs) >= total:
            break
        page += 1
    return docs


def main():
    import psycopg2
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    docs = all_lr_docs()
    by_rid8 = {}
    for d in docs:
        fp = d.get("file_path") or ""
        stem = fp.rsplit(".", 1)[0]
        if "_" in stem:
            rid8 = stem.rsplit("_", 1)[-1]
            if len(rid8) == 8 and rid8 not in by_rid8:
                by_rid8[rid8] = (d["id"], fp)
    with conn.cursor() as cur:
        cur.execute("""SELECT resource_id, title, source_url FROM resources
                       WHERE (lightrag_doc_id IS NULL OR lightrag_doc_id='')
                         AND admission_status IN ('CORE','CONTEXT')""")
        rows = cur.fetchall()
        fixed = 0
        for rid, title, url in rows:
            rid8 = rid[-8:]
            hit = by_rid8.get(rid8)
            if hit:
                cur.execute("""UPDATE resources
                               SET lightrag_doc_id=%s, lightrag_file_source=%s
                               WHERE resource_id=%s""", (hit[0], hit[1], rid))
                fixed += 1
        # 同步 evidence.document_id 空值
        cur.execute("""UPDATE evidence e SET document_id = r.lightrag_doc_id
                       FROM resources r
                       WHERE e.resource_id=r.resource_id
                         AND (e.document_id IS NULL OR e.document_id='')""")
        ev = cur.rowcount
    conn.commit()
    print(f"回填 resources: {fixed}/{len(rows)}；evidence.document_id 补齐: {ev}")
    conn.close()


if __name__ == "__main__":
    main()
