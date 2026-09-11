# -*- coding: utf-8 -*-
"""YCKI 一键启动器：双击 bat 后由本脚本拉起全部服务并保持运行。

架构：
  本脚本（start_all.py）作为常驻进程，负责：
  1. 确保 Docker Desktop 运行
  2. 启动容器（lightrag / postgres / searxng）
  3. 启动控制台 dashboard (:9622)
  4. 启动自增长引擎（autonomous_growth）
  5. 健康检查 + 自动重启崩溃的服务

用法：双击 启动长江文化知识库.bat 即可
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

LOG_DIR = ROOT / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PROCESSES: dict[str, subprocess.Popen] = {}


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def start_detached(name: str, cmd: list[str], logfile: str):
    """启动一个真正独立的后台进程（父进程退出后子进程存活）。"""
    if name in PROCESSES and PROCESSES[name].poll() is None:
        log(f"  {name} 已在运行，跳过")
        return
    logf = open(LOG_DIR / logfile, "a", encoding="utf-8")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                            cwd=str(ROOT), **kwargs)
    PROCESSES[name] = proc
    log(f"  {name} 已启动 (PID {proc.pid})")


def wait_http(url: str, timeout: int = 120, name: str = ""):
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(url, timeout=10)
            log(f"  {name} OK ({int(time.time()-t0)}s)")
            return True
        except Exception:
            time.sleep(5)
    log(f"  {name} 超时！")
    return False


def start_docker():
    """确保 Docker Desktop 运行。"""
    r = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    if r.returncode == 0:
        log("Docker 已运行")
        return
    log("启动 Docker Desktop…")
    docker_path = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
    if docker_path.exists():
        subprocess.Popen([str(docker_path)], creationflags=subprocess.DETACHED_PROCESS)
    for _ in range(24):                     # 最多等 2 分钟
        time.sleep(5)
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        if r.returncode == 0:
            log("Docker 就绪")
            return
    log("Docker 启动超时！")


def start_containers():
    """启动 Docker 容器。"""
    containers = ["lightrag-lightrag-1", "ycki-postgres", "searxng"]
    for c in containers:
        subprocess.run(["docker", "start", c], capture_output=True, timeout=30)
    log("容器已启动")


def main():
    print("=" * 60)
    print("  YCKI 长江文化知识库 - 启动中…")
    print("  控制台: http://localhost:9622")
    print("  WebUI:  http://localhost:9621/webui/")
    print("=" * 60)

    # 1. Docker
    start_docker()

    # 2. 容器
    start_containers()
    time.sleep(5)

    # 3. 等 LightRAG
    log("等待 LightRAG 就绪…")
    wait_http("http://localhost:9621/health", timeout=120, name="LightRAG")

    # 4. 控制台
    log("启动控制台 :9622…")
    start_detached("dashboard", [sys.executable, str(ROOT / "dashboard" / "app.py")],
                   "dashboard.log")

    # 5. 自增长引擎
    log("启动自增长引擎…")
    start_detached("growth", [sys.executable, str(ROOT / "tools" / "autonomous_growth.py")],
                   "autonomous_growth.log")

    # 6. 打开浏览器
    log("打开浏览器…")
    subprocess.Popen(["cmd", "/c", "start", "http://localhost:9622"],
                     creationflags=subprocess.DETACHED_PROCESS)
    time.sleep(2)
    subprocess.Popen(["cmd", "/c", "start", "http://localhost:9621/webui/"],
                     creationflags=subprocess.DETACHED_PROCESS)

    print()
    print("=" * 60)
    print("  全部服务已启动！")
    print("  关闭此窗口不会停止服务")
    print("  数据安全：每次采集自动保存到 PostgreSQL")
    print("=" * 60)

    # 保持脚本运行，监控子进程
    while True:
        time.sleep(60)
        # 检查子进程健康
        for name, proc in PROCESSES.items():
            if proc.poll() is not None:
                log(f"  {name} 已退出 (code={proc.returncode})，自动重启…")
                if name == "dashboard":
                    start_detached("dashboard",
                                   [sys.executable, str(ROOT / "dashboard" / "app.py")],
                                   "dashboard.log")
                elif name == "growth":
                    start_detached("growth",
                                   [sys.executable, str(ROOT / "tools" / "autonomous_growth.py")],
                                   "autonomous_growth.log")


if __name__ == "__main__":
    main()
