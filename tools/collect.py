# -*- coding: utf-8 -*-
"""YCKI 采集编排器（真实实现）：
SearXNG 搜索 -> 轻量抓取 -> 正文抽取 -> 湖存储 -> PG 注册（去重） -> LightRAG 入库
可断点续跑：canonical_url 唯一约束 + text_checksum 去重，重跑自动跳过。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import requests

from adapters.searxng_provider import SearxngProvider, SearchConfig
from adapters.wikipedia_provider import WikipediaProvider
from tools.fetcher import fetch, domain_of, lake_safe, FetchedDoc
from tools.registry import Registry, rid_of

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("ycki.collect")

LIGHTRAG = "http://localhost:9621"
LR_HEADERS = {"X-API-Key": "ycki-baseline-6f2a91c4"}
LAKE = Path(r"D:\长江学论纲\ycki\data\lake")


def safe_name(s: str, maxlen: int = 40) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", s)
    return s[:maxlen].strip("_") or "untitled"


def upload_to_lightrag(rid: str, title: str, text: str) -> tuple[bool, str]:
    """上传正文文本；file_path 用可读名+rid 后8位保证唯一且可回查。"""
    file_source = f"{safe_name(title)}_{rid[-8:]}.txt"
    try:
        r = requests.post(f"{LIGHTRAG}/documents/text", headers=LR_HEADERS,
                          json={"text": text, "file_source": file_source}, timeout=120)
        if r.status_code == 200:
            return True, file_source
        log.warning("lightrag upload %s -> %d %s", rid, r.status_code, r.text[:150])
        return False, ""
    except Exception as exc:
        log.warning("lightrag upload error %s: %s", rid, exc)
        return False, ""


def handle_wiki_doc(w: dict, reg: Registry, batch: str, stats: dict) -> None:
    """把维基 extract 结果接入同一注册/入湖/上传链路。"""
    from tools.fetcher import canonicalize, domain_of, lake_safe

    class _Doc:
        """与 FetchedDoc 字段对齐的轻包装（避免重复网络请求）。"""
        pass

    d = _Doc()
    d.url = w["url"]
    d.canonical_url = canonicalize(w["url"])
    d.final_url = w["url"]
    d.http_status = 200
    d.raw_sha256 = w["raw_sha256"]
    d.text_sha256 = w["text_sha256"]
    d.title = w["title"]
    d.text = w["text"]
    d.author = None
    d.date = None
    d.raw_bytes = w.get("raw_content") or json.dumps(
        {"title": w["title"], "query": w["search_query"]},
        ensure_ascii=False).encode("utf-8")
    d.mime_type = w["mime_type"]

    domain = domain_of(d.canonical_url)
    ddir = LAKE / "raw" / lake_safe(domain)
    tdir = LAKE / "text" / lake_safe(domain)
    ddir.mkdir(parents=True, exist_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    rid = rid_of(d.canonical_url)
    (ddir / f"{rid}.json").write_bytes(d.raw_bytes)
    text_path = str(tdir / f"{rid}.txt")
    (tdir / f"{rid}.txt").write_text(d.text, encoding="utf-8")

    status, rid = reg.insert_resource(d, w["search_query"], batch,
                                      str(ddir / f"{rid}.json"), text_path)
    if status != "registered":
        stats["dup_url" if status == "duplicate_url" else "dup_text"] += 1
        return
    stats["registered"] += 1
    ok, file_source = upload_to_lightrag(rid, d.title, d.text)
    if ok:
        stats["uploaded"] += 1
        reg.mark(rid, ingest_status="uploaded", lightrag_doc_id=file_source)
    else:
        stats["upload_fail"] += 1
        reg.mark(rid, ingest_status="failed", fail_reason="lightrag_upload")


def run(batch: str, topics_file: str, max_urls_per_query: int = 6,
        max_total: int = 200, fetch_delay: float = 1.2, wiki_per_query: int = 2):
    reg = Registry()
    try:
        seed = json.loads(Path(topics_file).read_text(encoding="utf-8"))
        provider = SearxngProvider(SearchConfig())
        wiki = WikipediaProvider()
        total_registered = 0
        stats = {"search_ok": 0, "search_empty": 0, "fetched": 0, "fetch_fail": 0,
                 "wiki_docs": 0, "registered": 0, "dup_url": 0, "dup_text": 0,
                 "uploaded": 0, "upload_fail": 0}

        for theme in seed["themes"]:
            topic = theme["topic"]
            for query in theme["queries"]:
                if total_registered >= max_total:
                    log.info("max_total=%d reached, stop.", max_total)
                    break
                # ---- 来源一：维基百科官方 API（百科深度）----
                for w in wiki.search_and_fetch(query, top_k=wiki_per_query):
                    before = stats["registered"]
                    handle_wiki_doc(w, reg, batch, stats)
                    if stats["registered"] > before:
                        stats["wiki_docs"] += 1
                        total_registered += 1
                    time.sleep(fetch_delay)
                # ---- 来源二：SearXNG（bing/sogou → 政府/媒体/机构网页）----
                results = provider.search(query, top_k=max_urls_per_query + 2)
                reg.log_job(batch, "search", "ok" if results else "skipped",
                            query=query, engine="searxng",
                            detail={"results": len(results), "topic": topic})
                if not results:
                    stats["search_empty"] += 1
                    continue
                stats["search_ok"] += 1
                log.info("[%s] %s -> wiki+%d urls", topic, query, len(results))
                for res in results[:max_urls_per_query]:
                    if total_registered >= max_total:
                        break
                    from tools.fetcher import BLOCKED_DOMAINS
                    if any(b in res.url.lower() for b in BLOCKED_DOMAINS):
                        stats["skipped_blocked"] = stats.get("skipped_blocked", 0) + 1
                        reg.log_job(batch, "fetch", "skipped", query=query,
                                    target=res.url, detail={"reason": "hard-blocked domain"})
                        continue
                    try:
                        doc = fetch(res.url)
                    except Exception as exc:
                        log.warning("fetch raised %s: %s", res.url, exc)
                        doc = None
                    if doc is None:
                        stats["fetch_fail"] += 1
                        reg.log_job(batch, "fetch", "error", query=query,
                                    target=res.url, detail={"reason": "fetch/extract failed"})
                        time.sleep(fetch_delay)
                        continue
                    domain = domain_of(doc.canonical_url)
                    sdomain = lake_safe(domain)
                    ddir = LAKE / "raw" / sdomain
                    tdir = LAKE / "text" / sdomain
                    ddir.mkdir(parents=True, exist_ok=True)
                    tdir.mkdir(parents=True, exist_ok=True)
                    rid = rid_of(doc.canonical_url)
                    raw_path = str(ddir / f"{rid}.html")
                    text_path = str(tdir / f"{rid}.txt")
                    (ddir / f"{rid}.html").write_bytes(doc.raw_bytes)
                    (tdir / f"{rid}.txt").write_text(doc.text, encoding="utf-8")

                    status, rid = reg.insert_resource(doc, query, batch, raw_path, text_path)
                    if status == "duplicate_url":
                        stats["dup_url"] += 1
                        continue
                    if status == "duplicate_text":
                        stats["dup_text"] += 1
                        continue
                    stats["registered"] += 1
                    total_registered += 1
                    stats["fetched"] += 1

                    ok, file_source = upload_to_lightrag(rid, doc.title, doc.text)
                    if ok:
                        stats["uploaded"] += 1
                        reg.mark(rid, ingest_status="uploaded", lightrag_doc_id=file_source)
                        reg.log_job(batch, "ingest", "ok", query=query,
                                    target=doc.canonical_url, detail={"file_source": file_source})
                    else:
                        stats["upload_fail"] += 1
                        reg.mark(rid, ingest_status="failed", fail_reason="lightrag_upload")
                        reg.log_job(batch, "ingest", "error", query=query,
                                    target=doc.canonical_url)
                    time.sleep(fetch_delay)
                print(f"    progress: {json.dumps(stats, ensure_ascii=False)}", flush=True)
            if total_registered >= max_total:
                break
        print("FINAL:", json.dumps(stats, ensure_ascii=False))
        print("DB stats:", json.dumps(reg.stats(), ensure_ascii=False, default=str))
    finally:
        reg.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="batch1")
    ap.add_argument("--topics", default=r"D:\长江学论纲\ycki\yangtze\topics_batch1.json")
    ap.add_argument("--max-urls", type=int, default=6)
    ap.add_argument("--max-total", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--wiki-per-query", type=int, default=2)
    a = ap.parse_args()
    run(a.batch, a.topics, a.max_urls, a.max_total, a.delay, a.wiki_per_query)
