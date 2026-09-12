# -*- coding: utf-8 -*-
"""数字人文基准包（DH Benchmark Pack）加载与验证器。

加载并校验两个基准文件（不依赖任何数据库，纯文件校验）：
  yangtze/benchmarks/dh_benchmark_100.yaml   100 道系统性研究问题
  yangtze/benchmarks/golden_ten.yaml         10 个 Golden Ten 展示案例

校验规则（validate_benchmark）：
  - 基准题库恰好 100 题，id 从 DH-001 连续编到 DH-100，无重复；
  - category 恰好为 10 类之一，且每类恰好 10 题；
  - 11 道必备题存在（按 question 文本精确匹配）；
  - target_systems 非空且全部属于稳定 id 集合；
  - required_object_types / evaluation_dimensions / question /
    evidence_requirements / difficulty 齐全且合法；
  - Golden Ten 恰好 10 案例（G1-G10 无重复），每案例必填字段齐全，
    required_components 各键非空且 key_entities 非空。

用法：
  python tools/benchmark_loader.py        # 打印 PASS/FAIL 明细，exit 0/1
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_FILE = ROOT / "yangtze" / "benchmarks" / "dh_benchmark_100.yaml"
GOLDEN_TEN_FILE = ROOT / "yangtze" / "benchmarks" / "golden_ten.yaml"

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("benchmark_loader 需要 PyYAML：请先 pip install pyyaml") from exc

# ---------------------------------------------------------------------------
# 稳定词汇表
# ---------------------------------------------------------------------------

# 区域系统稳定 id（与 yangtze/schema/cultural_systems.yaml 对齐）
ALLOWED_SYSTEMS = {
    "yangtze_culture", "qiang_tibet", "ba_shu", "dian_qian",
    "jing_chu", "hu_xiang", "gan_wan", "wu_yue",
}

# 恰好 10 类研究问题类别
CATEGORIES = [
    "STRUCTURE", "EVOLUTION", "INTERACTION", "FLOW", "HUMAN_ENVIRONMENT",
    "CONTINUITY", "TRANSFORMATION", "CROSS_REGION", "CROSS_PERIOD",
    "INTERPRETATION",
]

DIFFICULTIES = {"EASY", "MEDIUM", "HARD"}

EVALUATION_DIMENSIONS = {
    "structural_correctness", "evidence_grounding", "temporal_coherence",
    "spatial_coherence", "mechanism_explanation", "uncertainty_honesty",
    "citation_completeness",
}

# 11 道必备题（按 question 文本精确匹配）
REQUIRED_QUESTIONS = [
    "长江文化由什么结构构成？",
    "长江水系怎样参与文化生成？",
    "巴蜀文化如何形成并演进？",
    "荆楚文化内部有哪些主要传统？",
    "巴蜀与荆楚在哪些历史过程中发生互动？",
    "湖广填四川带来了什么人口与文化流动？",
    "抗战时期文化教育资源如何向长江上游迁移？",
    "近代武汉工业文化与长江航运之间是什么关系？",
    "端午/龙舟传统如何形成区域变体？",
    "长江史前文明如何呈现多中心结构？",
    "传统水文化与当代生态文明有哪些连续和转型？",
]

# Golden Ten
GOLDEN_IDS = [f"G{i}" for i in range(1, 11)]
GOLDEN_CASE_FIELDS = [
    "title", "anchor_systems", "anchor_hydro", "anchor_phases",
    "required_components", "acceptance",
]
GOLDEN_COMPONENT_KEYS = [
    "traditions", "processes", "flows", "key_entities", "interpretation_questions",
]

QUESTION_FIELDS = [
    "category", "question", "target_systems", "required_object_types",
    "evidence_requirements", "evaluation_dimensions", "difficulty",
]


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def load_benchmark(path: Path | str = BENCHMARK_FILE) -> dict:
    """加载 dh_benchmark_100.yaml 并返回解析后的结构。"""
    with open(path, encoding="utf-8-sig") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是合法的 YAML 映射结构")
    return data


def load_golden_ten(path: Path | str = GOLDEN_TEN_FILE) -> dict:
    """加载 golden_ten.yaml 并返回解析后的结构。"""
    with open(path, encoding="utf-8-sig") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是合法的 YAML 映射结构")
    return data


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _is_nonempty_list(value) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(
        isinstance(v, str) and v.strip() for v in value
    )


def _validate_benchmark_rules(data: dict) -> list[str]:
    """校验 100 题基准题库，返回错误列表（空列表表示通过）。"""
    errors: list[str] = []
    questions = data.get("questions")

    if not isinstance(questions, list) or len(questions) != 100:
        actual = len(questions) if isinstance(questions, list) else "非列表"
        errors.append(f"[count] 题目数量必须恰好为 100，实际为 {actual}")
        return errors

    ids: list[str] = []
    seen_ids: set[str] = set()
    all_questions_text: set[str] = set()

    for idx, q in enumerate(questions, start=1):
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid:
            errors.append(f"[id] 第 {idx} 题缺少 id")
            qid = f"<missing-{idx}>"
        ids.append(str(qid))
        if qid in seen_ids:
            errors.append(f"[id] 重复的题目 id：{qid}")
        seen_ids.add(qid)

        for field in QUESTION_FIELDS:
            if field not in q or q[field] in (None, "", []):
                errors.append(f"[{qid}] 缺少必填字段或字段为空：{field}")

        question_text = q.get("question")
        if isinstance(question_text, str):
            all_questions_text.add(question_text)

        category = q.get("category")
        if category not in CATEGORIES:
            errors.append(f"[{qid}] 非法 category：{category!r}（应为 10 类之一）")

        difficulty = q.get("difficulty")
        if difficulty not in DIFFICULTIES:
            errors.append(f"[{qid}] 非法 difficulty：{difficulty!r}（应为 EASY/MEDIUM/HARD）")

        target_systems = q.get("target_systems")
        if not _is_nonempty_list(target_systems):
            errors.append(f"[{qid}] target_systems 必须是非空字符串列表")
        else:
            bad = [s for s in target_systems if s not in ALLOWED_SYSTEMS]
            if bad:
                errors.append(f"[{qid}] target_systems 含非法 id：{bad}")

        rot = q.get("required_object_types")
        if not _is_nonempty_list(rot):
            errors.append(f"[{qid}] required_object_types 必须是非空字符串列表")

        dims = q.get("evaluation_dimensions")
        if not _is_nonempty_list(dims):
            errors.append(f"[{qid}] evaluation_dimensions 必须是非空字符串列表")
        else:
            bad_dims = [d for d in dims if d not in EVALUATION_DIMENSIONS]
            if bad_dims:
                errors.append(f"[{qid}] evaluation_dimensions 含非法维度：{bad_dims}")

        if not isinstance(q.get("evidence_requirements"), str) or not q.get("evidence_requirements", "").strip():
            errors.append(f"[{qid}] evidence_requirements 必须为非空字符串")

    # id 连续性：DH-001..DH-100
    expected_ids = [f"DH-{i:03d}" for i in range(1, 101)]
    if ids != expected_ids:
        errors.append("[sequence] id 必须从 DH-001 连续编到 DH-100（实际序列不连续或顺序不符）")

    # 类别计数：10 类各恰好 10 题
    counts = Counter(q.get("category") for q in questions)
    for cat in CATEGORIES:
        if counts.get(cat, 0) != 10:
            errors.append(f"[category] 类别 {cat} 应恰好 10 题，实际 {counts.get(cat, 0)} 题")
    extra_cats = set(counts) - set(CATEGORIES)
    if extra_cats:
        errors.append(f"[category] 出现非法类别：{sorted(extra_cats)}")

    # 11 道必备题（question 文本精确匹配）
    missing_required = [rq for rq in REQUIRED_QUESTIONS if rq not in all_questions_text]
    if missing_required:
        for rq in missing_required:
            errors.append(f"[required] 缺少必备题（question 精确匹配失败）：{rq}")

    return errors


def _validate_golden_rules(data: dict) -> list[str]:
    """校验 Golden Ten 案例定义，返回错误列表（空列表表示通过）。"""
    errors: list[str] = []
    cases = data.get("cases")

    if not isinstance(cases, list) or len(cases) != 10:
        actual = len(cases) if isinstance(cases, list) else "非列表"
        errors.append(f"[golden] 案例数量必须恰好为 10，实际为 {actual}")
        return errors

    ids = [c.get("id") for c in cases if isinstance(c, dict)]
    if len(ids) != len(set(ids)):
        errors.append("[golden] 案例 id 存在重复")
    if set(ids) != set(GOLDEN_IDS):
        errors.append(f"[golden] 案例 id 必须为 G1-G10，实际为 {ids}")

    for idx, case in enumerate(cases, start=1):
        cid = case.get("id") if isinstance(case, dict) else f"<case-{idx}>"
        for field in GOLDEN_CASE_FIELDS:
            value = case.get(field)
            if field == "required_components":
                continue  # 单独校验
            if value in (None, "", []):
                errors.append(f"[{cid}] 缺少必填字段或字段为空：{field}")
            elif field in ("anchor_systems", "anchor_hydro", "anchor_phases") and not _is_nonempty_list(value):
                errors.append(f"[{cid}] {field} 必须是非空字符串列表")

        # anchor_systems 属于稳定 id 集合
        anchor_systems = case.get("anchor_systems")
        if _is_nonempty_list(anchor_systems):
            bad = [s for s in anchor_systems if s not in ALLOWED_SYSTEMS]
            if bad:
                errors.append(f"[{cid}] anchor_systems 含非法 id：{bad}")

        comps = case.get("required_components")
        if not isinstance(comps, dict):
            errors.append(f"[{cid}] required_components 必须为映射结构")
            continue
        for key in GOLDEN_COMPONENT_KEYS:
            value = comps.get(key)
            if not _is_nonempty_list(value):
                errors.append(f"[{cid}] required_components.{key} 必须是非空列表")
        if not _is_nonempty_list(comps.get("key_entities")):
            errors.append(f"[{cid}] required_components.key_entities 必须非空")

        acceptance = case.get("acceptance")
        if not isinstance(acceptance, str) or not acceptance.strip():
            errors.append(f"[{cid}] acceptance 必须为非空字符串")

    return errors


def validate_benchmark() -> tuple[bool, list[str]]:
    """校验完整基准包（100 题 + Golden Ten）。

    返回 (ok, errors)：ok 为 True 表示全部通过。
    """
    errors: list[str] = []
    try:
        errors.extend(_validate_benchmark_rules(load_benchmark()))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"[load] 加载 {BENCHMARK_FILE} 失败：{exc}")
    try:
        errors.extend(_validate_golden_rules(load_golden_ten()))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"[load] 加载 {GOLDEN_TEN_FILE} 失败：{exc}")
    return (not errors, errors)


def category_stats(data: dict) -> dict[str, int]:
    """返回类别 -> 题目数 的统计。"""
    counter = Counter(q.get("category") for q in data.get("questions", []))
    return {cat: counter.get(cat, 0) for cat in CATEGORIES}


def difficulty_stats(data: dict) -> dict[str, int]:
    """返回难度 -> 题目数 的统计。"""
    counter = Counter(q.get("difficulty") for q in data.get("questions", []))
    return {d: counter.get(d, 0) for d in ("EASY", "MEDIUM", "HARD")}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ok, errors = validate_benchmark()

    try:
        bench = load_benchmark()
        gold = load_golden_ten()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL 加载基准包失败：{exc}")
        return 1

    print("=" * 62)
    print("数字人文基准包校验（dh_benchmark_100.yaml + golden_ten.yaml）")
    print("=" * 62)
    print(f"题库文件：{BENCHMARK_FILE}")
    print(f"案例文件：{GOLDEN_TEN_FILE}")
    print(f"题目总数：{len(bench.get('questions', []))} / 100")
    print(f"案例总数：{len(gold.get('cases', []))} / 10")
    print("-" * 62)
    print("分类统计（每类应为 10）：")
    for cat, n in category_stats(bench).items():
        mark = "OK " if n == 10 else "BAD"
        print(f"  [{mark}] {cat:<18} {n}")
    print("难度分布：")
    for diff, n in difficulty_stats(bench).items():
        print(f"  {diff:<8} {n}")
    print("-" * 62)

    if ok:
        print("PASS：基准包全部校验通过（100 题 + 10 案例结构完整）")
        return 0
    print(f"FAIL：共 {len(errors)} 项校验错误：")
    for err in errors:
        print(f"  - {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
