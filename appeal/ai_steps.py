"""AI 負責的三個步驟：讀罰單、整理陳述、改寫事實經過。
每一步都有離線替代方案，且 AI 的輸出都會經過檢查，不合格就退回規則／範本結果。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

from .llm import LLM, extract_json
from .models import Case, Facts, Ticket, Finding, SOURCES
from . import knowledge_base as kb
from .parsing import find_article_numbers, normalize_vehicle, parse_article

PROMPT_DIR = Path(__file__).parent / "prompts"


def _prompt(name: str, **vars) -> str:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _ticket_text(t: Ticket) -> str:
    return json.dumps({k: v for k, v in asdict(t).items() if v not in ("", None)},
                      ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 1. 讀罰單

def extract_ticket(image: bytes, mime: str, llm: LLM) -> tuple[dict, list[str]]:
    """從罰單影像擷取欄位。回傳 (欄位, 警告訊息)。"""
    if not llm.available:
        return {}, ["離線模式無法辨識罰單影像，請手動輸入罰單欄位。"]
    try:
        raw = llm.complete("你只輸出 JSON。", _prompt("extract_ticket"), images=[(image, mime)])
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001
        return {}, [f"罰單辨識失敗（{e}），請手動輸入。"]
    allowed = {f.name for f in fields(Ticket)}
    data = {k: v for k, v in data.items() if k in allowed and v not in (None, "")}
    warnings = []
    if data.get("vehicle_type"):
        data["vehicle_type"] = normalize_vehicle(data["vehicle_type"])
    if data.get("source") and data["source"] not in SOURCES:
        warnings.append(f"辨識到的舉發方式「{data['source']}」無法對應，請手動選擇。")
        data.pop("source")
    if data.get("article") and parse_article(data["article"]) is None:
        warnings.append("辨識到的違反法條格式無法解析，請手動確認。")
    for k in ("fine", "points"):
        if k in data:
            try:
                data[k] = int(re.sub(r"[^\d]", "", str(data[k])))
            except ValueError:
                data.pop(k)
    warnings.append("AI 辨識結果請逐欄核對罰單正本。")
    return data, warnings


# ---------------------------------------------------------------- 2. 整理陳述

_KEYWORDS = {
    "plate_mismatch": ["不是我的車", "車牌不符", "車牌錯", "不是我的機車", "車牌辨識錯", "車型不符"],
    "evidence_unclear": ["看不清楚", "模糊", "看不到車牌", "無法辨識"],
    "sign_obscured": ["遮住", "被樹", "遮蔽", "擋住", "看不到標誌", "標線不清", "標線模糊", "沒有標線", "標誌不清"],
    "emergency": ["救護車", "消防車", "閃避", "緊急"],
    "not_driver": ["不是我開", "不是我騎", "朋友開", "朋友騎", "借給", "家人開", "家人騎", "別人開", "別人騎"],
}
_NO_SIGN = ["沒有測速標誌", "沒有警示標誌", "沒有測速警示", "沒看到測速", "沒有任何標誌", "未設置警示", "沒有測速照相的牌子"]


def heuristic_facts(statement: str) -> Facts:
    """離線模式：用關鍵字粗略整理事實。只把「有提到」的事項設為 True，其餘維持 None。"""
    s = statement or ""
    f = Facts()
    for key, words in _KEYWORDS.items():
        if any(w in s for w in words):
            setattr(f, key, True)
    for loc in ("行人穿越道", "人行道", "騎樓"):
        if loc in s:
            f.location_type = loc
            break
    else:
        if "斑馬線" in s:
            f.location_type = "行人穿越道"
        elif any(w in s for w in ("路邊", "停車格", "路肩")):
            f.location_type = "一般道路"
    if any(w in s for w in ("超速", "測速")):
        f.is_speeding = True
        if any(w in s for w in _NO_SIGN):
            f.sign_present = False
        m = re.search(r"(?:標誌|牌子|警示)[^。]{0,25}?(\d{2,4})\s*(?:公尺|米)", s) or \
            re.search(r"(\d{2,4})\s*(?:公尺|米)[^。]{0,15}?(?:標誌|牌子|警示)", s)
        if m:
            f.sign_distance_m = float(m.group(1))
            f.sign_present = True
    if any(w in s for w in ("國道", "高速公路")):
        f.road_type = "高速公路"
    elif any(w in s for w in ("快速道路", "快速公路")):
        f.road_type = "快速公路"
    elif any(w in s for w in ("一般道路", "市區道路", "市區")):
        f.road_type = "一般道路"
    f.notes.append("離線模式：事實由關鍵字整理，請在表單中確認。")
    return f


def analyze_statement(case: Case, llm: LLM) -> tuple[Facts, Optional[str], list[str]]:
    """把白話陳述整理成 Facts。回傳 (facts, 摘要, 警告)。"""
    if not llm.available:
        return heuristic_facts(case.statement), None, []
    ev = "\n".join(f"- {e.name}：{e.description}" for e in case.evidence) or "（無）"
    try:
        raw = llm.complete("你只輸出 JSON。", _prompt(
            "analyze_statement", TICKET=_ticket_text(case.ticket),
            STATEMENT=case.statement or "（無）", EVIDENCE=ev))
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001
        return heuristic_facts(case.statement), None, [f"AI 分析失敗（{e}），已改用關鍵字整理。"]
    f = Facts()
    allowed = {x.name for x in fields(Facts)}
    for k, v in data.items():
        if k in allowed and v is not None and k != "notes":
            setattr(f, k, v)
    if not isinstance(f.repeat_ticket_times, list):
        f.repeat_ticket_times = []
    if f.sign_distance_m is not None:
        try:
            f.sign_distance_m = float(f.sign_distance_m)
        except (TypeError, ValueError):
            f.sign_distance_m = None
    return f, data.get("summary"), []


def merge_facts(base: Facts, override: Facts) -> Facts:
    """使用者在表單明確填寫的值（override）優先於 AI／關鍵字整理的值（base）。"""
    out = Facts(**asdict(base))
    for fld in fields(Facts):
        v = getattr(override, fld.name)
        if fld.name in ("repeat_ticket_times", "notes"):
            if v:
                setattr(out, fld.name, list(dict.fromkeys(getattr(out, fld.name) + v)))
        elif v is not None and v != "":
            setattr(out, fld.name, v)
    return out


# ---------------------------------------------------------------- 3. 陳述意見書

def _template_facts(case: Case) -> str:
    t = case.ticket
    head = "緣陳述人"
    if t.violation_time:
        head += f"於{t.violation_time}"
    if t.plate:
        head += f"所有車號{t.plate}之{t.vehicle_type or '車輛'}"
    if t.violation_place:
        head += f"，於{t.violation_place}"
    head += f"，經{t.agency or '舉發單位'}以「{t.violation_fact or '違規'}」為由舉發。"
    body = (case.statement or "").strip()
    if body:
        body = "陳述人說明當時情形如下：" + body.rstrip("。") + "。"
    return head + body


def allowed_articles(case: Case, findings: list[Finding]) -> set[str]:
    arts = {"9"}
    ref = parse_article(case.ticket.article)
    if ref:
        arts.add(ref.article)
    for f in findings:
        for key in f.law_refs:
            arts.add(kb.law(key)["article"])
    return arts


def draft_facts(case: Case, llm: LLM, findings: list[Finding]) -> tuple[str, bool, list[str]]:
    """產生「事實經過」段落。回傳 (文字, 是否使用 AI, 警告)。"""
    fallback = _template_facts(case)
    if not llm.available or not case.statement:
        return fallback, False, []
    try:
        text = llm.complete("你是公文寫作助手。", _prompt(
            "draft_facts", TICKET=_ticket_text(case.ticket), STATEMENT=case.statement)).strip()
    except Exception as e:  # noqa: BLE001
        return fallback, False, [f"AI 改寫失敗（{e}），已使用範本。"]
    problems = check_draft(text, case, findings)
    if problems:
        return fallback, False, ["AI 改寫內容未通過檢查（" + "；".join(problems) + "），已改用範本文字。"]
    return text, True, []


def check_draft(text: str, case: Case, findings: list[Finding]) -> list[str]:
    """防幻覺檢查：AI 不得引用未經規則引擎確認的法條，也不得新增原始資料沒有的數字。"""
    problems = []
    extra = find_article_numbers(text) - allowed_articles(case, findings)
    if extra:
        problems.append(f"引用了未經確認的法條：第{'、'.join(sorted(extra))}條")
    source = _ticket_text(case.ticket) + (case.statement or "")
    nums_src = set(re.findall(r"\d+", source))
    nums_out = set(re.findall(r"\d+", text))
    new_nums = {n for n in nums_out - nums_src if len(n) >= 2}
    if new_nums:
        problems.append(f"出現原始資料沒有的數字：{'、'.join(sorted(new_nums))}")
    if not (40 <= len(text) <= 600):
        problems.append("長度不合理")
    return problems
