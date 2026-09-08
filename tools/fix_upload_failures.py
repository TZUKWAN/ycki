# -*- coding: utf-8 -*-
"""修复 40 条 PG failed(lightrag_upload)：重新上传正文到 LightRAG，用 resource_id 做安全 file_source。
不依赖原 title（可能有乱码/截断），用 title 前 30 字 + rid 后缀。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from tools.registry import Registry

LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def safe_title(t: str, rid: str) -> str:
    t = (t or "untitled").strip()[:30]
    t = "".join(c for c in t if c.isalnum() or c in " _-（）()[]")
    return f"{t}_{rid[-8:]}.txt"


def main():
    reg = Registry()
    try:
        with reg.conn.cursor() as cur:
            cur.execute("""SELECT resource_id, title, text_path, source_url
                           FROM resources WHERE ingest_status='failed' AND fail_reason='lightrag_upload'""")
            rows = cur.fetchall()
        print(f"需要补传: {len(rows)}")
        ok = fail = 0
        for rid, title, text_path, url in rows:
            if not text_path or not Path(text_path).exists():
                print(f"  ✗ 文本缺失: {rid} {title[:30]}")
                fail += 1
                continue
            text = Path(text_path).read_text(encoding="utf-8", errors="replace")
            fs = safe_title(title, rid)
            r = requests.post(f"{LIGHTRAG}/documents/text", headers=H,
                              json={"text": text, "file_source": fs}, timeout=120)
            if r.status_code == 200:
                reg.mark(rid, ingest_status="uploaded", fail_reason=None,
                         lightrag_file_source=fs)
                print(f"  ✓ {fs}")
                ok += 1
            else:
                print(f"  ✗ HTTP {r.status_code}: {fs}")
                fail += 1
        print(f"补传完成: 成功 {ok} / 失败 {fail}")
    finally:
        reg.close()


if __name__ == "__main__":
    main()
