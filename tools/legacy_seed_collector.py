# -*- coding: utf-8 -*-
"""YCKI 持续自增长引擎（双击启动脚本的后端循环）

职责：
1. 探针唤醒 LightRAG 管道（重启后不自恢复，见 ADR-016）
2. 轮换执行 yangtze/topics_batch*.json 全部主题表（断点续跑+双去重，重复执行只增新内容）
3. 每轮后：对账回写 PG、重排失败文档（自愈）
4. 休眠后进入下一轮 —— 知识库随时间持续增长

用法：
  python auto_growth.py            # 持续循环（默认）
  python auto_growth.py --once     # 单轮后退出（测试用）
"""
import argparse
import glob
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # 文件位于 tools/ 下，ROOT=ycki/
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import requests

LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4"}  # 服务端已关闭鉴权则此头被忽略，两边兼容
LOG = ROOT / "data" / "auto_growth.log"
ENGINE_STATE = ROOT / "data" / "engine_state.json"
PAUSE_FLAG = ROOT / "data" / "engine_pause.flag"
CUSTOM_TOPICS = ROOT / "yangtze" / "custom_topics.json"
CYCLE_SLEEP = 1800          # 两轮之间休眠 30 分钟
PER_PASS_TOTAL = 40         # 每个主题表每轮最多新增条数（控制单轮时长）


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def heartbeat(cycle: int, last_msg: str):
    ENGINE_STATE.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_STATE.write_text(json.dumps(
        {"cycle": cycle, "last_msg": last_msg, "ts": time.time()},
        ensure_ascii=False), encoding="utf-8")


