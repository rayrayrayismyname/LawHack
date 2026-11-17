"""載入法規知識庫。法條內容一律從這裡取得，AI 不自行生成條文。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .parsing import ArticleRef

KB_DIR = Path(__file__).parent / "knowledge"


@lru_cache
def _load(name: str) -> dict:
    with open(KB_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def laws() -> dict:
    return _load("laws.json")["laws"]


def law(key: str) -> dict:
    return laws()[key]


def stats() -> dict:
    return _load("stats.json")


def reportable() -> dict:
    return _load("reportable_items.json")


def match_reportable(ref: ArticleRef) -> tuple[str, Optional[dict]]:
    """判斷某條款是否屬第7條之1第1項可檢舉項目。

    回傳 (status, item)：
      "yes"       ：屬可檢舉項目（item 可能帶有 qualifier，需再檢查地點／態樣）
      "no"        ：確定不屬可檢舉項目
      "uncertain" ：罰單上的法條缺少項或款，無法確定
    """
    candidates = [it for it in reportable()["items"] if it["article"] == ref.article]
    if not candidates:
        return "no", None
    uncertain = None
    for it in candidates:
        if it["para"] is not None:
            if ref.para is None:
                uncertain = it
                continue
            if it["para"] != ref.para:
                continue
        if it["subs"] is not None:
            if ref.sub is None:
                uncertain = it
                continue
            if ref.sub not in it["subs"]:
                continue
        return "yes", it
    if uncertain is not None:
        return "uncertain", uncertain
    return "no", None
