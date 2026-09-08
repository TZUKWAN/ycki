# -*- coding: utf-8 -*-
"""T01 基线上传/管理脚本：UTF-8 文件名安全上传 + 状态轮询 + 查询 + 删除"""
import io
import json
import sys
import time

import requests

API = "http://localhost:9621"
KEY = "ycki-baseline-6f2a91c4"
H = {"X-API-Key": KEY}


def upload(path):
    fn = path.split("/")[-1].split("\\")[-1]
    with open(path, "rb") as f:
        r = requests.post(f"{API}/documents/upload", headers=H,
                          files={"file": (fn, f)}, timeout=120)
    print("upload:", fn, r.status_code, r.text[:200])


def list_docs():
    r = requests.post(f"{API}/documents/paginated", headers=H, timeout=30,
                      json={"page": 1, "page_size": 20})
    data = r.json()
    for d in data.get("data", {}).get("documents", data.get("documents", [])):
        print(f"  id={d['id'][:14]} status={d['status']} file={d['file_path']} chunks={d.get('chunks_count')}")
    return data


def delete_all():
    r = requests.post(f"{API}/documents/paginated", headers=H, timeout=30,
                      json={"page": 1, "page_size": 100})
    data = r.json()
    docs = data.get("data", {}).get("documents", data.get("documents", []))
    ids = [d["id"] for d in docs]
    if ids:
        r = requests.delete(f"{API}/documents/delete_document", headers=H,
                            json={"doc_ids": ids}, timeout=300)
        print("deleted:", ids, r.status_code, r.text[:200])


def wait_done(timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.post(f"{API}/documents/paginated", headers=H, timeout=30,
                          json={"page": 1, "page_size": 20})
        data = r.json()
        docs = data.get("data", {}).get("documents", data.get("documents", []))
        stats = {}
        for d in docs:
            stats[d["status"]] = stats.get(d["status"], 0) + 1
        print(f"  [{int(time.time()-t0)}s] {stats}")
        busy = requests.get(f"{API}/documents/pipeline_status", headers=H, timeout=10).json()
        if docs and all(d["status"] in ("processed", "failed") for d in docs) and not busy.get("busy"):
            return docs
        time.sleep(10)
    return []


def doc_status():
    busy = requests.get(f"{API}/documents/pipeline_status", headers=H, timeout=10)
    print(json.dumps(busy.json(), ensure_ascii=False)[:1500])


def query(q, mode="hybrid", stream=False):
    body = {"query": q, "mode": mode, "only_need_chunks": False}
    r = requests.post(f"{API}/query", headers=H, json=body, timeout=300)
    print(f"--- [{mode}] {q}")
    print(r.json().get("response", r.text)[:1200] if r.ok else r.text[:500])


def graph_heads():
    r = requests.post(f"{API}/graph/entity/list", headers=H, json={"max_nodes": 50}, timeout=30)
    if r.ok:
        nodes = r.json()
        print("graph nodes:", len(nodes.get("nodes", [])), "edges:", len(nodes.get("edges", [])))
        for n in nodes.get("nodes", [])[:15]:
            print("  -", n.get("labels"), n.get("id"), "|", (n.get("properties") or {}).get("entity_type"))
    else:
        print(r.status_code, r.text[:300])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "upload":
        for p in sys.argv[2:]:
            upload(p)
    elif cmd == "list":
        list_docs()
    elif cmd == "delete_all":
        delete_all()
    elif cmd == "wait":
        docs = wait_done()
        list_docs()
    elif cmd == "status":
        doc_status()
    elif cmd == "query":
        query(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "hybrid")
    elif cmd == "graph":
        graph_heads()
