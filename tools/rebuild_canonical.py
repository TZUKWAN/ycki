# -*- coding: utf-8 -*-
"""Phase 11 v3：存量资源重评编排器（五阶段断点续跑，抽取载荷持久化）。

resources.rebuild_stage：PENDING → GATED → CHUNK_GATED → EXTRACTED → DONE
每阶段完成即落库；崩溃后从上一阶段继续，不重复评审、不重复抽取。

关键修复（对齐外审 P0 清单）：
- Claim 端点禁止按谓词补建实体（entity_for 只查已解析实体）
- Evidence.chunk_id 指向 quote 实际所在分段（chunk://{rid}#{part}），page=part
- 事件 quote 绑定真实分段后才 ADMITTED
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg2
import psycopg2.extras

from config.settings import SETTINGS
from extensions.admission import resource_gate, chunk_gate
from extensions.admission.claim_gate import admit
from extensions.entity_resolution.resolver import resolve
from extensions.kg.pg_retrieval_graph import PGRetrievalGraph
from extensions.extraction.extract import extract, persist_candidates, \
    predicate_domain_range

STATE_LOG = ROOT / "data" / "rebuild_canonical.log"
CHUNK_SIZE = 1200


def log(msg: str):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(STATE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


_DYNASTY = ["夏", "商", "周", "秦", "汉", "三国", "晋", "南北朝", "隋", "唐",
            "宋", "元", "明", "清", "民国", "近代", "现代", "当代"]


def make_timespan(conn, time_text: str, period: str = "") -> str | None:
    """纪年解析统一走 extensions.timespan_cn（年号/朝代/干支/公元全支持）。"""
    from extensions.timespan_cn import parse as cn_parse
    raw = (time_text or period or "").strip()
    if not raw:
        return None
    parsed = cn_parse(raw)
    if not parsed and period:
        parsed = cn_parse(period)
    if not parsed:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO timespans (valid_from, approximate, granularity, dynasty,
               historical_period, raw_text)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING timespan_id""",
            (parsed["valid_from"], parsed["approximate"], parsed["granularity"],
             parsed["dynasty"], parsed["historical_period"], raw[:80]))
        return cur.fetchone()[0]


