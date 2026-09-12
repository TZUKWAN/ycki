# -*- coding: utf-8 -*-
"""YCKI 可视化控制台 (http://localhost:9622)
- 增长总览/最新入库/每日增长/队列状态
- 自定义搜索词条管理（写入即被自增长引擎采用，可一键立即采集）
- 引擎暂停/恢复
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.registry import Registry  # noqa: E402

LIGHTRAG = "http://localhost:9621"
H = {"X-API-Key": "ycki-baseline-6f2a91c4"}
CUSTOM_TOPICS = ROOT / "yangtze" / "custom_topics.json"
ENGINE_STATE = ROOT / "data" / "engine_state.json"
PAUSE_FLAG = ROOT / "data" / "engine_pause.flag"
COLLECT_LOCK = ROOT / "data" / "custom_collect.lock"

app = FastAPI(title="YCKI Console")

# 实体规模缓存（graphml 解析较重，后台线程低频刷新）
_entity_cache = {"count": None, "relations": None, "updated": 0, "lock": threading.Lock()}


def refresh_entities():
    with _entity_cache["lock"]:
        try:
            sys.path.insert(0, str(ROOT))
            from tools.verify_chain import load_graphml
            nodes, edges = load_graphml()
            _entity_cache["count"] = len(nodes)
            _entity_cache["relations"] = len(edges)
            _entity_cache["updated"] = time.time()
        except Exception:
            pass


def entity_scheduler():
    while True:
        refresh_entities()
        time.sleep(300)


threading.Thread(target=entity_scheduler, daemon=True).start()


def pg_stats():
    reg = Registry()
    try:
        with reg.conn.cursor() as cur:
            cur.execute("""SELECT count(*), COALESCE(sum(content_chars),0),
                                  count(DISTINCT source_domain) FROM resources""")
            total, chars, domains = cur.fetchone()
            cur.execute("SELECT count(*) FROM sources")
            sources = cur.fetchone()[0]
            cur.execute("""SELECT title, source_domain, retrieved_at, ingest_status, source_url
                           FROM resources ORDER BY retrieved_at DESC LIMIT 30""")
            recent = [{"title": r[0], "domain": r[1], "at": str(r[2]),
                       "status": r[3], "url": r[4]} for r in cur.fetchall()]
            cur.execute("""SELECT to_char(retrieved_at::date,'MM-DD'), count(*)
                           FROM resources WHERE retrieved_at > now() - interval '14 days'
                           GROUP BY 1 ORDER BY 1""")
            daily = [{"day": r[0], "n": r[1]} for r in cur.fetchall()]
        return {"resources": total, "chars": chars, "domains": domains,
                "sources": sources, "recent": recent, "daily": daily}
    finally:
        reg.close()


def lr_stats():
    try:
        d = requests.get(f"{LIGHTRAG}/documents/status_counts", headers=H, timeout=90).json()
        return d.get("status_counts", {})
    except Exception:
        return {}


def engine_state():
    st = {"running": False, "cycle": None, "last_msg": "", "paused": PAUSE_FLAG.exists()}
    try:
        if ENGINE_STATE.exists():
            d = json.loads(ENGINE_STATE.read_text(encoding="utf-8"))
            age = time.time() - d.get("ts", 0)
            st["running"] = age < 3600
            st["cycle"] = d.get("cycle")
            st["last_msg"] = d.get("last_msg", "")[:160]
            st["last_ts"] = datetime.fromtimestamp(d.get("ts", 0)).strftime("%m-%d %H:%M")
    except Exception:
        pass
    return st


def custom_topics():
    if CUSTOM_TOPICS.exists():
        try:
            return json.loads(CUSTOM_TOPICS.read_text(encoding="utf-8"))
        except Exception:
            return {"queries": [], "seen": []}
    return {"queries": [], "seen": []}


@app.get("/api/overview")
def overview():
    try:
        p = pg_stats()
    except Exception as exc:
        p = {"error": str(exc), "resources": 0, "chars": 0, "domains": 0,
             "sources": 0, "recent": [], "daily": []}
    canon = {}
    try:
        reg = Registry()
        with reg.conn.cursor() as cur:
            cur.execute("SELECT * FROM v_canonical_stats")
            cols = [d[0] for d in cur.description]
            canon = dict(zip(cols, cur.fetchone()))
        reg.close()
    except Exception:
        pass
    return {
        "pg": p,
        "lr": lr_stats(),
        "retrieval": {  # 仅供 RAG 内部检索的索引层，不代表正式知识关系
            "entities": _entity_cache["count"],
            "relations": _entity_cache["relations"],
            "updated": datetime.fromtimestamp(_entity_cache["updated"]).strftime("%H:%M") if _entity_cache["updated"] else "",
        },
        "canonical": canon,
        "engine": engine_state(),
    }


@app.get("/api/topics")
def get_topics():
    return custom_topics()


@app.post("/api/topics/add")
def add_topics(payload: dict):
    queries = [q.strip() for q in (payload.get("queries") or []) if q.strip()]
    if not queries:
        return JSONResponse({"ok": False, "msg": "没有有效词条"}, status_code=400)
    data = custom_topics()
    seen = set(data.get("seen", []))
    new = [q for q in queries if q not in seen]
    data.setdefault("seen", []).extend(new)
    data["queries"] = new          # 只保留未采过的新词，采集完自动清空
    CUSTOM_TOPICS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "added": len(new), "total_seen": len(data["seen"])}


@app.post("/api/collect/run")
def run_collect_now():
    # stale lock 自动清理（>30 分钟视为崩溃残留）
    if COLLECT_LOCK.exists():
        age = time.time() - COLLECT_LOCK.stat().st_mtime
        if age < 1800:
            return {"ok": False, "msg": f"已有一次立即采集在运行（{int(age)}s）"}
        COLLECT_LOCK.unlink()
    data = custom_topics()
    if not data.get("queries"):
        return {"ok": False, "msg": "请先添加词条"}
    COLLECT_LOCK.write_text(datetime.now().isoformat(), encoding="utf-8")
    logf = open(ROOT / "data" / "custom_collect.log", "a", encoding="utf-8")

    def _run():
        try:
            # custom_topics.json 是 {queries, seen} 结构：包装成 collect 需要的 themes
            pending = data.get("queries", [])
            tmp = ROOT / "data" / "custom_pending.json"
            tmp.write_text(json.dumps(
                {"themes": [{"topic": "自定义词条", "queries": pending}]},
                ensure_ascii=False), encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "tools" / "collect.py"),
                 "--batch", "custom", "--topics", str(tmp),
                 "--max-total", "60", "--max-urls", "6", "--wiki-per-query", "2",
                 "--delay", "1.1"],
                stdout=logf, stderr=subprocess.STDOUT, cwd=str(ROOT))
            proc.wait(timeout=3600)       # 等待完成再释放锁
        except Exception:
            pass
        finally:
            if COLLECT_LOCK.exists():
                COLLECT_LOCK.unlink()

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "msg": "立即采集已启动，结果稍后出现在『最新入库』"}


@app.post("/api/collect/clear_lock")
def clear_lock():
    if COLLECT_LOCK.exists():
        COLLECT_LOCK.unlink()
    return {"ok": True}


@app.post("/api/engine/pause")
def pause_engine():
    PAUSE_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
    return {"ok": True, "paused": True}


@app.post("/api/engine/resume")
def resume_engine():
    if PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink()
    return {"ok": True, "paused": False}


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


@app.get("/canonical", response_class=HTMLResponse)
def canonical_page():
    return (ROOT / "dashboard" / "canonical.html").read_text(encoding="utf-8")


@app.get("/v2", response_class=HTMLResponse)
def v2_page():
    """canonical_v2 文化系统页（§81-83：分层钻取入口，首屏回答"长江文化是什么"）。"""
    return (ROOT / "dashboard" / "v2.html").read_text(encoding="utf-8")


from extensions.canonical.yangtze_api import mount as mount_yangtze
mount_yangtze(app)

# canonical_v2 受控本体只读 API（/yangtze/v2/*，13 端点）
from dashboard.api_v2 import router as api_v2_router  # noqa: E402
app.include_router(api_v2_router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9622, log_level="warning")
