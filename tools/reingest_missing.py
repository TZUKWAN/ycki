# -*- coding: utf-8 -*-
"""把已过准入但缺失 LightRAG 文档的 CORE/CONTEXT 资源重灌检索索引。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import time

import requests

from config.settings import SETTINGS

H = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def safe_fs(title: str, rid: str) -> str:
    t = (title or "untitled").strip()[:30]
    t = "".join(ch for ch in t if ch.isalnum() or ch in " _-（）()[]")
    return f"{t}_{rid[-8:]}.txt"


def wait_drained(timeout: int = 300):
    """等 pending_enqueues 清零（准入门按队列排空放行）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d = requests.get(f"{SETTINGS.lightrag_url}/documents/pipeline_status",
                             headers=H, timeout=60).json()
            if not d.get("pending_enqueues"):
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def main():
    import psycopg2
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    with conn.cursor() as cur:
        cur.execute("""SELECT resource_id, title, text_path FROM resources
                       WHERE (lightrag_doc_id IS NULL OR lightrag_doc_id='')
                         AND admission_status IN ('CORE','CONTEXT')
                         AND text_path IS NOT NULL""")
        rows = cur.fetchall()
    print(f"待重灌: {len(rows)}")
    ok = fail = 0
    for rid, title, text_path in rows:
        if not text_path or not Path(text_path).exists():
            continue
        text = Path(text_path).read_text(encoding="utf-8", errors="replace")
        fs = safe_fs(title, rid)
        r = requests.post(f"{SETTINGS.lightrag_url}/documents/text", headers=H,
                          json={"text": text, "file_source": fs}, timeout=120)
        if r.status_code == 200:
            with conn.cursor() as cur:
                cur.execute("""UPDATE resources SET lightrag_doc_id=%s,
                               lightrag_file_source=%s WHERE resource_id=%s""",
                            (fs, fs, rid))
            ok += 1
            wait_drained()          # 串行：排空再传下一篇
        else:
            print(f"  ✗ {rid} HTTP {r.status_code}")
            fail += 1
            wait_drained(60)
    conn.commit()
    conn.close()
    print(f"重灌完成: 成功 {ok} / 失败 {fail}")


if __name__ == "__main__":
    main()
