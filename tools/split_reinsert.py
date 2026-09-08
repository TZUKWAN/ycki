# -*- coding: utf-8 -*-
"""顽固失败文档终态处置：按段落边界对半拆分 → 注册为两条新资源 → 重灌 LightRAG。
原 PG 行标记 duplicate（fail_reason 指向拆分件），内容零丢失。
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from tools.fetcher import domain_of, lake_safe
from tools.registry import Registry, rid_of

LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4"}
LAKE = Path(r"D:\长江学论纲\ycki\data\lake")


def split_text(text: str):
    """按段落边界对半拆分；过短则不拆。"""
    if len(text) < 800:
        return None
    mid = len(text) // 2
    for delta in range(0, 2000):
        i = mid + delta
        if i < len(text) - 1 and text[i] == "\n" and text[i + 1] == "\n":
            return text[:i], text[i:]
    i = text.find("\n", mid)
    if 0 < i < len(text) - 1:
        return text[:i], text[i:]
    return None


def main():
    H2 = dict(H, **{})
    reg = Registry()
    try:
        failed = requests.post(f"{LIGHTRAG}/documents/paginated", headers=H,
                               json={"page": 1, "page_size": 100, "status_filters": ["failed"]},
                               timeout=90).json().get("documents", [])
        print(f"LightRAG failed: {len(failed)}")
        # 删除 LR 中的失败文档（正文将拆分重灌）
        ids = [d["id"] for d in failed]
        if ids:
            r = requests.delete(f"{LIGHTRAG}/documents/delete_document", headers=H,
                                json={"doc_ids": ids}, timeout=300)
            print("delete failed docs:", r.status_code)

        for d in failed:
            fs = d.get("file_path") or ""
            with reg.conn.cursor() as cur:
                cur.execute("""SELECT resource_id, title, text_path, source_url, source_domain,
                                      source_id, search_query, collection_batch
                               FROM resources WHERE lightrag_file_source=%s""", (fs,))
                row = cur.fetchone()
            if not row:
                # 基线/探针文档，不在 PG 中，跳过（其失败仅影响测试文档）
                print(f"  - 跳过(不在PG): {fs[:50]}")
                continue
            rid, title, text_path, url, domain, sid, query, batch = row
            text = Path(text_path).read_text(encoding="utf-8", errors="replace") if text_path and Path(text_path).exists() else ""
            parts = split_text(text)
            if not parts:
                print(f"  - 无法拆分(过短): {title[:30]} ({len(text)}字)")
                continue
            # 原 PG 行标记 duplicate，指向拆分件
            with reg.conn.cursor() as cur:
                cur.execute("""UPDATE resources SET ingest_status='duplicate',
                               fail_reason=%s WHERE resource_id=%s""",
                            (f"split_reinserted:{rid[-8:]}p1/{rid[-8:]}p2", rid))
            for pi, part in enumerate(parts, 1):
                canon = f"{url}#ycki-part{pi}"
                nrid = "res-" + hashlib.sha1(canon.encode()).hexdigest()[:16]
                # 湖存储
                sdomain = lake_safe(domain)
                tdir = LAKE / "text" / sdomain
                tdir.mkdir(parents=True, exist_ok=True)
                ntp = str(tdir / f"{nrid}.txt")
                Path(ntp).write_text(part, encoding="utf-8")
                tsha = hashlib.sha256(part.encode("utf-8")).hexdigest()
                nfs = f"{nrid[-8:]}p{pi}.txt"
                # PG 登记（直插，含 source 继承）
                with reg.conn.cursor() as cur:
                    cur.execute("""INSERT INTO resources (resource_id, title, source_url, canonical_url,
                        source_domain, source_id, source_type, mime_type, http_status,
                        checksum, text_checksum, raw_path, text_path, content_chars,
                        search_query, collection_batch, retrieved_at, rights)
                        VALUES (%s,%s,%s,%s,%s,%s,'GeneralWebsite','text/plain',200,
                        %s,%s,%s,%s,%s,%s,%s,now(),'{}'::jsonb)
                        ON CONFLICT (text_checksum) DO NOTHING
                        RETURNING resource_id""",
                        (nrid, f"{title}（部分{pi}/2）", canon, canon, domain, sid,
                         tsha, tsha, text_path, ntp, len(part), query, batch))
                    ins = cur.fetchone()
                # 上传
                r = requests.post(f"{LIGHTRAG}/documents/text", headers=H,
                                  json={"text": part, "file_source": nfs}, timeout=120)
                if r.status_code == 200 and ins:
                    with reg.conn.cursor() as cur:
                        cur.execute("""UPDATE resources SET ingest_status='uploaded',
                                       lightrag_doc_id=%s, lightrag_file_source=%s WHERE resource_id=%s""",
                                    (nfs, nfs, nrid))
                    print(f"  ✓ {title[:24]} -> p{pi} ({len(part)}字)")
                else:
                    print(f"  ✗ {title[:24]} p{pi}: HTTP {r.status_code}")
    finally:
        reg.close()


if __name__ == "__main__":
    main()
