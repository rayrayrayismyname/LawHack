"""期限提醒：產生 Google 行事曆連結與 .ics 行事曆檔。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode


def _d(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(d)


def google_link(title: str, due, details: str = "") -> str:
    """全天事件，日期為期限當天。"""
    d = _d(due)
    q = {"action": "TEMPLATE", "text": title,
         "dates": f"{d:%Y%m%d}/{d + timedelta(days=1):%Y%m%d}", "details": details}
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def make_ics(events: list[dict], uid_prefix: str) -> str:
    """events: [{"title", "due", "details"}]。每個期限前 3 天提醒。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ticket-appeal-ai//ZH-TW", "CALSCALE:GREGORIAN"]
    for i, e in enumerate(events):
        d = _d(e["due"])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid_prefix}-{i}@ticket-appeal-ai",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
            f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_esc(e['title'])}",
            f"DESCRIPTION:{_esc(e.get('details', ''))}",
            "BEGIN:VALARM", "TRIGGER:-P3D", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(e['title'])}", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
