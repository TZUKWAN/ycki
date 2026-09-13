# -*- coding: utf-8 -*-
"""source_strategy.py — 来源策略引擎（§5.1-§5.3）。

回答：这个问题最可能由什么来源回答？
  - 按 gap 类型 / 主题关键词选择来源类排序（考古文明/地方历史/非遗/水文化/
    红色文化/近代工业 各有偏好谱，§5.3）。
  - 输出 provider 计划：wikipedia / searxng / searxng+site 限定。
供 collect.py 与 cultural_system_growth 消费。
"""
from __future__ import annotations

from typing import Any

# §5.3 缺口/主题 → 来源类优先谱
TOPIC_PROFILES: dict[str, list[str]] = {
    "archaeology": ["ArchaeologicalInstitute", "Museum", "AcademicJournal", "University", "Government"],
    "local_history": ["LocalChronicle", "Archive", "Museum", "University", "AcademicJournal"],
    "ich": ["ICHDatabase", "CulturalInstitution", "Museum", "AcademicJournal"],
    "water": ["WaterConservancyInstitution", "Gazetteer", "LocalChronicle", "AcademicJournal"],
    "red": ["PartyHistoryInstitution", "Archive", "Museum", "AcademicJournal"],
    "industry": ["Archive", "LocalChronicle", "AcademicJournal", "Museum", "University"],
    "general": ["Wikipedia", "LocalChronicle", "AcademicJournal", "Museum", "Government"],
}

_TOPIC_KEYWORDS = [
    ("archaeology", ("考古", "遗址", "出土", "新石器", "青铜", "墓葬", "文明", "城址")),
    ("ich", ("非遗", "非物质", "传承", "习俗", "技艺", "节庆", "表演")),
    ("water", ("水利", "水系", "航运", "堤防", "灌溉", "航道", "治水", "水灾")),
    ("red", ("革命", "红色", "抗战", "起义", "根据地", "红军", "党史")),
    ("industry", ("工业", "铁路", "工厂", "开埠", "洋务", "铁厂", "纺织", "商会")),
    ("local_history", ("府", "县", "志", "沿革", "移民", "商帮", "古镇", "码头")),
]

SITE_FILTERS = {
    "Government": "site:gov.cn",
    "University": "site:edu.cn",
    "ArchaeologicalInstitute": "考古 文物",
    "Museum": "博物馆",
    "LocalChronicle": "地方志",
    "Archive": "档案",
    "AcademicJournal": "学报 OR 期刊",
    "ICHDatabase": "非物质文化遗产",
    "WaterConservancyInstitution": "水利",
    "PartyHistoryInstitution": "党史",
    "Gazetteer": "水经注 OR 建置沿革",
    "Newspaper": "申报 OR 近代报刊",
    "Wikipedia": "site:zh.wikipedia.org",
}


def classify_topic(text: str) -> str:
    best, hits = "general", 0
    for prof, kws in _TOPIC_KEYWORDS:
        n = sum(1 for k in kws if k in text)
        if n > hits:
            best, hits = prof, n
    return best


def source_classes_for(topic_text: str, gap_type: str | None = None) -> list[str]:
    """返回按优先级排序的来源类。"""
    prof = classify_topic(topic_text)
    classes = list(TOPIC_PROFILES.get(prof, TOPIC_PROFILES["general"]))
    if gap_type == "MISSING_HYDRO_LINK" and "WaterConservancyInstitution" not in classes[:2]:
        classes.insert(0, "WaterConservancyInstitution")
    if gap_type == "MISSING_EVIDENCE" and "ICHDatabase" not in classes:
        classes.insert(1, "ICHDatabase")
    return classes


def provider_plan(queries: list[str], topic_text: str,
                  gap_type: str | None = None,
                  max_site_queries: int = 6) -> list[dict[str, Any]]:
    """把一组裸查询展开为 provider 计划：
      wikipedia  官方 API 词条
      searxng    泛网页
      searxng+site 来源类限定查询（Top-N 类）
    """
    classes = source_classes_for(topic_text, gap_type)
    plan: list[dict[str, Any]] = []
    for q in queries:
        plan.append({"provider": "wikipedia", "query": q, "source_class": "Wikipedia"})
    for q in queries:
        plan.append({"provider": "searxng", "query": q, "source_class": "GeneralWebsite"})
    n = 0
    for cls in classes:
        filt = SITE_FILTERS.get(cls)
        if not filt:
            continue
        for q in queries:
            if n >= max_site_queries:
                break
            plan.append({"provider": "searxng", "query": f"{q} {filt}",
                         "source_class": cls})
            n += 1
        if n >= max_site_queries:
            break
    return plan
