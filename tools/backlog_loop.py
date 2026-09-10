# -*- coding: utf-8 -*-
"""积压清零循环：解楔 → gate 评审 → 补传 → 等 LightRAG 消化 → canonical pass → 对账。
循环直到 PG 中 CORE/CONTEXT 资源全部有 lightrag_doc_id 且无 FETCHED 积压。
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import requests

from config.settings import SETTINGS

H = {"X-API-Key": "ycki-baseline-6f2a91c4"}


def log(msg):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(ROOT / "data" / "backlog_loop.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=7200):
    return subprocess.run([sys.executable] + cmd, cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def backlog_count(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM resources
                       WHERE admission_status IN ('DISCOVERED','FETCHED')""")
        gate_pending = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM resources
                       WHERE admission_status IN ('CORE','CONTEXT')
                         AND (lightrag_doc_id IS NULL OR lightrag_doc_id='')""")
        upload_missing = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM resources WHERE ingest_status='failed'")
        failed = cur.fetchone()[0]
    return gate_pending, upload_missing, failed


def main():
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    rounds = 0
    while True:
        rounds += 1
        gate_pending, upload_missing, failed = backlog_count(conn)
        log(f"round {rounds}: gate_pending={gate_pending} upload_missing={upload_missing} failed={failed}")
        if upload_missing == 0 and gate_pending == 0:
            log("=== 积压清零 ===")
            break

        # 1) 解楔
        for _ in range(2):
            try:
                d = requests.get(f"{SETTINGS.lightrag_url}/documents/pipeline_status",
                                 headers=H, timeout=60).json()
                if d.get("busy") or d.get("pending_enqueues"):
                    requests.post(f"{SETTINGS.lightrag_url}/documents/cancel_pipeline",
                                  headers=H, json={}, timeout=60)
                    time.sleep(12)
            except Exception as exc:
                log(f"unfreeze err: {exc}")
                time.sleep(10)

        # 2) gate 评审积压（DISCOVERED/FETCHED → CORE/CONTEXT/REJECTED）
        if gate_pending:
            r = run(["tools/repair_backlog.py"], timeout=7200)
            log(f"repair_backlog exit={r.returncode} tail={((r.stdout or '')[-120:])}")

        # 3) CORE/CONTEXT 缺文档补传
        if upload_missing:
            r = run(["tools/reingest_missing.py"], timeout=7200)
            log(f"reingest exit={r.returncode} tail={((r.stdout or '')[-120:])}")

        # 4) LightRAG 消化（等待队列排空，最多 40 分钟/轮）
        t0 = time.time()
        while time.time() - t0 < 2400:
            try:
                c = requests.get(f"{SETTINGS.lightrag_url}/documents/status_counts",
                                 headers=H, timeout=60).json().get("status_counts", {})
                inflight = (c.get("pending", 0) + c.get("parsing", 0)
                            + c.get("analyzing", 0) + c.get("processing", 0))
                if inflight == 0:
                    break
                log(f"  LightRAG: processed={c.get('processed')} inflight={inflight}")
            except Exception as exc:
                log(f"poll err: {exc}")
            time.sleep(120)

        # 5) canonical pass（新 processed 资源进 Canonical KG）
        r = run(["tools/rebuild_canonical.py", "--all"], timeout=None)
        log(f"canonical pass exit={r.returncode}")

    conn.close()


if __name__ == "__main__":
    main()
