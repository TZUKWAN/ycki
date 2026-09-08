# -*- coding: utf-8 -*-
"""Canonical 重建守护：python 进程消失且队列未完 → 自动重启（断点续跑）。"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "watchdog.log"


def log(msg: str):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def progress():
    sys.path.insert(0, str(ROOT))
    import psycopg2
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM resources WHERE rebuild_stage<>'DONE'")
        left = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM resources WHERE rebuild_stage='DONE'")
        done = cur.fetchone()[0]
    conn.close()
    return done, left


def rebuild_alive() -> bool:
    """按命令行检测是否已有重评进程（避免双实例 ER 竞态）。"""
    out = subprocess.run(
        ["powershell", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object {$_.CommandLine -like '*rebuild_canonical*'} | "
         "Select-Object -First 1 ProcessId | Format-List"],
        capture_output=True, text=True, timeout=60).stdout
    return "ProcessId" in out


def main():
    log("=== 重建守护启动（单实例锁：按命令行检测） ===")
    while True:
        try:
            done, left = progress()
            if left == 0:
                log(f"全部完成（DONE={done}），守护退出")
                break
            if rebuild_alive():
                log(f"重评进程存活，跳过拉起（DONE={done} 剩余={left}）")
                time.sleep(120)
                continue
            log(f"进度 DONE={done} 剩余={left}，无存活实例，拉起重评…")
            subprocess.run([sys.executable, str(ROOT / "tools" / "rebuild_canonical.py"),
                            "--all"], cwd=str(ROOT))
            log("重评进程退出，60 秒后复查")
            time.sleep(60)
        except Exception as exc:
            log(f"watchdog error: {exc}")
            time.sleep(120)


if __name__ == "__main__":
    main()
