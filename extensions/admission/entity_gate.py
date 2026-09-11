# -*- coding: utf-8 -*-
"""entity_scope_v3：实体级文化相关性过滤（Scope Gate 后的第二道门）。

Scope Gate 判断资源是否在长江流域；本 Gate 判断抽取出的实体是否真正构成
长江文化研究对象。一个上海的交通报告虽在长江流域，但"P+R停车换乘"不是
长江文化。实体必须满足以下至少一条：
1. 在长江流域有历史/文化/地理意义
2. 是长江文化事件/人物/作品/遗产
3. 是长江流域特有的民俗/工艺/水系/物种

判定标准从严：泛泛的城市基础设施、通用概念、现代行政标签 → REJECT。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from config.settings import SETTINGS
from extensions.llm import chat, parse_json

log = logging.getLogger("ycki.entity_gate")

PROMPT = """你是长江文化知识库的实体质量审核员。判断以下实体是否值得纳入"长江文化知识图谱"。

## 纳入标准（必须至少满足一条）
1. 与长江流域的自然地理、水系、水利直接相关
2. 是长江流域历史事件、历史人物、历史地名
3. 是长江流域文化遗产、非遗、民俗、艺术
4. 是长江流域城市有历史意义的地标、遗址、建筑
5. 是研究长江文化的重要概念/思想/著作

## 排除标准（必须排除，即使位于长江流域）
- 现代城市基础设施（停车场、地铁站、高速公路、立交桥）
- 网站/软件/技术产品（APP、查重系统、游戏）
- 通用字典释义（"X的意思""X怎么读"）
- 无历史文化意义的现代行政区划变更
- 商业广告、订票系统、官方导航页

## 待审核实体
名称：{name}
类型：{etype}
描述：{description}
来源资源标题：{source_title}

## 输出严格 JSON
{{"verdict":"KEEP|REJECT","reason":"20字内",
"topic":"水利工程|历史事件|历史人物|文化遗产|非遗民俗|文学艺术|城市史|水系地理|红色文化|工业史|对外交流|其他"}}"""

ENTITY_TYPES = {"Person", "Place", "Organization", "Institution", "Event", "Work",
                "Artifact", "Heritage", "Site", "Practice", "Concept", "WaterSystem",
                "Route", "NaturalObject", "EthnicGroup"}

# 硬负例：出现即 REJECT
HARD_REJECT = re.compile(
    r"停车|换乘|P\+R|收费站|高速公路|G\d+|S\d+省道|立交|高架|地铁线路|公交线路|"
    "查重|搬运|DNF|搬砖|bilibili|快手|抖音|APP|下载|安装|"
    "怎么读|的意思|的解释|的拼音|的笔顺|新华字典|汉典|"
    "官网|首页|订票|门票价格|导航|在线|系统说明|"
    "搬砖攻略|游戏|论坛", re.I)


def gate_entity(name: str, etype: str, description: str,
                source_title: str = "") -> dict[str, Any]:
    """审核单个实体。返回 {"verdict": "KEEP"|"REJECT", "reason": str}。"""
    # 快速硬拒
    if HARD_REJECT.search(name or ""):
        return {"verdict": "REJECT", "reason": "硬负例命中（交通/网站/字典/游戏）"}

    prompt = PROMPT.format(
        name=name, etype=etype, description=(description or "")[:200],
        source_title=source_title[:60])
    raw = chat([{"role": "user", "content": prompt}], max_tokens=200)
    v = parse_json(raw) or {}
    verdict = v.get("verdict", "REJECT")
    if verdict not in ("KEEP", "REJECT"):
        verdict = "REJECT"
    return {"verdict": verdict, "reason": v.get("reason", ""), "topic": v.get("topic", "")}


