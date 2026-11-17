"""產生 Word 文件：陳述意見書、申訴指引、歸責實際駕駛人申請書。

所有函式都吃「結果字典」（Result.to_dict() 的格式），這樣使用者在網頁上
編輯陳述意見書後，伺服器可以直接用存下來的 JSON 重新產生文件。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

from . import knowledge_base as kb
from .models import Result, STRONG, MEDIUM, PROCEDURE, INFO

FONT = "標楷體"
_NUM = "一二三四五六七八九十"
LETTER = "陳述意見書.docx"
GUIDE = "申訴指引.docx"
ATTRIBUTION = "歸責實際駕駛人申請書.docx"


def _doc() -> Document:
    d = Document()
    sec = d.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    st = d.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(13)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    st.paragraph_format.line_spacing = 1.4
    st.paragraph_format.space_after = Pt(4)
    return d


def _run(p, text, bold=False, size=None, color=None):
    r = p.add_run(text)
    r.bold = bold
    r.font.name = FONT
    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if size:
        r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return r


def _para(d, text="", bold=False, size=None, align=None, indent=0, first=0, color=None):
    p = d.add_paragraph()
    if text:
        _run(p, text, bold, size, color)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if indent:
        p.paragraph_format.left_indent = Pt(13 * indent)
    if first:
        p.paragraph_format.first_line_indent = Pt(13 * first)
    return p


def _set_cell(cell, text, bold=False):
    cell.text = ""
    _run(cell.paragraphs[0], text or "", bold)


def _cn(i: int) -> str:
    return _NUM[i] if i < len(_NUM) else str(i + 1)


def _today(r: dict) -> date:
    t = r["case"].get("today")
    return date.fromisoformat(t) if t else date.today()


def _date_line(d, today: date):
    _para(d, f"中華民國　{today.year - 1911}　年　{today.month}　月　{today.day}　日", align="right")


def _info_table(d, rows):
    tbl = d.add_table(rows=0, cols=4)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for a, b, e, f in rows:
        cells = tbl.add_row().cells
        _set_cell(cells[0], a, True)
        if e:
            _set_cell(cells[1], b)
            _set_cell(cells[2], e, True)
            _set_cell(cells[3], f)
        else:
            _set_cell(cells[1].merge(cells[3]), b)
    return tbl


# ---------------------------------------------------------------- 陳述意見書

def write_letter(r: dict, path: Path) -> Path:
    L, t, c = r["letter"], r["case"]["ticket"], r["case"]
    d = _doc()
    _para(d, L["title"], bold=True, size=20, align="center")
    _info_table(d, [
        ("陳述人姓名", c.get("applicant_name", ""), "身分證字號", ""),
        ("聯絡電話", c.get("applicant_phone", ""), "車牌號碼", t.get("plate", "")),
        ("通訊地址", c.get("applicant_address", ""), "", ""),
        ("通知單號", t.get("ticket_no", ""), "違規時間", t.get("violation_time", "")),
        ("違規地點", t.get("violation_place", ""), "", ""),
        ("違規事實", t.get("violation_fact", ""), "", ""),
        ("違反法條", t.get("article", ""), "", ""),
    ])
    _para(d)
    p = _para(d)
    _run(p, "主旨：", bold=True)
    _run(p, L["subject"])
    _para(d, "說明：", bold=True)
    _para(d, "一、事實經過", bold=True, indent=1)
    for chunk in [x for x in L["facts"].split("\n") if x.strip()]:
        _para(d, chunk.strip(), indent=2, first=2)
    i = 1
    if L["reasons"]:
        _para(d, f"{_cn(i)}、陳述理由", bold=True, indent=1)
        for j, x in enumerate(L["reasons"]):
            _para(d, f"（{_cn(j)}）{x}", indent=2)
        i += 1
    _para(d, f"{_cn(i)}、檢附證據", bold=True, indent=1)
    for j, e in enumerate(L["evidence"]):
        _para(d, f"附件{j + 1}：{e}", indent=2)
    i += 1
    _para(d, f"{_cn(i)}、請求事項", bold=True, indent=1)
    _para(d, L["request"], indent=2, first=2)
    _para(d)
    _para(d, "此致", indent=1)
    _para(d, L["to"])
    _para(d)
    _para(d, "陳述人：＿＿＿＿＿＿＿＿（簽章）", align="right")
    _date_line(d, _today(r))
    d.save(path)
    return path


# ---------------------------------------------------------------- 歸責申請書

def write_attribution(r: dict, path: Path) -> Path:
    t, c = r["case"]["ticket"], r["case"]
    agency = t.get("punish_agency") or "處罰機關"
    d = _doc()
    _para(d, "歸責實際駕駛人申請書", bold=True, size=20, align="center")
    _para(d, "（各處罰機關多有固定格式的申請書表，若機關網站有提供，請優先使用機關表單）",
          size=10, align="center", color="777777")
    _info_table(d, [
        ("通知單號", t.get("ticket_no", ""), "車牌號碼", t.get("plate", "")),
        ("違規時間", t.get("violation_time", ""), "應到案日期", t.get("due_date", "")),
        ("違規事實", t.get("violation_fact", ""), "", ""),
        ("原被通知人", c.get("applicant_name", ""), "身分證字號", ""),
        ("聯絡電話", c.get("applicant_phone", ""), "", ""),
        ("實際駕駛人", "", "身分證字號", ""),
        ("駕駛人電話", "", "駕照號碼", ""),
    ])
    _para(d)
    p = _para(d)
    _run(p, "主旨：", bold=True)
    _run(p, f"本人所有車號{t.get('plate', '')}之車輛，於通知單號{t.get('ticket_no', '')}所載違規時間，"
            "實際駕駛人另有其人，依道路交通管理處罰條例第85條規定，申請歸責實際駕駛人，請查照。")
    _para(d, "說明：", bold=True)
    _para(d, "一、本案違規當時駕駛人確屬＿＿＿＿＿＿駕駛無訛，請依規定另行通知應歸責人到案處理。", indent=1)
    _para(d, "二、隨文檢附下列文件：", indent=1)
    for j, x in enumerate(["舉發違反道路交通管理事件通知單及採證照片", "原被通知人身分證正反面影本",
                           "實際駕駛人駕駛執照或身分證正反面影本", "其他佐證資料（如借用、租賃證明）"]):
        _para(d, f"（{_cn(j)}）{x}", indent=2)
    _para(d, "三、本人知悉明知為不實之事項而使公務員登載於公文書，可能涉及刑事責任，所填內容均屬實。", indent=1)
    _para(d)
    _para(d, "此致", indent=1)
    _para(d, agency)
    _para(d)
    _para(d, "原被通知人：＿＿＿＿＿＿＿＿（簽章）", align="right")
    _para(d, "實際駕駛人：＿＿＿＿＿＿＿＿（簽章）", align="right")
    _date_line(d, _today(r))
    d.save(path)
    return path


# ---------------------------------------------------------------- 申訴指引

_LEVEL_COLOR = {"高": "1E7B34", "中": "B7791F", "低": "8A8A8A"}
_STRENGTH = {STRONG: "明確法律瑕疵", MEDIUM: "可主張理由", PROCEDURE: "應辦理程序", INFO: "待補充資訊"}


def write_guide(r: dict, path: Path) -> Path:
    a, t = r["assessment"], r["case"]["ticket"]
    d = _doc()
    _para(d, "罰單申訴指引", bold=True, size=20, align="center")
    _para(d, f"通知單 {t.get('ticket_no') or '（未填）'}｜{t.get('violation_fact') or ''}",
          align="center", color="555555")

    _para(d, "一、申訴可行性評估（參考）", bold=True, size=15)
    p = _para(d)
    _run(p, "評估等級：")
    _run(p, a["level"], bold=True, size=16, color=_LEVEL_COLOR.get(a["level"]))
    _run(p, f"　　建議：{a['recommendation']}", bold=True)
    for x in a["reasons"]:
        _para(d, "• " + x, indent=1)
    _para(d, a["base_rate_note"], size=11, color="555555")
    for x in a["cost_note"]:
        _para(d, "• " + x, indent=1)

    _para(d, "二、檢核結果與法令依據", bold=True, size=15)
    if not r["findings"]:
        _para(d, "沒有找到可主張的理由。", indent=1)
    for f in r["findings"]:
        p = _para(d, indent=1)
        _run(p, f"［{_STRENGTH[f['strength']]}］{f['title']}", bold=True)
        _para(d, f["reason"], indent=2)
        for k in f["law_refs"]:
            _para(d, f"依據：{k}－{kb.law(k)['summary']}", indent=2, size=11, color="555555")

    _para(d, "三、重要期限", bold=True, size=15)
    for dl in r["deadlines"]:
        if dl["due"]:
            dd = date.fromisoformat(dl["due"])
            left = dl["days_left"]
            tag = f"（剩 {left} 天）" if left is not None and left >= 0 else "（已逾期）"
            _para(d, f"• {dl['label']}：{dd.year - 1911}年{dd.month}月{dd.day}日{tag}－{dl['note']}", indent=1)
        else:
            _para(d, f"• {dl['label']}：{dl['note']}", indent=1)

    _para(d, "四、下一步", bold=True, size=15)
    for j, s in enumerate(r["steps"]):
        _para(d, f"{j + 1}. {s}", indent=1)

    _para(d, "五、證據清單", bold=True, size=15)
    for e in r["letter"]["evidence"]:
        _para(d, "☑ " + e, indent=1)
    needs = [n for f in r["findings"] if f["strength"] in (STRONG, MEDIUM, PROCEDURE) for n in f["needs"]]
    for n in dict.fromkeys(needs):
        _para(d, "☐ 建議補充：" + n, indent=1)

    if r.get("warnings"):
        _para(d, "六、系統提醒", bold=True, size=15)
        for w in r["warnings"]:
            _para(d, "• " + w, indent=1)

    _para(d)
    _para(d, "本文件由「罰單申訴通」依使用者提供之資料與法規知識庫自動產生，僅供參考，不構成法律意見。"
             "法規以全國法規資料庫最新公告為準；如有疑問，請洽處罰機關或法律扶助基金會（412-8518）。",
          size=10, color="777777")
    d.save(path)
    return path


def write_all(res, out_dir: Path) -> dict:
    """res 可以是 Result 物件或其 to_dict() 字典。"""
    r = res.to_dict() if isinstance(res, Result) else res
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {"guide": write_guide(r, out_dir / GUIDE)}
    # 沒有可主張的理由時不產生陳述意見書，避免鼓勵無理由申訴
    if r["letter"]["reasons"]:
        out["letter"] = write_letter(r, out_dir / LETTER)
    if any(f["strength"] == PROCEDURE for f in r["findings"]):
        out["attribution"] = write_attribution(r, out_dir / ATTRIBUTION)
    return out
