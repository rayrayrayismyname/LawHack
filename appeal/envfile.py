"""讀取專案根目錄的 .env（不需安裝 python-dotenv）。已存在的環境變數不會被覆蓋。"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | str | None = None) -> bool:
    p = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
    return True
