# -*- coding: utf-8 -*-
"""SimHash 近重复检测（Phase 8 转载链聚类）。

64 位 simhash（中文 3-gram 特征），汉明距离 ≤6 视为近重复转载。
同一原稿的 N 个转载只计 1 个独立证据来源。
"""
from __future__ import annotations


def _features(text: str, k: int = 3) -> set[str]:
    t = "".join(text.split())
    if len(t) < k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def _hash64(s: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")


def simhash64(text: str) -> int:
    feats = _features(text)
    if not feats:
        return 0
    v = [0] * 64
    for f in feats:
        h = _hash64(f)
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, x in enumerate(v):
        if x > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def near_duplicate(a_text: str, b_text: str, max_dist: int = 6) -> bool:
    return hamming(simhash64(a_text), simhash64(b_text)) <= max_dist


def to_int64(sim: int) -> int:
    """无符号 64 位 → 有符号（PostgreSQL BIGINT 兼容）。"""
    return sim - (1 << 64) if sim >= (1 << 63) else sim


def to_unsigned(v: int) -> int:
    return v & 0xFFFFFFFFFFFFFFFF
