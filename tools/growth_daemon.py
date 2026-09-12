#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""growth_daemon.py — 文化系统自主增长常驻模式（goal §103/§120）。

循环执行 cultural_system_growth --cycle（每轮重新检测缺口，非固定主题）。
熔断触发时暂停并退避重试审计；心跳写 reports/V2_GROWTH_DAEMON_HEARTBEAT.json。

用法：
  python tools/growth_daemon.py                 # 前台常驻
  python tools/growth_daemon.py --interval 1800 # 每轮间隔秒数
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEARTBEAT = ROOT / "reports" / "V2_GROWTH_DAEMON_HEARTBEAT.json"
LOG = ROOT / "reports" / "growth_daemon.log"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%dT%H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def heartbeat(state: str, cycle: int, extra: dict | None = None) -> None:
    doc = {"state": state, "cycle": cycle, "updated_at": datetime.now().isoformat(timespec="seconds"),
           "pid": None, "extra": extra or {}}
    try:
        import os
        doc["pid"] = os.getpid()
    except Exception:
        pass
    HEARTBEAT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=1800, help="轮间休息秒数")
    ap.add_argument("--gaps", type=int, default=3)
    ap.add_argument("--pause-on-breaker", type=int, default=900, help="熔断后退避秒数")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    log("growth daemon v2 启动")
    cycle = 0
    consecutive_breaks = 0
    while True:
        cycle += 1
        heartbeat("RUNNING_CYCLE", cycle)
        try:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "cultural_system_growth.py"),
                 "--cycle", "--gaps", str(args.gaps)],
                capture_output=True, text=True, timeout=5400, cwd=str(ROOT))
            out = (proc.stdout or "")[-800:]
            log(f"cycle {cycle} exit={proc.returncode}\n{out}")
            if "PAUSE_GROWTH" in out:
                consecutive_breaks += 1
                log(f"熔断暂停 {args.pause_on_breaker}s（连续 {consecutive_breaks} 次）")
                heartbeat("PAUSED_BREAKER", cycle, {"consecutive": consecutive_breaks})
                time.sleep(args.pause_on_breaker)
                continue
            consecutive_breaks = 0
            heartbeat("IDLE", cycle)
        except subprocess.TimeoutExpired:
            log(f"cycle {cycle} 超时，跳过")
            heartbeat("TIMEOUT", cycle)
        except Exception as exc:
            log(f"cycle {cycle} 异常: {type(exc).__name__}: {exc}")
            heartbeat("ERROR", cycle, {"error": str(exc)[:200]})
            time.sleep(300)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