def wait_lightrag(timeout=1800):
    """等 LightRAG 服务可用（Docker 未就绪时由 .bat 负责，这里兜底等待）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(f"{LIGHTRAG}/health", timeout=10).ok:
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def probe():
    """非写数式管道唤醒：检查是否积压未完成文档；有则用官方 recovery 接口复位重跑。

    禁止向生产知识库写伪文档（Phase 1 冻结，REFACTOR_PHASE0_AUDIT P0-2）。
    """
    try:
        counts = requests.get(f"{LIGHTRAG}/documents/status_counts", headers=H,
                              timeout=90).json().get("status_counts", {})
        stuck = (counts.get("pending", 0) + counts.get("parsing", 0)
                 + counts.get("analyzing", 0) + counts.get("processing", 0))
        busy = requests.get(f"{LIGHTRAG}/documents/pipeline_status", headers=H,
                            timeout=60).json().get("busy", False)
        if stuck == 0 or busy:
            return True          # 无积压或管道在工作，无需干预
        r = requests.post(f"{LIGHTRAG}/documents/recovery/force_reset", headers=H,
                          json={"confirm": True}, timeout=120)
        log(f"recovery force_reset: {r.status_code} {r.text[:120]}")
        return True
    except Exception as exc:
        log(f"probe(recovery) error: {exc}")
        return False


def run_collect(topics: Path, batch: str):
    cmd = [sys.executable, str(ROOT / "tools" / "collect.py"),
           "--batch", batch, "--topics", str(topics),
           "--max-total", str(PER_PASS_TOTAL), "--max-urls", "5",
           "--wiki-per-query", "1", "--delay", "1.1"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=5400,
                       cwd=str(ROOT))
    tail = (r.stdout or "").strip().splitlines()
    err = (r.stderr or "").strip().splitlines()
    msg = tail[-1] if tail else ""
    if r.returncode not in (0, None) and err:
        msg += " | ERR: " + err[-1][:200]
    return r.returncode, msg


def pipe_state():
    try:
        d = requests.get(f"{LIGHTRAG}/documents/pipeline_status", headers=H, timeout=90).json()
        return bool(d.get("busy")), int(d.get("pending_enqueues") or 0)
    except Exception:
        return True, 1   # 未知状态按"忙"处理，避免撞栅栏


def wait_fence_clear(max_wait=900):
    """等 manual_freeze/排队重试清空，否则新上传会被 409 弹回。"""
    t0 = time.time()
    while time.time() - t0 < max_wait:
        busy, pending = pipe_state()
        if not busy and pending == 0:
            return True
        time.sleep(20)
    return False


def heal_failed():
    """只在管道空闲且确有失败时重排；重排会设排他栅栏，调用后必须等栅栏清空。"""
    failed = stats().get("failed", 0)
    if not failed:
        return "no-failed"
    busy, pending = pipe_state()
    if busy or pending:
        return f"skip(busy={busy},pending={pending})"
    try:
        r = requests.post(f"{LIGHTRAG}/documents/reprocess_failed", headers=H, timeout=60)
        st = r.json().get("status")
        if st == "reprocessing_started":
            wait_fence_clear()
        return st
    except Exception as exc:
        return f"error: {exc}"


def reconcile():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reconcile.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, cwd=str(ROOT))
    return (r.stdout or "").strip().splitlines()



def stats():
    try:
        d = requests.get(f"{LIGHTRAG}/documents/status_counts", headers=H, timeout=90).json()
        return d.get("status_counts", {})
    except Exception:
        return {}


def run_custom():
    """把控制台保存的自定义词条包成临时主题表采集，完成后清空待办。"""
    if not CUSTOM_TOPICS.exists():
        return
    try:
        data = json.loads(CUSTOM_TOPICS.read_text(encoding="utf-8"))
    except Exception:
        return
    queries = [q for q in data.get("queries", []) if q]
    if not queries:
        return
    tmp = ROOT / "data" / "custom_pending.json"
    tmp.write_text(json.dumps(
        {"themes": [{"topic": "自定义词条", "queries": queries}]},
        ensure_ascii=False), encoding="utf-8")
    code, tail = run_collect(tmp, "custom")
    log(f"collect[custom] exit={code} | {tail[:160]}")
    data["queries"] = []
    CUSTOM_TOPICS.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def main(once: bool):
    topics_files = sorted(glob.glob(str(ROOT / "yangtze" / "topics_batch*.json")))
    log(f"=== 自增长引擎启动，主题表 {len(topics_files)} 个 ===")
    if not wait_lightrag():
        log("LightRAG 长时间不可达，退出")
        sys.exit(1)

    cycle = 0
    while True:
        cycle += 1
        try:
            heartbeat(cycle, "轮次开始")
            if PAUSE_FLAG.exists():
                heartbeat(cycle, "已暂停（控制台可恢复）")
                log("引擎处于暂停状态，等待…")
                time.sleep(CYCLE_SLEEP)
                continue
            log(f"--- 第 {cycle} 轮开始 ---")
            if not wait_fence_clear():
                log("栅栏长时间未清空，跳过本轮采集")
            probe()
            time.sleep(8)
            run_custom()
            for tf in topics_files:
                name = Path(tf).stem.replace("topics_", "")
                batch = f"auto-{name}"
                heartbeat(cycle, f"采集 {name}")
                try:
                    code, tail = run_collect(Path(tf), batch)
                    log(f"collect[{name}] exit={code} | {tail[:200]}")
                except subprocess.TimeoutExpired:
                    log(f"collect[{name}] 超时被杀（续跑安全，下轮继续）")
                except Exception as exc:
                    log(f"collect[{name}] error: {exc}")
            # 自愈 + 对账（heal 内部会等栅栏清空再返回）
            heartbeat(cycle, "自愈与对账")
            log(f"heal_failed: {heal_failed()}")
            for line in reconcile()[-2:]:
                log(f"reconcile: {line[:200]}")
            st = stats()
            log(f"cycle {cycle} 完成，队列: {json.dumps(st, ensure_ascii=False)}")
            heartbeat(cycle, f"轮次完成 {json.dumps(st, ensure_ascii=False)[:110]}")
        except Exception:
            log("cycle error:\n" + traceback.format_exc()[-1500:])
        if once:
            log("=== 单轮模式退出 ===")
            break
        time.sleep(CYCLE_SLEEP)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="单轮后退出")
    a = ap.parse_args()
    main(a.once)
