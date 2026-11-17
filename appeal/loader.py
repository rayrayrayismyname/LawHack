"""把 JSON／表單資料轉成 Case 物件。"""
from __future__ import annotations

from dataclasses import fields
from typing import Any

from .models import Case, Evidence, Facts, Ticket
from .parsing import normalize_vehicle, parse_date


def _pick(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in (data or {}).items() if k in names}


def case_from_dict(data: dict[str, Any]) -> Case:
    ticket = Ticket(**_pick(Ticket, data.get("ticket", {})))
    ticket.vehicle_type = normalize_vehicle(ticket.vehicle_type)
    facts = Facts(**_pick(Facts, data.get("facts", {})))
    evidence = [Evidence(**_pick(Evidence, e)) if isinstance(e, dict) else Evidence(name=str(e))
                for e in data.get("evidence", [])]
    applicant = data.get("applicant", {})
    return Case(
        ticket=ticket,
        statement=data.get("statement", ""),
        evidence=evidence,
        facts=facts,
        applicant_name=applicant.get("name", ""),
        applicant_phone=applicant.get("phone", ""),
        applicant_address=applicant.get("address", ""),
        today=parse_date(data.get("today")),
    )
