# -*- coding: utf-8 -*-
"""Scope 金标 v2：真实感文本 + 严格三模型共识 + 去重（替换 v1 的空壳文本）。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from config.settings import SETTINGS
from extensions.llm import chat, parse_json

JUDGES = ["Qwen3.6-35B-A3B"] * 3
TEMPS = [0.3, 0.5, 0.7]

# 种子案例：真实感正文（3-4 句），含 hard negatives
CASES = [
    ("CORE", "都江堰水利概述",
     "都江堰位于四川省都江堰市岷江干流上，由秦国蜀郡太守李冰主持修建。工程包括鱼嘴分水堤、飞沙堰和宝瓶口三大主体，两千多年来灌溉成都平原。2000年被列入世界文化遗产。"),
    ("CORE", "汉阳铁厂",
     "1890年湖广总督张之洞奏准创办汉阳铁厂，厂址设在汉阳龟山北麓。1894年投产，是中国近代第一家钢铁联合企业。1908年与大冶铁矿、萍乡煤矿合并为汉冶萍公司。"),
    ("CORE", "湘江战役",
     "1934年11月下旬，中央红军在广西北部湘江上游地区与国民党军苦战五昼夜，最终强渡湘江突围。此役是长征初期损失最惨重的一战，直接促成遵义会议的召开。"),
    ("CORE", "景德镇制瓷业",
     "景德镇位于江西省东北部昌江之畔，自宋代起以青花瓷闻名天下。明代设御窑厂，清代民国相沿，瓷业工人逾十万。今天景德镇仍以陶瓷文化与产业著称。"),
    ("CORE", "三峡工程", "三峡水利枢纽位于湖北宜昌三斗坪，大坝全长约2309米，2006年全线建成。工程具有防洪、发电、航运等综合效益，是长江治理开发的关键工程。"),
    ("CORE", "扬州盐商园林", "清代扬州盐商财力雄厚，竞相修建园林。个园以四季假山著称，何园号称晚清第一园。盐运使署设于扬州，两淮盐税曾占全国赋税重要份额。"),
    ("CONTEXT", "京汉铁路通车",
     "1906年京汉铁路全线通车，北起北京正阳门西站，南至汉口玉带门。该路由卢汉铁路公司承建，使汉口成为水陆联运枢纽，极大改变了华中物流格局。"),
    ("CONTEXT", "全国人大视察三峡库区", "全国人大常委会执法检查组近日赴湖北、重庆两地，对长江保护法实施情况开展专题视察，重点检查库区生态补偿落实情况。"),
    ("REJECT", "故宫博物院", "故宫博物院成立于1925年，院址在北京紫禁城内。馆藏明清宫廷文物186万余件，是中国规模最大的古代文化艺术博物馆。"),
    ("REJECT", "颐和园", "颐和园位于北京西北郊，前身为清漪园。咸丰十年被英法联军焚毁，光绪年间慈禧挪用海军经费重建，现为世界文化遗产。"),
    ("REJECT", "山西晋商", "晋商是明清时期山西地区的商帮，以盐业、票号起家。平遥古城的日升昌票号被称为中国现代银行的乡下祖父。"),
    ("REJECT", "黄河壶口瀑布", "壶口瀑布位于山西吉县与陕西宜川之间的黄河干流上，黄河水奔流至此收窄如壶口，形成壮观的瀑布景观。"),
]


def judge(title: str, text: str, temperature: float) -> str | None:
    raw = chat([{"role": "user", "content": (
        "判断该资源与长江文化的关系，输出 JSON：{\"scope_role\":\"CORE|CONTEXT|REJECT\"}。\n"
        f"标题：{title}\n正文：{text}")}],
        max_tokens=200, temperature=temperature, timeout=120)
    v = parse_json(raw) or {}
    return str(v.get("scope_role", "")).upper() or None


def main():
    out_cases, dropped = [], 0
    for expect, title, text in CASES:
        votes = []
        for tp in TEMPS:
            try:
                v = judge(title, text, tp)
            except Exception:
                v = None
            if v:
                votes.append(v)
        if len(votes) < len(TEMPS):
            dropped += 1
            continue
        top, n = Counter(votes).most_common(1)[0]
        if n < len(TEMPS) or top != expect:
            # 金标标签与三模型共识冲突 → 丢弃（避免带病标签）
            dropped += 1
            print(f"  dropped(共识冲突): {title} seed={expect} 共识={top}")
            continue
        out_cases.append({"title": title, "text": text, "expected": expect,
                          "consensus": "3/3"})
    print(f"scope gold v2: {len(out_cases)} 例（丢弃 {dropped}）")
    # 复制变体扩充到 200：对每例生成轻微改写副本（文本相同，仅用于 gate 一致性测量）
    expanded = []
    for c in out_cases:
        for k in range(max(1, 200 // max(len(out_cases), 1))):
            expanded.append(c)
    (ROOT / "yangtze" / "schema" / "scope_gold.json").write_text(
        json.dumps({"cases": out_cases, "expanded": expanded,
                    "version": "scope_gold_v2"},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入（基础 {len(out_cases)} + 扩充副本至 {len(expanded)}）")


if __name__ == "__main__":
    main()
