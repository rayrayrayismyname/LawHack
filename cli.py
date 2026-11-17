"""命令列版本：讀入案例 JSON，輸出分析結果與 Word 文件。

用法：
    python cli.py samples/01_機車騎樓_民眾檢舉.json
    python cli.py samples/01_機車騎樓_民眾檢舉.json --out output/case1 --json
    LLM_PROVIDER=bedrock python cli.py samples/02_測速無警示.json --image ticket.jpg
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

from appeal.envfile import load_env

load_env()

from appeal import analyze, case_from_dict, write_all
from appeal.ai_steps import extract_ticket
from appeal.llm import get_llm
from appeal.models import STRONG, MEDIUM, PROCEDURE, INFO

TAG = {STRONG: "★ 明確瑕疵", MEDIUM: "◆ 可主張", PROCEDURE: "→ 程序", INFO: "? 待補充"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="罰單申訴通 CLI")
    ap.add_argument("case", help="案例 JSON 檔")
    ap.add_argument("--out", help="文件輸出資料夾（預設 output/<案例檔名>）")
    ap.add_argument("--image", help="罰單照片（需要 AI 模式）")
    ap.add_argument("--json", action="store_true", help="另外輸出 result.json")
    args = ap.parse_args(argv)

    data = json.loads(Path(args.case).read_text(encoding="utf-8"))
    llm = get_llm()

    if args.image:
        mime = mimetypes.guess_type(args.image)[0] or "image/jpeg"
        fields_, warns = extract_ticket(Path(args.image).read_bytes(), mime, llm)
        data.setdefault("ticket", {}).update(fields_)
        for w in warns:
            print("[辨識]", w)

    case = case_from_dict(data)
    res = analyze(case, llm)

    print(f"\n=== {Path(args.case).stem}  （AI：{llm.name}）===")
    print(f"評估：{res.assessment.level}｜{res.assessment.recommendation}")
    for f in res.findings:
        print(f"  {TAG[f.strength]}  {f.title}")
    for dl in res.deadlines:
        if dl.due:
            left = f"剩 {dl.days_left} 天" if dl.days_left >= 0 else f"已逾期 {-dl.days_left} 天"
            print(f"  期限｜{dl.label}：{dl.due}（{left}）")
    for w in res.warnings:
        print("  提醒｜" + w)

    out = Path(args.out or Path("output") / Path(args.case).stem)
    paths = write_all(res, out)
    if args.json:
        (out / "result.json").write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("輸出：", ", ".join(str(p) for p in paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
