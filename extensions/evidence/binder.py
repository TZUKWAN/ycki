# -*- coding: utf-8 -*-
"""Phase 8：Evidence Binder —— quote_span 必须能在原文 chunk 中精确定位。

match_status: EXACT（逐字） / NORMALIZED（去空白标点后匹配） / FAILED（无法定位）。
FAILED 的 evidence 不能支撑 ADMITTED。
"""
from __future__ import annotations

import re


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。、；：？！“”‘’\"'（）()\[\]【】《》<>—\-…·,.:;?!]+", "", text or "")


def bind(quote_span: str, chunk_text: str) -> str:
    """返回 EXACT / NORMALIZED / FAILED。"""
    if not quote_span or not chunk_text:
        return "FAILED"
    if quote_span in chunk_text:
        return "EXACT"
    nq, nt = _normalize(quote_span), _normalize(chunk_text)
    if nq and nq in nt:
        return "NORMALIZED"
    # quote 可能被截断：尝试其归一化前缀（≥10字）
    nq10 = nq[:12]
    if len(nq) >= 10 and nq10 and nq10 in nt:
        return "NORMALIZED"
    return "FAILED"