def _split(text: str, size: int = CHUNK_SIZE):
    return [(i // size, text[i:i + size]) for i in range(0, len(text), size)]


_NORM_RE = re.compile(r"[\s，。、；：？！\"'（）()\[\]【】《》<>—\-…·,.:;?!]+")


def _find_chunk(rid: str, quote: str, chunks: list[tuple[int, str]]):
    """定位 quote 实际所在分段 → (part, chunk_id, chunk_text, match_status)。"""
    if not quote:
        return None
    if quote in {t for _, t in chunks} or any(quote in t for _, t in chunks):
        for part, text in chunks:
            if quote in text:
                return part, f"chunk://{rid}#{part}", text, "EXACT"
    nq = _NORM_RE.sub("", quote)
    if not nq:
        return None
    for part, text in chunks:
        nt = _NORM_RE.sub("", text)
        if nq in nt:
            return part, f"chunk://{rid}#{part}", text, "NORMALIZED"
    if len(nq) >= 16:                      # 截断引文：前 16 归一化字符定位
        for part, text in chunks:
            nt = _NORM_RE.sub("", text)
            if nq[:16] in nt:
                return part, f"chunk://{rid}#{part}", text, "NORMALIZED"
    return None


def process_resource(resource: dict, conn) -> dict:
    pg_graph = PGRetrievalGraph(conn)
    rid = resource["resource_id"]
    stage = resource.get("rebuild_stage") or "PENDING"
    title = resource["title"] or ""
    text_path = resource["text_path"]
    text = Path(text_path).read_text(encoding="utf-8", errors="replace") \
        if text_path and Path(text_path).exists() else ""
    stats = {"rid": rid, "scope": resource.get("admission_status"), "entities": 0,
             "events": 0, "claims": 0, "admitted": 0, "rejected": 0, "unresolved": 0}

    def set_stage(s: str):
        nonlocal stage
        stage = s
        with conn.cursor() as cur:
            cur.execute("UPDATE resources SET rebuild_stage=%s WHERE resource_id=%s",
                        (s, rid))
        conn.commit()

    # ---- PENDING → GATED：Resource Scope Gate ----
    if stage == "PENDING":
        verdict = resource_gate.evaluate(
            title, text, resource["source_domain"] or "",
            resource.get("source_type") or "",
            discovery_topic=resource.get("discovery_topic") or "",
            search_query=resource.get("search_query") or "")
        resource_gate.persist(rid, verdict, conn)
        if verdict["scope_role"] == "REJECT":
            set_stage("DONE")
            stats["scope"] = "REJECT"
            return stats
        set_stage("GATED")

    # ---- GATED → CHUNK_GATED：Chunk Gate ----
    if stage == "GATED":
        chunks = _split(text)
        chunk_verdicts = chunk_gate.evaluate_chunks(title, stats["scope"], chunks)
        chunk_gate.persist(rid, chunk_verdicts, conn)
        set_stage("CHUNK_GATED")

    # 读取已通过片段（幂等）
    with conn.cursor() as cur:
        cur.execute("""SELECT chunk_index FROM chunk_admissions
                       WHERE resource_id=%s AND relevance IN ('CORE','CONTEXT')
                       ORDER BY chunk_index""", (rid,))
        admitted_idx = [r[0] for r in cur.fetchall()]
    all_parts = _split(text)
    admitted_chunks = [(p, all_parts[p][1]) for p in admitted_idx if p < len(all_parts)]
    if not admitted_chunks:
        set_stage("DONE")
        return stats

    # ---- CHUNK_GATED → EXTRACTED：抽取（载荷持久化） ----
    if stage == "CHUNK_GATED":
        result = extract(title, admitted_chunks)
        persist_candidates(rid, resource.get("lightrag_doc_id") or "", result, conn)
        set_stage("EXTRACTED")

    # ---- EXTRACTED：ER → 事件准入 → Claim 准入 ----
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT candidate_id, surface_name, normalized_name, entity_type,
                              description FROM candidate_entities
                       WHERE resource_id=%s AND resolution_status='UNRESOLVED'""", (rid,))
        candidates = cur.fetchall()
    resolved: dict[str, str] = {}
    for cand in candidates:
        # 实体门禁：文化相关性审核（§新增）
        g = gate_entity(cand["surface_name"], cand["entity_type"],
                        cand.get("description", ""), title)
        if g["verdict"] == "REJECT":
            with conn.cursor() as cur:
                cur.execute("""UPDATE candidate_entities SET resolution_status='TYPE_CONFLICT' WHERE candidate_id=%s""",
                            (cand["candidate_id"],))
            conn.commit()
            stats["entity_rejected"] = stats.get("entity_rejected", 0) + 1
            continue
        r = resolve(dict(cand), conn)
        if r["status"] == "UNRESOLVED":
            stats["unresolved"] += 1
            continue
        resolved[cand["surface_name"]] = str(r["entity_id"])
        # 写入 Retrieval Graph（PG 逐条，原子性保证）
        pg_graph.upsert_node(
            cand["surface_name"], cand["entity_type"],
            cand.get("description", ""), rid, doc_id)

    def entity_for(name: str) -> str | None:
        """只取已解析实体；不存在返回 None（claim 在 entity_resolution 阶段拒绝）。

        禁止按谓词期望类型补建实体（Phase 0 P0：循环验证）。
        """
        if not name:
            return None
        if name in resolved:
            return resolved[name]
        with conn.cursor() as cur:
            cur.execute("""SELECT resolved_entity_id FROM candidate_entities
                           WHERE resource_id=%s AND surface_name=%s
                             AND resolved_entity_id IS NOT NULL
                           ORDER BY created_at DESC LIMIT 1""", (rid, name))
            row = cur.fetchone()
        if row:
            resolved[name] = str(row[0])
            return resolved[name]
        return None

    # ---- 事件：解析实体 + quote 绑定真实分段 → ADMITTED / 保持 CANDIDATE ----
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT event_id, canonical_name AS name, event_type, description,
                              time_text, period, participants_json, organizations_json,
                              quote_span
                       FROM events WHERE resource_id=%s AND status='CANDIDATE'""", (rid,))
        events = cur.fetchall()
    for ev in events:
        eid = entity_for(ev["name"])
        if not eid:
            continue                          # 事件名实体未解析 → 保持 CANDIDATE
        place_eid = entity_for(ev["place"]) if ev.get("place") else None
        ts = make_timespan(conn, ev.get("time_text", ""), ev.get("period", ""))
        located = _find_chunk(rid, ev["quote_span"], admitted_chunks)
        status = "ADMITTED" if located else "CANDIDATE"
        part, cid, match = (located[0], located[1], located[3]) if located else \
            (None, None, "FAILED")
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE events SET timespan_id=%s, place_entity_id=%s, entity_id=%s,
                   status=%s, chunk_id=%s, match_status=%s WHERE event_id=%s""",
                (ts, place_eid, eid, status, cid, match, ev["event_id"]))
            for pname in (ev.get("participants_json") or [])[:8]:
                pid = entity_for(pname)
                if pid:
                    cur.execute("""INSERT INTO event_participants
                                   (event_id, entity_id, role) VALUES (%s,%s,'participant')
                                   ON CONFLICT DO NOTHING""", (ev["event_id"], pid))
            for oname in (ev.get("organizations_json") or [])[:6]:
                oid = entity_for(oname)
                if oid:
                    cur.execute("""INSERT INTO event_participants
                                   (event_id, entity_id, role) VALUES (%s,%s,'organization')
                                   ON CONFLICT DO NOTHING""", (ev["event_id"], oid))
        conn.commit()
        stats["events"] += 1

    # ---- Claims：十阶段准入（quote 绑定真实分段） ----
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT id, subject, predicate, object, time_text, place, quote_span
                       FROM pending_claims WHERE resource_id=%s AND consumed=false
                       ORDER BY id""", (rid,))
        pending = cur.fetchall()
    for c in pending:
        subj = entity_for(c["subject"])
        obj = entity_for(c["object"])
        located = _find_chunk(rid, c["quote_span"], admitted_chunks)
        chunk_id, chunk_text, part_idx = None, "", None
        if located:
            part_idx, chunk_id, chunk_text, _ = located
        else:
            chunk_text = admitted_chunks[0][1]     # 让 binder 产生 FAILED（诚实拒绝）

        dr = predicate_domain_range(c["predicate"])
        ts = make_timespan(conn, c.get("time_text", ""))
        place_eid = entity_for(c["place"]) if c.get("place") else None
        with conn.cursor() as cur:
            cur.execute("SELECT authority_level FROM sources WHERE source_id=%s",
                        (resource.get("source_id") or "",))
            ar = cur.fetchone()
        draft = {
            "subject_entity_id": subj, "object_entity_id": obj,
            "predicate": c["predicate"], "quote_span": c["quote_span"],
            "chunk_id": chunk_id, "chunk_part_index": part_idx,
            "chunk_text": chunk_text,
            "resource_id": rid, "document_id": resource.get("lightrag_doc_id") or "",
            "source_id": resource.get("source_id"),
            "authority_level": ar[0] if ar else "UNKNOWN",
            "timespan_id": ts, "time_text": c.get("time_text", ""),
            "place_name": c.get("place", ""), "object_name": c["object"],
            "place_entity_id": place_eid,
        }
        r = admit(draft, conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_claims SET consumed=true WHERE id=%s",
                        (c["id"],))
        conn.commit()
        stats["claims"] += 1
        if r["status"] in ("ADMITTED", "CONTESTED", "SUPPORTED"):
            stats["admitted"] += 1
        else:
            stats["rejected"] += 1

    set_stage("DONE")
    return stats


