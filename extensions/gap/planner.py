# -*- coding: utf-8 -*-
"""Phase 15：Gap → ResearchTask（查询扩展 + 任务生成）。

对 OPEN 缺口生成 ResearchTask：
- missing_region  → "该省 + 长江" 模板查询 + LLM 扩展
- missing_period  → "时期 + 主要主题" 模板查询 + LLM 扩展
- single_source   → 为主张生成补充来源检索词
- uncovered_subquestion / conflicting 同理

所有查询写入 research_tasks.queries，由 runner（tools/gap_growth.py）执行采集，
采集结果经 Scope Gate 准入后重算覆盖，Gap 自动收敛/关闭。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, parse_json

log = logging.getLogger("ycki.gap_planner")

TEMPLATE_HINT = {
    "missing_region": "围绕该地区在长江流域中的历史文化、水利、城市、非遗、名人生成检索词",
    "missing_period": "围绕该时期发生在长江流域的事件、人物、工程、作品生成检索词",
    "single_source": "围绕该主张寻找第二独立来源（权威媒体/政府/学术）验证",
    "missing_entity_info": "围绕该实体补充生平/沿革/影响的权威来源",
    "conflicting": "寻找能裁决两条冲突主张的权威史料",
    "uncovered_subquestion": "直接检索该子问题",
}


def expand_queries(gap: dict[str, Any]) -> list[str]:
    """LLM 查询扩展：缺口 → 6-10 条中文检索词。失败时用模板兜底。"""
    gtype = gap.get("gap_type", "")
    region = gap.get("region") or ""
    period = gap.get("period") or ""
    topic = gap.get("topic") or ""
    hint = TEMPLATE_HINT.get(gtype, "围绕该缺口生成检索词")
    target = " ".join(x for x in (region, period, topic) if x)
    prompt = (
        f"你是长江文化研究资料采集规划员。知识缺口类型：{gtype}。\n"
        f"缺口对象：{target or gap.get('detail', '')[:80]}\n"
        f"任务：{hint}。\n"
        "输出 JSON 数组（6-8 条中文搜索词，每条 6-14 字，面向网页搜索）："
        '["检索词1","检索词2",...]')
    try:
        raw = chat([{"role": "user", "content": prompt}], max_tokens=400, temperature=0.4)
        from extensions.llm import parse_json
        import json as _json
        data = parse_json(raw)
        if isinstance(data, list):
            return [str(x).strip()[:40] for x in data if str(x).strip()][:8]
        if isinstance(data, dict):
            qs = data.get("queries")
            if isinstance(qs, list):
                return [str(x).strip()[:40] for x in qs if str(x).strip()][:8]
    except Exception as exc:
        log.warning("expand error: %s", exc)
    # 模板兜底
    base = target or "长江文化"
    return [f"{base} 概况", f"{base} 历史", f"{base} 文化遗产"]


def make_task(gap: dict[str, Any], queries: list[str]) -> dict[str, Any]:
    gid = gap.get("gap_id", "")
    tid = "rt-" + hashlib.sha1(f"{gid}|{datetime.utcnow()}".encode()).hexdigest()[:12]
    intent = f"[{gap.get('gap_type')}] " + " ".join(
        x for x in (gap.get("region"), gap.get("period"), gap.get("topic")) if x)
    return {"task_id": tid, "gap_id": gid, "status": "PLANNED",
            "search_intent": intent[:200], "queries": queries}


import hashlib  # noqa: E402  (hashlib 引用延后避免顶部噪音)
from datetime import datetime, timezone  # noqa: E402
