# -*- coding: utf-8 -*-
"""Phase 11：存量资源全量重评 → Canonical KG 重建编排器。

流程（每资源）：
  Resource Scope Gate → Chunk Gate → 抽取(实体/事件/claims)
  → Entity Resolution → Evidence Binding → Claim Admission

可断点续跑：以 admission_status 与 chunk_admissions 幂等。
用法：
  python tools/rebuild_canonical.py --limit 10      # 抽样真实验证
  python tools/rebuild_canonical.py --all           # 全量（后台长跑）
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
from extensions.evidence.binder import bind
from extensions.extraction.extract import extract, persist_candidates

STATE_LOG = ROOT / "data" / "rebuild_canonical.log"


def log(msg: str):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(STATE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


_DYNASTY = [("夏", "夏"), ("商", "商"), ("周", "周"), ("秦", "秦"), ("汉", "汉"),
            ("三国", "三国"), ("晋", "晋"), ("南北朝", "南北朝"), ("隋", "隋"),
            ("唐", "唐"), ("宋", "宋"), ("元", "元"), ("明", "明"), ("清", "清"),
            ("民国", "民国"), ("近代", "近代"), ("现代", "现代"), ("当代", "当代")]


def make_timespan(conn, time_text: str, period: str = "") -> str | None:
    """从时间文本建 TimeSpan（v1：年份正则 + 朝代关键词）。"""
    raw = (time_text or period or "").strip()
    if not raw:
        return None
    year = None
    m = re.search(r"(公元前\s*\d{1,4}|公元\s*\d{1,4}|\d{4})年?", raw)
    if m:
        y = m.group(1).replace(" ", "")
        year = y if y.startswith("公元前") else y
    dynasty = next((d for d, _ in _DYNASTY if d in raw), None) if not year else None
    if not year and not dynasty and not period:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO timespans (valid_from, approximate, granularity, dynasty,
               historical_period, raw_text)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING timespan_id""",
            (year, bool(year and not re.fullmatch(r"\d{4}年?", year)),
             "year" if year else "dynasty", dynasty, period or None, raw[:80]))
        return cur.fetchone()[0]


