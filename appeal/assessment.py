"""申訴可行性評估（附加功能）與期限計算。

不輸出百分比，只輸出「高／中／低」與具體理由，避免讓使用者誤以為是精準預測。
"""
from __future__ import annotations

from datetime import date, timedelta

from . import knowledge_base as kb
from .models import (Case, Finding, Deadline, Assessment,
                     STRONG, MEDIUM, PROCEDURE, INFO)
from .parsing import parse_date, roc


def compute_deadlines(case: Case) -> list[Deadline]:
    today = case.today or date.today()
    out = []
    received = parse_date(case.ticket.received_date)
    due = parse_date(case.ticket.due_date)
    if received:
        d = received + timedelta(days=30)
        out.append(Deadline("陳述意見期限", d, (d - today).days, "道交條例第9條",
                            "收到通知單後30日內，向處罰機關陳述意見。"))
    if due:
        out.append(Deadline("應到案日期", due, (due - today).days, "通知單所載",
                            "陳述、繳納或歸責他人都應在此日前完成；逾期可能依裁罰基準加重罰鍰。"))
    if not received and not due:
        out.append(Deadline("陳述意見期限", None, None, "道交條例第9條",
                            "請輸入收到通知單的日期或應到案日期，系統才能計算剩餘天數。"))
    out.append(Deadline("行政訴訟期限", None, None, "道交條例第87條",
                        "若陳述後仍收到裁決書且不服，應於裁決書送達後30日內起訴。"))
    return out


def assess(case: Case, findings: list[Finding]) -> Assessment:
    strong = [f for f in findings if f.strength == STRONG]
    medium = [f for f in findings if f.strength == MEDIUM]
    procedure = [f for f in findings if f.strength == PROCEDURE]

    if strong:
        level, rec = "高", "建議申訴"
    elif medium:
        level, rec = "中", "可考慮申訴，請先補強證據"
    else:
        level, rec = "低", "建議繳納結案"
    if procedure:
        rec = "先辦理歸責實際駕駛人" + ("" if level == "低" else f"；若另有理由，{rec}")

    reasons = [f"【{'明確法律瑕疵' if f.strength == STRONG else '可主張理由'}】{f.title}：{f.reason}"
               for f in strong + medium]
    if not reasons:
        reasons.append("目前沒有找到明確的法律瑕疵或可主張的理由。若你認為罰單有誤，請補充更多經過或證據後再分析。")

    st = {s["id"]: s for s in kb.stats()["stats"]}
    base = (f"參考基準：{st['taichung_108']['label']}{st['taichung_108']['detail']}；"
            f"{st['taipei_tech_113']['label']}{st['taipei_tech_113']['detail']}。"
            "本評估依法規檢核結果分級，僅供參考，不代表個案結果。")

    t = case.ticket
    cost = []
    if t.fine:
        cost.append(f"罰鍰 {t.fine:,} 元" + (f"，記違規點數 {t.points} 點" if t.points else ""))
    cost.append("在期限內陳述意見不需要費用；陳述期間請留意應到案日期，避免逾期加重。")
    cost.append(f"若進入行政訴訟，第一審裁判費 {kb.stats()['court_fee_first_instance']} 元，由敗訴方負擔。")
    if level == "低" and not procedure:
        cost.append("沒有明確理由時提出申訴，通常只會增加往返時間，建議衡量後再決定。")
    if is_overdue(case):
        cost.insert(0, "應到案日期已過，逾期未處理可能依裁罰基準加重罰鍰，請盡快向處罰機關查詢案件狀態。")
    return Assessment(level, rec, reasons, base, cost)


def is_overdue(case: Case) -> bool:
    today = case.today or date.today()
    due = parse_date(case.ticket.due_date)
    received = parse_date(case.ticket.received_date)
    limit = due or (received + timedelta(days=30) if received else None)
    return bool(limit and limit < today)


OVERDUE_STEP = ("已超過應到案日期：陳述意見與歸責他人的期限可能都已經過了。請先向處罰機關（或監理服務網）查詢本案是否已經裁決；"
                "若已收到裁決書，且送達未滿30日，仍可向高等行政法院地方行政訴訟庭提起撤銷訴訟。")


def next_steps(case: Case, findings: list[Finding], assessment: Assessment) -> list[str]:
    steps = [OVERDUE_STEP] if is_overdue(case) else []
    agency = case.ticket.punish_agency or "通知單上「應到案處所」所載的處罰機關"
    if any(f.strength == PROCEDURE for f in findings):
        steps.append(f"在應到案日期前，向{agency}提出「歸責實際駕駛人」申請（使用該機關提供的申請書表），"
                     "附上實際駕駛人駕照、身分證影本與罰單。")
    infos = [f for f in findings if f.strength == INFO]
    for f in infos:
        for n in f.needs:
            steps.append(f"補充資訊：{n}")
    if assessment.level in ("高", "中"):
        steps.append("檢查並補齊下方「證據清單」中標示的證據。")
        steps.append("確認陳述意見書內容與事實相符後簽名。")
        steps.append(f"於期限內向{agency}提出陳述意見（多數機關提供線上陳述，也可郵寄或臨櫃）。")
        steps.append("保留送件紀錄（線上案件編號、掛號收據），等待機關查復或裁決。")
        steps.append("若收到裁決書仍不服，於送達後30日內向高等行政法院地方行政訴訟庭提起撤銷訴訟。")
    elif is_overdue(case):
        steps.append("若決定繳納，請盡快至監理服務網查詢應繳金額後繳納，避免移送強制執行。")
    else:
        steps.append("若決定繳納，請在應到案日期前繳納結案（可至監理服務網、超商或郵局）。")
    return steps
