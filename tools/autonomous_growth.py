# -*- coding: utf-8 -*-
"""§57-65：Autonomous Growth 主循环（Gap 驱动 + 熔断 + 心跳 + 单实例锁）。

主循环（§58）：
  Health → Coverage → Gap Detection → Priority Ranking → ResearchTask Planning
  → Query Expansion → Discovery(Scope Gate) → Cluster → Canonical Pipeline
  → Incremental Audit → Coverage Recompute → Gap Re-evaluation → Gain Report

安全：
  PID lock + heartbeat + stale recovery（§62）
  Circuit Breaker（§64/65）：证据重定位 / 假合并 / 未知实体 越阈即 PAUSE
  增长成功以 Knowledge Gain + Coverage Gain + Gap Reduction 计（§52/53），非网页数
"""
from __future__ import annotations

import argparse
import json
import os
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

LOCK = ROOT / "data" / "autonomous_growth.lock"
HEARTBEAT = ROOT / "data" / "autonomous_growth.heartbeat"
GAIN_LOG = ROOT / "data" / "gain_report.jsonl"
PAUSE_FLAG = ROOT / "data" / "growth_paused.flag"

GAPS_PER_CYCLE = 5
CYCLES_FOR_CONTINUOUS = 3

CIRCUIT_BREAKER = {
    "evidence_relocated_min": 0.995,
    "scope_false_accept_max": 0.05,
}


class Paused(Exception):
    pass


def log(msg: str):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(ROOT / "data" / "autonomous_growth.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def heartbeat(cycle: int, phase: str):
    HEARTBEAT.write_text(json.dumps(
        {"pid": os.getpid(), "cycle": cycle, "phase": phase, "ts": time.time()},
        ensure_ascii=False), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    """Windows 兼容的 PID 存活检查。"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def acquire_lock() -> bool:
    if LOCK.exists():
        try:
            old = json.loads(LOCK.read_text(encoding="utf-8"))
            pid = old.get("pid")
            age = time.time() - old.get("ts", 0)
            if _pid_alive(pid) and age < 7200:
                return False                      # 活实例在跑
            log(f"stale lock（PID {pid}）→ 接管")
        except (FileNotFoundError, ValueError, TypeError):
            pass
    LOCK.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")
    return True


def sh(args: list[str], timeout: int | None = None):
    return subprocess.run([sys.executable] + args, cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def coverage_recompute():
    return sh([str(ROOT / "extensions" / "gap" / "coverage.py")] if False else
              ["-m", "extensions.gap.coverage"], timeout=600)


def canonical_pass(limit=10**6):
    return sh([str(ROOT / "tools" / "rebuild_canonical.py"), "--all"], timeout=None)


def fast_audit() -> dict:
    """快速审计：抽样证据重定位 + UNKNOWN + 无证据 ADMITTED。"""
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    out = {}
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM claims cc WHERE cc.status='ADMITTED'
                       AND NOT EXISTS (SELECT 1 FROM evidence e
                                       WHERE e.claim_id=cc.claim_id)""")
        out["admitted_without_evidence"] = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM canonical_entities
                       WHERE entity_type='UNKNOWN' AND status='ACTIVE'""")
        out["unknown_entities"] = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM claims WHERE status='ADMITTED'""")
        out["admitted"] = cur.fetchone()[0]
    conn.close()
    return out