def process_resource(resource: dict, conn) -> dict:
    rid = resource["resource_id"]
    title = resource["title"] or ""
    text_path = resource["text_path"]
    text = Path(text_path).read_text(encoding="utf-8", errors="replace") \
        if text_path and Path(text_path).exists() else ""

    # ---- Phase 2: Resource Scope Gate ----
    verdict = resource_gate.evaluate(
        title, text, resource["source_domain"] or "", resource.get("source_type") or "",
        discovery_topic=resource.get("discovery_topic") or "",
        search_query=resource.get("search_query") or "")
    resource_gate.persist(rid, verdict, conn)
    if verdict["scope_role"] == "REJECT":
        return {"rid": rid, "scope": "REJECT", "claims": 0, "entities": 0}

    # ---- Phase 4: Chunk Gate（按 1200 字切段） ----
    chunks = []
    size = 1200
    for i in range(0, len(text), size):
        chunks.append((i // size, text[i:i + size]))
    chunk_verdicts = chunk_gate.evaluate_chunks(title, verdict["scope_role"], chunks)
    chunk_gate.persist(rid, chunk_verdicts, conn)
    admitted_chunks = [(v["chunk_index"], chunks[v["chunk_index"]][1])
                       for v in chunk_verdicts if v["relevance"] in ("CORE", "CONTEXT")
                       and v["chunk_index"] < len(chunks)]
    if not admitted_chunks:
        return {"rid": rid, "scope": verdict["scope_role"], "claims": 0, "entities": 0}

    # ---- Phase 5: 抽取 ----
    result = extract(title, admitted_chunks)
    doc_id = resource.get("lightrag_doc_id") or ""
    n_cand = persist_candidates(rid, doc_id, result, conn)

    stats = {"rid": rid, "scope": verdict["scope_role"], "entities": n_cand,
             "events": 0, "claims": 0, "admitted": 0, "rejected": 0, "unresolved": 0}

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT candidate_id, surface_name, normalized_name, entity_type,
                              description FROM candidate_entities
                       WHERE resource_id=%s AND resolution_status='UNRESOLVED'""", (rid,))
        candidates = cur.fetchall()
    resolved: dict[str, str] = {}     # surface_name -> entity_id
    for cand in candidates:
        r = resolve(dict(cand), conn)
        if r["status"] == "UNRESOLVED":
            stats["unresolved"] += 1
            continue
        resolved[cand["surface_name"]] = str(r["entity_id"])

    def entity_for(name: str, etype: str = "Concept") -> str | None:
        """把名称解析成 entity_id；必要时补建 candidate 行（保证 FK 完整）。"""
        import hashlib
        if not name:
            return None
        if name in resolved:
            return resolved[name]
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT candidate_id, entity_type FROM candidate_entities
                           WHERE resource_id=%s AND surface_name=%s
                           ORDER BY created_at DESC LIMIT 1""", (rid, name))
            row = cur.fetchone()
        if row:
            cand = dict(row)
            cand["surface_name"] = name
            cand["normalized_name"] = name.strip().lower()
            cand["description"] = ""
        else:
            cid = "ce-" + hashlib.sha1(f"{rid}|{name}|{etype}".encode()).hexdigest()[:16]
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO candidate_entities
                       (candidate_id, surface_name, normalized_name, entity_type,
                        resource_id, document_id, extraction_model, prompt_version,
                        pipeline_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (candidate_id) DO NOTHING""",
                    (cid, name, name.strip().lower(), etype, rid, doc_id,
                     result["model"], result["prompt_version"], result["pipeline_version"]))
            cand = {"candidate_id": cid, "entity_type": etype,
                    "surface_name": name, "normalized_name": name.strip().lower(),
                    "description": ""}
        r = resolve(cand, conn)
        if r["status"] == "UNRESOLVED":
            stats["unresolved"] += 1
            return None
        resolved[name] = str(r["entity_id"])
        return resolved[name]

    # ---- 事件（Event 化，替代 pairwise 共现） ----
    chunk_text_by_idx = dict(admitted_chunks)
    first_chunk_id = f"{rid}-part0"
    for ev in result["events"]:
        eid = entity_for(ev["name"], "Event")
        if not eid:
            continue
        place_eid = entity_for(ev["place"]) if ev.get("place") else None
        ts = make_timespan(conn, ev.get("time", ""), ev.get("period", ""))
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO events (event_type, canonical_name, description,
                   timespan_id, place_entity_id, entity_id, status, resource_id,
                   quote_span, extraction_model, prompt_version)
                   VALUES (%s,%s,%s,%s,%s,%s,'CANDIDATE',%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING RETURNING event_id""",
                (ev["event_type"], ev["name"], ev["description"], ts, place_eid, eid,
                 rid, ev["quote_span"], result["model"], result["prompt_version"]))
            row = cur.fetchone()
        conn.commit()
        if row:
            stats["events"] += 1
            event_id = row[0]
            with conn.cursor() as cur:
                for pname in ev["participants"][:8]:
                    pid = entity_for(pname)
                    if pid:
                        cur.execute("""INSERT INTO event_participants
                                       (event_id, entity_id, role)
                                       VALUES (%s,%s,'participant')
                                       ON CONFLICT DO NOTHING""", (event_id, pid))
                for oname in ev["organizations"][:6]:
                    oid = entity_for(oname)
                    if oid:
                        cur.execute("""INSERT INTO event_participants
                                       (event_id, entity_id, role)
                                       VALUES (%s,%s,'organization')
                                       ON CONFLICT DO NOTHING""", (event_id, oid))
            conn.commit()

    # ---- Claims：ER → Evidence Binding → Admission ----
    from extensions.extraction.extract import predicate_domain_range
    for c in result["claims"]:
        subj = entity_for(c["subject"],
                          (predicate_domain_range(c["predicate"]) or [["Concept"]])[0][0])
        obj = entity_for(c["object"],
                         (predicate_domain_range(c["predicate"]) or ["", "Concept"])[1][0])
        if not subj or not obj:
            stats["rejected"] += 1
            continue
        chunk_text = next((t for _, t in admitted_chunks
                           if c["quote_span"][:20] in t), admitted_chunks[0][1])
        time_text = c.get("time", "")
        if not time_text:   # 时间缺失时从引文自动提取年份（缓解 temporal FAIL）
            m = re.search(r"(公元前\s*\d{1,4}|公元\s*\d{1,4}|\d{4})年?", c["quote_span"])
            if m:
                time_text = m.group(1).replace(" ", "")
        ts = make_timespan(conn, time_text)
        place_eid = entity_for(c["place"]) if c.get("place") else None
        draft = {
            "subject_entity_id": subj, "object_entity_id": obj,
            "predicate": c["predicate"], "quote_span": c["quote_span"],
            "chunk_id": first_chunk_id, "document_id": doc_id,
            "resource_id": rid,
            "source_id": resource.get("source_id"),
            "timespan_id": ts, "time_text": time_text,
            "place_name": c.get("place", ""), "object_name": c["object"],
            "chunk_text": chunk_text,
        }
        r = admit(draft, conn)
        if r["status"] == "ADMITTED":
            stats["admitted"] += 1
        else:
            stats["rejected"] += 1
        stats["claims"] += 1

    return stats


def fetch_batch(conn, limit: int, all_rows: bool):
    order = "r.resource_id ASC" if all_rows else "random()"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""SELECT r.resource_id, r.title, r.text_path, r.source_domain,
                              r.source_type, r.source_id, r.search_query, r.lightrag_doc_id,
                              COALESCE(r.discovery_topic,'') AS discovery_topic
                       FROM resources r
                       WHERE r.ingest_status='processed'
                         AND r.admission_status IN ('DISCOVERED','FETCHED')
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
    log(f"=== Canonical 重建：本批 {len(batch)} 资源 ===")
    totals = {"resources": 0, "CORE": 0, "CONTEXT": 0, "REJECT": 0,
              "claims": 0, "admitted": 0, "rejected": 0, "events": 0, "unresolved": 0}
    for res in batch:
        try:
            s = process_resource(dict(res), conn)
            totals["resources"] += 1
            totals[s.get("scope", "REJECT")] = totals.get(s.get("scope"), 0) + 1
            for k in ("claims", "admitted", "rejected", "events", "unresolved"):
                totals[k] += s.get(k, 0)
            log(f"{s.get('rid')} scope={s.get('scope')} entities={s.get('entities')} "
                f"events={s.get('events')} claims={s.get('claims')} "
                f"admitted={s.get('admitted')} rejected={s.get('rejected')} "
                f"unresolved={s.get('unresolved')}")
        except Exception as exc:
            conn.rollback()
            log(f"ERROR {res['resource_id']}: {exc}")
            import traceback
            log(traceback.format_exc()[-800:])
        time.sleep(1)
    log(f"=== 批完成: {json.dumps(totals, ensure_ascii=False)} ===")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM v_canonical_stats")
        cols = [d[0] for d in cur.description]
        log("canonical stats: " + str(dict(zip(cols, cur.fetchone()))))
    conn.close()


if __name__ == "__main__":
    main()
