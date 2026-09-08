# -*- coding: utf-8 -*-
"""YCKI 对账：把 LightRAG 文档处理状态真实回写 resources 表。
匹配键：resources.lightrag_doc_id 中保存的 file_source（上传时的 file_path）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from tools.registry import Registry

LIGHTRAG = "http://localhost:9621"
LR_HEADERS = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def fetch_all_docs():
    docs, page = [], 1
    while True:
        r = requests.post(f"{LIGHTRAG}/documents/paginated", headers=LR_HEADERS,
                          json={"page": page, "page_size": 100}, timeout=30)
        data = r.json()  # 顶层: documents / pagination / status_counts
        batch = data.get("documents", [])
        if not batch:
            break
        docs.extend(batch)
        total = (data.get("pagination") or {}).get("total_count") or len(docs)
        if len(docs) >= total:
            break
        page += 1
    return docs


def reconcile():
    reg = Registry()
    try:
        docs = fetch_all_docs()
        by_path = {d["file_path"]: d for d in docs}
        with reg.conn.cursor() as cur:
            cur.execute("""SELECT resource_id, lightrag_doc_id FROM resources
                           WHERE ingest_status='uploaded' AND lightrag_doc_id IS NOT NULL""")
            rows = cur.fetchall()
        updated = {"processed": 0, "failed": 0, "parsing": 0}
        for rid, file_source in rows:
            doc = by_path.get(file_source)
            if not doc:
                continue
            status = doc["status"]
            if status == "processed":
                reg.mark(rid, ingest_status="processed",
                         lightrag_doc_id=doc["id"],
                         lightrag_file_source=file_source)
                updated["processed"] += 1
            elif status == "failed":
                reg.mark(rid, ingest_status="failed",
                         lightrag_doc_id=doc["id"],
                         lightrag_file_source=file_source,
                         fail_reason=str(doc.get("error_msg") or "lightrag_failed")[:500])
                updated["failed"] += 1
            else:
                updated["parsing"] += 1
        print(f"lightrag docs={len(docs)} | resources matched: {updated}")
        print("DB stats:", reg.stats())
        print("authority:", reg.authority_hist())
    finally:
        reg.close()


if __name__ == "__main__":
    reconcile()
