# -*- coding: utf-8 -*-
"""Phase 8 v2：Evidence Binder —— quote_span 必须能在原文 chunk 中精确定位。

match_status:
  EXACT       逐字命中
  NORMALIZED  全文归一化（空白/标点/常见 OCR 差异）后整段命中
  FAILED      无法定位

v2 收紧（§32）：删除「归一化前 16 字前缀命中」的宽松规则——
大面积截断匹配不再视为成功。只允许空白/标点/OCR 符号差异。
"""
from __future__ import annotations

import re

# 归一化：去空白、中英文标点、OCR 常见混淆符
_STRIP_RE = re.compile(
    r"[\s，。、；：？！“”‘’\"'（）()\[\]【】《》<>—\-–_…·,.:;?!※◆●★☆→↑↓【】〓◎§※]+")
# OCR/繁简常见差异符（保守：仅结构符，不做繁简转换——繁简由 ER 层处理）
_OCR_RE = re.compile(r"[⺀-⺟⻀-⻳〇○●◇◆□■△▲▽▽]")


def _normalize(text: str) -> str:
    t = _STRIP_RE.sub("", text or "")
    return _OCR_RE.sub("", t)


def bind(quote_span: str, chunk_text: str) -> str:
    """返回 EXACT / NORMALIZED / FAILED。

    v2：NORMALIZED 要求整段归一化命中；不再接受前缀截断。
    """
    if not quote_span or not chunk_text:
        return "FAILED"
    if quote_span in chunk_text:
        return "EXACT"
    nq, nt = _normalize(quote_span), _normalize(chunk_text)
    if nq and len(nq) >= 6 and nq in nt:
        return "NORMALIZED"
    return "FAILED"
