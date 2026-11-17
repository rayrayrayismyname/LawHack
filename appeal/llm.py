"""大型語言模型介接層。

支援三種模式（環境變數 LLM_PROVIDER）：
  none      ：離線模式（預設）。不呼叫任何 AI，改用表單欄位與關鍵字規則，方便 Demo 與測試。
  bedrock   ：AWS Bedrock（與 PartyRock 同一套模型服務），需安裝 boto3 並設定 AWS 憑證。
  anthropic ：Anthropic API，需安裝 anthropic 並設定 ANTHROPIC_API_KEY。
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional


class LLM:
    name = "none"
    available = False

    def complete(self, system: str, user: str,
                 images: Optional[list[tuple[bytes, str]]] = None,
                 max_tokens: int = 2000) -> str:
        raise RuntimeError("目前為離線模式，沒有可用的 AI 模型")


class NullLLM(LLM):
    pass


class BedrockLLM(LLM):
    name = "bedrock"
    available = True

    def __init__(self, model_id: Optional[str] = None, region: Optional[str] = None):
        import boto3  # 延遲載入：離線模式不需要安裝
        self.model_id = model_id or os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
        self.client = boto3.client("bedrock-runtime",
                                   region_name=region or os.getenv("AWS_REGION", "us-east-1"))

    def complete(self, system, user, images=None, max_tokens=2000):
        content = []
        for data, mime in images or []:
            fmt = mime.split("/")[-1].replace("jpg", "jpeg")
            content.append({"image": {"format": fmt, "source": {"bytes": data}}})
        content.append({"text": user})
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts)


class AnthropicLLM(LLM):
    name = "anthropic"
    available = True

    def __init__(self, model: Optional[str] = None):
        import anthropic  # 延遲載入
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.client = anthropic.Anthropic()

    def complete(self, system, user, images=None, max_tokens=2000):
        content = []
        for data, mime in images or []:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": mime,
                "data": base64.b64encode(data).decode()}})
        content.append({"type": "text", "text": user})
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class GeminiLLM(LLM):
    name = "gemini"
    available = True

    def __init__(self, model: Optional[str] = None):
        from google import genai  # 延遲載入
        from google.genai import types
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        api_key = os.getenv("GEMINI_API_KEY", "")
        # 單次 AI 呼叫（含重試）的總時間上限。網站一次分析最多呼叫兩次，
        # 兩次加起來要低於 gunicorn 的 120 秒，否則使用者會看到 502。
        self.budget = max(10.0, float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45")))
        self.client = genai.Client(api_key=api_key,
                                   http_options=types.HttpOptions(timeout=int(self.budget * 1000)))

    def complete(self, system, user, images=None, max_tokens=2000):
        from google.genai import types
        parts = []
        for data, mime in images or []:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        parts.append(types.Part.from_text(text=user))
        resp = self._call_with_retry(
            model=self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                temperature=0,
            ),
        )
        # 直接取文字段落（避免 resp.text 遇到 thought_signature 時印出警告）
        if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
            return "".join(p.text for p in resp.candidates[0].content.parts
                           if getattr(p, "text", None) and not getattr(p, "thought", False))
        return ""

    def _call_with_retry(self, **kwargs):
        """免費額度常遇到 429（每分鐘次數上限）與 503（模型忙碌），自動等待後重試。"""
        import time
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
        from google.genai import errors
        retries = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
        deadline = time.monotonic() + self.budget
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            for attempt in range(retries + 1):
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                fut = pool.submit(self.client.models.generate_content, **kwargs)
                try:
                    return fut.result(timeout=left)
                except FutTimeout:
                    break
                except errors.APIError as e:
                    if e.code not in (429, 500, 503) or attempt >= retries or "PerDay" in str(e):
                        raise  # 每日額度用完等也沒用，直接退回離線規則
                    m = re.search(r"'retryDelay': '(\d+)s'", str(e))
                    wait = float(m.group(1)) + 1 if m else 2 ** attempt * 2
                    if time.monotonic() + wait >= deadline:
                        raise
                    time.sleep(wait)
            raise TimeoutError(f"Gemini 超過 {self.budget:.0f} 秒沒有回應")
        finally:
            pool.shutdown(wait=False)


def get_llm(provider: Optional[str] = None) -> LLM:
    provider = (provider or os.getenv("LLM_PROVIDER", "none")).lower()
    if provider == "bedrock":
        return BedrockLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "gemini":
        return GeminiLLM()
    return NullLLM()


def extract_json(text: str) -> dict:
    """從模型回覆中取出第一個 JSON 物件（容許前後有說明文字或 ```json 區塊）。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("模型回覆中沒有 JSON")
        raw = text[start:end + 1]
    return json.loads(raw)
