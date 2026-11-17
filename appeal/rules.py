"""規則引擎：逐條檢核可主張的申訴理由。

設計原則：
  * 判斷「是否符合法律要件」一律由這裡的確定性規則負責，AI 只負責把白話描述轉成 Facts。
  * 每個結論都附上法條（law_refs），可追溯、可解釋。
  * 資訊不足時回傳 INFO，請使用者補充，而不是自行假設。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional

from . import knowledge_base as kb
from .models import (Case, Finding, STRONG, MEDIUM, PROCEDURE, INFO,
                     SOURCE_CITIZEN, SOURCE_CAMERA, SOURCE_DIRECT, SOURCE_STOP)
from .parsing import parse_article, parse_date, parse_datetime, roc

Rule = Callable[[Case], Optional[Finding]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _is_citizen(case: Case) -> bool:
    return case.ticket.source == SOURCE_CITIZEN


# ---------------------------------------------------------------- 民眾檢舉

@rule
def r01_not_reportable(case: Case) -> Optional[Finding]:
    """民眾檢舉的違規項目不在第7條之1第1項表列範圍內。"""
    if not _is_citizen(case):
        return None
    ref = parse_article(case.ticket.article)
    if ref is None:
        return Finding("R01", "無法判斷違規項目是否可被民眾檢舉", INFO,
                       "罰單上的「違反法條」沒有讀到，無法比對可檢舉項目。",
                       "", ["道交條例第7條之1"], ["請輸入罰單上完整的違反法條（含條、項、款）"])
    status, item = kb.match_reportable(ref)
    label = ref.label()
    if status == "no":
        return Finding(
            "R01", "違規項目不屬民眾得檢舉之範圍", STRONG,
            f"本件為民眾檢舉，但{label}不在道交條例第7條之1第1項所列的可檢舉項目中。",
            f"本件係依民眾檢舉而舉發，惟所援引之道路交通管理處罰條例{label}，並非同條例第7條之1第1項"
            f"所列民眾得檢舉之違規行為，舉發機關依法不得僅憑民眾檢舉予以舉發，原舉發程序顯有違誤。",
            ["道交條例第7條之1"])
    if status == "uncertain":
        return Finding("R01", "需要完整法條才能判斷是否可被檢舉", INFO,
                       f"{label}的部分項款屬於可檢舉項目，但罰單法條缺少項或款，無法確定。",
                       "", ["道交條例第7條之1"], ["請輸入罰單上完整的違反法條（含項、款）"])
    q = item.get("qualifier")
    if not q:
        return None
    f = case.facts
    vt = case.ticket.vehicle_type or ""
    if any(v in vt for v in q.get("exclude_vehicles", [])):
        return Finding(
            "R01", "此項目對機車不開放民眾檢舉", STRONG,
            f"{label}雖列於可檢舉項目，但條文明定「{q['text']}」，本件車輛為{vt}。",
            f"本件係依民眾檢舉而舉發。道路交通管理處罰條例第7條之1第1項雖將{label}列為得檢舉之行為，"
            f"惟明定{q['text']}。本件車輛為{vt}，不在民眾得檢舉之範圍，舉發機關不得據以舉發。",
            ["道交條例第7條之1"])
    loc = f.location_type
    if loc and any(x in loc for x in q.get("exclude_locations", [])):
        return Finding(
            "R01", "違規地點不屬可檢舉範圍", STRONG,
            f"{label}的可檢舉範圍是「{q['text']}」，本件地點為{loc}。",
            f"本件係依民眾檢舉而舉發。依道路交通管理處罰條例第7條之1第1項，{label}僅於{q['text']}之情形"
            f"始得由民眾檢舉。本件停放地點為{loc}，不在得檢舉之範圍內。",
            ["道交條例第7條之1"])
    if loc and q.get("locations") and not any(x in loc for x in q["locations"]):
        return Finding(
            "R01", "違規地點不屬可檢舉範圍", STRONG,
            f"{label}只有在「{'、'.join(q['locations'])}」時才能被民眾檢舉，本件地點為{loc}。",
            f"本件係依民眾檢舉而舉發。依道路交通管理處罰條例第7條之1第1項，{label}僅於{q['text']}之情形"
            f"始得由民眾檢舉。本件地點為{loc}，非屬得檢舉之範圍。",
            ["道交條例第7條之1"])
    if q.get("behaviors") and f.behavior and not any(b in f.behavior for b in q["behaviors"]):
        return Finding(
            "R01", "違規態樣可能不屬可檢舉範圍", MEDIUM,
            f"{label}只有「{q['text']}」才能被民眾檢舉，你描述的情況是「{f.behavior}」。",
            f"本件係依民眾檢舉而舉發。依道路交通管理處罰條例第7條之1第1項，{label}僅限{q['text']}，"
            f"本件情形為{f.behavior}，是否屬得檢舉之範圍，請貴機關詳予審酌。",
            ["道交條例第7條之1"])
    if not loc and (q.get("locations") or q.get("exclude_locations")):
        return Finding("R01", "需要確認違規地點", INFO,
                       f"{label}只有特定地點（{q['text']}）才能被民眾檢舉。",
                       "", ["道交條例第7條之1"], ["請說明停車地點是人行道、行人穿越道、騎樓或一般路邊"])
    return None


@rule
def r02_report_overdue(case: Case) -> Optional[Finding]:
    """檢舉日距違規行為終了日逾7日。"""
    if not _is_citizen(case):
        return None
    vt = parse_date(case.ticket.violation_time)
    rd = parse_date(case.facts.report_date)
    if vt is None:
        return None
    if rd is None:
        return Finding("R02", "可確認檢舉是否逾7日", INFO,
                       "民眾須在違規行為終了日起7日內檢舉。罰單通常不會寫檢舉日期，可向舉發單位詢問。",
                       "", ["道交條例第7條之1"], ["向舉發單位查詢本件的檢舉日期"])
    gap = (rd - vt).days
    if gap > 7:
        return Finding(
            "R02", "檢舉已逾7日期限", STRONG,
            f"違規日為{roc(vt)}，檢舉日為{roc(rd)}，相隔{gap}日，超過法定7日。",
            f"依道路交通管理處罰條例第7條之1第2項但書，行為終了日起逾七日之檢舉，不予舉發。本件違規行為"
            f"終了日為{vt.year - 1911}年{vt.month}月{vt.day}日，檢舉日為{rd.year - 1911}年{rd.month}月{rd.day}日，"
            f"已逾七日，依法不應舉發。",
            ["道交條例第7條之1"])
    return None


@rule
def r03_repeat_within_six_minutes(case: Case) -> Optional[Finding]:
    """同一輛車、同一規定，相隔未逾6分鐘且未經過一個路口以上，以舉發一次為限。"""
    if not _is_citizen(case) or not case.facts.repeat_ticket_times:
        return None
    t0 = parse_datetime(case.ticket.violation_time)
    if t0 is None:
        return None
    gaps = []
    for s in case.facts.repeat_ticket_times:
        t = parse_datetime(s)
        if t is not None:
            gaps.append(abs((t - t0).total_seconds()) / 60)
    close = [g for g in gaps if g <= 6]
    if not close:
        return None
    g = min(close)
    if case.facts.crossed_intersection is False:
        return Finding(
            "R03", "同一行為被重複舉發", STRONG,
            f"另一張同規定的罰單與本件相隔約{g:.0f}分鐘，且期間未經過路口，依法只能舉發一次。",
            f"本件與同一檢舉之其他罰單，係對同一輛汽車違反同一規定之行為所為舉發，違規時間相隔約{g:.0f}分鐘，"
            f"且行駛未經過一個路口以上。依道路交通管理處罰條例第7條之1第3項，應以舉發一次為限，"
            f"重複舉發部分應予撤銷。",
            ["道交條例第7條之1"])
    return Finding(
        "R03", "可能屬重複舉發", MEDIUM,
        f"另一張同規定的罰單與本件相隔約{g:.0f}分鐘。若期間沒有經過路口，依法只能舉發一次。",
        f"本件與同一檢舉之其他罰單違規時間相隔約{g:.0f}分鐘，如行駛未經過一個路口以上，依道路交通管理處罰條例"
        f"第7條之1第3項應以舉發一次為限，請貴機關查明。",
        ["道交條例第7條之1"], ["行車紀錄器或地圖截圖，證明兩次違規之間沒有經過路口"])


# ---------------------------------------------------------------- 測速取締

@rule
def r04_speed_warning_sign(case: Case) -> Optional[Finding]:
    """測速取締未依規定距離明顯標示警告。"""
    f = case.facts
    if not f.is_speeding:
        return None
    highway = bool(f.road_type) and any(k in f.road_type for k in ("高速", "快速"))
    lo, hi = (300, 1000) if highway else (100, 300)
    road = "高速公路／快速公路" if highway else "一般道路"
    if f.sign_present is False:
        return Finding(
            "R04", "測速前未設置警示標誌", STRONG,
            f"{road}的測速取締，依法應在測速點前{lo}～{hi}公尺明顯標示，你表示現場沒有警示標誌。",
            f"依道路交通管理處罰條例第7條之2第3項，以科學儀器取締超速者，於{road}應於{lo}公尺至{hi}公尺間"
            f"明顯標示之。本件測速地點前方未設置測速取締標誌，取締程序不符法定要件，所取得之證據不應作為舉發依據。",
            ["道交條例第7條之2"], ["測速點前方道路的照片或行車紀錄器影像，顯示沒有警示標誌"])
    if f.sign_distance_m is not None and not (lo <= f.sign_distance_m <= hi):
        return Finding(
            "R04", "測速警示標誌距離不符規定", STRONG,
            f"{road}應在測速點前{lo}～{hi}公尺標示，你量到的距離約{f.sign_distance_m:.0f}公尺。",
            f"依道路交通管理處罰條例第7條之2第3項，以科學儀器取締超速者，於{road}應於{lo}公尺至{hi}公尺間"
            f"明顯標示之。經實地量測，本件警示標誌距測速地點約{f.sign_distance_m:.0f}公尺，不符法定距離，"
            f"取締程序有瑕疵。",
            ["道交條例第7條之2"], ["標示位置與測速點的照片、地圖測距截圖"])
    if f.sign_present is None and f.sign_distance_m is None:
        return Finding("R04", "可確認測速警示標誌", INFO,
                       f"{road}的測速取締，應在測速點前{lo}～{hi}公尺明顯標示。",
                       "", ["道交條例第7條之2"], ["回到現場或用街景確認是否有警示標誌、距離多遠"])
    return None


# ---------------------------------------------------------------- 事實與證據

@rule
def r05_plate_mismatch(case: Case) -> Optional[Finding]:
    if not case.facts.plate_mismatch:
        return None
    return Finding(
        "R05", "採證照片中的車輛不是本人車輛", STRONG,
        "你表示照片中的車牌、車種或顏色與你的車不符，可能是車牌辨識錯誤。",
        "經核對採證照片，照片中車輛之車牌號碼、車種或外觀與陳述人所有車輛不符，陳述人並無被指之違規行為。"
        "依行政程序法第36條，行政機關應依職權調查證據，對當事人有利及不利事項一律注意，懇請貴機關調閱原始影像查明。",
        ["行政程序法第36條", "行政罰法第7條"], ["行照照片、車輛外觀照片（與採證照片對照）"])


@rule
def r06_evidence_unclear(case: Case) -> Optional[Finding]:
    if not case.facts.evidence_unclear:
        return None
    return Finding(
        "R06", "採證影像無法明確辨識", MEDIUM,
        "採證照片模糊或角度不足，看不清楚車牌或違規事實，可要求機關提出完整影像。",
        "本件採證影像模糊不清，無法明確辨識車牌號碼及違規事實。依行政程序法第36條，行政機關應依職權調查證據，"
        "現有證據尚不足以證明陳述人有違規行為，懇請貴機關調閱完整原始影像審認。",
        ["行政程序法第36條"], ["罰單上的採證照片（標示看不清楚的地方）"])


@rule
def r07_sign_obscured(case: Case) -> Optional[Finding]:
    if not case.facts.sign_obscured:
        return None
    return Finding(
        "R07", "標誌標線不清或遭遮蔽", MEDIUM,
        "標誌或標線被遮蔽、模糊或設置不當時，駕駛人難以遵守，可主張無故意過失。",
        "違規地點之交通標誌、標線遭遮蔽或模糊不清，陳述人依當時路況客觀上無從辨識相關管制規定。"
        "依道路交通管理處罰條例第4條，標誌標線應提供駕駛人明確之路況資訊；又依行政罰法第7條，"
        "非出於故意或過失之行為不予處罰。",
        ["道交條例第4條", "行政罰法第7條"], ["現場標誌、標線的照片（最好與違規時間相近）"])


@rule
def r08_emergency(case: Case) -> Optional[Finding]:
    if not case.facts.emergency:
        return None
    return Finding(
        "R08", "為避免緊急危難而不得已", MEDIUM,
        "例如為了讓救護車、閃避突發危險而違規，可主張緊急避難。",
        "陳述人當時係為避免自己或他人生命、身體之緊急危難，出於不得已而為之，依行政罰法第13條規定，不予處罰。",
        ["行政罰法第13條"], ["行車紀錄器影像，呈現當時的緊急狀況"])


@rule
def r09_not_driver(case: Case) -> Optional[Finding]:
    if not case.facts.not_driver:
        return None
    return Finding(
        "R09", "違規時不是你駕駛：應辦理歸責", PROCEDURE,
        "這不是撤銷罰單的理由，而是要在「應到案日期」前告知處罰機關實際駕駛人，罰單會改寄給對方。逾期未辦理仍會罰車主。",
        "",
        ["道交條例第85條"], ["實際駕駛人的駕照影本與身分證影本", "罰單與採證照片", "處罰機關的歸責申請書表"])


def run_rules(case: Case) -> list[Finding]:
    findings = []
    for r in RULES:
        res = r(case)
        if res is not None:
            findings.append(res)
    order = {STRONG: 0, MEDIUM: 1, PROCEDURE: 2, INFO: 3}
    findings.sort(key=lambda x: order[x.strength])
    return findings


def reportability(article: str, vehicle_type: str = "", location_type: Optional[str] = None) -> dict:
    """法條快速查詢：這個違規項目可以被民眾檢舉嗎？"""
    from .models import Ticket, Facts
    ref = parse_article(article)
    if ref is None:
        return {"status": "invalid", "label": "", "message": "看不懂這個法條，請輸入例如「第56條第1項第1款」或「56-1-1」。"}
    status, item = kb.match_reportable(ref)
    label = ref.label()
    base = {"label": label, "qualifier": (item or {}).get("qualifier", {}).get("text") if item else None}
    if status == "no":
        return {**base, "status": "no",
                "message": f"{label}不在民眾可檢舉的項目中。如果你的罰單是民眾檢舉開出的，這是明確的申訴理由。"}
    if status == "uncertain":
        return {**base, "status": "uncertain",
                "message": f"{label}只有部分項、款可以被檢舉，請輸入完整的項與款。"}
    case = Case(ticket=Ticket(source=SOURCE_CITIZEN, article=article, vehicle_type=vehicle_type),
                facts=Facts(location_type=location_type))
    f = r01_not_reportable(case)
    if f and f.strength == STRONG:
        return {**base, "status": "no", "message": f.reason}
    if base["qualifier"]:
        return {**base, "status": "conditional",
                "message": f"{label}可以被民眾檢舉，但有限制：{base['qualifier']}。"}
    return {**base, "status": "yes",
            "message": f"{label}屬於民眾可檢舉的項目。可以再確認檢舉是否超過 7 天、是否被重複舉發。"}
