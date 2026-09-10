# -*- coding: utf-8 -*-
"""统一修复：栅栏清理 → 对 failed/pending 资源做 Scope Gate → CORE/CONTEXT 补上传 LightRAG。"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from config.settings import SETTINGS
from extensions.admission import resource_gate

H = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def unfreeze():
    for _ in range(3):
        d = requests.get(f"{SETTINGS.lightrag_url}/documents/pipeline_status",
                         headers=H, timeout=60).json()
        if not d.get("busy") and not d.get("pending_enqueues"):
            return True
        requests.post(f"{SETTINGS.lightrag_url}/documents/cancel_pipeline",
                      headers=H, json={}, timeout=60)
        time.sleep(15)
    d = requests.get(f"{SETTINGS.lightrag_url}/documents/pipeline_status",
                     headers=H, timeout=60).json()
    return not d.get("busy") and not d.get("pending_enqueues")


def wait_drained(timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = requests.get(f"{SETTINGS.lightrag_url}/documents/pipeline_status",
                         headers=H, timeout=60).json()
        if not d.get("pending_enqueues"):
            return True
        time.sleep(15)
    return False


def main():
    if not unfreeze():
        print("无法解除楔死，退出")
        return
    import psycopg2
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    with conn.cursor() as cur:
        cur.execute("""SELECT resource_id, title, text_path, admission_status
                       FROM resources
                       WHERE admission_status IN ('DISCOVERED','FETCHED')
                         AND text_path IS NOT NULL
                       ORDER BY resource_id""")
        rows = cur.fetchall()
    print(f"待评审+补传: {len(rows)}")
    ok = rej = fail = 0
    for rid, title, tp, adm in rows:
        if not tp or not Path(tp).exists():
            continue
        text = Path(tp).read_text(encoding="utf-8", errors="replace")
        verdict = resource_gate.evaluate(title or "", text, "", "GeneralWebsite")
        resource_gate.persist(rid, verdict, conn)
        if verdict["scope_role"] == "REJECT":
            rej += 1
            continue
        fs = f"{(title or 'untitled').strip()[:30]}_{rid[-8:]}.txt"
        fs = "".join(ch for ch in fs if ch.isalnum() or ch in " _-（）()[]")
        r = requests.post(f"{SETTINGS.lightrag_url}/documents/text", headers=H,
                          json={"text": text, "file_source": fs}, timeout=120)
        if r.status_code == 200:
            with conn.cursor() as cur:
                cur.execute("""UPDATE resources SET lightrag_doc_id=%s,
                               lightrag_file_source=%s WHERE resource_id=%s""",
                            (fs, fs, rid))
            conn.commit()
            ok += 1
        else:
            fail += 1
        if (ok + rej) % 20 == 0:
            wait_drained()
        time.sleep(0.8)
    print(f"评审完成: 上传 {ok} / REJECT {rej} / 上传失败 {fail}")
    wait_drained()
    conn.close()


if __name__ == "__main__":
    main()
