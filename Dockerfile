FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_POOL_MIN=1 \
    DB_POOL_MAX=5 \
    PRODUCTOS_CACHE_TTL=300 \
    PUBLIC_BASE_URL=http://64.181.176.160:8000

WORKDIR /app

COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api.py plataform_sunat_client.py plataform_sunat_server.py plataform_sunat_panel.html /app/
COPY webapp /app/webapp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=50s --retries=4 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT','8000'), timeout=6)"

# 1 worker: VM Oracle free ~1GB. Concurrency baja para no OOM.
# timeout-keep-alive alto: no corta clientes/caja que dejan la conexion abierta.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 75 --limit-concurrency 15 --limit-max-requests 1200 --proxy-headers --forwarded-allow-ips='*'"]
