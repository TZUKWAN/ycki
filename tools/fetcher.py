# -*- coding: utf-8 -*-
"""YCKI 抓取器：轻量 HTTP + trafilatura 正文抽取 + 质量守卫（真实实现，失败如实记录）
方案 §17：普通网页轻量 fetch 优先；浏览器 fallback 留待后续批次。
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
import trafilatura
from bs4 import BeautifulSoup

log = logging.getLogger("ycki.fetcher")

UA = "YCKI-ResearchBot/0.1 (+Yangtze Cultural Knowledge Infrastructure; academic; contact: local)"
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}

SKIP_SUFFIX = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
               ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
               ".zip", ".rar", ".7z", ".mp3", ".mp4", ".avi", ".wmv", ".flv",
               ".exe", ".apk", ".iso")
# 实测硬封锁（403，含浏览器 UA）或需登录的站点：直接跳过，如实记录（2026-09-06 实测）
BLOCKED_DOMAINS = ("baike.baidu.com", "zhihu.com", "zhuanlan.zhihu.com",
                   "wenku.baidu.com", "zhidao.baidu.com", "baijiahao.baidu.com",
                   "xueqiu.com", "docs.qq.com")
STRIP_PARAMS = re.compile(r"^(utm_|spm|from|fr|share_|isapp|scene|subscene|refer|sharer|tdsourcetag)", re.I)


@dataclass
class FetchedDoc:
    url: str
    canonical_url: str
    final_url: str
    http_status: int
    raw_sha256: str
    text_sha256: str
    title: str
    text: str
    author: str | None
    date: str | None
    raw_bytes: bytes
    mime_type: str


def canonicalize(url: str) -> str:
    """URL 规范化：去 fragment、去跟踪参数、统一 scheme/host 大小写、去尾斜杠。"""
    p = urlparse(url)
    scheme = p.scheme.lower() or "http"
    netloc = p.netloc.lower()
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not STRIP_PARAMS.match(k)]
    query = urlencode(kept)
    path = p.path or "/"
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", query, ""))


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def lake_safe(domain: str) -> str:
    """域名 → Windows 安全目录名（去除端口冒号等非法字符）。"""
    return re.sub(r"[^a-z0-9.\-_]", "_", domain.lower())


def looks_like_garbage(text: str) -> bool:
    """词表 dump 启发式：句末标点密度过低视为乱码/词表（CJK 感知）。"""
    if len(text) < 300:
        return True
    sample = text[:2000]
    ends = len(re.findall(r"[。！？.!?\n]", sample))
    return (ends / max(len(sample), 1)) < 0.01


def fetch(url: str, timeout: int = 25, max_bytes: int = 2_000_000) -> FetchedDoc | None:
    """真实抓取。任何失败返回 None（调用方记录失败原因）。"""
    low = url.lower()
    if low.endswith(SKIP_SUFFIX):
        log.info("skip non-html suffix: %s", url)
        return None
    if any(b in low for b in BLOCKED_DOMAINS):
        log.info("skip hard-blocked domain: %s", url)
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True,
                            allow_redirects=True)
    except Exception as exc:
        log.warning("fetch error %s: %s", url, exc)
        return None
    status = resp.status_code
    if status != 200:
        log.warning("fetch http %d: %s", status, url)
        resp.close()
        return None
    raw = resp.raw.read(max_bytes + 1, decode_content=True) or b""
    if len(raw) > max_bytes:
        log.warning("too large: %s", url)
        return None
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype.lower() and "text" not in ctype.lower() and "xhtml" not in ctype.lower():
        log.info("skip non-text content-type %s: %s", ctype, url)
        return None
    if resp.encoding and resp.encoding.lower() not in ("utf-8", "utf8", "gbk", "gb2312", "gb18030", "big5"):
        resp.encoding = None
    if not resp.encoding:
        resp.encoding = resp.apparent_encoding
    html = raw.decode(resp.encoding or "utf-8", errors="replace")

    # 正文抽取：trafilatura 优先，bs4 兜底
    text = trafilatura.extract(html, url=url, include_comments=False,
                               include_tables=True, favor_recall=True) or ""
    title, author, date = None, None, None
    meta = trafilatura.extract_metadata(html)
    if meta:
        title, author, date = meta.title, meta.author, meta.date
    if not text or len(text) < 200:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
            tag.decompose()
        text2 = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
        if len(text2) > len(text):
            text = text2
            if not title:
                title = soup.title.string.strip() if soup.title and soup.title.string else None
    text = text.strip()
    if looks_like_garbage(text):
        log.info("low-quality/short after extraction: %s (%d chars)", url, len(text))
        return None

    canon = canonicalize(url)
    return FetchedDoc(
        url=url, canonical_url=canon, final_url=str(resp.url), http_status=status,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        title=(title or "").strip()[:300] or canon.rsplit("/", 1)[-1][:80],
        text=text, author=(author or None), date=(date or None),
        raw_bytes=raw, mime_type=ctype.split(";")[0].strip() or "text/html",
    )
