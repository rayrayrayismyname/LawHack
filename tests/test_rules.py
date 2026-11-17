"""規則引擎與防幻覺檢查的測試。執行：python -m pytest -q"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from appeal import analyze, case_from_dict  # noqa: E402
from appeal import knowledge_base as kb  # noqa: E402
from appeal.ai_steps import check_draft, heuristic_facts  # noqa: E402
from appeal.llm import LLM, extract_json  # noqa: E402
from appeal.models import STRONG, MEDIUM, PROCEDURE, INFO  # noqa: E402
from appeal.parsing import parse_article, parse_date, cn_to_int, ArticleRef  # noqa: E402


def load(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def ids(res, strength=None):
    return {f.rule_id for f in res.findings if strength is None or f.strength == strength}


# ---------------------------------------------------------------- 解析

@pytest.mark.parametrize("text,expected", [
    ("道路交通管理處罰條例第56條第1項第1款", ArticleRef("56", 1, 1)),
    ("第三十一條之一第一項", ArticleRef("31-1", 1, None)),
    ("第五十三條第一項", ArticleRef("53", 1, None)),
    ("第42條", ArticleRef("42", None, None)),
    ("56-1-1", ArticleRef("56", 1, 1)),
    ("道路交通管理處罰條例第40條第0項00款", ArticleRef("40", None, None)),   # 罰單常見印法
])
def test_parse_article(text, expected):
    assert parse_article(text) == expected


def test_cn_numbers():
    assert cn_to_int("五十六") == 56 and cn_to_int("十") == 10 and cn_to_int("一百零二") == 102


def test_parse_roc_date():
    assert str(parse_date("115/11/03 08:12")) == "2026-11-03"
    assert str(parse_date("115年11月3日")) == "2026-11-03"
    assert str(parse_date("2026-11-03")) == "2026-11-03"


@pytest.mark.parametrize("ref,status", [
    (ArticleRef("53", 1, None), "yes"),        # 闖紅燈：可檢舉
    (ArticleRef("40", None, None), "no"),      # 一般超速：不在表列
    (ArticleRef("56", 1, 1), "yes"),           # 人行道停車：可檢舉但有限制
    (ArticleRef("56", 1, 2), "no"),            # 其他違停態樣：不可檢舉
    (ArticleRef("56", None, None), "uncertain"),
    (ArticleRef("33", 1, 5), "no"),
    (ArticleRef("33", 1, 12), "yes"),
])
def test_reportable(ref, status):
    assert kb.match_reportable(ref)[0] == status


# ---------------------------------------------------------------- 範例案例

def test_case01_motorcycle_and_overdue():
    res = analyze(case_from_dict(load("01_機車騎樓_民眾檢舉")))
    assert {"R01", "R02"} <= ids(res, STRONG)
    assert res.assessment.level == "高"


def test_case02_speed_sign_distance():
    res = analyze(case_from_dict(load("02_測速警示距離不足")))
    assert "R04" in ids(res, STRONG)
    assert res.case.facts.sign_distance_m == 60


def test_case03_obscured_sign():
    res = analyze(case_from_dict(load("03_標誌被樹遮蔽")))
    assert "R07" in ids(res, MEDIUM) and res.assessment.level == "中"


def test_case04_valid_ticket_recommends_paying():
    res = analyze(case_from_dict(load("04_闖紅燈證據明確")))
    assert not ids(res, STRONG) and not ids(res, MEDIUM)
    assert res.assessment.level == "低" and res.letter["reasons"] == []


def test_case05_not_driver_is_procedure():
    res = analyze(case_from_dict(load("05_車借朋友騎")))
    assert "R09" in ids(res, PROCEDURE)
    assert "歸責" in res.assessment.recommendation


def test_case06_repeat_within_six_minutes():
    res = analyze(case_from_dict(load("06_方向燈重複舉發")))
    assert "R03" in ids(res, STRONG)


def test_not_citizen_report_skips_reportable_rule():
    d = load("01_機車騎樓_民眾檢舉")
    d["ticket"]["source"] = "員警攔停"
    res = analyze(case_from_dict(d))
    assert "R01" not in ids(res) and "R02" not in ids(res)


def test_report_within_seven_days_is_fine():
    d = load("01_機車騎樓_民眾檢舉")
    d["facts"]["report_date"] = "115/11/05"
    assert "R02" not in ids(analyze(case_from_dict(d)), STRONG)


def test_highway_distance_range():
    d = load("02_測速警示距離不足")
    d["statement"] = "在國道上被測速，警示標誌距離大約500公尺。"
    res = analyze(case_from_dict(d))
    assert "R04" not in ids(res, STRONG)          # 高速公路 300～1000 公尺內，合法


# ---------------------------------------------------------------- 防幻覺

def test_check_draft_rejects_unverified_article():
    case = case_from_dict(load("03_標誌被樹遮蔽"))
    res = analyze(case)
    bad = "緣陳述人行經路口，依道路交通管理處罰條例第99條規定應不予處罰。" * 2
    assert any("未經確認的法條" in p for p in check_draft(bad, case, res.findings))


def test_check_draft_rejects_invented_numbers():
    case = case_from_dict(load("03_標誌被樹遮蔽"))
    res = analyze(case)
    bad = "緣陳述人於當日以時速45公里行經路口，標誌遭樹枝遮蔽，陳述人無從辨識。" * 2
    assert any("數字" in p for p in check_draft(bad, case, res.findings))


class FakeLLM(LLM):
    """模擬 AI：故意在事實經過中亂引法條，系統應退回範本文字。"""
    name, available = "fake", True

    def complete(self, system, user, images=None, max_tokens=2000):
        if "只輸出 JSON" in system:
            return '```json\n{"sign_obscured": true, "location_type": "路口", "summary": "測試"}\n```'
        return "緣陳述人行經路口，依刑法第185條，標誌遭遮蔽故不應處罰，請貴機關撤銷。"


def test_fake_llm_falls_back_to_template():
    res = analyze(case_from_dict(load("03_標誌被樹遮蔽")), FakeLLM())
    assert res.letter["facts"].startswith("緣陳述人於")
    assert any("未通過檢查" in w for w in res.warnings)
    assert "R07" in ids(res, MEDIUM)


def test_extract_json():
    assert extract_json('說明 {"a": 1} 結尾') == {"a": 1}


def test_heuristics_do_not_invent_facts():
    f = heuristic_facts("那天趕時間闖紅燈。")
    assert f.plate_mismatch is None and f.not_driver is None and f.location_type is None


# ---------------------------------------------------------------- 真實罰單（航警局測速單）

def test_real_speeding_ticket_is_detected_and_overdue():
    d = load("07_航警測速_真實罰單")
    res = analyze(case_from_dict(d))
    assert res.case.ticket.vehicle_type == "汽車"          # 自小客(貨) → 汽車
    assert res.case.facts.is_speeding is True              # 從罰單判斷為超速單
    assert "R04" in ids(res, INFO)                         # 提醒確認測速警示標誌
    assert res.steps[0].startswith("已超過應到案日期")      # 期限已過的處理


def test_speed_ticket_without_sign_is_strong():
    d = load("07_航警測速_真實罰單")
    d["statement"] = "測速照相前面沒有警示標誌。"
    d["today"] = "101/11/12"
    res = analyze(case_from_dict(d))
    assert "R04" in ids(res, STRONG) and res.assessment.level == "高"
    assert not res.steps[0].startswith("已超過")


def test_normalize_vehicle():
    from appeal.parsing import normalize_vehicle as n
    assert n("自小客(貨)") == "汽車" and n("普重機") == "機車" and n("大貨車") == "大型車" and n("機車") == "機車"
