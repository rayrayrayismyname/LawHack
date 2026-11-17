"""網頁伺服器的測試（不需要啟動伺服器）。"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def sample(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def test_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/?sample=03_標誌被樹遮蔽").status_code == 200
    assert client.get("/healthz").get_json()["status"] == "ok"


def test_article_lookup(client):
    r = client.post("/api/check-article", json={"article": "56-1-1", "vehicle_type": "機車"}).get_json()
    assert r["status"] == "no"
    r = client.post("/api/check-article", json={"article": "第53條第1項"}).get_json()
    assert r["status"] == "yes"


def test_facts_keywords(client):
    r = client.post("/api/facts", json={"statement": "那天車借給朋友騎，不是我騎的"}).get_json()
    assert r["facts"]["not_driver"] is True and r["source"] == "keywords"


def test_extract_without_ai(client):
    assert client.post("/api/extract").get_json()["ai"] is False


def test_api_analyze_and_downloads(client):
    r = client.post("/api/analyze", json=sample("05_車借朋友騎")).get_json()
    assert "attribution" in r["downloads"] and "letter" not in r["downloads"]
    rid = r["id"]
    assert client.get(f"/result/{rid}").status_code == 200
    assert client.get(f"/download/{rid}/attribution").status_code == 200
    ics = client.get(f"/download/{rid}/ics")
    assert ics.status_code == 200 and b"BEGIN:VCALENDAR" in ics.data


def test_edit_letter_warns_on_unverified_article(client):
    rid = client.post("/api/analyze", json=sample("01_機車騎樓_民眾檢舉")).get_json()["id"]
    r = client.post(f"/result/{rid}/letter", json={"facts": "依刑法第185條", "reasons": ["理由"],
                                                   "evidence": ["照片"], "request": "請撤銷"}).get_json()
    assert r["ok"] and "185" in r["warnings"][0]
    assert client.get(f"/download/{rid}/letter").status_code == 200


def test_form_confirmed_facts_override(client):
    form = {"source": "民眾檢舉", "article": "第56條第1項第1款", "vehicle_type": "汽車",
            "violation_time": "115/11/02 09:30", "received_date": "115/11/10",
            "statement": "照片不是我的車", "facts_confirmed": "1", "plate_mismatch": "no",
            "location_type": "人行道"}
    loc = client.post("/analyze", data=form).headers["Location"]
    page = client.get(loc).get_data(as_text=True)
    assert "採證照片中的車輛不是本人車輛" not in page


def test_bad_ids_are_404(client):
    assert client.get("/result/../../etc").status_code == 404
    assert client.get("/download/0123456789abcdef/letter").status_code == 404
    assert client.get("/download/zz/letter").status_code == 404
