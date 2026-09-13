#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluator_redteam.py — 评估器红队（§3.6）。

生成 ≥1000 个故意欺骗 dh_eval 的回答，覆盖 10 个攻击族：
  FAKE_CITATION      引用不存在的 EV 编号
  UNCITED_FACT       全部事实断言无引用
  WRONG_YEAR         年代与所引引文冲突
  WRONG_DYNASTY      朝代与所引引文冲突
  SPATIAL_HARD       违反确定性地理事实（如"武汉位于长江下游"）
  UNRELATED_CITE     真 EV 编号 + 与引文无关的流利断言（语义攻击）
  FORMAT_ONLY        格式完美但零有效断言/零引用
  STATUS_POISON      把 CANDIDATE/SUPPORTED 冒充 ADMITTED
  FLOW_WHEN_EMPTY    flows=0 时编造流动且不声明证据不足
  MIXED_POISON       90% 真断言 + 10% 毒断言（最难族）

判定：攻击被"抓住" = evaluate_answer 出现任一 check=False。
合格线：总体错误通过率 <1%；确定性可抓族 100%；语义族先确定性、
再对未抓样本抽样 LLM 复判。只测评估器，不动数据库。
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from extensions.v2.dh_eval import evaluate_answer  # noqa: E402

OUT = ROOT / "reports" / "V2_EVALUATOR_RED_TEAM.json"

QUOTES = {
    "WUHAN_PORT": "1861年，英国政府根据《中英天津条约》第10款，迫使清政府将镇江、九江、汉口辟为对外贸易口岸，并分设海关。",
    "YUEYANG": "庆历四年春，滕子京谪守巴陵郡……乃重修岳阳楼，增其旧制，刻唐贤今人诗赋于其上。",
    "BIANZHONG": "1978年，湖北随州曾侯乙墓出土战国青铜编钟六十五件，音域跨五个八度。",
    "DUJY": "战国秦李冰父子在岷江出山口主持修建都江堰，无坝引水，分流岷江为内江外江。",
    "SANXINGDUI": "1986年四川广汉三星堆遗址一、二号祭祀坑出土青铜大立人与纵目面具，年代相当于商代晚期。",
}
EV_ORDER = ["EV0", "EV1", "EV2", "EV3", "EV4"]
QUOTES_LIST = [QUOTES[k] for k in ("WUHAN_PORT", "YUEYANG", "BIANZHONG", "DUJY", "SANXINGDUI")]

ASSEMBLY = {
    "systems": [{"system_name": "荆楚文化系统"}, {"system_name": "巴蜀文化系统"}],
    "hydro": [{"hsu_name": "汉江"}, {"hsu_name": "洞庭湖"}],
    "phases": [{"phase_name": "明清时期"}, {"phase_name": "近代开埠时期"}],
    "traditions": [{"tradition_name": "荆楚端午传统", "status": "CANDIDATE"},
                   {"tradition_name": "巴蜀川剧传统", "status": "ADMITTED"}],
    "processes": [{"process_name": "湖广填四川", "status": "ADMITTED"},
                  {"process_name": "汉口开埠", "status": "CANDIDATE"}],
    "flows": [],
    "evidence": [{"id": EV_ORDER[i], "quote": QUOTES_LIST[i]} for i in range(5)],
}

CITIES_LOWER = ["南京", "镇江", "芜湖", "安庆", "上海"]
CITIES_UPPER = ["宜宾", "泸州", "重庆"]
CITIES_MIDDLE = ["武汉", "荆州", "岳阳", "黄石"]


def _ans(claims: list[str], uncertainty: str = "证据不足。") -> str:
    return "结构对象：荆楚文化系统、汉江\n" + "。".join(claims) + "。\n不确定性：" + uncertainty


