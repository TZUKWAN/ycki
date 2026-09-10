# -*- coding: utf-8 -*-
"""YCKI 注册表：PostgreSQL sources/resources 读写 + 权威分级（真实实现，方案 §13/§14）"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from tools.fetcher import canonicalize, domain_of

log = logging.getLogger("ycki.registry")

import os

DSN = os.environ.get(
    "YCKI_PG_DSN",
    "host=127.0.0.1 port=5433 dbname=ycki user=postgres password=ycki_pg_2026",
)

# 权威分级（方案 §14：仅作证据信息之一，非唯一真值判据）
GOV_SUFFIX = (".gov.cn",)
EDU_SUFFIX = (".edu.cn",)
ACADEMIC = ("cnki.net", "wanfangdata.com.cn", "cssn.cn", "cnki.com.cn", "cqvip.com")
MUSEUM_LIB = ("museum", "bowuguan", "library", "archives", "dangan")
S_DOMAINS = {
    "www.gov.cn": "S", "www.sach.gov.cn": "S", "www.ncha.gov.cn": "S",
    "www.whc.unesco.org": "S",
}
A_DOMAINS = (
    "kaogu.cssn.cn", "www.kaogu.cn",            # 考古
    "www.ncha.gov.cn",
)
MEDIA = (
    "people.com.cn", "xinhuanet.com", "news.cn", "cctv.com", "cntv.cn",
    "chinanews.com", "chinanews.com.cn", "thepaper.cn", "gmw.cn", "cnr.cn",
    "legaldaily.com.cn", "china.com.cn", "china.com", "yicai.com", "caixin.com",
    "hubei.gov.cn",
)
UGC = ("baike.baidu.com", "zhihu.com", "zhidao.baidu.com", "wenku.baidu.com",
       "douban.com", "tieba.baidu.com", "weibo.com", "sohu.com", "163.com",
       "qq.com", "sina.com.cn", "baijiahao.baidu.com", "toutiao.com",
       "bilibili.com", "douyin.com", "36kr.com", "ifeng.com")
# 网络百科/专业参考（社区编辑但编辑流程规范）：按 B 级参考源处理，记录于 DECISIONS
REFERENCE = ("wikipedia.org", "britannica.com")


def classify_source(domain: str) -> tuple[str, str, int]:
    """返回 (source_type, authority_level, priority)。真实规则分级。"""
    d = domain.lower()
    if d in S_DOMAINS:
        return "Government", S_DOMAINS[d], 1
    if d.endswith(GOV_SUFFIX):
        return "Government", "S", 1
    if d.endswith(EDU_SUFFIX):
        return "University", "A", 2
    if any(d.endswith(a) or d == a for a in ACADEMIC):
        return "AcademicJournal", "A", 2
    if any(d.endswith(m) or d == m for m in MEDIA):
        return "Newspaper", "B", 3
    if any(d.endswith(r) or d == r for r in REFERENCE):
        return "GeneralWebsite", "B", 3
    if any(k in d for k in MUSEUM_LIB):
        return "Museum", "A", 2
    if any(d.endswith(u) or d == u for u in UGC):
        return "GeneralWebsite", "C", 5
    return "GeneralWebsite", "UNKNOWN", 4


def rid_of(canonical_url: str) -> str:
    return "res-" + hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()[:16]


def sid_of(domain: str) -> str:
    return "src-" + hashlib.sha1(domain.encode("utf-8")).hexdigest()[:10]


class Registry:
    def __init__(self):
        self.conn = psycopg2.connect(DSN)
        self.conn.autocommit = True

    def close(self):
        self.conn.close()

    # ---- sources ----
    def get_or_create_source(self, domain: str, name: str | None = None) -> str:
        stype, level, prio = classify_source(domain)
        sid = sid_of(domain)
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sources (source_id, name, domain, source_type,
                                     authority_level, priority, last_checked)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (domain) DO UPDATE SET last_checked = now()
                RETURNING source_id
            """, (sid, name or domain, domain, stype, level, prio))
            return cur.fetchone()[0]

    # ---- resources ----
    def url_known(self, canonical_url: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM resources WHERE canonical_url=%s", (canonical_url,))
            return cur.fetchone() is not None

    def insert_resource(self, doc, query: str, batch: str, raw_path: str,
                        text_path: str, discovery_topic: str | None = None) -> tuple[str, str]:
        """返回 (status, resource_id)。status ∈ registered|duplicate_url|duplicate_text"""
        canon = doc.canonical_url
        domain = domain_of(canon)
        sid = self.get_or_create_source(domain)
        stype, _level, _prio = classify_source(domain)
        rid = rid_of(canon)
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO resources (resource_id, title, source_url, canonical_url,
                        source_domain, source_id, source_type, author, publication_time,
                        mime_type, http_status, checksum, text_checksum,
                        raw_path, text_path, content_chars,
                        search_query, collection_batch, retrieved_at, discovery_topic)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),
                            %s)
                    ON CONFLICT (text_checksum) DO NOTHING
                    RETURNING resource_id
                """, (rid, doc.title, doc.url, canon, domain, sid, stype,
                      doc.author, doc.date, doc.mime_type, doc.http_status,
                      doc.raw_sha256, doc.text_sha256, raw_path, text_path,
                      len(doc.text), query, batch, discovery_topic))
                row = cur.fetchone()
                if row:
                    return "registered", row[0]
                cur.execute("SELECT resource_id FROM resources WHERE canonical_url=%s", (canon,))
                if cur.fetchone():
                    return "duplicate_url", rid
                return "duplicate_text", rid
        except psycopg2.errors.UniqueViolation:
            return "duplicate_url", rid

    def mark(self, rid: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=%s" for k in fields)
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE resources SET {cols} WHERE resource_id=%s",
                        (*fields.values(), rid))

    def log_job(self, batch, phase, status, query=None, target=None,
                engine=None, detail=None):
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO collection_jobs
                (batch, phase, status, query, target, engine, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (batch, phase, status, query, target, engine,
                 json.dumps(detail or {}, ensure_ascii=False)))

    def stats(self) -> dict:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM v_collection_stats")
            return dict(cur.fetchone())

    def authority_hist(self) -> list:
        with self.conn.cursor() as cur:
            cur.execute("""SELECT s.authority_level, count(*) FROM resources r
                           JOIN sources s USING (source_id) GROUP BY 1 ORDER BY 1""")
            return cur.fetchall()
