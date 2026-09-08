# -*- coding: utf-8 -*-
"""YCKI SearchProvider — 本机 SearXNG 适配器（真实实现，方案 §16 search(query, filters, top_k)）"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger("ycki.searxng")


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    engine: str
    query: str = ""


@dataclass
class SearchConfig:
    base_url: str = "http://127.0.0.1:8080/search"
    engines: list = field(default_factory=lambda: ["bing", "sogou"])
    language: str = "zh-CN"
    timeout: int = 30
    max_retries: int = 2


class SearxngProvider:
    """search(query, top_k) -> list[SearchResult]。跨引擎 URL 去重，按引擎真实返回为准。"""

    def __init__(self, cfg: SearchConfig | None = None):
        self.cfg = cfg or SearchConfig()
        self.session = requests.Session()

    def search(self, query: str, top_k: int = 10, engines: list[str] | None = None) -> list[SearchResult]:
        params = {
            "q": query,
            "format": "json",
            "language": self.cfg.language,
            "safesearch": 1,
            "engines": ",".join(engines or self.cfg.engines),
        }
        for attempt in range(self.cfg.max_retries + 1):
            try:
                r = self.session.get(self.cfg.base_url, params=params, timeout=self.cfg.timeout)
                if r.status_code == 200:
                    data = r.json()
                    out, seen = [], set()
                    for item in data.get("results", []):
                        url = (item.get("url") or "").strip()
                        if not url.startswith("http"):
                            continue
                        key = url.rstrip("/").lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(SearchResult(
                            url=url,
                            title=(item.get("title") or "").strip(),
                            snippet=(item.get("content") or "").strip(),
                            engine=item.get("engine") or "?",
                            query=query,
                        ))
                        if len(out) >= top_k:
                            break
                    log.info("search[%s] -> %d results", query, len(out))
                    return out
                log.warning("searxng http %d on %r (attempt %d)", r.status_code, query, attempt)
            except Exception as exc:  # 真实失败必须暴露
                log.warning("searxng error on %r: %s (attempt %d)", query, exc, attempt)
            time.sleep(2 * (attempt + 1))
        return []


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    p = SearxngProvider()
    for r in p.search(sys.argv[1] if len(sys.argv) > 1 else "长江文明", top_k=5):
        print(f"[{r.engine}] {r.title}\n    {r.url}")
