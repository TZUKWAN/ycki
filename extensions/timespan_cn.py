# -*- coding: utf-8 -*-
"""中国纪年转换器（治 timespan「未分期」问题）。

能力：
- 朝代 → 年份区间（含分裂期：三国/南北朝/五代十国取主政权区间，approximate=true）
- 年号（era）→ 公元起算年（收录汉至清主要年号 ~90 个），年号 N 年 → 起年+N-1
- 干支年 → 公元年（以 1984 甲子为锚，结合上下文朝代在 ±1200 内取合理解）
- 民国 N 年 → 1911+N
- 公元前/公元 N 年原样解析
输出：dict(valid_from, valid_to, approximate, granularity, dynasty, historical_period)
"""
from __future__ import annotations

import re

DYNASTY_RANGES = {
    "夏": (-2070, -1600), "商": (-1600, -1046), "西周": (-1046, -771),
    "周": (-1046, -256), "东周": (-770, -256), "春秋": (-770, -476),
    "战国": (-475, -221), "秦": (-221, -207), "西汉": (-202, 8), "汉": (-202, 220),
    "东汉": (25, 220), "三国": (220, 280), "魏": (220, 266), "蜀汉": (221, 263),
    "吴": (222, 280), "西晋": (266, 316), "晋": (266, 420), "东晋": (317, 420),
    "南北朝": (420, 589), "南朝": (420, 589), "北朝": (386, 581), "隋": (581, 618),
    "唐": (618, 907), "五代": (907, 979), "五代十国": (907, 979),
    "北宋": (960, 1127), "南宋": (1127, 1279), "宋": (960, 1279),
    "辽": (907, 1125), "金": (1115, 1234), "元": (1271, 1368),
    "明": (1368, 1644), "清": (1636, 1912), "民国": (1912, 1949),
}
PERIODS = {
    "先秦": (-2070, -221), "秦汉": (-221, 220), "两晋南北朝": (266, 589),
    "隋唐": (581, 907), "宋元": (960, 1368), "明清": (1368, 1912),
    "近代": (1840, 1949), "现代": (1949, 2100), "当代": (1978, 2100),
}

# 年号 → (朝代起算公元年)。收录主要年号；同年号跨朝代（如永乐仅明）不冲突。
ERAS = {
    "建元": (-140, "汉"), "元光": (-134, "汉"), "元朔": (-128, "汉"),
    "元狩": (-122, "汉"), "元鼎": (-116, "汉"), "元封": (-110, "汉"),
    "建武": (25, "东汉"), "永平": (58, "东汉"), "建安": (196, "东汉"),
    "黄初": (220, "三国"), "太康": (280, "晋"), "永嘉": (307, "晋"),
    "开皇": (581, "隋"), "大业": (605, "隋"), "武德": (618, "唐"),
    "贞观": (627, "唐"), "永徽": (650, "唐"), "开元": (713, "唐"),
    "天宝": (742, "唐"), "贞元": (785, "唐"), "会昌": (841, "唐"),
    "建隆": (960, "宋"), "庆历": (1041, "宋"), "熙宁": (1068, "宋"),
    "元祐": (1086, "宋"), "宣和": (1119, "宋"), "靖康": (1126, "宋"),
    "绍兴": (1131, "宋"), "淳熙": (1174, "宋"), "庆元": (1195, "宋"),
    "嘉定": (1208, "宋"), "至元": (1264, "元"), "元贞": (1295, "元"),
    "至正": (1341, "元"), "洪武": (1368, "明"), "建文": (1399, "明"),
    "永乐": (1403, "明"), "宣德": (1426, "明"), "正统": (1436, "明"),
    "成化": (1465, "明"), "弘治": (1488, "明"), "正德": (1506, "明"),
    "嘉靖": (1522, "明"), "隆庆": (1567, "明"), "万历": (1573, "明"),
    "泰昌": (1620, "明"), "天启": (1621, "明"), "崇祯": (1628, "明"),
    "顺治": (1644, "清"), "康熙": (1662, "清"), "雍正": (1723, "清"),
    "乾隆": (1736, "清"), "嘉庆": (1796, "清"), "道光": (1821, "清"),
    "咸丰": (1851, "清"), "同治": (1862, "清"), "光绪": (1875, "清"),
    "宣统": (1909, "清"),
}

_GAN = "甲乙丙丁戊己庚辛壬癸"
_ZHI = "子丑寅卯辰巳午未申酉戌亥"
_GANZHI = [_GAN[i % 10] + _ZHI[i % 12] for i in range(60)]
_GZ_INDEX = {g: i for i, g in enumerate(_GANZHI)}      # 1984=甲子=index0
_DYNASTY_ANCHOR = {                                      # 干支歧义消解锚点
    "明": (1368, 1644), "清": (1636, 1912), "宋": (960, 1279),
    "唐": (618, 907), "汉": (-202, 220), "元": (1271, 1368),
}


def _dynasty_range(name: str):
    if name in DYNASTY_RANGES:
        return DYNASTY_RANGES[name]
    if name in PERIODS:
        return PERIODS[name]
    return None


_CN_DIG = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10}


def _cn2int(t: str) -> int | None:
    """中文数字（年号用，1–999）：二十五→25，元→1。"""
    t = t.strip()
    if t == "元":
        return 1
    if t.isdigit():
        return int(t)
    total, num = 0, 0
    for ch in t:
        if ch in _CN_DIG:
            d = _CN_DIG[ch]
            if ch == "十":
                total += (num or 1) * 10
                num = 0
            elif ch == "百":
                total += (num or 1) * 100
                num = 0
            else:
                num = d
        else:
            return None
    return total + num


