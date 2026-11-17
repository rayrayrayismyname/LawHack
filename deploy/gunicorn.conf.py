# gunicorn 設定（容器內使用）
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_WORKERS", "2"))
threads = int(os.getenv("WEB_THREADS", "4"))
timeout = 120            # AI 辨識照片可能需要數十秒
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
