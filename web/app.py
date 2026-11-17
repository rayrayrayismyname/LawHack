"""罰單申訴通 網頁伺服器（Flask）。

本機開發：  python web/app.py
正式部署：  gunicorn -c deploy/gunicorn.conf.py wsgi:app   （詳見 docs/部署指南.md）
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from flask import (Flask, Response, abort, jsonify, redirect, render_template, request,
                   send_file, url_for)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from appeal.envfile import load_env  # noqa: E402

load_env()  # 讀取專案根目錄的 .env（AI 金鑰等設定）

from appeal import analyze, case_from_dict  # noqa: E402
from appeal import knowledge_base as kb  # noqa: E402
from appeal.ai_steps import analyze_statement, extract_ticket  # noqa: E402
from appeal.calendar_links import google_link, make_ics  # noqa: E402
from appeal.documents import ATTRIBUTION, GUIDE, LETTER, write_all, write_letter  # noqa: E402
from appeal.llm import get_llm  # noqa: E402
from appeal.models import SOURCES, STRONG, MEDIUM, PROCEDURE, INFO  # noqa: E402
from appeal.parsing import find_article_numbers, parse_article  # noqa: E402
from appeal.rules import reportability  # noqa: E402

TICKET_FIELDS = ["ticket_no", "plate", "vehicle_type", "violation_time", "violation_place",
                 "violation_fact", "article", "fine", "points", "source", "agency",
                 "punish_agency", "received_date", "due_date"]
FACT_FIELDS = ["report_date", "location_type", "behavior", "repeat_ticket_times", "crossed_intersection",
               "is_speeding", "road_type", "sign_present", "sign_distance_m", "plate_mismatch",
               "evidence_unclear", "sign_obscured", "emergency", "not_driver"]
RID_RE = re.compile(r"^[0-9a-f]{16}$")
FILES = {"letter": LETTER, "guide": GUIDE, "attribution": ATTRIBUTION}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class RateLimiter:
    """簡單的每 IP 每分鐘次數限制，保護 AI 呼叫的費用。"""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def _client_ip() -> str:
    # 部署在反向代理（Caddy／nginx）後面時，設定 TRUST_PROXY=1，remote_addr 才會是真實 IP
    return request.remote_addr or "?"


def _to_bool(v):
    if isinstance(v, bool) or v is None:
        return v
    return {"yes": True, "true": True, "1": True, "on": True, "no": False, "false": False, "0": False}.get(
        str(v).lower())


def clean_facts(raw: dict) -> dict:
    """把表單或 API 傳來的事實整理成規則引擎要的型別。空值一律視為「不知道」。"""
    out = {}
    for k in FACT_FIELDS:
        v = raw.get(k)
        if v in (None, ""):
            continue
        if k in ("crossed_intersection", "is_speeding", "sign_present", "plate_mismatch",
                 "evidence_unclear", "sign_obscured", "emergency", "not_driver"):
            v = _to_bool(v)
        elif k == "sign_distance_m":
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        elif k == "repeat_ticket_times":
            v = [s.strip() for s in (v if isinstance(v, list) else str(v).splitlines()) if s.strip()]
        if v is not None:
            out[k] = v
    return out


def create_app() -> Flask:
    app = Flask(__name__)
    if os.getenv("TRUST_PROXY", "0") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        OUTPUT_DIR=Path(os.getenv("OUTPUT_DIR", ROOT / "output" / "web")),
        OUTPUT_TTL_HOURS=float(os.getenv("OUTPUT_TTL_HOURS", "24")),
    )
    out_dir: Path = app.config["OUTPUT_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        llm = get_llm()
    except ImportError as e:  # 設定了 AI 但沒裝套件時，不要讓整個網站起不來
        print(f"[警告] AI 套件 {e.name} 未安裝，改用示範模式。請執行 pip install -r requirements-ai.txt")
        from appeal.llm import NullLLM
        llm = NullLLM()
    limiter = RateLimiter(int(os.getenv("AI_RATE_PER_MINUTE", "20")))
    samples_dir = ROOT / "samples"
    state = {"last_cleanup": 0.0}

    # ------------------------------------------------------------ 共用

    def cleanup():
        """刪除超過保存時間的結果，避免個資留在伺服器上。最多每 10 分鐘執行一次。"""
        now = time.time()
        if now - state["last_cleanup"] < 600:
            return
        state["last_cleanup"] = now
        ttl = app.config["OUTPUT_TTL_HOURS"] * 3600
        for p in out_dir.iterdir():
            if p.is_dir() and RID_RE.match(p.name) and now - p.stat().st_mtime > ttl:
                shutil.rmtree(p, ignore_errors=True)

    def result_dir(rid: str) -> Path:
        if not RID_RE.match(rid):
            abort(404)
        p = out_dir / rid
        if not (p / "result.json").exists():
            abort(404)
        return p

    def load_result(rid: str) -> dict:
        return json.loads((result_dir(rid) / "result.json").read_text(encoding="utf-8"))

    def save_result(rid: str, r: dict):
        (out_dir / rid / "result.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")

    def run_case(data: dict, warnings=None, facts_confirmed=False) -> str:
        res = analyze(case_from_dict(data), llm, facts_confirmed=facts_confirmed)
        res.warnings = (warnings or []) + res.warnings
        rid = uuid.uuid4().hex[:16]
        write_all(res, out_dir / rid)
        save_result(rid, res.to_dict())
        return rid

    def ai_guard():
        if not limiter.allow(_client_ip()):
            return jsonify({"error": "操作太頻繁，請一分鐘後再試。"}), 429
        return None

    @app.before_request
    def _before():
        cleanup()

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.context_processor
    def _ctx():
        return {"ai_on": llm.available, "ai_name": llm.name}

    # ------------------------------------------------------------ 頁面

    @app.get("/")
    def index():
        samples = sorted(p.stem for p in samples_dir.glob("*.json"))
        data = {}
        name = request.args.get("sample")
        if name in samples:
            data = json.loads((samples_dir / f"{name}.json").read_text(encoding="utf-8"))
        return render_template("index.html", d=data, samples=samples, sources=SOURCES)

    @app.post("/analyze")
    def do_analyze():
        form = request.form
        ticket = {k: form.get(k, "").strip() for k in TICKET_FIELDS}
        for k in ("fine", "points"):
            ticket[k] = int(ticket[k]) if ticket[k].isdigit() else None
        facts = clean_facts(form)
        evidence = []
        for line in form.get("evidence_text", "").splitlines():
            if line.strip():
                name, _, desc = line.strip().partition("：")
                evidence.append({"name": name.strip(), "description": desc.strip()})
        data = {"ticket": ticket, "statement": form.get("statement", ""), "facts": facts,
                "evidence": evidence,
                "applicant": {"name": form.get("applicant_name", ""), "phone": form.get("applicant_phone", ""),
                              "address": form.get("applicant_address", "")}}
        warnings = [w for w in form.get("client_warnings", "").split("\n") if w.strip()]
        confirmed = form.get("facts_confirmed") == "1"
        return redirect(url_for("result", rid=run_case(data, warnings, confirmed)))

    @app.get("/result/<rid>")
    def result(rid):
        r = load_result(rid)
        d = result_dir(rid)
        files = {k: (d / v).exists() for k, v in FILES.items()}
        cal = []
        for dl in r["deadlines"]:
            if dl["due"]:
                title = f"罰單{dl['label']}（{r['case']['ticket'].get('ticket_no') or '交通罰單'}）"
                cal.append({**dl, "google": google_link(title, dl["due"], dl["note"])})
        return render_template("result.html", r=r, rid=rid, files=files, cal=cal, laws=kb.laws(),
                               STRONG=STRONG, MEDIUM=MEDIUM, PROCEDURE=PROCEDURE, INFO=INFO)

    @app.post("/result/<rid>/letter")
    def update_letter(rid):
        """使用者在網頁上修改陳述意見書後，重新產生 Word 檔。"""
        r = load_result(rid)
        body = request.get_json(force=True, silent=True) or {}
        L = r["letter"]
        if isinstance(body.get("facts"), str):
            L["facts"] = body["facts"].strip()[:3000]
        if isinstance(body.get("reasons"), list):
            L["reasons"] = [str(x).strip()[:2000] for x in body["reasons"] if str(x).strip()][:10]
        if isinstance(body.get("evidence"), list):
            L["evidence"] = [str(x).strip()[:200] for x in body["evidence"] if str(x).strip()][:20]
        if isinstance(body.get("request"), str) and body["request"].strip():
            L["request"] = body["request"].strip()[:1000]
        L["edited"] = True
        # 提醒：使用者自行加入的法條，系統沒有檢核過
        allowed = {"9"} | {kb.law(k)["article"] for f in r["findings"] for k in f["law_refs"]}
        ref = parse_article(r["case"]["ticket"].get("article", ""))
        if ref:
            allowed.add(ref.article)
        text = L["facts"] + "".join(L["reasons"]) + L["request"]
        extra = sorted(find_article_numbers(text) - allowed)
        warnings = [f"你加入了系統沒有檢核過的法條（第{'、'.join(extra)}條），請自行確認內容正確。"] if extra else []
        save_result(rid, r)
        if L["reasons"]:
            write_letter(r, result_dir(rid) / LETTER)
        return jsonify({"ok": True, "warnings": warnings})

    @app.get("/download/<rid>/<kind>")
    def download(rid, kind):
        d = result_dir(rid)
        if kind == "ics":
            r = load_result(rid)
            events = [{"title": f"罰單{dl['label']}", "due": dl["due"], "details": dl["note"]}
                      for dl in r["deadlines"] if dl["due"] and dl["days_left"] >= 0]
            if not events:
                abort(404)
            return Response(make_ics(events, rid), mimetype="text/calendar",
                            headers={"Content-Disposition": "attachment; filename=ticket-deadlines.ics"})
        if kind not in FILES or not (d / FILES[kind]).exists():
            abort(404)
        return send_file(d / FILES[kind], as_attachment=True, download_name=FILES[kind])

    # ------------------------------------------------------------ API

    @app.post("/api/extract")
    def api_extract():
        """上傳罰單照片 → AI 辨識欄位。"""
        if not llm.available:
            return jsonify({"fields": {}, "warnings": ["目前未啟用 AI，請手動輸入罰單欄位。"], "ai": False})
        blocked = ai_guard()
        if blocked:
            return blocked
        f = request.files.get("image")
        if not f or f.mimetype not in IMAGE_TYPES:
            return jsonify({"error": "請上傳 JPG、PNG 或 WEBP 格式的罰單照片。"}), 400
        fields, warnings = extract_ticket(f.read(), f.mimetype, llm)
        return jsonify({"fields": fields, "warnings": warnings, "ai": True})

    @app.post("/api/facts")
    def api_facts():
        """白話陳述 → 規則引擎要的事實（給使用者確認）。"""
        body = request.get_json(force=True, silent=True) or {}
        if llm.available:
            blocked = ai_guard()
            if blocked:
                return blocked
        case = case_from_dict({"ticket": body.get("ticket", {}), "statement": body.get("statement", ""),
                               "evidence": body.get("evidence", [])})
        facts, summary, warnings = analyze_statement(case, llm)
        d = {k: getattr(facts, k) for k in FACT_FIELDS}
        return jsonify({"facts": {k: v for k, v in d.items() if v not in (None, [], "")},
                        "summary": summary, "warnings": warnings,
                        "source": "ai" if llm.available else "keywords"})

    @app.post("/api/check-article")
    def api_check_article():
        body = request.get_json(force=True, silent=True) or {}
        return jsonify(reportability(str(body.get("article", ""))[:100], str(body.get("vehicle_type", "")),
                                     body.get("location_type") or None))

    @app.post("/api/analyze")
    def api_analyze():
        """JSON API：輸入格式與 samples/*.json 相同。"""
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "請傳入 JSON 物件"}), 400
        data["facts"] = clean_facts(data.get("facts", {}))
        rid = run_case(data)
        r = load_result(rid)
        r["id"] = rid
        r["result_url"] = url_for("result", rid=rid, _external=True)
        r["downloads"] = {k: url_for("download", rid=rid, kind=k, _external=True)
                          for k, v in FILES.items() if (out_dir / rid / v).exists()}
        return jsonify(r)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "ai": llm.name})

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               msg="找不到這份結果。結果只保存一段時間，過期會自動刪除，請重新分析。"), 404

    @app.errorhandler(413)
    def too_large(_):
        return jsonify({"error": "檔案太大，請壓縮照片後再上傳。"}), 413

    return app


app = create_app()

if __name__ == "__main__":
    print(f"AI 模式：{os.getenv('LLM_PROVIDER', 'none')}　→ http://127.0.0.1:{os.getenv('PORT', '5000')}")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False)
