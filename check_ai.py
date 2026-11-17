"""Demo 前檢查 AI 是否連得上。

用法：
    python check_ai.py                      # 測試文字
    python check_ai.py 罰單照片.jpg          # 再測試罰單照片辨識
"""
from __future__ import annotations

import json
import mimetypes
import sys
import time
from pathlib import Path

from appeal.envfile import load_env

load_env()

from appeal.ai_steps import extract_ticket  # noqa: E402
from appeal.llm import get_llm  # noqa: E402


def main() -> int:
    try:
        llm = get_llm()
    except ImportError as e:
        print(f"✗ 缺少套件：{e.name}。請執行 pip install -r requirements-ai.txt")
        return 1
    if not llm.available:
        print("✗ 目前是離線模式（LLM_PROVIDER=none）。請在 .env 設定 LLM_PROVIDER 與金鑰。")
        return 1
    print(f"AI 服務：{llm.name}")
    t = time.time()
    try:
        out = llm.complete("你是測試助手。", "請只回覆兩個字：正常", max_tokens=20)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 呼叫失敗：{e}")
        print("  常見原因：金鑰錯誤或沒額度、模型名稱打錯、Bedrock 尚未開通該模型或區域不對。")
        return 1
    print(f"✓ 文字測試成功（{time.time() - t:.1f} 秒）：{out.strip()}")

    if len(sys.argv) > 1:
        img = Path(sys.argv[1])
        mime = mimetypes.guess_type(img.name)[0] or "image/jpeg"
        t = time.time()
        fields, warnings = extract_ticket(img.read_bytes(), mime, llm)
        print(f"{'✓' if fields else '✗'} 罰單辨識（{time.time() - t:.1f} 秒）：")
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        for w in warnings:
            print("  提醒：", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
