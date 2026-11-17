FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/data \
    PORT=8000

WORKDIR /app

# 安裝相依套件（INSTALL_AI=1 時一併安裝 boto3、anthropic）
ARG INSTALL_AI=1
COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn \
 && if [ "$INSTALL_AI" = "1" ]; then pip install --no-cache-dir -r requirements-ai.txt; fi

COPY appeal ./appeal
COPY web ./web
COPY samples ./samples
COPY wsgi.py ./
COPY deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py

# 以非 root 使用者執行；分析結果存在 /data（可掛載 volume）
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown appuser /data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "wsgi:app"]
