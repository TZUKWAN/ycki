# -*- coding: utf-8 -*-
"""research_planner.py — 研究规划引擎（§6）。

替代固定 QUERY_TEMPLATES：
  6.1 Epistemic Diagnosis：对 Gap 回答 已知/未知/为何未知/缺什么维度
  6.2 Evidence Requirement Matrix：字段级 REQUIRED 矩阵（证据类型、来源类、
      最少独立来源）
  6.3 迭代查询波次：Wave1 概览 → Wave2 补缺失字段 → Wave3 矛盾搜索
  6.4 查询扩展维度：历史名/别名/繁简/时间/地点/人物/机构/路线/来源限定
  6.5 来源限定查询：site:gov.cn / site:edu.cn / 博物馆 / 地方志 / 档案 / 学报…
  6.6 强制矛盾搜索：高风险断言 ADMIT 前必须搜索 反例/争议/另一说
  6.7 停止规则：矩阵满足 或 连续两波无有效增益

输出 ResearchPlan(dict)：{diagnosis, matrix, waves: [{purpose, queries}], stop_rule}
供 cultural_system_growth 消费；LLM 缺席时退化为确定性模板（明确标注 degraded）。
"""
from __future__ import annotations

import re
from typing import Any

from extensions.llm import chat, parse_json  # noqa: E402

# §5.2 来源类 → 查询限定符（§6.5）
SOURCE_CLASSES: dict[str, dict[str, Any]] = {
    "Government": {"filters": ["site:gov.cn"], "hint": "政府 文件 公报"},
    "Archive": {"filters": ["site:gov.cn 档案", "档案馆"], "hint": "档案 馆藏 全宗"},
    "LocalChronicle": {"filters": ["地方志", "县志", "府志", "省志"], "hint": "地方志"},
    "Museum": {"filters": ["博物馆", "博物院"], "hint": "馆藏 陈列"},
    "ArchaeologicalInstitute": {"filters": ["考古", "文物考古研究所", "遗址"], "hint": "考古 发掘 简报"},
    "University": {"filters": ["site:edu.cn"], "hint": "大学 学报 研究"},
    "AcademicJournal": {"filters": ["学报", "期刊论文", "cnki"], "hint": "论文 考证"},
    "ResearchInstitute": {"filters": ["研究院", "研究所"], "hint": "研究 动态"},
    "Library": {"filters": ["图书馆"], "hint": "特藏 影印"},
    "AncientText": {"filters": ["原文", "影印", "四库", "丛书"], "hint": "古文 原文"},
    "Gazetteer": {"filters": ["水经注", "一统志", "地方志"], "hint": "水道 建置沿革"},
    "Newspaper": {"filters": ["申报", "大公报", "日报"], "hint": "近代 报刊"},
    "CulturalInstitution": {"filters": ["文化馆", "文旅"], "hint": "非遗 保护 名录"},
    "ICHDatabase": {"filters": ["非物质文化遗产", "非遗 名录", "代表性传承人"], "hint": "非遗"},
    "WaterConservancyInstitution": {"filters": ["水利", "长江水利委员会", "水文"], "hint": "水利 史料"},
    "PartyHistoryInstitution": {"filters": ["党史", "党史研究室", "革命纪念馆"], "hint": "党史 文献"},
    "Statistics": {"filters": ["统计年鉴", "统计"], "hint": "数据 统计"},
    "Wikipedia": {"filters": ["site:zh.wikipedia.org"], "hint": "维基"},
}

# §6.2 字段 → 证据类型 + 偏好来源类（缺省）
FIELD_MATRIX: dict[str, dict[str, Any]] = {
    "time": {"evidence_type": "chronicle/inscription", "sources": ["LocalChronicle", "AncientText", "AcademicJournal"], "min_sources": 2},
    "origin": {"evidence_type": "historical narrative", "sources": ["LocalChronicle", "AcademicJournal", "University"], "min_sources": 2},
    "destination": {"evidence_type": "historical narrative", "sources": ["LocalChronicle", "AcademicJournal"], "min_sources": 2},
    "content": {"evidence_type": "economic/custom record", "sources": ["Newspaper", "LocalChronicle", "AcademicJournal"], "min_sources": 2},
    "route": {"evidence_type": "route/transport record", "sources": ["Gazetteer", "WaterConservancyInstitution", "LocalChronicle"], "min_sources": 2},
    "mechanism": {"evidence_type": "institutional record", "sources": ["Government", "AcademicJournal", "PartyHistoryInstitution"], "min_sources": 2},
    "core_practices": {"evidence_type": "ethnographic/ICH record", "sources": ["ICHDatabase", "CulturalInstitution", "Museum"], "min_sources": 2},
    "carriers": {"evidence_type": "population/institution", "sources": ["LocalChronicle", "Archive", "University"], "min_sources": 2},
    "outcomes": {"evidence_type": "impact analysis", "sources": ["AcademicJournal", "University"], "min_sources": 1},
}

TRADITION_FIELDS = ["origin", "core_practices", "carriers", "time"]
PROCESS_FIELDS = ["time", "origin", "destination", "carriers", "mechanism", "outcomes"]
FLOW_FIELDS = ["origin", "destination", "content", "time", "route", "mechanism"]

GAP_TYPE_FIELDS = {
    "MISSING_SYSTEM_MEMBERSHIP": ["origin", "carriers"],
    "MISSING_PROCESS_STAGE": PROCESS_FIELDS,
    "MISSING_EVIDENCE": TRADITION_FIELDS,
    "SINGLE_SOURCE_STRUCTURE": TRADITION_FIELDS + PROCESS_FIELDS,
    "MISSING_CROSS_REGION_LINK": FLOW_FIELDS,
    "MISSING_HYDRO_LINK": ["route", "mechanism"],
}

