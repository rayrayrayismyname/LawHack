"""資料結構：罰單、使用者陳述、檢核結果、評估結果。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


# 舉發方式
SOURCE_STOP = "員警攔停"
SOURCE_DIRECT = "逕行舉發"
SOURCE_CITIZEN = "民眾檢舉"
SOURCE_CAMERA = "科技執法"
SOURCES = [SOURCE_STOP, SOURCE_DIRECT, SOURCE_CITIZEN, SOURCE_CAMERA]


@dataclass
class Ticket:
    """罰單（舉發違反道路交通管理事件通知單）上的欄位。"""
    ticket_no: str = ""
    plate: str = ""
    vehicle_type: str = ""            # 汽車 / 機車 / 大型車
    violation_time: str = ""          # 原始字串，例如 115/11/03 08:12
    violation_place: str = ""
    violation_fact: str = ""          # 違規事實，例如「在人行道停車」
    article: str = ""                 # 違反法條，例如「道路交通管理處罰條例第56條第1項第1款」
    fine: Optional[int] = None        # 罰鍰（元）
    points: Optional[int] = None      # 記違規點數
    source: str = ""                  # 舉發方式（見 SOURCES）
    agency: str = ""                  # 舉發單位
    punish_agency: str = ""           # 處罰機關／應到案處所
    due_date: str = ""                # 應到案日期
    received_date: str = ""           # 收到通知單日期（使用者填）


@dataclass
class Facts:
    """從使用者陳述與證據整理出的、規則引擎要用的事實。
    None 表示「不知道」，規則遇到 None 會改提示使用者補充，而不是自行假設。"""
    report_date: Optional[str] = None          # 民眾檢舉日期（若知道）
    location_type: Optional[str] = None        # 人行道 / 行人穿越道 / 騎樓 / 一般道路 ...
    behavior: Optional[str] = None             # 補充違規態樣，例如「不依順行方向」
    repeat_ticket_times: list[str] = field(default_factory=list)  # 同一檢舉、同一規定的其他罰單時間
    crossed_intersection: Optional[bool] = None
    is_speeding: Optional[bool] = None
    road_type: Optional[str] = None            # 一般道路 / 高速公路 / 快速公路
    sign_present: Optional[bool] = None        # 是否有測速警示標誌
    sign_distance_m: Optional[float] = None    # 測速警示標誌與測速點距離（公尺）
    plate_mismatch: Optional[bool] = None      # 照片車牌、車種與本人車輛不符
    evidence_unclear: Optional[bool] = None    # 採證影像無法辨識車牌或違規事實
    sign_obscured: Optional[bool] = None       # 標誌標線遭遮蔽、不清或設置不當
    emergency: Optional[bool] = None           # 為避免緊急危難（讓救護車、閃避危險等）
    not_driver: Optional[bool] = None          # 違規時駕駛人並非收到罰單的人
    notes: list[str] = field(default_factory=list)  # 分析過程中的補充說明


@dataclass
class Evidence:
    name: str
    description: str = ""
    path: str = ""


@dataclass
class Case:
    ticket: Ticket
    statement: str = ""               # 使用者用白話寫的經過與立場
    evidence: list[Evidence] = field(default_factory=list)
    facts: Facts = field(default_factory=Facts)
    applicant_name: str = ""
    applicant_phone: str = ""
    applicant_address: str = ""
    today: Optional[date] = None      # 測試時可固定日期


# 檢核結果的強度
STRONG = "strong"      # 有明確法律依據、足以構成不得舉發或撤銷的瑕疵
MEDIUM = "medium"      # 有可主張的理由，但需證據支持、由機關審酌
PROCEDURE = "procedure"  # 不是撤銷理由，而是應走另一個程序（例如歸責他人）
INFO = "info"          # 需要使用者補充資訊才能判斷


@dataclass
class Finding:
    rule_id: str
    title: str
    strength: str
    reason: str                      # 給使用者看的白話說明
    argument: str                    # 寫進陳述意見書的論述
    law_refs: list[str] = field(default_factory=list)  # 對應 laws.json 的鍵
    needs: list[str] = field(default_factory=list)     # 建議補充的證據


@dataclass
class Deadline:
    label: str
    due: Optional[date]
    days_left: Optional[int]
    basis: str
    note: str = ""


@dataclass
class Assessment:
    level: str                 # 高 / 中 / 低
    recommendation: str        # 建議申訴 / 可考慮申訴 / 建議繳納
    reasons: list[str]
    base_rate_note: str
    cost_note: list[str]


@dataclass
class Result:
    case: Case
    findings: list[Finding]
    deadlines: list[Deadline]
    assessment: Assessment
    steps: list[str]
    letter: dict                       # 陳述意見書各段文字
    warnings: list[str] = field(default_factory=list)
    llm_used: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        for dl in d["deadlines"]:
            if dl["due"] is not None:
                dl["due"] = dl["due"].isoformat()
        if d["case"]["today"] is not None:
            d["case"]["today"] = d["case"]["today"].isoformat()
        return d
