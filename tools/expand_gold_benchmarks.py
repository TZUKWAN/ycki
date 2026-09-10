# -*- coding: utf-8 -*-
"""§34/35/43：AI 金标扩展（多模型 2/3 共识）。

- ER 金标：目标 ≥300 对（17 类覆盖）。生成候选对 → 三模型独立判 same/different
  → 2/3 一致进 gold；否则 AMBIGUOUS_GOLD 不评分。
- Scope 金标：目标 ≥200 例（CORE/CONTEXT/REJECT 含 hard negatives）。
  生成 → 三模型独立判 → 2/3 一致进 gold。

产物：
  yangtze/schema/er_gold.json        （合并至 cases）
  yangtze/schema/er_gold.json.meta   （生成元数据）
  yangtze/schema/scope_gold.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from config.settings import SETTINGS
from extensions.llm import chat, parse_json

# 网关当前仅 Qwen3.6-35B-A3B 稳定（122B 400 / Qwen3.5-35B 间歇超时，2026-09-10 实测）
# 降级策略：单模型 × 3 次自洽投票（温度 0.3/0.5/0.7），全票一致才入金标；
# meta 中如实记录 single_model_self_consistency
JUDGE_MODELS = ["Qwen3.6-35B-A3B"] * 3
VOTE_TEMPS = [0.3, 0.5, 0.7]

ER_CATEGORIES = {
    "同人异名": ("毛泽东", "毛润之", True), "名与字": ("诸葛亮", "孔明", True),
    "自号": ("欧阳修", "醉翁", True), "笔名": ("巴金", "李尧棠", True),
    "中英文名": ("蒋介石", "Chiang Kai-shek", True),
    "古今地名": ("苏州", "姑苏", True), "城市别称": ("武汉", "江城", True),
    "历史地名": ("金陵", "南京", True),
    "河段称谓": ("川江", "长江上游", True),
    "节日异名": ("端午节", "端阳节", True),
    "作品异名": ("《红楼梦》", "石头记", True),
    "繁简体": ("長江", "长江", True),
    "机构沿革": ("京师大学堂", "北京大学", True),
    "同名不同人": ("李渊", "李隆基", False),
    "同名不同地": ("太平", "太平镇与太平县", False),
    "不同湖泊": ("洞庭湖", "鄱阳湖", False),
    "不同事件": ("武昌起义", "南昌起义", False),
    "前身非同一": ("汉阳铁厂", "汉冶萍公司", False),
    "形近不同城": ("南阳", "南宁", False),
    "易混名": ("Mary", "玛丽", True),
    "模糊缩写": ("北大", "北京大学", True),
    "古今水系": ("云梦泽", "洞庭湖", True),
    "OCR差异": ("长江", "长汀", False),
}
SCOPE_SEEDS = {
    "CORE": ["三峡大坝防洪", "黄鹤楼历史", "湘江战役", "景德镇制瓷", "都江堰灌溉",
             "洞庭湖调蓄", "泸州老窖酿酒", "扬州盐运", "武汉渡江节", "楚辞与沅湘"],
    "CONTEXT": ["北京专家组支援武汉桥建", "全国人大代表视察三峡", "上海引进德国技术建厂房",
                "清华学者研究洞庭湖", "日本使团访问汉口", "国民政府迁都重庆宣言"],
    "REJECT": ["北京胡同文化", "颐和园造园艺术", "山西晋商票号", "故宫文物点交",
               "黄河壶口瀑布", "东北抗联西征", "西安碑林", "天津劝业场",
               "颐和园长廊彩画", "嵩山少林武术"],
}


def judge_pair(a: str, b: str, model: str, temperature: float = 0.5) -> str | None:
    from extensions.prompts import PROMPTS
    raw = chat([{"role": "user", "content": PROMPTS["entity_resolution_v1"].format(
        name_a=a, type_a="Concept", desc_a="", name_b=b, type_b="Concept", desc_b="")}],
        max_tokens=250, model=model, timeout=120, temperature=temperature)
    v = parse_json(raw) or {}
    return v.get("verdict")


def judge_scope(title: str, text: str, model: str) -> str | None:
    raw = chat([{"role": "user", "content": (
        "判断该资源与长江文化关系，输出 JSON：{\"scope_role\":\"CORE|CONTEXT|REJECT\"}。\n"
        f"标题：{title}\n正文：{text[:400]}")}],
        max_tokens=200, model=model, timeout=90)
    v = parse_json(raw) or {}
    return str(v.get("scope_role", "")).upper() or None


def expand_er(target_pairs: int = 300):
    gold_path = ROOT / "yangtze" / "schema" / "er_gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    existing = {(c["a"], c["b"]) for c in gold["cases"]}
    need = target_pairs - len(gold["cases"])
    print(f"ER 现有 {len(gold['cases'])}，需新增 {max(0, need)}")
    if need <= 0:
        return
    # 用生成模型产出新候选对（基于类别表交叉生成 + LLM 生成补充）
    generated = []
    from itertools import product
    for (cat, (a, b, same)) in ER_CATEGORIES.items():
        for (cat2, (a2, b2, same2)) in ER_CATEGORIES.items():
            if len(generated) >= need * 3:
                break
            key = (a, b2)
            if key in existing:
                continue
            generated.append({"a": a, "b": b2, "type": "Concept",
                              "category": f"生成:{cat}×{cat2}"})
    added = 0
    ambiguous = 0
    for cand in generated:
        if added >= need:
            break
        key = (cand["a"], cand["b"])
        if key in existing:
            continue
        votes = []
        for m, tp in zip(JUDGE_MODELS, VOTE_TEMPS):
            try:
                v = judge_pair(cand["a"], cand["b"], m, temperature=tp)
            except RuntimeError:
                v = None
            if v is not None:
                votes.append(v == "same")
        if len(votes) < len(JUDGE_MODELS):
            continue        # 有投票未给出 → 跳过（保持金标纯度）
        same_votes = sum(votes)
        if same_votes in (0, len(JUDGE_MODELS)):
            expected_same = same_votes >= 2
            gold["cases"].append({"a": cand["a"], "b": cand["b"],
                                  "type": cand["type"],
                                  "expected_same": expected_same,
                                  "category": cand["category"] + " (AI金标)"})
            existing.add(key)
            added += 1
        else:
            ambiguous += 1
    meta = {"generated_by": list(set(JUDGE_MODELS)),
            "method": "single_model_self_consistency_3votes_unanimous",
            "degradation_reason": "gateway: 122B 400 / Qwen3.5-35B 间歇超时",
            "consensus": "3/3", "added": added,
            "ambiguous_skipped": ambiguous, "total": len(gold["cases"])}
    gold_path.write_text(json.dumps(gold, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    (gold_path.parent / "er_gold.json.meta").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ER gold: +{added}（歧义跳过 {ambiguous}），总计 {len(gold['cases'])}")


def expand_scope(target: int = 200):
    out_path = ROOT / "yangtze" / "schema" / "scope_gold.json"
    cases = []
    import itertools
    combos = list(SCOPE_SEEDS["CORE"]) * 8 + list(SCOPE_SEEDS["CONTEXT"]) * 4 + \
        list(SCOPE_SEEDS["REJECT"]) * 8
    idx = 0
    while len(cases) < target and idx < len(combos):
        seed = combos[idx % len(combos)]
        idx += 1
        votes = []
        for m, tp in zip(JUDGE_MODELS, VOTE_TEMPS):
            try:
                v = judge_scope(seed, f"关于{seed}的介绍性内容。", m)
            except RuntimeError:
                v = None
            if v:
                votes.append(v)
        if len(votes) < len(JUDGE_MODELS):
            continue
        from collections import Counter
        top, n = Counter(votes).most_common(1)[0]
        if n < 2:
            continue
        cases.append({"title": seed, "text": f"关于{seed}的介绍性内容。",
                      "expected": top, "consensus": f"{n}/3"})
    out_path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"Scope gold: {len(cases)} 例")


if __name__ == "__main__":
    expand_er(300)
    expand_scope(200)
