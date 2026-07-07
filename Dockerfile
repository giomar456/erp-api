FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_POOL_MIN=1 \
    DB_POOL_MAX=8 \
    PRODUCTOS_CACHE_TTL=180

WORKDIR /app

COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api.py plataform_sunat_client.py plataform_sunat_server.py plataform_sunat_panel.html /app/
COPY webapp /app/webapp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT','8000'), timeout=8)"

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 30 --limit-concurrency 25 --limit-max-requests 500 --proxy-headers --forwarded-allow-ips='*'"]