def parse(text: str) -> dict | None:
    """解析中文纪年文本 → TimeSpan 字段 dict；无法解析返回 None。"""
    if not text:
        return None
    t = text.strip()

    # 0) 年号（含中文数字年）优先于朝代名——按已知年号字典逐个确定匹配
    for era, (start, dyn) in ERAS.items():
        m = re.search(re.escape(era) +
                      r"\s*(?:元年|([一二三四五六七八九十百零\d]{1,6})\s*年)", t)
        if m:
            n = _cn2int(m.group(1) or "元") or 1
            y = start + n - 1
            return _mk(y, y, False, "year", dynasty=dyn, raw=t)
    m = re.search(r"民国\s*(?:元年|([一二三四五六七八九十百零\d]{1,4})\s*年)", t)
    if m:
        n = _cn2int(m.group(1) or "元") or 1
        return _mk(1911 + n, 1911 + n, False, "year", dynasty="民国", raw=t)

    # 1) 公元前/公元 N 年
    m = re.search(r"公元前\s*(\d{1,4})\s*年?", t)
    if m:
        y = -int(m.group(1))
        return _mk(y, y, False, "year", raw=t)
    m = re.search(r"公元\s*(\d{4})\s*年", t) or re.search(r"\b(\d{4})\s*年", t)
    if m:
        y = int(m.group(1))
        if 1000 <= y <= 2100:
            return _mk(y, y, False, "year", raw=t)

    # 2) 民国 N 年
    m = re.search(r"民国\s*(\d{1,3})\s*年", t)
    if m:
        y = 1911 + int(m.group(1))
        return _mk(y, y, False, "year", dynasty="民国", raw=t)

    # 3) 年号 N 年
    m = re.search(r"([\u4e00-\u9fff]{2,3})\s*(?:元年|(\d{1,3})\s*年)", t)
    if m and m.group(1) in ERAS:
        era = m.group(1)
        start, dyn = ERAS[era]
        n = int(m.group(2) or 1)
        y = start + n - 1
        return _mk(y, y, False, "year", dynasty=dyn, raw=t)

    # 4) 干支年（结合朝代锚消解 60 年歧义）
    m = re.search(r"([甲乙丙丁戊己庚辛壬癸])([子丑寅卯辰巳午未申酉戌亥])年?", t)
    if m and m.group(1) + m.group(2) in _GZ_INDEX:
        gz = m.group(1) + m.group(2)
        idx = _GZ_INDEX[gz]
        anchor_dyn = next((d for d in _DYNASTY_ANCHOR if d in t), None)
        lo, hi = _DYNASTY_ANCHOR.get(anchor_dyn, (1000, 2000))
        candidates = sorted([y for y in range(lo - 60, hi + 61)
                             if (y - 1984) % 60 == idx % 60])
        if candidates:
            # 无朝代锚时优先近代候选（庚子→1900 优先于 940）
            y = min(candidates, key=lambda v: abs(v - 1900)) if not anchor_dyn                 else candidates[0]
            return _mk(y, y, True, "year", dynasty=anchor_dyn, raw=t)

    # 5) 世纪
    m = re.search(r"(\d{1,2})\s*世纪", t)
    if m:
        c = int(m.group(1))
        y = (c - 1) * 100
        return _mk(y, y + 99, True, "era", raw=t)

    # 6) 朝代/时期名
    for name in list(ERAS):
        continue
    for name in sorted(list(DYNASTY_RANGES) + list(PERIODS), key=len, reverse=True):
        if name in t:
            lo, hi = _dynasty_range(name)
            return _mk(lo, hi, True, "period", dynasty=name if name in DYNASTY_RANGES else None,
                       historical_period=name if name in PERIODS else None, raw=t)

    # 7) 相对描述（20世纪初 / 40年代）
    m = re.search(r"(\d{2,3})\s*年代", t)
    if m:
        dec = int(m.group(2)) if False else int(m.group(1))
        base = 1900 if dec < 100 else dec
        y = (base // 10) * 10
        return _mk(y, y + 9, True, "decade", raw=t)
    m = re.search(r"(\d{2})\s*世纪初", t)
    if m:
        y = (int(m.group(1)) - 1) * 100
        return _mk(y, y + 99, True, "era", raw=t)
    return None


def _mk(y_from: int, y_to: int, approx: bool, granularity: str, dynasty: str | None = None,
        historical_period: str | None = None, raw: str = "") -> dict:
    # 负数年转 BC 表示保留数字（PostgreSQL TEXT 存原值）
    return {"valid_from": str(y_from), "valid_to": str(y_to),
            "approximate": approx, "granularity": granularity,
            "dynasty": dynasty, "historical_period": historical_period,
            "raw_text": raw[:80]}


def period_of_year(y: int) -> str:
    """公元年 → 目标书周期轴标签。"""
    for name, (lo, hi) in [("先秦", (-2070, -221)), ("秦汉", (-221, 220)),
                           ("两晋南北朝", (266, 589)), ("隋唐", (581, 907)),
                           ("宋元", (960, 1368)), ("明清", (1368, 1912)),
                           ("近代", (1840, 1949)), ("现代", (1949, 2100))]:
        if lo <= y <= hi:
            return name
    # 边界归属
    if -221 <= y <= 220:
        return "秦汉"
    if 220 <= y <= 266:
        return "秦汉"
    return "未分期"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for t in ["光绪二十五年", "民国二十七年", "贞观三年", "1984年", "公元前256年",
              "唐代", "明朝万历年间", "20世纪初", "90年代", "庚子年", "1840年",
              "南宋绍兴年间", "1927年8月1日"]:
        print(t, "->", parse(t))