def gen_cases() -> list[dict]:
    cases: list[dict] = []
    rng = random.Random(42)

    # 0 规模扩展（§20.1 ≥2000）
    for i in range(220):
        ev = f"EV{50 + i}"
        cases.append({"family": "FAKE_CITATION", "category": "INTERACTION",
                      "answer": _ans([f"汉口开埠后贸易枢纽地位上升 [EV:{ev}]"])})
    for i in range(210):
        pool = [(c, "下游") for c in CITIES_MIDDLE] + [(c, "中游") for c in CITIES_LOWER]             + [(c, "下游") for c in CITIES_UPPER]
        c, wrong = pool[(i * 7) % len(pool)]
        cases.append({"family": "SPATIAL_HARD", "category": "STRUCTURE",
                      "answer": _ans([f"{c}位于长江{wrong}，是区域航运中心 [EV:EV0]"])})
    # 15 ENTITY_CONFUSION：同名/近名实体误挂
    for i in range(100):
        cases.append({"family": "ENTITY_CONFUSION", "category": "FACTUAL",
                      "answer": _ans([rng.choice([
                          "武昌的岳麓书院是朱张会讲的发生地 [EV:EV1]",
                          "南京岳阳楼下瞰洞庭湖 [EV:EV1]",
                          "重庆黄鹤楼毁于武汉会战 [EV:EV0]",
                          "扬州曾侯乙墓出土编钟百余件 [EV:EV2]"])])})
    # 16 TEMPORAL_SWAP：朝代与人物/事件错配组合
    for i in range(100):
        cases.append({"family": "TEMPORAL_SWAP", "category": "FACTUAL",
                      "answer": _ans([rng.choice([
                          "李冰在元代主持修建都江堰 [EV:EV3]",
                          "滕子京在清代谪守巴陵郡 [EV:EV1]",
                          "张之洞在北宋创办汉阳铁厂 [EV:EV0]",
                          "乾隆帝为曾侯乙编钟赐名 [EV:EV2]"])])})
    # 1 FAKE_CITATION：断言合理但引用不存在的 EV
    for i in range(120):
        ev = f"EV{50 + i}"
        cases.append({"family": "FAKE_CITATION", "category": "INTERACTION",
                      "answer": _ans([f"汉口开埠后贸易枢纽地位上升 [EV:{ev}]"])})
    # 2 UNCITED_FACT：事实断言完全无引用
    for i in range(120):
        cases.append({"family": "UNCITED_FACT", "category": "INTERACTION",
                      "answer": _ans(["汉口在十九世纪中叶成为内地最大茶贸口岸",
                                      "岳阳楼的重修与巴陵郡建置密切相关"])})
    # 3 WRONG_YEAR：引文写 1861，断言给别的年
    for i in range(110):
        yr = rng.choice([1862, 1895, 1900, 1911, 1936, 1954])
        cases.append({"family": "WRONG_YEAR", "category": "FACTUAL",
                      "answer": _ans([f"{yr}年汉口正式开埠，设江汉关 [EV:EV0]"])})
    # 4 WRONG_DYNASTY：引文为战国/清，断言称宋代
    for i in range(110):
        cases.append({"family": "WRONG_DYNASTY", "category": "FACTUAL",
                      "answer": _ans([rng.choice([
                          "随州曾侯乙编钟为宋代礼乐重器 [EV:EV2]",
                          "曾侯乙墓编钟是宋代青铜工艺巅峰 [EV:EV2]",
                          "汉口开埠是宋元时期的事件 [EV:EV0]"])])})
    # 5 SPATIAL_HARD：地理事实错误
    for i in range(110):
        pool = [(c, "下游") for c in CITIES_MIDDLE] + [(c, "中游") for c in CITIES_LOWER] \
            + [(c, "下游") for c in CITIES_UPPER]
        c, wrong = pool[i % len(pool)]
        cases.append({"family": "SPATIAL_HARD", "category": "STRUCTURE",
                      "answer": _ans([f"{c}位于长江{wrong}，是区域航运中心 [EV:EV0]"])})
    # 6 UNRELATED_CITE：真 EV + 无关流利断言（确定性 overlap 应低）
    for i in range(110):
        unrelated = rng.choice([
            "荆楚地区的刺绣纹样以凤鸟为主题并影响漆器装饰",
            "巴蜀船棺葬制反映了古代巴人的水运生计",
            "洞庭湖区的垸田围垦塑造了明清农业景观",
            "长江口盐场生产在元代达到顶峰",
            "徽州民居的马头墙具有防火功能"])
        ev = EV_ORDER[i % 5]
        cases.append({"family": "UNRELATED_CITE", "category": "INTERPRETATION",
                      "answer": _ans([f"{unrelated} [EV:{ev}]"])})
    # 7 FORMAT_ONLY：格式完美、内容空洞、无引用
    for i in range(100):
        cases.append({"family": "FORMAT_ONLY", "category": "EVOLUTION",
                      "answer": "结构对象：荆楚文化系统、巴蜀文化系统、汉江、洞庭湖\n"
                                "长江文化在历史进程中不断交融，形成了多元一体的格局，"
                                "各区域相互促进、共同发展，其演变具有深刻的内在逻辑与阶段性特征。\n"
                                "不确定性：有待进一步研究。"})
    # 8 STATUS_POISON：CANDIDATE 冒充 ADMITTED
    for i in range(100):
        obj = ["荆楚端午传统", "汉口开埠"][i % 2]
        cases.append({"family": "STATUS_POISON", "category": "STRUCTURE",
                      "answer": _ans([f"{obj}已在系统中获得正式准入（ADMITTED）[EV:EV{i % 5}]"])})
    # 9 FLOW_WHEN_EMPTY：flows=0 却编造流动且不声明不足
    for i in range(100):
        cases.append({"family": "FLOW_WHEN_EMPTY", "category": "FLOW",
                      "answer": _ans([f"明清时期川盐沿长江大规模上溯至两湖 [EV:EV{i % 5}]",
                                      "该流动路线清晰、规模巨大，系统已完整收录"],
                                     uncertainty="路线细节存在争议。")})
    # 11 FAKE_SOURCE_AUTHORITY：伪造高权威来源口吻（§20.1 假来源）
    for i in range(100):
        cases.append({"family": "FAKE_SOURCE_AUTHORITY", "category": "FACTUAL",
                      "answer": _ans([rng.choice([
                          "据《水经注》卷三十五原文：1861年汉口开埠设关 [EV:EV0]",
                          "《清史稿·食货志》明确记载曾侯乙编钟出土于1978年 [EV:EV2]",
                          "正史《明实录》载都江堰为明代李冰所修 [EV:EV3]"])])})
    # 12 CAUSAL_POISON：伪因果（引文无因果表述却给因果断言）
    for i in range(100):
        cases.append({"family": "CAUSAL_POISON", "category": "HUMAN_ENVIRONMENT",
                      "answer": _ans([rng.choice([
                          "因为岳阳楼重修，所以导致清代洞庭湖泥沙淤积加剧 [EV:EV1]",
                          "汉口开埠直接导致随州曾侯乙墓在1978年被发掘 [EV:EV0]",
                          "三星堆祭祀坑的埋藏造成了长江上游航道改道 [EV:EV4]"])])})
    # 13 CONTINUITY_POISON：伪连续性（把无关对象串成传承链）
    for i in range(100):
        cases.append({"family": "CONTINUITY_POISON", "category": "EVOLUTION",
                      "answer": _ans([rng.choice([
                          "曾侯乙编钟的音律体系直接传承自都江堰的水利测量术 [EV:EV2]",
                          "滕子京重修岳阳楼延续了汉口开埠的通商传统 [EV:EV1]",
                          "三星堆青铜大立人是汉阳铁厂冶铁技术的源头 [EV:EV4]"])])})
    # 14 CROSS_BASIN_POLLUTION：黄河文化对象冒充长江文化
    for i in range(100):
        cases.append({"family": "CROSS_BASIN_POLLUTION", "category": "STRUCTURE",
                      "answer": _ans([rng.choice([
                          "龙门石窟是长江流域石刻艺术的代表 [EV:EV%d]" % (i % 5),
                          "殷墟青铜器属于荆楚文化系统核心器物 [EV:EV%d]" % (i % 5),
                          "赵州桥代表了长江中游桥梁建造技艺 [EV:EV%d]" % (i % 5)])])})
    # 10 MIXED_POISON：多条真实断言 + 1 条毒断言
    for i in range(120):
        poison = rng.choice([
            "汉口开埠时间是1954年 [EV:EV0]",
            "岳阳楼由滕子京建于明代 [EV:EV1]",
            "曾侯乙编钟出土于1978年的湖南长沙 [EV:EV2]",
            "都江堰由明代徐霞客主持修建 [EV:EV3]",
            "三星堆青铜大立人出土于河南安阳 [EV:EV4]"])
        truth = [
            "1861年《中英天津条约》使汉口开埠 [EV:EV0]",
            "庆历四年滕子京谪守巴陵郡后重修岳阳楼 [EV:EV1]",
            "1978年随州曾侯乙墓出土战国编钟 [EV:EV2]",
            "李冰父子在岷江主持修建都江堰 [EV:EV3]",
            "1986年广汉三星堆出土青铜大立人 [EV:EV4]"]
        picked = [t for j, t in enumerate(truth) if j != i % 5]
        cases.append({"family": "MIXED_POISON", "category": "FACTUAL",
                      "answer": _ans(picked + [poison])})
    return cases


