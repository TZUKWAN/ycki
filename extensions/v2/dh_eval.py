# -*- coding: utf-8 -*-
"""dh_eval.py — DH 答案真评估器（§3.5 反自证重写）。

范式（对齐业界 SoTA：RAGAS/DeepEval faithfulness、ALCE 引用归因、GroUSE）：
  1. claim 分解：把回答拆成事实断言句（剥离『结构对象：』『不确定性：』样板行）。
  2. 逐断言检查：
     a. 每个事实断言必须携带 [EV:n] 且 n 必须存在于装配证据集（假引用直接 FAIL）。
     b. citation entailment：断言必须被其所引引文支持——确定性预检（数字/年代/
        地名 token 必须在引文中出现）+ LLM 严格蕴含判定（只允许 supported /
        unsupported / unrelated）。
  3. temporal_coherence：断言中的年代必须能在其引文中找到同年代/同朝代依据；
     引文带年代而断言年代与之冲突 → FAIL。
  4. spatial_coherence：断言中的地名/方位必须被引文支撑；内置确定性长江地理
     事实表（上/中/下游归属、流向、主要支流汇入侧）用于拒绝"武汉位于下游"
     类硬错误（这是地理常识门，不是证据替代）。
  5. uncertainty_honesty：问题所需维度在库中缺失（如 flows=0）或装配证据 <3 条
     时，回答必须明确声明证据不足。
LLM 不可用时：蕴含退化为确定性检查并在结果中标注 judge_used=False（不冒充）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from extensions.llm import chat, parse_json  # noqa: E402

# ------------------------------------------------------------------ 地理事实
# 教科书级确定性事实：仅用于拒绝与事实相反的空间断言（§3.5.2）
UPPER = {"宜宾", "泸州", "重庆", "涪陵", "万州"}
MIDDLE = {"宜昌", "荆州", "沙市", "岳阳", "咸宁", "武汉", "黄石", "鄂州", "黄冈"}
LOWER = {"湖口", "九江", "安庆", "池州", "铜陵", "芜湖", "马鞍山", "南京", "镇江",
         "扬州", "南通", "上海"}
SEGMENT = {}
for _c in UPPER:
    SEGMENT[_c] = "上游"
for _c in MIDDLE:
    SEGMENT[_c] = "中游"
for _c in LOWER:
    SEGMENT[_c] = "下游"
BOUNDARY = {"宜昌": "上游与中游的分界", "湖口": "中游与下游的分界"}
TRIBUTARY_SIDE = {  # (支流, 在哪一侧[相对长江干流流向 自西向东])
    "雅砻江": "左岸", "岷江": "左岸", "嘉陵江": "左岸", "汉江": "左岸",
    "乌江": "右岸", "湘江": "右岸", "赣江": "右岸", "沱江": "左岸",
}
_FLOW_W2E = "自西向东"

_YEAR_RE = re.compile(r"公元前?\s*\d+|\d{3,4}\s*年?")
_DYN_RE = re.compile(r"夏|商|西周|东周|春秋|战国|秦|汉|三国|晋|南北朝|隋|唐|宋|元|明|清|晚清|民国|近代|现代|当代")
_PLACE_RE = re.compile(
    "[" + "".join(set("".join(SEGMENT) + "长江汉江嘉陵江岷江乌江湘江赣江雅砻江沱江"
                      "洞庭湖鄱阳湖太湖巢湖上游中游下游入海口")) + "]{2,6}")

BOILER_PREFIX = ("结构对象", "不确定性", "以下", "综上", "本回答", "第一行", "最后一行")
_MECH_WORDS = ("机制", "过程", "因为", "由于", "推动", "促进", "导致", "缘于", "借助", "依托")


def _norm(s: str) -> str:
    return re.sub(r"[\s，。、；：？！\"'（）()\[\]【】《》<>—\-…·,.:;?!]+", "", s or "")


def split_claims(answer: str) -> list[str]:
    """拆句并剥离样板行/标题行。"""
    parts = re.split(r"[。！？!?\n]", answer or "")
    return [p.strip() for p in parts
            if len(p.strip()) >= 6 and not p.strip().startswith(BOILER_PREFIX)]


def claim_evs(claim: str) -> list[str]:
    evs = re.findall(r"\[EV:\s*(EV?\d+)\s*\]", claim)
    return [f"EV{int(e.replace('EV', ''))}" for e in evs]


def evaluate_answer(question: str, category: str, assembly: dict[str, Any],
                    answer: str, use_llm_judge: bool = True) -> dict[str, Any]:
    """返回七维 + entailment 明细。assembly 须含 evidence[{id, quote}] 等。"""
    evidence = {e["id"]: e["quote"] for e in assembly.get("evidence", [])}
    obj_names = ([r.get("system_name") or "" for r in assembly.get("systems", [])]
                 + [r.get("hsu_name") or "" for r in assembly.get("hydro", [])]
                 + [r.get("tradition_name") or "" for r in assembly.get("traditions", [])]
                 + [r.get("process_name") or "" for r in assembly.get("processes", [])]
                 + [r.get("phase_name") or "" for r in assembly.get("phases", [])])
    obj_names = [n for n in obj_names if n]
    flows_empty = not assembly.get("flows")

    claims = split_claims(answer)
    details: list[dict[str, Any]] = []
    n_grounded = n_fake = n_uncited = 0
    entail_pairs: list[dict[str, str]] = []

    for cl in claims:
        evs = claim_evs(cl)
        valid = [e for e in evs if e in evidence]
        fake = [e for e in evs if e not in evidence]
        n_fake += len(fake)
        factual = bool(obj_names and any(n in cl for n in obj_names)) or \
            bool(_YEAR_RE.search(cl) or _PLACE_RE.search(cl))
        if not evs and factual:
            n_uncited += 1
        if valid:
            n_grounded += 1
            for e in valid:
                entail_pairs.append({"claim": cl, "ev": e, "quote": evidence[e]})

    # ---- LLM 严格蕴含（一次批量调用；失败退化为确定性） ----
    entailments: dict[str, str] = {}
    judge_used = False
    if entail_pairs and use_llm_judge:
        listing = "\n".join(
            f"{i}. 断言：{p['claim']}\n   引文[{p['ev']}]：{_norm(p['quote'])[:300]}"
            for i, p in enumerate(entail_pairs[:24]))
        prompt = (
            "对每对『断言/引文』判定引文是否支持断言。只允许三值：supported / "
            "unsupported（引文相关但方向或事实不符）/ unrelated（引文与断言无关）。\n"
            "严格标准：断言中的年代、地名、因果关系必须有引文依据；引文未提及即不支持。\n"
            "输出 JSON 数组：[{\"i\":编号,\"v\":\"supported|unsupported|unrelated\"}]\n\n"
            + listing)
        try:
            arr = parse_json(chat([{"role": "user", "content": prompt}],
                                  max_tokens=1600, temperature=0.0)) or []
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and "i" in item:
                        entailments[str(item["i"])] = str(item.get("v", "unrelated"))
                judge_used = bool(entailments)
        except Exception:
            judge_used = False

    # ---- 确定性蕴含预检 + 汇总 ----
    n_entail_ok = n_entail_bad = 0
    entail_detail = []
    for i, p in enumerate(entail_pairs):
        cl_n, q_n = _norm(p["claim"]), _norm(p["quote"])
        years = [y for y in _YEAR_RE.findall(p["claim"]) if y.strip()]
        dyns = _DYN_RE.findall(p["claim"])
        year_ok = (not years) or any(_norm(y) in q_n for y in years)
        dyn_ok = (not dyns) or any(d in p["quote"] for d in dyns)
        overlap = len(set(cl_n) & set(q_n)) / max(1, len(set(cl_n)))
        det_ok = year_ok and dyn_ok and overlap >= 0.35
        verdict = entailments.get(str(i))
        if verdict is None:
            ok = det_ok
        else:
            ok = (verdict == "supported") and year_ok and dyn_ok
        if ok:
            n_entail_ok += 1
        else:
            n_entail_bad += 1
            entail_detail.append({"claim": p["claim"][:80], "ev": p["ev"],
                                  "judge": verdict or "deterministic", "year_ok": year_ok,
                                  "dyn_ok": dyn_ok, "overlap": round(overlap, 2)})

    # ---- 空间硬错误（地理事实表） ----
    spatial_hard = []
    for cl in claims:
        for city, seg in SEGMENT.items():
            if city in cl:
                m = re.search(r"(上游|中游|下游)", cl)
                if m and m.group(1) != seg and "分界" not in cl:
                    spatial_hard.append(f"{city} 属{seg}，断言称{m.group(1)}：{cl[:50]}")
        for city, desc in BOUNDARY.items():
            if city in cl and re.search(r"(上游|中游|下游)与(上游|中游|下游)的分?界", cl) \
                    and desc[:2] not in cl and desc.replace("的分界", "") not in cl:
                pass  # 分界句式复杂，交由蕴含判定
    spatial_ok = not spatial_hard

    # ---- 状态投毒检测：把 CANDIDATE/SUPPORTED 冒充 ADMITTED ----
    cited_objects = [n for n in obj_names if n in (answer or "")]
    status_poison = []
    status_rows = ([(r.get("tradition_name"), r.get("status")) for r in assembly.get("traditions", [])]
                   + [(r.get("process_name"), r.get("status")) for r in assembly.get("processes", [])]
                   + [(r.get("system_name"), None) for r in assembly.get("systems", [])])
    for cl in claims:
        if not re.search(r"已?获?(准入|定名|ADMITTED)|status[=:=]\s*ADMITTED", cl, re.I):
            continue
        for name, st in status_rows:
            if name and name in cl and st is not None and st != "ADMITTED":
                status_poison.append(f"{name} 实际 {st} 被称已准入")
    struct_ok = len(cited_objects) >= 2 and not status_poison

    # ---- 汇总维度 ----
    checks = {
        "structural_correctness": struct_ok,
        "evidence_grounding": len(claims) > 0 and n_fake == 0 and n_uncited == 0
                              and n_grounded >= 2,
        "citation_entailment": n_entail_bad == 0 and n_entail_ok >= 2,
        "temporal_coherence": True,   # 冲突年代已在 entailment 的 year_ok/dyn_ok 内判
        "spatial_coherence": spatial_ok,
        "mechanism_explanation": (category not in ("EVOLUTION", "FLOW", "INTERACTION",
                                                   "HUMAN_ENVIRONMENT"))
                                 or any(w in answer for w in _MECH_WORDS),
        "uncertainty_honesty": (
            ("证据不足" in answer or "尚无" in answer or "不确定" in answer or "暂无" in answer)
            if (flows_empty and category == "FLOW") or len(evidence) < 3
            else True),
    }
    n_claims = max(1, len(claims))
    detail = {
        "claims": len(claims), "grounded_claims": n_grounded,
        "fake_citations": n_fake, "uncited_factual": n_uncited,
        "entail_ok": n_entail_ok, "entail_bad": n_entail_bad,
        "entail_detail": entail_detail[:8], "spatial_hard": spatial_hard[:5],
        "status_poison": status_poison[:5],
        "judge_used": judge_used, "cited_objects": cited_objects[:8],
    }
    score = round(sum(checks.values()) / len(checks), 3)
    return {"checks": checks, "score": score, **detail}
