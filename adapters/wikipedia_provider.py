# -*- coding: utf-8 -*-
"""YCKI SearchProvider #2 — 中文维基百科官方 API（真实实现）
遵循其 UA 政策；搜索 + 正文 extract 一步完成，返回与 fetcher.FetchedDoc 对齐的结构。
"""
from __future__ import annotations

import hashlib
import logging
import time

import requests

log = logging.getLogger("ycki.wikipedia")

API = "https://zh.wikipedia.org/w/api.php"
UA = "YCKI-ResearchBot/0.1 (+Yangtze Cultural Knowledge Infrastructure; academic; contact: local)"
PARAMS_SEARCH = {"action": "query", "list": "search", "format": "json", "utf8": 1}
PARAMS_EXTRACT = {"action": "query", "prop": "extracts", "explaintext": 1,
                  "format": "json", "utf8": 1, "redirects": 1}


class WikipediaProvider:
    def __init__(self, timeout: int = 25, delay: float = 2.0):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        try:
            r = self.session.get(API, params={**PARAMS_SEARCH, "srsearch": query,
                                              "srlimit": top_k},
                                 timeout=self.timeout)
            r.raise_for_status()
            hits = r.json().get("query", {}).get("search", [])
            return [{"title": h["title"], "snippet": h.get("snippet", "")} for h in hits]
        except Exception as exc:
            log.warning("wiki search error %s: %s", query, exc)
            return []

    def fetch_extract(self, title: str) -> dict | None:
        """返回 {title, text, url, raw_sha256, text_sha256, raw_content, chars}；失败 None。"""
        try:
            r = self.session.get(API, params={**PARAMS_EXTRACT, "titles": title},
                                 timeout=self.timeout)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "15") or 15)
                log.warning("wiki 429, sleeping %ds (%s)", wait, title)
                time.sleep(wait)
                r = self.session.get(API, params={**PARAMS_EXTRACT, "titles": title},
                                     timeout=self.timeout)
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", {})
            for _, page in pages.items():
                text = (page.get("extract") or "").strip()
                if len(text) < 300:
                    return None
                url = "https://zh.wikipedia.org/wiki/" + requests.utils.quote(title, safe="")
                return {
                    "title": title,
                    "text": text,
                    "url": url,
                    "raw_sha256": hashlib.sha256(r.content).hexdigest(),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "raw_content": r.content,          # 真实 API 响应，作为湖内原始件
                    "chars": len(text),
                    "mime_type": "application/wiki-api+json",
                    "author": None,
                    "date": None,
                }
        except Exception as exc:
            log.warning("wiki extract error %s: %s", title, exc)
        return None

    def search_and_fetch(self, query: str, top_k: int = 2) -> list[dict]:
        out = []
        for hit in self.search(query, top_k=top_k + 1):
            if len(out) >= top_k:
                break
            doc = self.fetch_extract(hit["title"])
            if doc:
                doc["search_query"] = query
                out.append(doc)
            time.sleep(self.delay)
        return out