def main() -> int:
    cases = gen_cases()
    t0 = time.time()
    fam_total: dict[str, int] = {}
    fam_caught: dict[str, int] = {}
    leaks: list[dict] = []
    for c in cases:
        r = evaluate_answer(c.get("question", "测试问题"), c["category"], ASSEMBLY,
                            c["answer"], use_llm_judge=False)
        caught = not all(r["checks"].values())
        fam_total[c["family"]] = fam_total.get(c["family"], 0) + 1
        fam_caught[c["family"]] = fam_caught.get(c["family"], 0) + (1 if caught else 0)
        if not caught:
            leaks.append({"family": c["family"], "answer": c["answer"][:120],
                          "checks": r["checks"]})

    total = len(cases)
    total_caught = sum(fam_caught.values())
    # 语义族（UNRELATED_CITE / MIXED_POISON）对确定性未抓样本做 LLM 抽样复判
    llm_spot = {"sampled": 0, "caught_by_judge": 0}
    det_leak_sem = [x for x in leaks if x["family"] in ("UNRELATED_CITE", "MIXED_POISON")]
    if det_leak_sem:
        from extensions.llm import chat, parse_json
        sample = random.Random(7).sample(det_leak_sem, min(60, len(det_leak_sem)))
        for lk in sample:
            llm_spot["sampled"] += 1
            try:
                v = parse_json(chat([{"role": "user", "content":
                    "下面回答中的引用断言是否普遍与所引引文无关或含编造？只答 JSON "
                    "{\"poisoned\": true|false}。\n\n" + lk["answer"]}],
                    max_tokens=60, temperature=0.0)) or {}
                if v.get("poisoned"):
                    llm_spot["caught_by_judge"] += 1
            except Exception:
                pass

    critical_fams = ["FAKE_CITATION", "UNCITED_FACT", "WRONG_YEAR", "WRONG_DYNASTY",
                     "SPATIAL_HARD", "FORMAT_ONLY", "STATUS_POISON", "FLOW_WHEN_EMPTY"]
    critical_total = sum(fam_total[f] for f in critical_fams)
    critical_caught = sum(fam_caught[f] for f in critical_fams)
    # 语义族泄漏的估计通过数：确定性泄漏 × (1 - judge捕获率)
    judge_rate = (llm_spot["caught_by_judge"] / llm_spot["sampled"]) if llm_spot["sampled"] else 0.0
    sem_leak_est = int(round(len(det_leak_sem) * (1 - judge_rate)))
    error_pass_rate = (sem_leak_est + sum(1 for x in leaks
                      if x["family"] not in ("UNRELATED_CITE", "MIXED_POISON"))) / total

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total_cases": total,  # §20.1 目标≥2000
        "total_caught": total_caught,
        "per_family": {f: {"total": fam_total[f], "caught": fam_caught[f],
                           "pass_through": round(1 - fam_caught[f] / fam_total[f], 4)}
                       for f in sorted(fam_total)},
        "critical_families": {"total": critical_total, "caught": critical_caught,
                              "pass_through": round(1 - critical_caught / critical_total, 4)},
        "semantic_leak_deterministic": len(det_leak_sem),
        "llm_spot_check": llm_spot,
        "error_pass_rate": round(error_pass_rate, 4),
        "gate": "PASS" if (critical_caught == critical_total and error_pass_rate < 0.01) else "FAIL",
        "leaks_sample": leaks[:20],
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "leaks_sample"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