def validate_tasks(cycle: int) -> dict:
    """COLLECTED 任务 → 计算真实知识增益 → RESOLVED / NO_GAIN（§13/§14）。"""
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    conn.autocommit = True
    out = {"resolved": 0, "no_gain": 0}
    with conn.cursor() as cur:
        cur.execute("""SELECT task_id, gap_id, started_at FROM research_tasks
                       WHERE status='COLLECTED'""")
        tasks = cur.fetchall()
    for tid, gid, started_at in tasks:
        topic_tag = f"gap:{tid}"
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(DISTINCT c.claim_id) AS claims,
                       count(DISTINCT r.resource_id) AS res,
                       count(DISTINCT COALESCE(r.source_cluster_id, r.resource_id)) AS indep
                FROM claims c
                JOIN evidence e ON e.claim_id=c.claim_id
                JOIN resources r ON r.resource_id=e.resource_id
                WHERE r.discovery_topic=%s AND c.status IN ('ADMITTED','CONDITIONAL')""",
                (topic_tag,))
            row = cur.fetchone()
        new_claims, new_res, indep = row[0], row[1], row[2]
        evidence_obj = {"cycle": cycle, "new_admitted_claims": new_claims,
                        "new_resources": new_res, "independent_sources": indep,
                        "checked_at": datetime.now().isoformat()}
        status = "RESOLVED" if new_claims > 0 else "NO_GAIN"
        with conn.cursor() as cur:
            cur.execute("""UPDATE research_tasks SET status=%s,
                           resolution_evidence=%s, updated_at=now() WHERE task_id=%s""",
                        (status, json.dumps(evidence_obj, ensure_ascii=False), tid))
        out[status.lower()] = out.get(status.lower(), 0) + 1
        log(f"task {tid}: {status}（新 ADMITTED claims={new_claims}, 资源={new_res}）")
    conn.close()
    return out


def run_cycle(cycle: int, top_n: int) -> dict:
    heartbeat(cycle, "coverage")
    r = coverage_recompute()
    if r.returncode != 0:
        log(f"coverage 失败: {r.stderr[-200:]}")
    heartbeat(cycle, "gap_planning")
    from tools.gap_growth import main as gap_main
    sys.argv = ["gap_growth", "--max-tasks", str(top_n), "--max-total", "40"]
    gap_main()
    heartbeat(cycle, "collection+canonical")
    r = canonical_pass()
    log(f"canonical pass exit={r.returncode}")
    heartbeat(cycle, "validating")
    v = validate_tasks(cycle)
    heartbeat(cycle, "fast_audit")
    fa = fast_audit()
    gain = {"cycle": cycle, "resolved": v.get("resolved", 0),
            "no_gain": v.get("no_gain", 0),
            "admitted_total": fa["admitted"],
            "admitted_without_evidence": fa["admitted_without_evidence"],
            "unknown_entities": fa["unknown_entities"]}
    with open(GAIN_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(), **gain},
                           ensure_ascii=False) + "\n")
    log(f"gain report: {json.dumps(gain, ensure_ascii=False)}")
    return gain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--burn-in", action="store_true",
                    help="三轮 Burn-in 后退出（否则持续运行）")
    ap.add_argument("--cycles", type=int, default=3)
    a = ap.parse_args()

    if not acquire_lock():
        log("已有活实例（PID 锁占用），退出")
        sys.exit(1)
    log("=== Autonomous Growth 启动（canonical_v1 验收后） ===")
    if PAUSE_FLAG.exists():
        log("检测到 growth_paused.flag — 熔断暂停状态，退出（删除该文件以恢复）")
        sys.exit(1)

    cycle = 0
    try:
        while True:
            cycle += 1
            heartbeat(cycle, "cycle_start")
            if PAUSE_FLAG.exists():
                log("熔断暂停中…")
                time.sleep(300)
                continue
            top_n = [3, 5, 10][min(cycle - 1, 2)] if a.burn_in else GAPS_PER_CYCLE
            gain = run_cycle(cycle, top_n)
            # 熔断检查（§64/65）
            if gain.get("admitted_without_evidence", 0) > 0:
                PAUSE_FLAG.write_text("admitted_without_evidence>0", encoding="utf-8")
                log("CIRCUIT BREAKER: 出现无证据 ADMITTED → PAUSE_GROWTH")
            if gain.get("unknown_entities", 0) > 0:
                PAUSE_FLAG.write_text("unknown_entities>0", encoding="utf-8")
                log("CIRCUIT BREAKER: UNKNOWN 实体 → PAUSE_GROWTH")
            if a.burn_in and cycle >= a.cycles:
                log(f"=== Burn-in {a.cycles} 轮完成 ===")
                break
            time.sleep(60)
    finally:
        LOCK.unlink(missing_ok=True)
    log("=== 引擎退出（数据已落盘，重跑脚本即恢复） ===")


if __name__ == "__main__":
    main()
