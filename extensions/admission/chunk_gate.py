# -*- coding: utf-8 -*-
"""Phase 4：Chunk Scope Gate —— 片段级相关性判定（允许一篇文档混合 CORE/CONTEXT/REJECT）。"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, parse_json
from extensions.prompts import PROMPTS

log = logging.getLogger("ycki.chunk_gate")

_VALID = {"CORE", "CONTEXT", "REJECT"}


def evaluate_chunks(title: str, scope_role: str,
                    chunks: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """对单个资源的全部片段一次性判定。chunks: [(index, text)]。"""
    if not chunks:
        return []
    listing = "\n".join(f"[片段{idx}] {text[:500]}" for idx, text in chunks)
    prompt = PROMPTS["chunk_scope_v1"].format(title=title, scope_role=scope_role,
                                              chunks=listing)
    raw = chat([{"role": "user", "content": prompt}], max_tokens=1800)
    data = parse_json(raw)
    if isinstance(data, dict):
        data = data.get("chunks") or data.get("results")
    verdicts: dict[int, dict[str, Any]] = {}
    for item in data or []:
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        rel = str(item.get("relevance", "REJECT")).upper()
        if rel not in _VALID:
            rel = "REJECT"
        verdicts[idx] = {"relevance": rel, "reason": str(item.get("reason", ""))[:150]}

    out = []
    for idx, text in chunks:
        v = verdicts.get(idx, {"relevance": "REJECT", "reason": "评审缺失，保守拒绝"})
        out.append({
            "chunk_index": idx,
            "chunk_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "relevance": v["relevance"],
            "reason": v["reason"],
            "model": SETTINGS.llm_model,
            "prompt_version": SETTINGS.prompt_scope_chunk,
        })
    return out


def persist(resource_id: str, verdicts: list[dict[str, Any]], conn) -> None:
    with conn.cursor() as cur:
        for v in verdicts:
            cur.execute(
                """INSERT INTO chunk_admissions
                   (resource_id, chunk_index, chunk_hash, relevance, reason,
                    model, prompt_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (resource_id, chunk_index) DO UPDATE
                   SET relevance=EXCLUDED.relevance, reason=EXCLUDED.reason,
                       evaluated_at=now()""",
                (resource_id, v["chunk_index"], v["chunk_hash"], v["relevance"],
                 v["reason"], v["model"], v["prompt_version"]))
        cur.execute(
            """INSERT INTO provenance_events (object_type, object_id, action, actor, detail)
               VALUES ('resource', %s, 'chunk_gate', 'chunk_gate', %s)""",
            (resource_id, json.dumps(
                {v["chunk_index"]: v["relevance"] for v in verdicts}, ensure_ascii=False)))
    conn.commit()
