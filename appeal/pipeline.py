"""主流程：罰單 + 立場 + 證據 → 檢核 → 評估 → 陳述意見書。"""
from __future__ import annotations

from typing import Optional

from . import knowledge_base as kb
from .ai_steps import analyze_statement, draft_facts, merge_facts
from .assessment import assess, compute_deadlines, next_steps
from .llm import LLM, NullLLM
from .models import Case, Facts, Result, STRONG, MEDIUM, PROCEDURE
from .parsing import parse_article


def build_letter(case: Case, findings, facts_text: str) -> dict:
    t = case.ticket
    usable = [f for f in findings if f.strength in (STRONG, MEDIUM)]
    agency = t.punish_agency or "處罰機關"
    ticket_desc = f"{t.ticket_no}號" if t.ticket_no else ""
    subject = (f"陳述人不服{t.agency or ''}{ticket_desc}舉發違反道路交通管理事件通知單之舉發事實，"
               f"依道路交通管理處罰條例第9條第1項規定，於法定期間內陳述意見，懇請撤銷原舉發，不予裁罰。")
    reasons = [f.argument for f in usable]
    evidence = [f"{e.name}" + (f"（{e.description}）" if e.description else "") for e in case.evidence]
    if not evidence:
        evidence = ["舉發違反道路交通管理事件通知單影本"]
    request = ("綜上所述，本件舉發" +
               ("於法未合" if any(f.strength == STRONG for f in usable) else "尚有疑義") +
               "，懇請貴機關詳予審酌，撤銷原舉發並不予裁罰，以維陳述人權益。")
    return {
        "title": "交通違規陳述意見書",
        "to": agency,
        "subject": subject,
        "facts": facts_text,
        "reasons": reasons,
        "evidence": evidence,
        "request": request,
        "basis_laws": sorted({k for f in usable for k in f.law_refs} | {"道交條例第9條"}),
    }


SPEEDING_REFS = {("40", None, None), ("43", 1, 2), ("33", 1, 1)}
SPEEDING_WORDS = ("超速", "時速", "速限", "最高速限")


def _facts_from_ticket(case: Case) -> None:
    """有些事實罰單上就寫了，不必等使用者說：例如這是一張超速罰單。使用者明確選「否」時不覆蓋。"""
    if case.facts.is_speeding is None:
        ref = parse_article(case.ticket.article)
        by_ref = ref is not None and ((ref.article, ref.para, ref.sub) in SPEEDING_REFS or ref.article == "40")
        by_text = any(w in (case.ticket.violation_fact or "") for w in SPEEDING_WORDS)
        if by_ref or by_text:
            case.facts.is_speeding = True
            case.facts.notes.append("依罰單內容判定為超速罰單。")


def analyze(case: Case, llm: Optional[LLM] = None, user_facts: Optional[Facts] = None,
            facts_confirmed: bool = False) -> Result:
    """執行完整分析。

    user_facts：使用者在表單明確勾選／填寫的事實，優先於 AI 整理結果。
    facts_confirmed：使用者已在網頁上逐項確認過事實，就不再呼叫 AI 重新整理（省一次 AI 呼叫）。
    """
    llm = llm or NullLLM()
    warnings: list[str] = []
    summary = None
    if facts_confirmed:
        case.facts = user_facts or case.facts
    else:
        ai_facts, summary, w = analyze_statement(case, llm)
        warnings += w
        case.facts = merge_facts(ai_facts, user_facts or case.facts)

    _facts_from_ticket(case)

    if case.ticket.article and parse_article(case.ticket.article) is None:
        warnings.append("違反法條格式無法解析，請輸入例如「第56條第1項第1款」的格式。")

    from .rules import run_rules
    findings = run_rules(case)
    assessment = assess(case, findings)
    deadlines = compute_deadlines(case)
    steps = next_steps(case, findings, assessment)

    facts_text, used, w = draft_facts(case, llm, findings)
    warnings += w
    letter = build_letter(case, findings, facts_text)
    if summary:
        letter["ai_summary"] = summary

    return Result(case=case, findings=findings, deadlines=deadlines, assessment=assessment,
                  steps=steps, letter=letter, warnings=warnings, llm_used=llm.available)


def law_details(keys) -> list[dict]:
    out = []
    for k in keys:
        d = kb.law(k)
        out.append({"key": k, **d})
    return out
