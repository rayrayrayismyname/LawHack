"""解析罰單上的法條字串與日期（支援民國年、國字數字）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "兩": 2}
_CN_UNITS = {"十": 10, "百": 100}


def cn_to_int(s: str) -> int:
    """國字數字轉整數，例如 五十六 -> 56、十 -> 10、一百零二 -> 102。也接受阿拉伯數字。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (num or 1) * unit
            num = 0
        else:
            raise ValueError(f"無法解析的數字：{s}")
    return total + num


@dataclass(frozen=True)
class ArticleRef:
    article: str              # "56" 或 "31-1"
    para: Optional[int] = None
    sub: Optional[int] = None

    def label(self) -> str:
        art = self.article.replace("-", "條之")
        out = f"第{art}條" if "-" not in self.article else f"第{art}"
        if self.para:
            out += f"第{self.para}項"
        if self.sub:
            out += f"第{self.sub}款"
        return out


_NUM = r"[0-9零〇一二兩三四五六七八九十百]+"
_ART_RE = re.compile(
    rf"第\s*(?P<art>{_NUM})\s*條(?:\s*之\s*(?P<zhi>{_NUM}))?"
    rf"(?:\s*第\s*(?P<para>{_NUM})\s*項)?"
    rf"(?:\s*第\s*(?P<sub>{_NUM})\s*款)?"
)
_SHORT_RE = re.compile(r"^\s*(\d+)(?:之(\d+))?(?:[-－.](\d+))?(?:[-－.](\d+))?\s*$")


def parse_article(text: str) -> Optional[ArticleRef]:
    """解析「道路交通管理處罰條例第56條第1項第1款」「第三十一條之一第一項」「56-1-1」等寫法。
    回傳第一個找到的條文；找不到時回傳 None。"""
    if not text:
        return None
    m = _ART_RE.search(text)
    if m:
        art = str(cn_to_int(m.group("art")))
        if m.group("zhi"):
            art += f"-{cn_to_int(m.group('zhi'))}"
        para = cn_to_int(m.group("para")) if m.group("para") else None
        sub = cn_to_int(m.group("sub")) if m.group("sub") else None
        # 罰單常印成「第0項00款」，代表沒有項、款
        return ArticleRef(art, para or None, sub or None)
    m = _SHORT_RE.match(text)
    if m:
        art = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
        para = int(m.group(3)) if m.group(3) else None
        sub = int(m.group(4)) if m.group(4) else None
        return ArticleRef(art, para or None, sub or None)
    return None


def find_article_numbers(text: str) -> set[str]:
    """找出文字中所有被引用的條號（只取條與之，例如 {"9", "7-1"}），用於檢查 AI 是否亂引法條。"""
    out = set()
    for m in _ART_RE.finditer(text):
        try:
            art = str(cn_to_int(m.group("art")))
            if m.group("zhi"):
                art += f"-{cn_to_int(m.group('zhi'))}"
            out.add(art)
        except ValueError:
            continue
    return out


_DATE_RES = [
    re.compile(r"(?P<y>\d{2,4})\s*[年/.\-]\s*(?P<m>\d{1,2})\s*[月/.\-]\s*(?P<d>\d{1,2})"),
]


def parse_date(text: str | None) -> Optional[date]:
    """解析日期，支援 115/11/03、115年11月3日、2026-11-03。三位數以下的年份視為民國年。"""
    if not text:
        return None
    if isinstance(text, date):
        return text
    for rx in _DATE_RES:
        m = rx.search(str(text))
        if m:
            y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
            if y < 1000:
                y += 1911
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    return None


def parse_datetime(text: str | None) -> Optional[datetime]:
    """解析含時間的字串，例如 115/11/03 08:12。沒有時間時回傳當天 00:00。"""
    d = parse_date(text)
    if d is None:
        return None
    m = re.search(r"(\d{1,2})\s*[:：時]\s*(\d{1,2})", str(text))
    if m:
        return datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)))
    return datetime(d.year, d.month, d.day)


def roc(d: date) -> str:
    """西元日期轉民國表示，例如 2026-11-17 -> 115年11月17日。"""
    return f"{d.year - 1911}年{d.month}月{d.day}日"


_VEHICLE_MAP = [
    ("機車", ("機車", "重機", "輕機", "重型", "輕型", "普重", "普輕", "大型重型")),
    ("大型車", ("大貨", "大客", "聯結", "曳引", "大型車", "遊覽")),
    ("汽車", ("自小客", "營小客", "小客", "小貨", "自小貨", "租賃小客", "汽車", "轎車", "自用")),
]


def normalize_vehicle(text: str) -> str:
    """把罰單上的車種（自小客(貨)、普重機…）對應到 汽車／機車／大型車。無法判斷時原樣回傳。"""
    t = (text or "").strip()
    if t in ("汽車", "機車", "大型車", ""):
        return t
    for label, words in _VEHICLE_MAP:
        if any(w in t for w in words):
            return label
    return t