ALIAS_HINTS = {
    "汉口": ["武汉", "江汉"], "川盐济楚": ["川盐", "盐济楚岸", "自贡 盐 两湖"],
    "湖广填四川": ["麻城孝感", "移民四川", "江西填湖广"], "万里茶道": ["羊楼洞", "中俄茶叶之路"],
}


class ResearchPlan(dict):
    @property
    def degraded(self) -> bool:
        return bool(self.get("_degraded"))


def _expand_terms(name: str) -> list[str]:
    """§6.4 查询扩展：别名/繁简/历史称谓（确定性起点，LLM 可增补）。"""
    terms = [name]
    for k, vals in ALIAS_HINTS.items():
        if k in name:
            terms += vals
    # 繁体近似：常见映射（不追求全量，覆盖高频字）
    t = name
    for s, tv in {"汉": "漢", "门": "門", "长": "長", "江": "江", "广": "廣",
                  "东": "東", "峡": "峽", "盐": "鹽", "济": "濟", "楚": "楚",
                  "铁": "鐵", "厂": "廠", "历": "歷", "历": "歷"}.items():
        t = t.replace(s, tv)
    if t != name:
        terms.append(t)
    return [x for x in dict.fromkeys(terms) if x]


def diagnose(conn_cursor, gap: dict[str, Any]) -> dict[str, Any]:
    """§6.1 确定性认识诊断：从库内统计已知/未知。"""
    ref = (gap.get("known") or {})
    name = ref.get("name") or ref.get("_ref") or gap.get("type", "")
    diag = {"target": name, "gap_type": gap["type"],
            "known_dimensions": sorted([k for k in ref.keys() if k != "_ref"]),
            "missing_dimensions": sorted((gap.get("missing") or {}).keys())}
    return diag


def build_plan(conn_cursor, gap: dict[str, Any], target_name: str,
               use_llm: bool = True) -> ResearchPlan:
    """生成 ResearchPlan。gap_type 决定字段矩阵；来源类决定查询限定。"""
    gap_type = gap["type"]
    fields = GAP_TYPE_FIELDS.get(gap_type, FLOW_FIELDS)
    matrix = {f: FIELD_MATRIX.get(f, {"evidence_type": "general", "sources": ["AcademicJournal"], "min_sources": 2})
              for f in fields}
    terms = _expand_terms(target_name)

    src_filters: list[str] = []
    for f, spec in matrix.items():
        for sc in spec["sources"]:
            for fl in SOURCE_CLASSES.get(sc, {}).get("filters", []):
                if fl not in src_filters:
                    src_filters.append(fl)

    waves: list[dict[str, Any]] = []
    w1 = [f"{t} 历史" for t in terms[:4]] + [f"{t} {h}" for t in terms[:2]
                                             for h in ("起源", "沿革", "考证")]
    waves.append({"purpose": "overview", "queries": _dedup(w1)[:8]})
    w2 = [f"{t} {fl}" for t in terms[:3] for fl in src_filters[:6]]
    w2 += [f"{t} {f} 史料" for t in terms[:2] for f in fields[:3]]
    waves.append({"purpose": "field_fill", "queries": _dedup(w2)[:10]})
    w3 = [f"{t} 争议" for t in terms[:3]] + [f"{t} 另一说" for t in terms[:2]] \
        + [f"{t} 质疑 考证" for t in terms[:2]]
    waves.append({"purpose": "contradiction", "queries": _dedup(w3)[:6]})

    plan = ResearchPlan({
        "target": target_name, "gap_type": gap_type, "diagnosis": diagnose(conn_cursor, gap),
        "matrix": matrix, "waves": waves,
        "stop_rule": "matrix_satisfied OR 2 consecutive waves without new CORE resources",
        "llm_augmented": False,
    })

    if use_llm:
        try:
            prompt = (
                "你是长江文化研究规划器。针对缺口目标，补充最多6个高质量中文检索词"
                "（含历史称谓、关键人物、关键地名、文献名），以及最多3个应优先的来源"
                "（如 地方志/博物馆/考古/非遗/档案/学报/水利/党史）。\n"
                f"缺口类型：{gap_type}\n目标：{target_name}\n"
                f"需求字段：{fields}\n只输出 JSON：{{\"queries\":[…],\"sources\":[…]}}")
            v = parse_json(chat([{"role": "user", "content": prompt}],
                                max_tokens=300, temperature=0.3)) or {}
            extra_q = [q for q in (v.get("queries") or []) if isinstance(q, str) and 2 <= len(q) <= 40]
            extra_s = [s for s in (v.get("sources") or []) if isinstance(s, str) and 2 <= len(s) <= 20]
            if extra_q:
                waves[0]["queries"] = _dedup(extra_q + waves[0]["queries"])[:8]
                plan["llm_augmented"] = True
            for s in extra_s:
                if s not in src_filters:
                    src_filters.append(s)
            waves[1]["queries"] = _dedup([f"{t} {s}" for t in terms[:3] for s in src_filters[:6]])[:10]
        except Exception:
            plan["_degraded"] = True
    plan["waves"] = waves
    return plan


def plan_queries(plan: ResearchPlan, wave_index: int, missing_fields: list[str] | None = None) -> list[str]:
    """取指定波次查询；field_fill 波可按缺失字段动态重生成。"""
    waves = plan["waves"]
    if wave_index == 1 and missing_fields:
        t = plan["target"]
        return _dedup([f"{t} {f} 史料 考证" for f in missing_fields] + waves[1]["queries"])[:10]
    return waves[min(wave_index, len(waves) - 1)]["queries"]


def _dedup(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
