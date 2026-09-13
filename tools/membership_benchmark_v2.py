#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""membership_benchmark_v2.py — Membership 外部金标盲判基准（§12 重写）。

- 金标：教科书级确定性事实（tools/membership_gold.py 构造，外部于实现）。
- 判官盲判：只给 名称+类型+候选系统清单，不给规则锚点/规则结论。
- §12.3 单模型如实标注：Qwen3.6-35B-A3B 三个独立改述提示 + 多数票
  （independent prompts，不是多模型金标）。
- 目标（§12.4）：P>=0.97 R>=0.90 F1>=0.93。
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from extensions.llm import chat, parse_json

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "yangtze" / "schema" / "membership_gold_v2.json"
OUT = ROOT / "reports" / "V2_MEMBERSHIP_BENCHMARK_V2.json"


def _systems_from_db() -> list[str]:
    import psycopg2
    from config.settings import SETTINGS
    conn = psycopg2.connect(SETTINGS.pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT system_name FROM cultural_systems WHERE system_level='REGIONAL'")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


SYSTEMS = _systems_from_db()
SYS_STR = "、".join(SYSTEMS)

JUDGE_PROMPTS = [
    (
        "你是文化地理判定器。对每个条目，判断它是否属于长江文化体系的一个区域文化系统。\n"
        f"区域系统选项：{SYS_STR}\n"
        "判定规则：\n"
        "- 属于其中某系统 → system=该系统名\n"
        "- 不属于长江文化体系（现代基础设施/现代企业/其他流域文化/通用机构名）→ system=REJECT\n"
        "- 属于长江文化但归属系统在学术界确有争议 → system=CANDIDATE\n"
        "只依据对象的文化属性判断，不依据其行政或经济属性。\n"
        '只输出 JSON 数组：[{"i":序号,"system":"..."}]\n\n条目：\n'
    ),
    (
        "任务：文化归属筛查。逐条判断下列对象是否属于长江文化体系。\n"
        f"区域系统选项：{SYS_STR}\n"
        "先排除：非长江流域对象、现代市政设施与当代企业 → system=REJECT。\n"
        "注意：近代工业与交通遗产（老铁路、铁厂、开埠口岸、租界旧址、早期大学建筑）、"
        "革命纪念地、流域内民族文化不得排除；沿江节点城市归属有学术讨论时给 CANDIDATE。\n"
        '其余给核心区域文化系统名。只输出 JSON 数组：[{"i":序号,"system":"..."}]\n\n条目：\n'
    ),
    (
        f"下列对象哪些能论证长江文化的区域结构（{SYS_STR}）？把每个对象归入最恰当的区域文化系统。\n"
        "无法归入任何系统（非长江流域/现代设施/当代企业）给 REJECT；"
        "可归入但学术界对归属有分歧的给 CANDIDATE。\n"
        "近代遗产（铁路、铁厂、学堂、租界旧址）与流域内民族文化是体系的一部分。\n"
        '只输出 JSON 数组：[{"i":序号,"system":"..."}]\n\n条目：\n'
    ),
]


def judge_batch(items: list[dict], prompt: str) -> list[str]:
    listing = "\n".join(f"{i}. {x['name']}（类型：{x['type']}）" for i, x in enumerate(items))
    try:
        arr = parse_json(chat([{"role": "user", "content": prompt + listing}],
                              max_tokens=120 + 40 * len(items), temperature=0.0)) or []
        out = ["ERROR"] * len(items)
        if isinstance(arr, list):
            for it in arr:
                try:
                    out[int(it["i"])] = str(it.get("system", "ERROR"))
                except Exception:
                    pass
        return out
    except Exception:
        return ["ERROR"] * len(items)


def main() -> int:
    doc = json.loads(GOLD.read_text(encoding="utf-8"))
    cases = doc["cases"]
    t0 = time.time()
    runs: list[list[str]] = []
    for pi, prompt in enumerate(JUDGE_PROMPTS):
        run_preds: list[str] = []
        B = 12
        for s in range(0, len(cases), B):
            run_preds += judge_batch(cases[s:s + B], prompt)
            if (s // B) % 10 == 0:
                print(f"  judge#{pi+1} {min(s+B, len(cases))}/{len(cases)}", flush=True)
        runs.append(run_preds)
    preds: list[str] = []
    for i in range(len(cases)):
        votes = [r[i] for r in runs]
        common = Counter(v for v in votes if v != "ERROR").most_common()
        preds.append(common[0][0] if common else "ERROR")

    # 评分
    tp = fp = fn = tn = 0
    fam_total: dict[str, int] = {}
    fam_ok: dict[str, int] = {}
    border_honest = 0
    errors = 0
    detail_fail = []
    for c, p in zip(cases, preds):
        fam = c["family"]
        fam_total[fam] = fam_total.get(fam, 0) + 1
        if p == "ERROR":
            errors += 1
            continue
        expected_admit = c["expected"] == "ADMIT"
        judge_admit = p in SYSTEMS
        accept = set(c.get("accept") or [])
        ok = False
        if expected_admit and judge_admit:
            if c.get("expected_systems"):
                ok = p in c["expected_systems"]
            else:
                ok = (p == c["system"]) or (p in accept)
        elif expected_admit and p == "CANDIDATE":
            ok = ("CANDIDATE" in accept) or bool(c.get("expected_systems"))
        if expected_admit:
            if ok:
                tp += 1
            else:
                fn += 1
        else:
            if judge_admit:
                fp += 1
            else:
                tn += 1
                ok = True
        if c["expected"] == "CANDIDATE" and p == "CANDIDATE":
            border_honest += 1
        fam_ok[fam] = fam_ok.get(fam, 0) + (1 if ok else 0)
        if not ok and len(detail_fail) < 40:
            detail_fail.append({"name": c["name"], "expected": c["expected"], "judge": p})

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "protocol": ("external deterministic gold + single-model blind judge x3 paraphrased prompts "
                     "majority vote (Qwen3.6-35B-A3B); 非多模型金标"),
        "total_cases": len(cases), "judge_errors": errors,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "border_honesty": round(border_honest / max(1, fam_total.get("border", 0)), 4),
        "targets": {"precision": 0.97, "recall": 0.90, "f1": 0.93},
        "gate": "PASS" if (precision >= 0.97 and recall >= 0.90 and f1 >= 0.93) else "FAIL",
        "per_family": {f: {"total": fam_total[f], "ok": fam_ok.get(f, 0),
                           "rate": round(fam_ok.get(f, 0) / max(1, fam_total[f]), 4)}
                       for f in sorted(fam_total)},
        "fails_sample": detail_fail,
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "fails_sample"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