def fetch_batch(conn, limit: int, all_rows: bool):
    order = "r.resource_id ASC" if all_rows else "random()"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""SELECT r.resource_id, r.title, r.text_path, r.source_domain,
                               r.source_type, r.source_id, r.search_query,
                               r.lightrag_doc_id, r.rebuild_stage,
                               COALESCE(r.admission_status,'DISCOVERED') AS admission_status,
                               COALESCE(r.discovery_topic,'') AS discovery_topic
                        FROM resources r
                        WHERE r.ingest_status IN ('processed','failed')
                          AND r.rebuild_stage <> 'DONE'
                        ORDER BY {order} LIMIT %s""", (limit,))
        return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    conn = psycopg2.connect(SETTINGS.pg_dsn)
    conn.autocommit = False
    batch = fetch_batch(conn, a.limit if not a.all else 10**6, a.all)
    log(f"=== Canonical 重建 v3：本批 {len(batch)} 资源 ===")
    totals = {"resources": 0, "claims": 0, "admitted": 0, "rejected": 0,
              "events": 0, "unresolved": 0}
    for res in batch:
        try:
            s = process_resource(dict(res), conn)
            totals["resources"] += 1
            for k in ("claims", "admitted", "rejected", "events", "unresolved"):
                totals[k] += s.get(k, 0) or 0
            log(f"{s.get('rid')} scope={s.get('scope')} events={s.get('events')} "
                f"claims={s.get('claims')} admitted={s.get('admitted')} "
                f"rejected={s.get('rejected')} unresolved={s.get('unresolved')}")
        except Exception as exc:
            conn.rollback()
            log(f"ERROR {res['resource_id']}: {exc}")
            import traceback
            log(traceback.format_exc()[-600:])
        time.sleep(1)
    log(f"=== 批完成: {json.dumps(totals, ensure_ascii=False)} ===")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM v_canonical_stats")
        cols = [d[0] for d in cur.description]
        log("canonical stats: " + str(dict(zip(cols, cur.fetchone()))))
    conn.close()


if __name__ == "__main__":
    main()
