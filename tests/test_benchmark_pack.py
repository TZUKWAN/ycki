# -*- coding: utf-8 -*-
"""数字人文基准包测试：100 题结构校验、11 道必备题、Golden Ten 案例完整性。"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import benchmark_loader as bl  # noqa: E402


def test_validate_benchmark_fully_passes():
    """validate_benchmark() 必须全部通过（100 题规则 + Golden Ten 规则）。"""
    ok, errors = bl.validate_benchmark()
    assert ok, "基准包校验失败：\n" + "\n".join(f"  - {e}" for e in errors)


def test_benchmark_structure_counts():
    data = bl.load_benchmark()
    questions = data["questions"]
    assert len(questions) == 100
    ids = [q["id"] for q in questions]
    assert ids == [f"DH-{i:03d}" for i in range(1, 101)], "id 必须从 DH-001 连续编到 DH-100"
    assert len(set(ids)) == 100, "id 不得重复"
    stats = bl.category_stats(data)
    assert all(n == 10 for n in stats.values()), f"10 类每类必须恰好 10 题：{stats}"


def test_eleven_required_questions_present():
    """11 道必备题按 question 文本精确匹配逐一存在。"""
    questions = {q["question"] for q in bl.load_benchmark()["questions"]}
    for required in bl.REQUIRED_QUESTIONS:
        assert required in questions, f"缺少必备题：{required}"


def test_target_systems_use_stable_ids():
    allowed = bl.ALLOWED_SYSTEMS
    for q in bl.load_benchmark()["questions"]:
        assert q["target_systems"], f"{q['id']} 的 target_systems 为空"
        for sid in q["target_systems"]:
            assert sid in allowed, f"{q['id']} 使用了非法系统 id：{sid}"


def test_golden_ten_cases_g1_to_g10_unique_and_complete():
    """Golden Ten 恰好 10 案例，id G1-G10 无重复，必填字段齐全且 key_entities 非空。"""
    data = bl.load_golden_ten()
    cases = data["cases"]
    assert len(cases) == 10
    ids = [c["id"] for c in cases]
    assert set(ids) == set(bl.GOLDEN_IDS), f"G1-G10 必须齐全：{ids}"
    assert len(set(ids)) == 10, "案例 id 不得重复"

    for case in cases:
        for field in bl.GOLDEN_CASE_FIELDS:
            assert case.get(field) not in (None, "", []), f"{case['id']} 缺少字段 {field}"
        comps = case["required_components"]
        for key in bl.GOLDEN_COMPONENT_KEYS:
            assert comps.get(key), f"{case['id']} 的 required_components.{key} 为空"
        assert comps["key_entities"], f"{case['id']} 的 key_entities 必须非空"
        for sid in case["anchor_systems"]:
            assert sid in bl.ALLOWED_SYSTEMS, f"{case['id']} 使用了非法系统 id：{sid}"
